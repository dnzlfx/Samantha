#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import difflib
import enum
import json
import logging
import math
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import requests
import webrtcvad
import yaml
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import async_read_event, async_write_event
from wyoming.tts import Synthesize

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - host audio varies
    sd = None

try:
    import websocket
except Exception:  # pragma: no cover
    websocket = None


class State(str, enum.Enum):
    BOOT = "BOOT"
    HEALTHCHECK = "HEALTHCHECK"
    PASSIVE_LISTENING = "PASSIVE_LISTENING"
    WAKE_CONFIRMED = "WAKE_CONFIRMED"
    RECORDING_USER = "RECORDING_USER"
    TRANSCRIBING = "TRANSCRIBING"
    TOKEN_FIREWALL = "TOKEN_FIREWALL"
    LOCAL_ACTION = "LOCAL_ACTION"
    N8N_ACTION = "N8N_ACTION"
    OPENCLAW_REQUEST = "OPENCLAW_REQUEST"
    SPEAKING = "SPEAKING"
    FOLLOW_UP_WINDOW = "FOLLOW_UP_WINDOW"
    ERROR_RECOVERY = "ERROR_RECOVERY"


@dataclass
class RouteDecision:
    route: str
    text: str
    action: str | None = None
    reason: str | None = None
    requires_confirmation: bool = False
    raw_text: str | None = None
    normalized_text: str | None = None
    matched_alias: str | None = None


class CircuitBreaker:
    def __init__(self, name: str, fail_threshold: int = 3, reset_seconds: int = 30):
        self.name = name
        self.fail_threshold = fail_threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if time.time() - self.opened_at >= self.reset_seconds:
            self.failures = 0
            self.opened_at = None
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.fail_threshold:
            self.opened_at = time.time()


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def setup_logging(config: dict[str, Any]) -> logging.Logger:
    log_file = config.get("server", {}).get("log_file", "/logs/voice-gateway.log")
    log_level = getattr(logging, str(config.get("server", {}).get("log_level", "INFO")).upper(), logging.INFO)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("voice-gateway")
    logger.setLevel(log_level)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger


def parse_tcp_uri(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    if parsed.scheme not in {"tcp", "ws", "http", "https"}:
        raise ValueError(f"unsupported uri scheme: {uri}")
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"missing host or port in uri: {uri}")
    return parsed.hostname, int(parsed.port)


def tcp_check(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "ok"
    except Exception as exc:
        return False, str(exc)


def ensure_audio_output_unmuted(logger: logging.Logger) -> None:
    commands = [
        ["amixer", "-c", "0", "sset", "Master", "unmute", "80%"],
        ["amixer", "-c", "0", "sset", "Speaker", "unmute", "100%"],
        ["amixer", "-c", "0", "sset", "Headphone", "unmute", "100%"],
        ["amixer", "-c", "0", "sset", "PCM", "100%"],
        ["amixer", "-c", "0", "sset", "Auto-Mute Mode", "Disabled"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                logger.info("audio control ok: %s", " ".join(command))
            else:
                logger.warning("audio control unavailable: %s: %s", " ".join(command), (result.stderr or result.stdout).strip())
        except FileNotFoundError:
            logger.warning("amixer not found; cannot unmute output")
            return
        except Exception as exc:
            logger.warning("audio control failed: %s: %s", " ".join(command), exc)


def wav_write(path: str, audio: np.ndarray, sample_rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def wav_read(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise ValueError(f"unsupported sample width: {sample_width}")
    pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, sample_rate


def resample_audio(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    duration = audio.size / float(source_rate)
    source_times = np.linspace(0.0, duration, num=audio.size, endpoint=False)
    target_size = max(1, int(round(duration * target_rate)))
    target_times = np.linspace(0.0, duration, num=target_size, endpoint=False)
    return np.interp(target_times, source_times, audio).astype(np.float32)


def write_text_file(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text or "", encoding="utf-8")


def read_text_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def normalize_text_for_intent(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = "".join(
        ch for ch in unicodedata.normalize("NFD", normalized)
        if unicodedata.category(ch) != "Mn"
    )
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    replacements = {
        "open cloud": "openclaw",
        "open claw": "openclaw",
        "open clau": "openclaw",
        "open clao": "openclaw",
        "open close": "openclaw",
        "openclao": "openclaw",
        "openclau": "openclaw",
    }
    for source, target in replacements.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    return re.sub(r"\s+", " ", normalized).strip()


class HealthChecker:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config
        self.logger = logger

    def check_all(self) -> dict[str, dict[str, Any]]:
        targets: dict[str, tuple[str, int]] = {}
        for name, section in (("voice-piper", "tts"), ("voice-whisper", "stt"), ("voice-wakeword", "wakeword")):
            uri = self.config.get(section, {}).get("uri")
            if uri:
                targets[name] = parse_tcp_uri(uri)
        openclaw_url = self.config.get("openclaw", {}).get("url")
        if openclaw_url:
            targets["openclaw"] = parse_tcp_uri(openclaw_url)
        n8n_base = self.config.get("n8n", {}).get("base_url")
        if n8n_base:
            targets["n8n"] = parse_tcp_uri(n8n_base)

        results: dict[str, dict[str, Any]] = {}
        for name, (host, port) in targets.items():
            ok, error = tcp_check(host, port)
            results[name] = {"host": host, "port": port, "ok": ok, "error": None if ok else error}
        return results

    def log_results(self) -> bool:
        results = self.check_all()
        all_ok = True
        for name, result in results.items():
            if result["ok"]:
                self.logger.info("health %s %s:%s ok", name, result["host"], result["port"])
            else:
                all_ok = False
                self.logger.warning("health %s %s:%s failed: %s", name, result["host"], result["port"], result["error"])
        return all_ok


class AudioDevices:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.root_config = config
        self.config = config.get("audio", {})
        self.logger = logger

    def list_devices(self) -> list[dict[str, Any]]:
        if sd is None:
            self.logger.warning("sounddevice is unavailable; cannot list audio devices through PortAudio")
            return []
        try:
            devices = sd.query_devices()
            normalized = []
            for idx, dev in enumerate(devices):
                normalized.append({
                    "index": idx,
                    "name": dev.get("name"),
                    "max_input_channels": dev.get("max_input_channels"),
                    "max_output_channels": dev.get("max_output_channels"),
                    "default_samplerate": dev.get("default_samplerate"),
                })
            return normalized
        except Exception as exc:
            self.logger.warning("failed to list audio devices: %s", exc)
            return []

    def log_devices(self) -> None:
        devices = self.list_devices()
        if not devices:
            self.logger.warning("no audio devices reported; check /dev/snd mount and audio group")
            return
        for dev in devices:
            self.logger.info("audio device %s: %s input=%s output=%s rate=%s", dev["index"], dev["name"], dev["max_input_channels"], dev["max_output_channels"], dev["default_samplerate"])

    def play_test_tone(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is unavailable")
        ensure_audio_output_unmuted(self.logger)
        output_device = self.config.get("output_device")
        output_rate = int(self.config.get("output_sample_rate", self.config.get("sample_rate", 48000)))
        duration = 1.0
        t = np.linspace(0.0, duration, int(output_rate * duration), endpoint=False)
        tone = (0.20 * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32)
        self.logger.info("playing test tone device=%s rate=%s duration=%.2fs", output_device, output_rate, duration)
        sd.play(tone, samplerate=output_rate, device=output_device, blocking=True)

    def play_wav(self, path: str) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is unavailable")
        ensure_audio_output_unmuted(self.logger)
        output_device = self.config.get("output_device")
        output_rate = int(self.config.get("output_sample_rate", self.config.get("sample_rate", 48000)))
        audio, original_rate = wav_read(path)
        rendered = resample_audio(audio, original_rate, output_rate)
        duration = rendered.size / float(output_rate)
        self.logger.info("playing wav path=%s original_rate=%s output_rate=%s duration=%.2fs device=%s", path, original_rate, output_rate, duration, output_device)
        sd.play(rendered.astype(np.float32), samplerate=output_rate, device=output_device, blocking=True)

    def record_once(self) -> dict[str, Any]:
        if sd is None:
            raise RuntimeError("sounddevice is unavailable")
        sample_rate = int(self.config.get("sample_rate", 16000))
        channels = int(self.config.get("channels", 1))
        frame_ms = int(self.config.get("frame_ms", 30))
        input_device = self.config.get("input_device")
        max_record_seconds = float(self.config.get("max_record_seconds", 12))
        phrase_end_silence_ms = int(self.config.get("phrase_end_silence_ms", 900))
        min_voice_ms = int(self.config.get("min_voice_ms", 450))
        frame_samples = int(sample_rate * frame_ms / 1000)
        vad_cfg = self.root_config.get("vad", {}) if isinstance(self.root_config.get("vad"), dict) else {}
        aggressiveness = int(vad_cfg.get("aggressiveness", 2))
        vad = webrtcvad.Vad(aggressiveness)
        max_frames = int(max_record_seconds * 1000 / frame_ms)
        end_silence_frames = max(1, int(phrase_end_silence_ms / frame_ms))
        voiced_frames = 0
        trailing_silence_frames = 0
        started = False
        all_frames: list[np.ndarray] = []
        captured_frames: list[np.ndarray] = []
        self.logger.info("record-once waiting input_device=%s rate=%s frame_ms=%s max_seconds=%s", input_device, sample_rate, frame_ms, max_record_seconds)
        with sd.InputStream(device=input_device, samplerate=sample_rate, channels=channels, dtype="int16", blocksize=frame_samples) as stream:
            for _ in range(max_frames):
                frame, _overflowed = stream.read(frame_samples)
                mono = frame[:, 0] if frame.ndim > 1 else frame
                mono = np.asarray(mono, dtype=np.int16)
                all_frames.append(mono.copy())
                is_speech = vad.is_speech(mono.tobytes(), sample_rate)
                if is_speech:
                    started = True
                    voiced_frames += 1
                    trailing_silence_frames = 0
                elif started:
                    trailing_silence_frames += 1
                if started:
                    captured_frames.append(mono.copy())
                if started and trailing_silence_frames >= end_silence_frames:
                    break
        total_frames = captured_frames if started else all_frames
        audio_i16 = np.concatenate(total_frames) if total_frames else np.zeros(0, dtype=np.int16)
        audio_f32 = audio_i16.astype(np.float32) / 32768.0
        total_ms = int(audio_i16.size / sample_rate * 1000) if audio_i16.size else 0
        voice_ms = voiced_frames * frame_ms
        final_silence_ms = trailing_silence_frames * frame_ms
        ok = started and voice_ms >= min_voice_ms
        path = "/logs/last_utterance.wav" if ok else "/logs/last_discarded.wav"
        wav_write(path, audio_f32, sample_rate)
        self.logger.info("record-once result ok=%s total_ms=%s voice_ms=%s final_silence_ms=%s path=%s", ok, total_ms, voice_ms, final_silence_ms, path)
        if not ok:
            self.logger.warning("record-once discarded: insufficient voice (%sms < %sms)", voice_ms, min_voice_ms)
        return {"ok": ok, "path": path, "total_ms": total_ms, "voice_ms": voice_ms, "final_silence_ms": final_silence_ms}


class TokenFirewall:
    FILLERS = {"eh", "mmm", "mm", "ah", "ok", "si", "aja", "este"}
    CANCEL_ALIASES = {"cancelar", "cancela", "yancelan", "pencilar", "canselar", "kanselar"}
    OPENCLAW_STATUS_ALIASES = (
        "estado de openclaw",
        "estado openclaw",
        "estatus de openclaw",
        "como esta openclaw",
        "revisar openclaw",
        "verifica openclaw",
    )
    LOCAL_ACTIONS = {
        "cancelar": "cancel",
        "para": "stop",
        "detente": "stop",
        "repetir": "repeat",
        "sube el volumen": "volume_up",
        "baja el volumen": "volume_down",
        "estado del sistema": "system_status",
        "estado de openclaw": "openclaw_status",
    }
    ADMIN_RESTART = {"reinicia openclaw", "reiniciar openclaw"}
    N8N_PATTERNS = {
        "notifica discord": "discord_notify",
        "estado administrativo de openclaw": "admin_openclaw_status",
        "logs de openclaw": "admin_openclaw_logs",
    }
    COMPLEX_HINTS = ("explic", "analiza", "diagnost", "por qué", "porque", "error", "contenedor", "openclaw", "ayúdame", "ayudame", "revisa")

    def __init__(self, config: dict[str, Any]):
        self.config = config.get("token_firewall", {})
        self.max_input_chars = int(self.config.get("max_input_chars", 600))
        self.min_text_chars = 3

    @staticmethod
    def normalize(text: str) -> str:
        return normalize_text_for_intent(text)

    @staticmethod
    def decision(route: str, raw_text: str, normalized_text: str, action: str | None = None, reason: str | None = None, requires_confirmation: bool = False, matched_alias: str | None = None) -> RouteDecision:
        return RouteDecision(route, normalized_text, action=action, reason=reason, requires_confirmation=requires_confirmation, raw_text=raw_text, normalized_text=normalized_text, matched_alias=matched_alias)

    def match_openclaw_status(self, text: str) -> str | None:
        if "openclaw" in text:
            if "estado" in text or "estatus" in text or "como esta" in text or "revisar" in text or "verifica" in text:
                return "keyword_openclaw_status"
        for alias in self.OPENCLAW_STATUS_ALIASES:
            if difflib.SequenceMatcher(None, text, alias).ratio() >= 0.82:
                return alias
        return None

    def classify(self, raw_text: str) -> RouteDecision:
        text = self.normalize(raw_text)
        if not text:
            return self.decision("discard", raw_text, text, reason="empty_text")
        if len(text) < self.min_text_chars:
            return self.decision("discard", raw_text, text, reason="too_short")
        if len(text) > self.max_input_chars:
            return self.decision("discard", raw_text, text[: self.max_input_chars], reason="too_long")
        words = text.split()
        if self.config.get("discard_single_words", True) and len(words) == 1 and words[0] in self.FILLERS:
            return self.decision("discard", raw_text, text, reason="filler_single_word")
        if text in self.FILLERS:
            return self.decision("discard", raw_text, text, reason="filler")
        if text in self.CANCEL_ALIASES:
            return self.decision("local", raw_text, text, action="cancel", reason="cancel_alias", matched_alias=text)
        status_alias = self.match_openclaw_status(text)
        if status_alias:
            return self.decision("local", raw_text, text, action="openclaw_status", reason="openclaw_status_alias", matched_alias=status_alias)
        for phrase, action in self.LOCAL_ACTIONS.items():
            if text == phrase or text.startswith(phrase + " "):
                return self.decision("local", raw_text, text, action=action, reason="local_command", matched_alias=phrase)
        if text in self.ADMIN_RESTART:
            return self.decision("n8n", raw_text, text, action="admin_restart_openclaw", reason="admin_requires_confirmation", requires_confirmation=True, matched_alias=text)
        if "confirma reiniciar openclaw" in text or "confirmo reiniciar openclaw" in text:
            return self.decision("n8n", raw_text, text, action="admin_restart_openclaw", reason="admin_confirmation_attempt", requires_confirmation=True)
        for phrase, action in self.N8N_PATTERNS.items():
            if phrase in text:
                return self.decision("n8n", raw_text, text, action=action, reason="n8n_action", matched_alias=phrase)
        if any(hint in text for hint in self.COMPLEX_HINTS) or len(words) >= 4:
            return self.decision("openclaw", raw_text, text, reason="complex_query")
        return self.decision("discard", raw_text, text, reason="low_value_short_text")


class LocalActions:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.last_response: str | None = None

    def run(self, action: str, text: str) -> dict[str, Any]:
        self.logger.info("local action=%s text=%r", action, text)
        if action in {"cancel", "stop"}:
            return {"ok": True, "speak": "Cancelado."}
        if action == "repeat":
            return {"ok": True, "speak": self.last_response or "No tengo una respuesta anterior para repetir."}
        if action in {"volume_up", "volume_down"}:
            return {"ok": True, "speak": "Control de volumen pendiente de conectar al mezclador ALSA."}
        if action in {"system_status", "openclaw_status"}:
            return {"ok": True, "speak": "Estado local disponible en logs; consulta administrativa preparada."}
        return {"ok": False, "speak": "Acción local no reconocida."}


class N8NClient:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config.get("n8n", {})
        self.logger = logger
        self.breaker = CircuitBreaker("n8n")

    def call(self, action: str, text: str, confirmation: str | None = None) -> dict[str, Any]:
        if not self.config.get("enabled", True):
            return {"ok": False, "error": "n8n disabled"}
        if not self.breaker.allow():
            return {"ok": False, "error": "n8n circuit breaker open"}
        base = str(self.config.get("base_url", "")).rstrip("/")
        path = self.config.get("voice_webhook_path", "/webhook/voice-gateway-action")
        token = os.environ.get(self.config.get("token_env", "VOICE_WEBHOOK_TOKEN"), "")
        url = base + path
        try:
            response = requests.post(
                url,
                headers={"x-voice-token": token} if token else {},
                json={"action": action, "text": text, "confirmation": confirmation},
                timeout=float(self.config.get("timeout_seconds", 8)),
            )
            response.raise_for_status()
            self.breaker.success()
            return response.json()
        except Exception as exc:
            self.breaker.failure()
            self.logger.warning("n8n action failed action=%s error=%s", action, exc)
            return {"ok": False, "error": str(exc)}


class OpenClawClient:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config.get("openclaw", {})
        self.logger = logger
        self.breaker = CircuitBreaker("openclaw")

    def send_text(self, text: str) -> dict[str, Any]:
        if not self.config.get("enabled", True):
            return {"ok": False, "error": "openclaw disabled"}
        if not self.breaker.allow():
            return {"ok": False, "error": "openclaw circuit breaker open"}
        if websocket is None:
            return {"ok": False, "error": "websocket-client unavailable"}
        rpc_method = self.config.get("rpc_method")
        if not rpc_method:
            self.logger.error("OpenClaw RPC method not configured; refusing to send prompt")
            return {"ok": False, "error": "openclaw rpc_method not configured; text not sent"}
        url = self.config.get("url", "ws://openclaw:18789")
        timeout = float(self.config.get("timeout_seconds", 35))
        payload = {"method": rpc_method, "params": {"agentId": self.config.get("agent_default", "main"), "message": text}}
        try:
            ws = websocket.create_connection(url, timeout=timeout)
            ws.send(json.dumps(payload))
            raw = ws.recv()
            ws.close()
            self.breaker.success()
            return {"ok": True, "raw": raw}
        except Exception as exc:
            self.breaker.failure()
            self.logger.warning("openclaw request failed: %s", exc)
            return {"ok": False, "error": str(exc)}


class WyomingAdapter:
    def __init__(self, name: str, uri: str, logger: logging.Logger):
        self.name = name
        self.uri = uri
        self.logger = logger

    def ensure_available(self) -> bool:
        host, port = parse_tcp_uri(self.uri)
        ok, error = tcp_check(host, port)
        if not ok:
            self.logger.warning("%s unavailable at %s: %s", self.name, self.uri, error)
        return ok

    def transcribe(self, _audio_bytes: bytes) -> str:
        raise NotImplementedError("Wyoming STT frame protocol adapter is intentionally stubbed until audio loop integration phase")

    def speak(self, text: str) -> None:
        self.logger.info("TTS adapter placeholder would synthesize %d chars", len(text))
        raise NotImplementedError("Wyoming TTS frame protocol adapter is intentionally stubbed until audio loop integration phase")


class STTClient:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config.get("stt", {})
        self.logger = logger

    def transcribe_wav(self, path: str) -> str:
        start = time.monotonic()
        try:
            text = asyncio.run(self._transcribe_wav(path))
            latency_ms = int((time.monotonic() - start) * 1000)
            self.logger.info("stt result chars=%s latency_ms=%s path=%s", len(text), latency_ms, path)
            return text.strip()
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            self.logger.warning("stt failed latency_ms=%s path=%s error=%s", latency_ms, path, exc)
            return ""

    async def _transcribe_wav(self, path: str) -> str:
        uri = self.config.get("uri", "tcp://voice-whisper:10300")
        host, port = parse_tcp_uri(uri)
        timeout = float(self.config.get("timeout_seconds", 12))
        language = self.config.get("language", "es")
        with wave.open(path, "rb") as wav:
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            data = wav.readframes(wav.getnframes())
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        try:
            await async_write_event(Transcribe(language=language).event(), writer)
            await async_write_event(AudioStart(rate=rate, width=width, channels=channels).event(), writer)
            chunk_bytes = max(width * channels, rate * width * channels // 10)
            for offset in range(0, len(data), chunk_bytes):
                await async_write_event(AudioChunk(rate=rate, width=width, channels=channels, audio=data[offset:offset + chunk_bytes]).event(), writer)
            await async_write_event(AudioStop().event(), writer)
            while True:
                event = await asyncio.wait_for(async_read_event(reader), timeout=timeout)
                if event is None:
                    return ""
                if Transcript.is_type(event.type):
                    return Transcript.from_event(event).text or ""
        finally:
            writer.close()
            await writer.wait_closed()


class TTSClient:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config.get("tts", {})
        self.logger = logger

    def synthesize_to_wav(self, text: str, out_path: str) -> str:
        start = time.monotonic()
        try:
            result = asyncio.run(self._synthesize_to_wav(text, out_path))
            latency_ms = int((time.monotonic() - start) * 1000)
            self.logger.info("tts result chars=%s latency_ms=%s path=%s", len(text), latency_ms, result)
            return result
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            self.logger.warning("tts failed latency_ms=%s error=%s", latency_ms, exc)
            raise

    async def _synthesize_to_wav(self, text: str, out_path: str) -> str:
        clean = (text or "").strip()
        if not clean:
            raise ValueError("empty TTS text")
        max_chars = int(self.config.get("max_chars", 700))
        clean = clean[:max_chars]
        uri = self.config.get("uri", "tcp://voice-piper:10200")
        host, port = parse_tcp_uri(uri)
        timeout = float(self.config.get("timeout_seconds", 10))
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        chunks: list[bytes] = []
        rate = 22050
        width = 2
        channels = 1
        try:
            await async_write_event(Synthesize(text=clean).event(), writer)
            while True:
                event = await asyncio.wait_for(async_read_event(reader), timeout=timeout)
                if event is None:
                    break
                if AudioStart.is_type(event.type):
                    audio_start = AudioStart.from_event(event)
                    rate = audio_start.rate
                    width = audio_start.width
                    channels = audio_start.channels
                elif AudioChunk.is_type(event.type):
                    chunks.append(AudioChunk.from_event(event).audio)
                elif AudioStop.is_type(event.type):
                    break
        finally:
            writer.close()
            await writer.wait_closed()
        if not chunks:
            raise RuntimeError("TTS returned no audio")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(out_path, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(width)
            wav.setframerate(rate)
            wav.writeframes(b"".join(chunks))
        return out_path


class VoiceGateway:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.state = State.BOOT
        self.health = HealthChecker(config, logger)
        self.audio = AudioDevices(config, logger)
        self.firewall = TokenFirewall(config)
        self.local = LocalActions(logger)
        self.n8n = N8NClient(config, logger)
        self.openclaw = OpenClawClient(config, logger)
        self.stt = STTClient(config, logger)
        self.tts = TTSClient(config, logger)
        self.followup_turns = 0

    def transition(self, state: State) -> None:
        self.logger.info("state %s -> %s", self.state, state)
        self.state = state

    def boot(self) -> None:
        ensure_audio_output_unmuted(self.logger)
        self.transition(State.HEALTHCHECK)
        self.health.log_results()
        self.audio.log_devices()
        self.transition(State.PASSIVE_LISTENING)

    def process_text(self, raw_text: str, confirmation: str | None = None) -> dict[str, Any]:
        self.transition(State.TOKEN_FIREWALL)
        decision = self.firewall.classify(raw_text)
        self.log_firewall_decision(decision)
        return self.handle_decision(decision, speak=False, confirmation=confirmation)

    def log_firewall_decision(self, decision: RouteDecision) -> None:
        self.logger.info(
            "firewall raw_text=%r normalized_text=%r route=%s action=%s reason=%s matched_alias=%s",
            decision.raw_text,
            decision.normalized_text,
            decision.route,
            decision.action,
            decision.reason,
            decision.matched_alias,
        )

    def handle_decision(self, decision: RouteDecision, speak: bool = False, confirmation: str | None = None) -> dict[str, Any]:
        if decision.route == "discard":
            self.logger.info("route discard reason=%s", decision.reason)
            return {"ok": True, "discarded": True, "reason": decision.reason}
        if decision.route == "local":
            self.transition(State.LOCAL_ACTION)
            if decision.action == "openclaw_status":
                ok = self.health.check_all().get("openclaw", {}).get("ok") is True
                result = {"ok": ok, "speak": "OpenClaw está accesible." if ok else "OpenClaw no está accesible."}
            else:
                result = self.local.run(decision.action or "unknown", decision.text)
            if speak and result.get("speak"):
                self.speak_text(str(result["speak"]))
            return result
        if decision.route == "n8n":
            self.transition(State.N8N_ACTION)
            result = self.n8n.call(decision.action or "unknown", decision.text, confirmation=confirmation)
            if speak:
                self.speak_text("Acción enviada a n8n." if result.get("ok") else "No pude contactar n8n.")
            return result
        if decision.route == "openclaw":
            self.transition(State.OPENCLAW_REQUEST)
            result = self.openclaw.send_text(decision.text)
            if speak:
                if result.get("ok"):
                    self.speak_text("OpenClaw recibió la solicitud.")
                elif "rpc_method" in str(result.get("error", "")):
                    self.speak_text("OpenClaw todavía no tiene método RPC configurado.")
                else:
                    self.speak_text("No pude contactar OpenClaw.")
            return result
        return {"ok": False, "error": "unknown route"}

    def speak_text(self, text: str) -> None:
        clean = (text or "").strip()
        if not clean:
            return
        self.transition(State.SPEAKING)
        out_path = "/logs/last_tts.wav"
        self.tts.synthesize_to_wav(clean, out_path)
        write_text_file("/logs/last_assistant_text.txt", clean)
        self.local.last_response = clean
        self.audio.play_wav(out_path)
        cooldown_ms = int(self.config.get("audio", {}).get("post_tts_mic_cooldown_ms", 700))
        if cooldown_ms > 0:
            self.logger.info("post-tts cooldown ms=%s", cooldown_ms)
            time.sleep(cooldown_ms / 1000.0)

    def is_likely_tts_loop(self, text: str) -> bool:
        last_spoken = read_text_file("/logs/last_assistant_text.txt")
        if not text or not last_spoken:
            return False
        ratio = difflib.SequenceMatcher(None, TokenFirewall.normalize(text), TokenFirewall.normalize(last_spoken)).ratio()
        if ratio >= 0.86:
            self.logger.warning("discarding possible TTS loop similarity=%.3f text=%r", ratio, text)
            return True
        return False

    def voice_turn_once(self, text: str | None = None, confirmation: str | None = None) -> dict[str, Any]:
        if text is None:
            self.transition(State.RECORDING_USER)
            record_result = self.audio.record_once()
            if not record_result.get("ok"):
                self.transition(State.TOKEN_FIREWALL)
                self.logger.info("voice-turn discarded before STT: %s", record_result)
                return {"ok": True, "route": "discard", "recording": record_result}
            self.transition(State.TRANSCRIBING)
            text = self.stt.transcribe_wav(str(record_result["path"]))
            if not text:
                self.logger.info("voice-turn discarded: empty STT")
                return {"ok": True, "route": "discard", "reason": "empty_stt", "recording": record_result}
        else:
            record_result = None
        write_text_file("/logs/last_user_text.txt", text)
        if self.is_likely_tts_loop(text):
            return {"ok": True, "route": "discard", "reason": "possible_tts_loop", "text": text, "recording": record_result}
        self.transition(State.TOKEN_FIREWALL)
        decision = self.firewall.classify(text)
        self.log_firewall_decision(decision)
        result = self.handle_decision(decision, speak=True, confirmation=confirmation)
        result.update({"route": decision.route, "text": decision.text})
        if record_result is not None:
            result["recording"] = record_result
        return result

    def run(self) -> None:
        self.boot()
        self.logger.info("voice gateway base loop is ready; full audio capture/wake/STT/TTS loop is adapter phase")
        while True:
            time.sleep(60)
            self.transition(State.HEALTHCHECK)
            self.health.log_results()
            self.transition(State.PASSIVE_LISTENING)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.environ.get("VOICE_GATEWAY_CONFIG", "/app/config.yaml"))
    parser.add_argument("--healthcheck-once", action="store_true")
    parser.add_argument("--list-audio", action="store_true")
    parser.add_argument("--play-test-tone", action="store_true")
    parser.add_argument("--record-once", action="store_true")
    parser.add_argument("--play-wav")
    parser.add_argument("--stt-once")
    parser.add_argument("--tts-once")
    parser.add_argument("--voice-turn-once", action="store_true")
    parser.add_argument("--self-test-firewall", action="store_true")
    parser.add_argument("--process-text")
    parser.add_argument("--text")
    parser.add_argument("--confirmation")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logging(config)
    gateway = VoiceGateway(config, logger)

    if args.healthcheck_once:
        return 0 if gateway.health.log_results() else 1
    if args.list_audio:
        gateway.audio.log_devices()
        return 0
    if args.play_test_tone:
        gateway.audio.play_test_tone()
        return 0
    if args.record_once:
        result = gateway.audio.record_once()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.play_wav:
        gateway.audio.play_wav(args.play_wav)
        return 0
    if args.stt_once:
        text = gateway.stt.transcribe_wav(args.stt_once)
        print(text)
        return 0 if text else 2
    if args.tts_once:
        out_path = gateway.tts.synthesize_to_wav(args.tts_once, "/logs/last_tts.wav")
        write_text_file("/logs/last_assistant_text.txt", args.tts_once)
        gateway.audio.play_wav(out_path)
        return 0
    if args.voice_turn_once:
        result = gateway.voice_turn_once(text=args.text, confirmation=args.confirmation)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") or result.get("route") == "discard" else 2
    if args.self_test_firewall:
        samples = [
            "estado de openclaw",
            "Estado de open cloud",
            "estado de open claw",
            "estatus de openclaw",
            "como esta openclaw",
            "revisar openclaw",
            "verifica openclaw",
            "cancelar",
            "yancelan",
            "pencilar",
            "analiza este error del contenedor",
        ]
        for sample in samples:
            print(json.dumps(gateway.firewall.classify(sample).__dict__, ensure_ascii=False))
        return 0
    if args.process_text is not None:
        print(json.dumps(gateway.process_text(args.process_text, confirmation=args.confirmation), ensure_ascii=False))
        return 0

    gateway.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
