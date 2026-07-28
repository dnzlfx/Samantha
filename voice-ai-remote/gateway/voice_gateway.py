#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import difflib
import enum
import fcntl
import json
import logging
import math
import os
import random
import re
import sqlite3
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import wave
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import numpy as np
import requests
import webrtcvad
import yaml
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient
from wyoming.event import async_read_event, async_write_event
from wyoming.tts import Synthesize
from wyoming.wake import Detect, Detection, NotDetected

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - host audio varies
    sd = None

try:
    import websocket
except Exception:  # pragma: no cover
    websocket = None

try:
    import mutagen
except Exception:
    mutagen = None



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
    fuzzy_score: float | None = None


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
        ["amixer", "-c", "0", "sset", "Master", "unmute", "90%"],
        ["amixer", "-c", "0", "sset", "Speaker", "unmute", "90%"],
        ["amixer", "-c", "0", "sset", "Headphone", "unmute", "90%"],
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




def ensure_mic_gain(logger: logging.Logger) -> None:
    for card in (0, 1, 2):
        for ctrl in ("Mic", "Internal Mic", "Capture", "Digital", "Front Mic"):
            try:
                result = subprocess.run(
                    ["amixer", "-c", str(card), "sset", ctrl, "100%", "cap"],
                    check=False, capture_output=True, text=True, timeout=3,
                )
                if result.returncode == 0:
                    logger.info("mic gain ok: amixer -c %s sset %s 100%% cap", card, ctrl)
            except Exception:
                pass
    for card in (0, 1, 2):
        try:
            result = subprocess.run(
                ["amixer", "-c", str(card), "sset", "Auto Gain Control", "Disabled"],
                check=False, capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                logger.info("mic agc disabled: card=%s", card)
        except Exception:
            pass

def wav_write(path: str, audio: np.ndarray, sample_rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def wav_write_int16(path: str, audio: np.ndarray, sample_rate: int, channels: int = 1) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pcm = np.asarray(audio, dtype=np.int16)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(channels)
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


def wav_read_int16(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise ValueError(f"unsupported sample width: {sample_width}")
    pcm = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return pcm.reshape(-1), sample_rate


def audio_level_stats(audio: np.ndarray) -> dict[str, float]:
    arr = np.asarray(audio)
    if arr.size == 0:
        return {"peak": 0.0, "peak_percent": 0.0, "rms": 0.0}
    if arr.dtype == np.int16:
        values = arr.astype(np.float32) / 32768.0
    else:
        values = arr.astype(np.float32)
    peak = float(np.max(np.abs(values))) if values.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(values)))) if values.size else 0.0
    return {"peak": peak, "peak_percent": peak * 100.0, "rms": rms}


def apply_audio_gain_int16(audio: np.ndarray, gain: float, max_peak: float = 0.85, logger: logging.Logger | None = None, label: str = "audio") -> np.ndarray:
    arr = np.asarray(audio)
    if arr.dtype == np.int16:
        values = arr.astype(np.float32) / 32768.0
    else:
        values = arr.astype(np.float32)
    before = audio_level_stats(values)
    gain = max(0.0, float(gain))
    boosted = values * gain
    boosted_peak = float(np.max(np.abs(boosted))) if boosted.size else 0.0
    if boosted_peak > max_peak > 0:
        boosted *= max_peak / boosted_peak
    boosted = np.clip(boosted, -1.0, 1.0)
    after = audio_level_stats(boosted)
    if logger is not None:
        logger.info(
            "%s gain=%.2f before_peak=%.4f before_rms=%.4f after_peak=%.4f after_rms=%.4f",
            label,
            gain,
            before["peak"],
            before["rms"],
            after["peak"],
            after["rms"],
        )
    return (boosted * 32767.0).astype(np.int16)


def analyze_wav_file(path: str) -> dict[str, Any]:
    with wave.open(path, "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames_count = wav.getnframes()
        frames = wav.readframes(frames_count)
    if sample_width != 2:
        raise ValueError(f"unsupported sample width: {sample_width}")
    pcm = np.frombuffer(frames, dtype=np.int16)
    stats = audio_level_stats(pcm)
    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "duration": frames_count / float(sample_rate) if sample_rate else 0.0,
        "peak": stats["peak"],
        "peak_percent": stats["peak_percent"],
        "rms": stats["rms"],
    }


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
    has_open_variant = re.search(r"\bopen\s+\w+\b|\bopencl\w*\b", normalized) is not None
    replacements = {
        "open clamp": "openclaw",
        "open plan": "openclaw",
        "open plum": "openclaw",
        "open plume": "openclaw",
        "open plun": "openclaw",
        "open cloud": "openclaw",
        "open claw": "openclaw",
        "open clau": "openclaw",
        "open clao": "openclaw",
        "open close": "openclaw",
        "openclao": "openclaw",
        "openclau": "openclaw",
        "esta en el": "estado",
        "esta en la": "estado",
        "estal": "estado",
        "estadle": "estado",
    }
    for source, target in replacements.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    if has_open_variant:
        normalized = re.sub(r"\bestamos\b", "estado", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def make_concise_response(text: str, config: dict[str, Any]) -> str:
    clean = preprocess_tts_text(text, config)
    if not clean:
        return ""
    assistant_cfg = config.get("assistant", {}) if isinstance(config.get("assistant"), dict) else {}
    style_cfg = config.get("tts_style", {}) if isinstance(config.get("tts_style"), dict) else {}
    if not assistant_cfg.get("concise_responses", True):
        return clean
    clean = re.sub(r"\b(?:por supuesto|claro que si|claro que sí|vale|ok)[,.]?\s*", "", clean, flags=re.IGNORECASE).strip()
    clean = clean.replace("El gateway de voz está activo. OpenClaw está accesible.", "Todo está activo.")
    clean = clean.replace("El gateway de voz está activo. OpenClaw no está accesible.", "Gateway activo. OpenClaw no está accesible.")
    clean = clean.replace("Modo prueba. No envié nada a OpenClaw.", "Modo prueba. No envié nada.")
    clean = clean.replace("OpenClaw todavía no tiene método RPC configurado.", "OpenClaw sigue protegido.")
    clean = re.sub(r"Recordatorio:\s*(tienes que|debes|hay que)\s+", "Recordatorio: ", clean, flags=re.IGNORECASE)
    max_sentences = max(1, int(assistant_cfg.get("max_response_sentences", 2)))
    max_chars = max(40, int(style_cfg.get("max_spoken_chars", assistant_cfg.get("max_response_chars", 350))))
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    shortened = " ".join(part for part in sentences[:max_sentences] if part).strip() or clean
    if len(shortened) <= max_chars:
        return shortened
    cut = shortened[:max_chars].rstrip()
    boundary = max(cut.rfind(". "), cut.rfind(", "), cut.rfind(" "))
    if boundary >= max_chars // 2:
        cut = cut[:boundary].rstrip()
    return cut.rstrip(" ,.;:") + "."


def preprocess_tts_text(text: str, config: dict[str, Any]) -> str:
    clean = (text or "").strip()
    if not clean:
        return ""
    clean = re.sub(r"```.*?```", " ", clean, flags=re.DOTALL)
    clean = re.sub(r"`([^`]*)`", r"\1", clean)
    clean = re.sub(r"[*_#>\[\]]", " ", clean)
    clean = re.sub(r"https?://\S+", " enlace ", clean)
    clean = re.sub(r"/[^\s]{24,}", " ruta larga ", clean)
    clean = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]", "", clean)
    if len(clean) > 600 and any(word in clean.lower() for word in ("traceback", "error", "exception", "logs")):
        clean = "Hay un error en los logs. Revisa el resumen en pantalla."
    clean = re.sub(r"\s+", " ", clean).strip()
    style_cfg = config.get("tts_style", {}) if isinstance(config.get("tts_style"), dict) else {}
    max_chars = int(style_cfg.get("max_spoken_chars", 350))
    if max_chars > 0 and len(clean) > max_chars:
        cut = clean[:max_chars].rstrip()
        boundary = max(cut.rfind(". "), cut.rfind(", "), cut.rfind(" "))
        if boundary >= max_chars // 2:
            cut = cut[:boundary].rstrip()
        clean = cut.rstrip(" ,.;:") + "."
    return clean


class AssistantCommandParser:
    NUMBER_WORDS = {
        "un": 1,
        "una": 1,
        "uno": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
    }

    @classmethod
    def parse(cls, raw_text: str) -> dict[str, Any] | None:
        text = normalize_text_for_intent(raw_text)
        if not text:
            return None
        if text in {"quien eres", "como te llamas", "cual es tu nombre"}:
            return {"action": "identity"}
        music = cls.parse_music_command(text)
        if music:
            return music
        alarm_cancel = cls.parse_alarm_cancel(text)
        if alarm_cancel:
            return alarm_cancel
        if text in {"que recordatorios tengo", "lista mis recordatorios", "que alarmas tengo", "lista mis alarmas"}:
            return {"action": "list_reminders"}
        if text in {"cancela la alarma", "deten la alarma", "detener alarma", "apaga la alarma"}:
            return {"action": "cancel_alarm"}
        if text in {"borra mis recordatorios", "borra recordatorios", "limpia recordatorios"}:
            return {"action": "cancel_all_reminders"}
        if text in {"olvida esta conversacion", "borra memoria", "limpia memoria"}:
            return {"action": "clear_memory"}
        if "despiertame manana" in text:
            return {"action": "unsupported_alarm", "error": "Solo soporto alarmas diarias o recordatorios en cierto tiempo."}
        reminder = cls.parse_one_shot_reminder(text)
        if reminder:
            return reminder
        alarm = cls.parse_daily_alarm(text)
        if alarm:
            return alarm
        return None

    @classmethod
    def parse_music_command(cls, text: str) -> dict[str, Any] | None:
        if text in {"siguiente", "siguiente cancion", "pasa la cancion"}:
            return {"action": "music_next"}
        if text in {"que cancion es", "que esta sonando", "que suena"}:
            return {"action": "music_now_playing"}
        if text in {"deten la musica", "detener musica", "para la musica", "apaga la musica"}:
            return {"action": "music_stop"}
        if not (text.startswith("reproduce") or text.startswith("pon ")):
            return None
        body = re.sub(r"^(reproduce|pon)\s+", "", text).strip()
        body = re.sub(r"^(la\s+)?cancion\s+", "", body).strip()
        body = re.sub(r"^una\s+cancion\s+llamada\s+", "", body).strip()
        if not body:
            return None
        match = re.match(r"(.+?)\s+de\s+(.+)$", body)
        if match:
            track = match.group(1).strip()
            artist = match.group(2).strip()
            if track and artist:
                return {"action": "music_play_track_by_artist", "track_query": track, "artist_query": artist}
        return {"action": "music_play_track", "track_query": body}

    @classmethod
    def parse_time_of_day(cls, text: str) -> str | None:
        text = normalize_text_for_intent(text)
        word_time = re.search(r"\bseis\s+treinta\b", text)
        if word_time:
            return "06:30"
        time_match = re.search(r"(?:a las|alas|de las|la alarma de las|alarma de las)?\s*(\d{1,2})(?:\s*[:.]\s*(\d{2})|\s+(\d{1,2}))?\s*(am|pm|de la manana|de la tarde|de la noche)?", text)
        if not time_match:
            return None
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or time_match.group(3) or 0)
        suffix = time_match.group(4) or ""
        if minute > 59 or hour > 23:
            return None
        if suffix in {"pm", "de la tarde", "de la noche"} and hour < 12:
            hour += 12
        if suffix in {"am", "de la manana"} and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    @classmethod
    def parse_alarm_cancel(cls, text: str) -> dict[str, Any] | None:
        if text in {"cancela todas las alarmas", "borra todas las alarmas", "elimina todas las alarmas"}:
            return {"action": "cancel_all_alarms"}
        skip_markers = (
            "solo manana",
            "manana la alarma",
            "no suenes manana",
            "omite la alarma de manana",
            "salta la alarma de manana",
        )
        permanent_markers = (
            "a partir de ahora",
            "desde ahora",
            "permanentemente",
            "borra la alarma",
            "elimina la alarma",
            "quita la alarma",
        )
        if any(marker in text for marker in skip_markers):
            time_of_day = cls.parse_time_of_day(text)
            if time_of_day:
                return {"action": "skip_alarm_once", "time_of_day": time_of_day}
        if "alarma" in text and any(marker in text for marker in permanent_markers):
            time_of_day = cls.parse_time_of_day(text)
            if time_of_day:
                return {"action": "cancel_alarm_permanent", "time_of_day": time_of_day}
        return None

    @classmethod
    def parse_int(cls, value: str) -> int | None:
        if value.isdigit():
            return int(value)
        return cls.NUMBER_WORDS.get(value)

    @classmethod
    def parse_one_shot_reminder(cls, text: str) -> dict[str, Any] | None:
        if not (text.startswith("recuerdame") or text.startswith("recordatorio")):
            return None
        minutes = 0
        hours = 0
        matched = False
        if "media hora" in text:
            minutes += 30
            matched = True
        for value in re.findall(r"\b(\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+horas?\b", text):
            amount = cls.parse_int(value)
            if amount is not None:
                hours += amount
                matched = True
        for value in re.findall(r"\b(\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+minutos?\b", text):
            amount = cls.parse_int(value)
            if amount is not None:
                minutes += amount
                matched = True
        if not matched:
            return {"action": "set_reminder", "missing": "time"}
        reminder_text = ""
        if " que " in text:
            reminder_text = text.split(" que ", 1)[1].strip()
        else:
            match = re.search(r"(?:minutos?|horas?)\s+(.+)$", text)
            if match:
                reminder_text = match.group(1).strip()
        if not reminder_text:
            return {"action": "set_reminder", "missing": "text", "delay_seconds": (hours * 3600) + (minutes * 60)}
        return {"action": "set_reminder", "delay_seconds": (hours * 3600) + (minutes * 60), "reminder_text": reminder_text}

    @classmethod
    def parse_daily_alarm(cls, text: str) -> dict[str, Any] | None:
        if not any(marker in text for marker in ("alarma", "despiertame")):
            return None
        if not any(marker in text for marker in ("todos los dias", "diario", "diaria")):
            return None
        time_of_day = cls.parse_time_of_day(text)
        if not time_of_day:
            return {"action": "set_alarm", "missing": "time"}
        return {"action": "set_alarm", "time_of_day": time_of_day, "alarm_text": ""}


class ConversationMemory:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config.get("conversation_memory", {}) if isinstance(config.get("conversation_memory"), dict) else {}
        self.logger = logger
        self.enabled = bool(self.config.get("enabled", True))
        self.max_turns = int(self.config.get("max_turns", 12))
        self.storage_path = str(self.config.get("storage_path", "/logs/conversation_memory.json"))
        self.turns: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        if not self.enabled:
            return
        try:
            raw = Path(self.storage_path).read_text(encoding="utf-8")
            data = json.loads(raw)
            self.turns = data if isinstance(data, list) else []
        except FileNotFoundError:
            self.turns = []
        except Exception as exc:
            self.logger.warning("conversation memory load failed: %s", exc)
            self.turns = []

    def save(self) -> None:
        if not self.enabled:
            return
        Path(self.storage_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.storage_path).write_text(json.dumps(self.turns[-self.max_turns :], ensure_ascii=False, indent=2), encoding="utf-8")

    def add_turn(self, user_text: str, route: str, action: str | None, assistant_text: str) -> None:
        if not self.enabled:
            return
        self.turns.append({
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "user_text": user_text,
            "route": route,
            "action": action,
            "assistant_text": make_concise_response(assistant_text, {"assistant": {"concise_responses": True, "max_response_chars": 180, "max_response_sentences": 1}}),
        })
        self.turns = self.turns[-self.max_turns :]
        self.save()

    def clear(self) -> None:
        self.turns = []
        try:
            Path(self.storage_path).unlink()
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.logger.warning("conversation memory clear failed: %s", exc)


class MusicAlarmPlayer:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.root_config = config
        self.config = config.get("scheduler", {}) if isinstance(config.get("scheduler"), dict) else {}
        self.audio_config = config.get("audio", {}) if isinstance(config.get("audio"), dict) else {}
        self.logger = logger

    def list_music_files(self) -> list[str]:
        music_dir = Path(str(self.config.get("alarm_music_dir", "/media/alarm-music")))
        extensions = {str(ext).lower() for ext in self.config.get("alarm_music_extensions", [".mp3", ".wav", ".flac", ".ogg", ".m4a"])}
        if not music_dir.exists() or not music_dir.is_dir():
            return []
        files = [str(path) for path in music_dir.rglob("*") if path.is_file() and path.suffix.lower() in extensions]
        return sorted(files)

    def choose_music_file(self) -> str | None:
        files = self.list_music_files()
        if not files:
            return None
        if self.config.get("alarm_music_random", True):
            return random.choice(files)
        return files[0]

    def play_random(self, stop_event: threading.Event, max_seconds: float | None = None) -> dict[str, Any]:
        if not self.config.get("alarm_music_enabled", True):
            return {"ok": False, "error": "alarm music disabled"}
        selected = self.choose_music_file()
        if not selected:
            self.logger.warning("alarm music unavailable: no files in %s", self.config.get("alarm_music_dir"))
            return {"ok": False, "error": "no alarm music files"}
        seconds = float(max_seconds if max_seconds is not None else self.config.get("alarm_music_max_seconds", 180))
        self.logger.info("alarm music selected file=%s max_seconds=%.1f", selected, seconds)
        result = self.play_file(selected, stop_event, seconds)
        result["file"] = selected
        return result

    def play_file(self, path: str, stop_event: threading.Event, max_seconds: float) -> dict[str, Any]:
        if sd is None:
            return {"ok": False, "error": "sounddevice unavailable"}
        output_device = self.audio_config.get("output_device")
        output_rate = int(self.audio_config.get("output_sample_rate", self.audio_config.get("sample_rate", 48000)))
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            path,
            "-t",
            str(max_seconds),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            str(output_rate),
            "pipe:1",
        ]
        proc: subprocess.Popen[bytes] | None = None
        try:
            ensure_audio_output_unmuted(self.logger)
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            chunk_frames = max(1024, output_rate // 10)
            chunk_bytes = chunk_frames * 2
            played_bytes = 0
            with sd.OutputStream(device=output_device, samplerate=output_rate, channels=1, dtype="int16") as stream:
                while not stop_event.is_set():
                    assert proc.stdout is not None
                    data = proc.stdout.read(chunk_bytes)
                    if not data:
                        break
                    if len(data) % 2:
                        data = data[:-1]
                    if not data:
                        continue
                    audio = np.frombuffer(data, dtype=np.int16).reshape(-1, 1)
                    stream.write(audio)
                    played_bytes += len(data)
            if stop_event.is_set():
                self.logger.info("alarm music cancelled file=%s", path)
                return {"ok": True, "cancelled": True, "played_seconds": played_bytes / float(output_rate * 2)}
            return {"ok": True, "cancelled": False, "played_seconds": played_bytes / float(output_rate * 2)}
        except FileNotFoundError as exc:
            self.logger.warning("alarm music failed: ffmpeg unavailable: %s", exc)
            return {"ok": False, "error": "ffmpeg unavailable"}
        except Exception as exc:
            self.logger.warning("alarm music failed file=%s error=%s", path, exc)
            return {"ok": False, "error": str(exc)}
        finally:
            if proc is not None:
                if stop_event.is_set() and proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


class MusicLibrary:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        music_cfg = config.get("music", {}) if isinstance(config.get("music"), dict) else {}
        scheduler_cfg = config.get("scheduler", {}) if isinstance(config.get("scheduler"), dict) else {}
        self.config = music_cfg or scheduler_cfg
        self.logger = logger
        self.music_dir = Path(str(music_cfg.get("library_dir", scheduler_cfg.get("alarm_music_dir", "/media/music"))))
        self.extensions = {str(ext).lower() for ext in music_cfg.get("extensions", scheduler_cfg.get("alarm_music_extensions", [".mp3", ".wav", ".flac", ".ogg", ".m4a"]))}
        self.db_path = str(music_cfg.get("db_path", "/logs/music_library.sqlite3"))
        self.fuzzy_threshold_artist = float(music_cfg.get("fuzzy_threshold_artist", 0.62))
        self.fuzzy_threshold_album = float(music_cfg.get("fuzzy_threshold_album", 0.62))
        self.fuzzy_threshold_short = float(music_cfg.get("fuzzy_threshold_short", 0.90))
        self._tracks: list[dict[str, Any]] | None = None
        self._db_conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._db_conn is None:
            self._db_conn = sqlite3.connect(self.db_path)
            self._db_conn.row_factory = sqlite3.Row
            self._db_conn.execute("PRAGMA journal_mode=WAL")
            self._db_conn.execute("PRAGMA synchronous=NORMAL")
        return self._db_conn

    def _init_db(self) -> None:
        conn = self._db()
        conn.execute("""CREATE TABLE IF NOT EXISTS tracks (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            title TEXT DEFAULT '',
            artist TEXT DEFAULT '',
            album_artist TEXT DEFAULT '',
            album TEXT DEFAULT '',
            track_number INTEGER,
            folder_artist TEXT DEFAULT '',
            filename TEXT DEFAULT '',
            folder TEXT DEFAULT '',
            duration REAL DEFAULT 0,
            bitrate INTEGER DEFAULT 0,
            genre TEXT DEFAULT '',
            year TEXT DEFAULT '',
            scanned_at REAL DEFAULT 0
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_folder_artist ON tracks(folder_artist)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_album_artist ON tracks(album_artist)")
        conn.commit()

    def scan(self) -> list[dict[str, Any]]:
        if not self.music_dir.exists():
            return []
        tracks = []
        for path in sorted(self.music_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self.extensions:
                continue
            metadata = self.read_metadata(path)
            title = metadata.get("title") or path.stem
            artist = metadata.get("artist") or ""
            album_artist = metadata.get("album_artist") or metadata.get("albumartist") or ""
            album = metadata.get("album") or metadata.get("album_title") or ""
            track_number = self.parse_track_number(metadata.get("track") or metadata.get("tracknumber") or "")
            try:
                folder_artist = path.relative_to(self.music_dir).parts[0]
            except (ValueError, IndexError):
                folder_artist = path.parent.name
            track_id = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
            duration = float(metadata.get("duration") or 0)
            bitrate = int(metadata.get("bitrate") or 0)
            genre = metadata.get("genre") or ""
            year = metadata.get("year") or metadata.get("date") or ""
            tracks.append({
                "id": track_id,
                "path": str(path),
                "title": title,
                "artist": artist,
                "album_artist": album_artist,
                "album": album,
                "track_number": track_number,
                "folder_artist": folder_artist,
                "filename": path.name,
                "folder": str(path.parent),
                "duration": duration,
                "bitrate": bitrate,
                "genre": genre,
                "year": year,
            })
        return tracks

    def scan_to_db(self) -> dict[str, Any]:
        self._init_db()
        tracks = self.scan()
        conn = self._db()
        now = time.time()
        track_paths = set()
        for track in tracks:
            track_paths.add(track["path"])
            conn.execute("""INSERT OR REPLACE INTO tracks
                (id, path, title, artist, album_artist, album, track_number, folder_artist, filename, folder, duration, bitrate, genre, year, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (track["id"], track["path"], track.get("title", ""), track.get("artist", ""),
                 track.get("album_artist", ""), track.get("album", ""), track.get("track_number"),
                 track.get("folder_artist", ""), track.get("filename", ""), track.get("folder", ""),
                 track.get("duration", 0), track.get("bitrate", 0), track.get("genre", ""), track.get("year", ""), now))
        existing = conn.execute("SELECT path FROM tracks").fetchall()
        deleted = 0
        for row in existing:
            if row["path"] not in track_paths:
                conn.execute("DELETE FROM tracks WHERE path = ?", (row["path"],))
                deleted += 1
        conn.commit()
        self._tracks = tracks
        artists = set()
        albums = set()
        for t in tracks:
            for a in (t.get("artist"), t.get("album_artist"), t.get("folder_artist")):
                if a:
                    artists.add(a)
            if t.get("album"):
                albums.add(t["album"])
        return {
            "ok": True,
            "total_tracks": len(tracks),
            "total_artists": len(artists),
            "total_albums": len(albums),
            "deleted": deleted,
            "scanned_at": now,
        }

    def stats(self) -> dict[str, Any]:
        conn = self._db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        except Exception:
            total = 0
        if total == 0:
            tracks = self.tracks()
            artists = set()
            albums = set()
            total_duration = 0.0
            for t in tracks:
                for a in (t.get("artist"), t.get("album_artist"), t.get("folder_artist")):
                    if a:
                        artists.add(a)
                if t.get("album"):
                    albums.add(t["album"])
                total_duration += float(t.get("duration") or 0)
        else:
            artists = set()
            for row in conn.execute("SELECT DISTINCT artist FROM tracks WHERE artist != '' UNION SELECT DISTINCT album_artist FROM tracks WHERE album_artist != '' UNION SELECT DISTINCT folder_artist FROM tracks WHERE folder_artist != ''"):
                if row[0]:
                    artists.add(row[0])
            albums = set()
            for row in conn.execute("SELECT DISTINCT album FROM tracks WHERE album != ''"):
                albums.add(row[0])
            total_duration = float(conn.execute("SELECT SUM(duration) FROM tracks").fetchone()[0] or 0)
        return {
            "total_tracks": total,
            "total_artists": len(artists),
            "total_albums": len(albums),
            "total_duration_seconds": round(total_duration, 1),
            "library_dir": str(self.music_dir),
            "db_path": self.db_path,
        }

    def search_artists(self, query: str) -> list[dict[str, Any]]:
        results = []
        seen = set()
        for track in self.tracks():
            for field in ("artist", "album_artist", "folder_artist"):
                val = str(track.get(field) or "")
                if not val or val in seen:
                    continue
                score = self.score_text(query, val)
                threshold = self.fuzzy_threshold_short if len(normalize_text_for_intent(query)) <= 4 else self.fuzzy_threshold_artist
                if score >= threshold:
                    results.append({"artist": val, "field": field, "score": round(score, 3)})
                    seen.add(val)
        return sorted(results, key=lambda r: r["score"], reverse=True)

    def list_albums(self, artist: str | None = None) -> list[dict[str, Any]]:
        albums = {}
        for track in self.tracks():
            album = str(track.get("album") or "")
            if not album:
                continue
            matching = True
            if artist:
                matching = self.same_artist(track, [normalize_text_for_intent(artist)])
            if matching:
                if album not in albums:
                    albums[album] = {"album": album, "artist": track.get("artist") or track.get("album_artist") or track.get("folder_artist") or "", "tracks": 0}
                albums[album]["tracks"] += 1
        return sorted(albums.values(), key=lambda a: a["album"])

    def read_metadata(self, path: Path) -> dict[str, str]:
        metadata: dict[str, str] = {}
        if mutagen is not None:
            try:
                mf = mutagen.File(str(path))
                if mf is not None:
                    tags = getattr(mf, "tags", None)
                    if tags is not None:
                        for k, v in tags.items():
                            key = str(k).lower().strip()
                            if isinstance(v, list):
                                val = str(v[0]) if v else ""
                            else:
                                val = str(v)
                            metadata[key] = val
                    info = mf.info
                    if hasattr(info, "length"):
                        metadata["duration"] = str(info.length)
                    if hasattr(info, "bitrate"):
                        metadata["bitrate"] = str(info.bitrate)
            except Exception:
                pass
        if not metadata.get("title"):
            command = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_entries", "format_tags", str(path)]
            try:
                result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=8)
                if result.returncode == 0:
                    data = json.loads(result.stdout or "{}")
                    tags = data.get("format", {}).get("tags", {}) if isinstance(data, dict) else {}
                    for k, v in tags.items():
                        key = str(k).lower()
                        if key not in metadata:
                            metadata[key] = str(v)
            except Exception:
                pass
        if not metadata.get("title"):
            metadata["title"] = path.stem
        return metadata

    def tracks(self) -> list[dict[str, Any]]:
        if self._tracks is None:
            conn = self._db()
            try:
                count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            except Exception:
                count = 0
            if count > 0:
                rows = conn.execute("SELECT * FROM tracks ORDER BY path").fetchall()
                self._tracks = [dict(row) for row in rows]
            else:
                self._tracks = self.scan()
        return self._tracks

    @staticmethod
    def parse_track_number(value: str) -> int | None:
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else None

    @staticmethod
    def score_text(query: str, value: str) -> float:
        q = normalize_text_for_intent(query)
        v = normalize_text_for_intent(value)
        if not q or not v:
            return 0.0
        if q == v:
            return 1.0
        if q in v:
            return 0.92 if len(q) >= 5 else 0.82
        return difflib.SequenceMatcher(None, q, v).ratio()

    def search_tracks(self, track_query: str, artist_query: str | None = None) -> list[dict[str, Any]]:
        query_norm = normalize_text_for_intent(track_query)
        artist_norm = normalize_text_for_intent(artist_query or "")
        min_score = 0.86 if len(query_norm) <= 5 else 0.68
        matches = []
        for track in self.tracks():
            title_score = self.score_text(track_query, str(track.get("title") or ""))
            file_score = self.score_text(track_query, Path(str(track.get("filename") or "")).stem)
            base_score = max(title_score + 0.08, file_score)
            if base_score < min_score:
                continue
            artist_score = 0.0
            if artist_norm:
                artist_score = max(
                    self.score_text(artist_query or "", str(track.get("artist") or "")),
                    self.score_text(artist_query or "", str(track.get("album_artist") or "")),
                    self.score_text(artist_query or "", str(track.get("folder_artist") or "")),
                )
                if artist_score < 0.55:
                    continue
            score = min(1.0, base_score + (artist_score * 0.25 if artist_norm else 0.0))
            item = dict(track)
            item["score"] = score
            item["title_score"] = title_score
            item["artist_score"] = artist_score
            matches.append(item)
        return sorted(matches, key=lambda item: item.get("score", 0), reverse=True)

    def get_track_by_id(self, track_id: str) -> dict[str, Any] | None:
        for track in self.tracks():
            if track.get("id") == track_id:
                return track
        return None

    def get_track_context_queue(self, track_id: str) -> list[dict[str, Any]]:
        initial = self.get_track_by_id(track_id)
        if not initial:
            return []
        queue = [initial]
        used = {track_id}
        album = normalize_text_for_intent(str(initial.get("album") or ""))
        artist_values = [initial.get("artist"), initial.get("album_artist"), initial.get("folder_artist")]
        artist_values = [normalize_text_for_intent(str(v)) for v in artist_values if v]
        if album:
            album_tracks = [t for t in self.tracks() if normalize_text_for_intent(str(t.get("album") or "")) == album and self.same_artist(t, artist_values)]
            album_tracks = sorted(album_tracks, key=lambda t: (t.get("track_number") is None, t.get("track_number") or 9999, str(t.get("filename"))))
            initial_number = initial.get("track_number") or 0
            for track in album_tracks:
                if track["id"] not in used and ((track.get("track_number") or 0) >= initial_number):
                    queue.append(track)
                    used.add(track["id"])
        folder = str(initial.get("folder") or "")
        folder_tracks = [t for t in self.tracks() if str(t.get("folder") or "") == folder]
        for track in sorted(folder_tracks, key=lambda t: str(t.get("filename"))):
            if track["id"] not in used:
                queue.append(track)
                used.add(track["id"])
        artist_tracks = [t for t in self.tracks() if self.same_artist(t, artist_values)]
        for track in sorted(artist_tracks, key=lambda t: (str(t.get("album") or ""), t.get("track_number") or 9999, str(t.get("filename")))):
            if track["id"] not in used:
                queue.append(track)
                used.add(track["id"])
        return queue

    @staticmethod
    def same_artist(track: dict[str, Any], artist_values: list[str]) -> bool:
        if not artist_values:
            return False
        fields = [track.get("artist"), track.get("album_artist"), track.get("folder_artist")]
        normalized = [normalize_text_for_intent(str(v)) for v in fields if v]
        return any(a and any(a == b or a in b or b in a for b in normalized) for a in artist_values)


class MusicPlayer:
    def __init__(self, config: dict[str, Any], logger: logging.Logger, library: MusicLibrary):
        self.config = config
        self.audio_config = config.get("audio", {}) if isinstance(config.get("audio"), dict) else {}
        self.logger = logger
        self.library = library
        self.state_path = "/logs/music_queue.json"
        self.stop_path = "/logs/music_stop.flag"
        self.next_path = "/logs/music_next.flag"
        self.stop_event = threading.Event()

    def save_state(self, queue: list[dict[str, Any]], index: int = 0, now_playing: dict[str, Any] | None = None) -> None:
        payload = {"queue": queue, "index": index, "now_playing": now_playing, "updated_at": dt.datetime.now().isoformat(timespec="seconds")}
        write_text_file(self.state_path, json.dumps(payload, ensure_ascii=False))

    def read_state(self) -> dict[str, Any]:
        try:
            return json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        except Exception:
            return {"queue": [], "index": 0, "now_playing": None}

    def queue_summary(self) -> dict[str, Any]:
        state = self.read_state()
        queue = state.get("queue", []) if isinstance(state.get("queue"), list) else []
        index = int(state.get("index") or 0)
        return {"now_playing": state.get("now_playing"), "queue_length": max(0, len(queue) - index), "next_tracks": queue[index + 1:index + 11]}

    def request_stop(self) -> None:
        write_text_file(self.stop_path, "stop")

    def request_next(self) -> None:
        write_text_file(self.next_path, "next")

    def clear_control_flags(self) -> None:
        for path in (self.stop_path, self.next_path):
            try:
                Path(path).unlink()
            except FileNotFoundError:
                pass

    def start_queue_process(self, queue: list[dict[str, Any]]) -> dict[str, Any]:
        self.clear_control_flags()
        self.save_state(queue, index=0, now_playing=None)
        command = [sys.executable, "/app/voice_gateway.py", "--config", os.environ.get("VOICE_GATEWAY_CONFIG", "/app/config.yaml"), "--music-run-queue"]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"ok": True, "queue_length": len(queue), "first": queue[0] if queue else None}

    def play_queue_from_state(self) -> dict[str, Any]:
        state = self.read_state()
        queue = state.get("queue", []) if isinstance(state.get("queue"), list) else []
        if not queue:
            return {"ok": False, "error": "empty queue"}
        for index, track in enumerate(queue):
            if Path(self.stop_path).exists():
                break
            self.save_state(queue, index=index, now_playing=track)
            result = self.play_file(str(track.get("path")))
            if Path(self.stop_path).exists():
                break
            if Path(self.next_path).exists():
                try:
                    Path(self.next_path).unlink()
                except FileNotFoundError:
                    pass
                continue
            if not result.get("ok"):
                self.logger.warning("music queue skipped failed track=%s error=%s", track.get("path"), result.get("error"))
        self.save_state([], index=0, now_playing=None)
        self.clear_control_flags()
        return {"ok": True}

    def play_file(self, path: str) -> dict[str, Any]:
        if sd is None:
            return {"ok": False, "error": "sounddevice unavailable"}
        allowed_dirs = ("/media/music", "/media/alarm-music")
        resolved = str(Path(path).resolve())
        if not any(resolved.startswith(d) for d in allowed_dirs):
            self.logger.error("music play_file path outside allowed dirs: %s", path)
            return {"ok": False, "error": f"path not in allowed dirs: {path}"}
        if not Path(path).exists():
            self.logger.error("music play_file path does not exist: %s", path)
            return {"ok": False, "error": f"path not found: {path}"}
        self.logger.info("music play_file path=%s size=%s", path, Path(path).stat().st_size)
        output_device = self.audio_config.get("output_device")
        output_rate = int(self.audio_config.get("output_sample_rate", self.audio_config.get("sample_rate", 48000)))
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(output_rate), "pipe:1"]
        proc = None
        try:
            ensure_audio_output_unmuted(self.logger)
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            chunk_bytes = max(1024, output_rate // 10) * 2
            with sd.OutputStream(device=output_device, samplerate=output_rate, channels=1, dtype="int16") as stream:
                while not Path(self.stop_path).exists() and not Path(self.next_path).exists():
                    assert proc.stdout is not None
                    data = proc.stdout.read(chunk_bytes)
                    if not data:
                        break
                    if len(data) % 2:
                        data = data[:-1]
                    stream.write(np.frombuffer(data, dtype=np.int16).reshape(-1, 1))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()


class ReminderScheduler:
    def __init__(self, config: dict[str, Any], logger: logging.Logger, speak_callback: Any | None = None, music_player: MusicAlarmPlayer | None = None):
        self.config = config.get("scheduler", {}) if isinstance(config.get("scheduler"), dict) else {}
        self.logger = logger
        self.speak_callback = speak_callback
        self.music_player = music_player
        self.enabled = bool(self.config.get("enabled", True))
        self.db_path = str(self.config.get("db_path", "/logs/reminders.sqlite3"))
        self.timezone = str(self.config.get("timezone", "America/Chicago"))
        self.check_interval_seconds = float(self.config.get("check_interval_seconds", 1))
        self.alarm_repeat_seconds = float(self.config.get("alarm_repeat_seconds", 20))
        self.alarm_max_repeats = int(self.config.get("alarm_max_repeats", 5))
        self.default_alarm_sound_text = str(self.config.get("default_alarm_sound_text", "Alarma."))
        self.default_reminder_prefix = str(self.config.get("default_reminder_prefix", "Recordatorio:"))
        self._stop_event = threading.Event()
        self._active_alarm_stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.init_db()

    def now(self) -> dt.datetime:
        try:
            return dt.datetime.now(ZoneInfo(self.timezone))
        except Exception:
            return dt.datetime.now().astimezone()

    def init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT,
                    text TEXT,
                    fire_at TEXT,
                    recurrence TEXT,
                    enabled INTEGER,
                    created_at TEXT,
                    last_fired_at TEXT,
                    fire_count INTEGER,
                    time_of_day TEXT,
                    skip_dates TEXT,
                    label TEXT,
                    deleted_at TEXT
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()}
            migrations = {
                "time_of_day": "ALTER TABLE reminders ADD COLUMN time_of_day TEXT",
                "skip_dates": "ALTER TABLE reminders ADD COLUMN skip_dates TEXT",
                "label": "ALTER TABLE reminders ADD COLUMN label TEXT",
                "deleted_at": "ALTER TABLE reminders ADD COLUMN deleted_at TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    conn.execute(statement)
            conn.execute("UPDATE reminders SET time_of_day=substr(fire_at, 12, 5) WHERE kind='alarm' AND (time_of_day IS NULL OR time_of_day='') AND fire_at IS NOT NULL")
            conn.execute("UPDATE reminders SET skip_dates='[]' WHERE kind='alarm' AND (skip_dates IS NULL OR skip_dates='')")

    def add_one_shot_reminder(self, text: str, fire_at: dt.datetime) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO reminders(kind, text, fire_at, recurrence, enabled, created_at, last_fired_at, fire_count, time_of_day, skip_dates, label, deleted_at) VALUES (?, ?, ?, ?, 1, ?, NULL, 0, NULL, '[]', NULL, NULL)",
                ("reminder", text.strip(), fire_at.isoformat(timespec="seconds"), "none", self.now().isoformat(timespec="seconds")),
            )
            return int(cur.lastrowid)

    def add_daily_alarm(self, time_of_day: str, text: str = "") -> int:
        hour, minute = [int(part) for part in time_of_day.split(":", 1)]
        now = self.now()
        fire_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if fire_at <= now:
            fire_at += dt.timedelta(days=1)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO reminders(kind, text, fire_at, recurrence, enabled, created_at, last_fired_at, fire_count, time_of_day, skip_dates, label, deleted_at) VALUES (?, ?, ?, ?, 1, ?, NULL, 0, ?, '[]', NULL, NULL)",
                ("alarm", text.strip(), fire_at.isoformat(timespec="seconds"), "daily", now.isoformat(timespec="seconds"), time_of_day),
            )
            return int(cur.lastrowid)

    def list_active_reminders(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM reminders WHERE enabled=1 ORDER BY fire_at ASC").fetchall()
            return [dict(row) for row in rows]

    def disable_reminder(self, reminder_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE reminders SET enabled=0 WHERE id=?", (reminder_id,))

    def disable_all(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE reminders SET enabled=0 WHERE enabled=1")
            return int(cur.rowcount or 0)

    def cancel_all_alarms(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE reminders SET enabled=0, deleted_at=? WHERE enabled=1 AND kind='alarm'", (self.now().isoformat(timespec="seconds"),))
            return int(cur.rowcount or 0)

    def find_daily_alarm_by_time(self, time_of_day: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM reminders WHERE enabled=1 AND kind='alarm' AND recurrence='daily' AND time_of_day=? ORDER BY id DESC LIMIT 1", (time_of_day,)).fetchone()
            return dict(row) if row else None

    def cancel_alarm_permanent(self, time_of_day: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE reminders SET enabled=0, deleted_at=? WHERE enabled=1 AND kind='alarm' AND recurrence='daily' AND time_of_day=?", (self.now().isoformat(timespec="seconds"), time_of_day))
            return int(cur.rowcount or 0) > 0

    def skip_alarm_once(self, time_of_day: str, date_value: dt.date) -> bool:
        alarm = self.find_daily_alarm_by_time(time_of_day)
        if not alarm:
            return False
        skip_dates = self._parse_skip_dates(alarm.get("skip_dates"))
        date_text = date_value.isoformat()
        if date_text not in skip_dates:
            skip_dates.append(date_text)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE reminders SET skip_dates=? WHERE id=?", (json.dumps(skip_dates), int(alarm["id"])))
        return True

    @staticmethod
    def _parse_skip_dates(value: Any) -> list[str]:
        try:
            data = json.loads(value or "[]")
            return [str(item) for item in data] if isinstance(data, list) else []
        except Exception:
            return []

    def due_reminders(self, now: dt.datetime | None = None) -> list[dict[str, Any]]:
        current = now or self.now()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM reminders WHERE enabled=1 AND fire_at <= ? ORDER BY fire_at ASC", (current.isoformat(timespec="seconds"),)).fetchall()
            return [dict(row) for row in rows]

    def mark_fired(self, reminder_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE reminders SET last_fired_at=?, fire_count=fire_count+1 WHERE id=?", (self.now().isoformat(timespec="seconds"), reminder_id))

    def reschedule_daily(self, reminder_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT fire_at, time_of_day FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            if not row:
                return
            if row[1]:
                hour, minute = [int(part) for part in str(row[1]).split(":", 1)]
                now = self.now()
                fire_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + dt.timedelta(days=1)
            else:
                fire_at = dt.datetime.fromisoformat(str(row[0])) + dt.timedelta(days=1)
            conn.execute("UPDATE reminders SET fire_at=?, enabled=1 WHERE id=?", (fire_at.isoformat(timespec="seconds"), reminder_id))

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop, name="ReminderScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._active_alarm_stop.set()

    def cancel_active_alarm(self) -> None:
        self._active_alarm_stop.set()

    def _run_loop(self) -> None:
        self.logger.info("scheduler started timezone=%s db=%s", self.timezone, self.db_path)
        while not self._stop_event.is_set():
            try:
                for reminder in self.due_reminders():
                    self._fire(reminder)
            except Exception as exc:
                self.logger.warning("scheduler loop failed: %s", exc)
            self._stop_event.wait(self.check_interval_seconds)

    def _fire(self, reminder: dict[str, Any]) -> None:
        reminder_id = int(reminder["id"])
        kind = str(reminder.get("kind") or "reminder")
        text = str(reminder.get("text") or "").strip()
        if kind == "alarm":
            speak_text = f"Alarma: {text}" if text else self.default_alarm_sound_text
            today = self.now().date().isoformat()
            if today in self._parse_skip_dates(reminder.get("skip_dates")):
                self.logger.info("alarm skipped id=%s date=%s time_of_day=%s", reminder_id, today, reminder.get("time_of_day"))
                self.mark_fired(reminder_id)
                self.reschedule_daily(reminder_id)
                return
            self._active_alarm_stop.clear()
            for _ in range(max(1, self.alarm_max_repeats)):
                if self._active_alarm_stop.is_set() or self._stop_event.is_set():
                    break
                if self.speak_callback:
                    self.speak_callback(speak_text)
                music_ok = False
                if self.music_player is not None and not self._active_alarm_stop.is_set():
                    music_result = self.music_player.play_random(self._active_alarm_stop)
                    music_ok = bool(music_result.get("ok"))
                if not music_ok and self.speak_callback and not self._active_alarm_stop.is_set():
                    self.speak_callback(speak_text)
                if self._active_alarm_stop.wait(self.alarm_repeat_seconds):
                    break
            self.mark_fired(reminder_id)
            if str(reminder.get("recurrence")) == "daily":
                self.reschedule_daily(reminder_id)
            else:
                self.disable_reminder(reminder_id)
            return
        speak_text = f"{self.default_reminder_prefix} {text}".strip()
        if self.speak_callback:
            self.speak_callback(speak_text)
        self.mark_fired(reminder_id)
        self.disable_reminder(reminder_id)


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

    def input_backend(self) -> str:
        return str(self.config.get("input_backend", "sounddevice")).strip().lower()

    def input_alsa_device(self) -> str:
        return str(self.config.get("input_alsa_device", "plughw:1,0")).strip()

    def is_alsa_arecord_input(self) -> bool:
        return self.input_backend() == "alsa_arecord"

    def ensure_input_gain(self) -> None:
        if not self.is_alsa_arecord_input():
            return
        try:
            result = subprocess.run(
                ["amixer", "-c", "1", "sset", "Mic", "100%"],
                check=False, capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                self.logger.info("alsa input mic gain ok: amixer -c 1 sset Mic 100%%")
            else:
                self.logger.warning("alsa input mic gain failed: %r", result.stderr.strip())
        except Exception as exc:
            self.logger.warning("alsa input mic gain failed: %r", exc)

    def record_fixed_window(self, path: str, seconds: float) -> dict[str, Any]:
        sample_rate = int(self.config.get("sample_rate", 16000))
        channels = int(self.config.get("channels", 1))
        if self.is_alsa_arecord_input():
            self.ensure_input_gain()
            alsa_device = self.input_alsa_device()
            duration = max(1, int(math.ceil(seconds)))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            args = ["arecord", "-D", alsa_device, "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels), "-d", str(duration), path]
            self.logger.info("alsa arecord input device=%s rate=%s channels=%s seconds=%s path=%s", alsa_device, sample_rate, channels, duration, path)
            try:
                with open("/logs/audio_input.lock", "w") as lock_file:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=duration + 5)
            except Exception as exc:
                self.logger.warning("alsa arecord failed: %r", exc)
                return {"ok": False, "path": path, "error": repr(exc), "backend": "alsa_arecord", "alsa_device": alsa_device}
            if result.returncode != 0:
                error = (result.stderr or result.stdout or "").strip()
                self.logger.warning("alsa arecord failed returncode=%s error=%r", result.returncode, error)
                return {"ok": False, "path": path, "error": error, "backend": "alsa_arecord", "alsa_device": alsa_device}
            try:
                audio, actual_rate = wav_read_int16(path)
            except Exception as exc:
                self.logger.warning("alsa arecord WAV read failed: %r", exc)
                return {"ok": False, "path": path, "error": repr(exc), "backend": "alsa_arecord", "alsa_device": alsa_device}
            return {"ok": True, "path": path, "audio": audio, "sample_rate": actual_rate, "channels": channels, "backend": "alsa_arecord", "alsa_device": alsa_device}
        if sd is None:
            raise RuntimeError("sounddevice is unavailable")
        input_device = self.config.get("input_device")
        frames = int(sample_rate * seconds)
        self.logger.info("sounddevice input device=%s rate=%s channels=%s seconds=%.2f path=%s", input_device, sample_rate, channels, seconds, path)
        raw = sd.rec(frames, samplerate=sample_rate, channels=channels, dtype="int16", device=input_device)
        sd.wait()
        audio_i16 = np.asarray(raw, dtype=np.int16).reshape(-1)
        wav_write_int16(path, audio_i16, sample_rate, channels=channels)
        return {"ok": True, "path": path, "audio": audio_i16, "sample_rate": sample_rate, "channels": channels, "backend": "sounddevice", "alsa_device": None}

    def audio_input_test(self, seconds: float = 5.0) -> dict[str, Any]:
        path = "/logs/audio_input_test.wav"
        record = self.record_fixed_window(path, seconds)
        if not record.get("ok"):
            return {"ok": False, "backend": self.input_backend(), "alsa_device": self.input_alsa_device() if self.is_alsa_arecord_input() else None, "path": path, "error": record.get("error")}
        audio_i16 = np.asarray(record.get("audio", np.zeros(0, dtype=np.int16)), dtype=np.int16).reshape(-1)
        sample_rate = int(record.get("sample_rate", self.config.get("sample_rate", 16000)))
        channels = int(record.get("channels", self.config.get("channels", 1)))
        stats = audio_level_stats(audio_i16)
        duration = float(audio_i16.size) / float(sample_rate) if sample_rate else 0.0
        return {
            "ok": True,
            "backend": record.get("backend"),
            "alsa_device": record.get("alsa_device"),
            "path": path,
            "peak": stats["peak"],
            "rms": stats["rms"],
            "duration": duration,
            "sample_rate": sample_rate,
            "channels": channels,
        }

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
        try:
            sd.play(tone, samplerate=output_rate, device=output_device, blocking=True)
        except Exception as _e:
            self.logger.error("play_test_tone audio error: %s", _e)

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
        try:
            sd.play(rendered.astype(np.float32), samplerate=output_rate, device=output_device, blocking=True)
        except Exception as _e:
            self.logger.error("play_wav audio error: %s", _e)

    def record_once(self) -> dict[str, Any]:
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
        vad_pregain = float(self.config.get("vad_pregain", 1.0))
        self.logger.info("record-once waiting backend=%s input_device=%s alsa_device=%s rate=%s frame_ms=%s max_seconds=%s vad_pregain=%.1f", self.input_backend(), input_device, self.input_alsa_device() if self.is_alsa_arecord_input() else None, sample_rate, frame_ms, max_record_seconds, vad_pregain)
        if self.is_alsa_arecord_input():
            record = self.record_fixed_window("/logs/last_record_once_raw.wav", max_record_seconds)
            if not record.get("ok"):
                return {"ok": False, "path": "/logs/last_discarded.wav", "error": record.get("error"), "total_ms": 0, "voice_ms": 0, "final_silence_ms": 0}
            audio_all = np.asarray(record.get("audio", np.zeros(0, dtype=np.int16)), dtype=np.int16).reshape(-1)
            for offset in range(0, audio_all.size - frame_samples + 1, frame_samples):
                mono = audio_all[offset:offset + frame_samples]
                all_frames.append(mono.copy())
                gained = np.clip(mono.astype(np.float64) * vad_pregain, -32767, 32767).astype(np.int16)
                is_speech = vad.is_speech(gained.tobytes(), sample_rate)
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
        else:
            if sd is None:
                raise RuntimeError("sounddevice is unavailable")
            with sd.InputStream(device=input_device, samplerate=sample_rate, channels=channels, dtype="int16", blocksize=frame_samples) as stream:
                for _ in range(max_frames):
                    frame, _overflowed = stream.read(frame_samples)
                    mono = frame[:, 0] if frame.ndim > 1 else frame
                    mono = np.asarray(mono, dtype=np.int16)
                    all_frames.append(mono.copy())
                    gained = np.clip(mono.astype(np.float64) * vad_pregain, -32767, 32767).astype(np.int16)
                    is_speech = vad.is_speech(gained.tobytes(), sample_rate)
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
        gain = min(float(self.config.get("command_input_gain", self.config.get("input_gain", 1.0))), float(self.config.get("max_input_gain", 16.0)))
        max_peak = float(self.config.get("max_input_peak", 0.85))
        gained_i16 = apply_audio_gain_int16(audio_i16, gain, max_peak=max_peak, logger=self.logger, label="record-once diagnostic")
        total_ms = int(audio_i16.size / sample_rate * 1000) if audio_i16.size else 0
        voice_ms = voiced_frames * frame_ms
        final_silence_ms = trailing_silence_frames * frame_ms
        ok = started and voice_ms >= min_voice_ms
        path = "/logs/last_utterance.wav" if ok else "/logs/last_discarded.wav"
        wav_write(path, audio_f32, sample_rate)
        if ok:
            wav_write_int16("/logs/last_utterance_gain.wav", gained_i16, sample_rate, channels=1)
        self.logger.info("record-once result ok=%s total_ms=%s voice_ms=%s final_silence_ms=%s path=%s", ok, total_ms, voice_ms, final_silence_ms, path)
        if not ok:
            self.logger.warning("record-once discarded: insufficient voice (%sms < %sms)", voice_ms, min_voice_ms)
        return {"ok": ok, "path": path, "total_ms": total_ms, "voice_ms": voice_ms, "final_silence_ms": final_silence_ms}

    def wake_debug_record(self) -> dict[str, Any]:
        sample_rate = int(self.config.get("sample_rate", 16000))
        channels = int(self.config.get("channels", 1))
        input_device = self.config.get("input_device")
        seconds = 10
        gain = min(float(self.config.get("wake_input_gain", self.config.get("input_gain", 1.0))), float(self.config.get("max_input_gain", 16.0)))
        self.logger.info("wake-debug-record backend=%s input_device=%s alsa_device=%s rate=%s channels=%s seconds=%s gain=%.2f", self.input_backend(), input_device, self.input_alsa_device() if self.is_alsa_arecord_input() else None, sample_rate, channels, seconds, gain)
        record = self.record_fixed_window("/logs/wake_debug_raw.wav", seconds)
        if not record.get("ok"):
            return {"ok": False, "error": record.get("error"), "raw_path": "/logs/wake_debug_raw.wav", "gain_path": "/logs/wake_debug_gain.wav", "backend": self.input_backend(), "alsa_device": self.input_alsa_device() if self.is_alsa_arecord_input() else None}
        raw_i16 = np.asarray(record.get("audio", np.zeros(0, dtype=np.int16)), dtype=np.int16).reshape(-1)
        gain_i16 = apply_audio_gain_int16(raw_i16, gain, logger=self.logger, label="wake-debug-record")
        wav_write_int16("/logs/wake_debug_gain.wav", gain_i16, sample_rate, channels=channels)
        result = {
            "ok": True,
            "backend": record.get("backend"),
            "alsa_device": record.get("alsa_device"),
            "raw_path": "/logs/wake_debug_raw.wav",
            "gain_path": "/logs/wake_debug_gain.wav",
            "raw": audio_level_stats(raw_i16),
            "gain": audio_level_stats(gain_i16),
            "gain_value": gain,
        }
        self.logger.info("wake-debug-record result=%s", result)
        return result

    def record_wake_fallback_window(self, path: str, window_seconds: float, min_voice_ms: int) -> dict[str, Any]:
        sample_rate = int(self.config.get("sample_rate", 16000))
        channels = int(self.config.get("channels", 1))
        frame_ms = int(self.config.get("frame_ms", 30))
        input_device = self.config.get("input_device")
        frame_samples = max(1, int(sample_rate * frame_ms / 1000))
        vad_cfg = self.root_config.get("vad", {}) if isinstance(self.root_config.get("vad"), dict) else {}
        vad = webrtcvad.Vad(int(vad_cfg.get("aggressiveness", 2)))
        max_frames = max(1, int(window_seconds * 1000 / frame_ms))
        voiced_frames = 0
        frames_out: list[np.ndarray] = []
        vad_pregain = float(self.config.get("vad_pregain", 1.0))
        self.logger.info("wake-fallback record window backend=%s input_device=%s alsa_device=%s rate=%s seconds=%.2f vad_pregain=%.1f", self.input_backend(), input_device, self.input_alsa_device() if self.is_alsa_arecord_input() else None, sample_rate, window_seconds, vad_pregain)
        if self.is_alsa_arecord_input():
            record = self.record_fixed_window(path, window_seconds)
            if not record.get("ok"):
                return {"ok": False, "path": path, "voice_ms": 0, "stats": {"peak": 0, "rms": 0}, "error": record.get("error")}
            audio_all = np.asarray(record.get("audio", np.zeros(0, dtype=np.int16)), dtype=np.int16).reshape(-1)
            for offset in range(0, audio_all.size - frame_samples + 1, frame_samples):
                mono = audio_all[offset:offset + frame_samples]
                frames_out.append(mono.copy())
                gained = np.clip(mono.astype(np.float64) * vad_pregain, -32767, 32767).astype(np.int16)
                if vad.is_speech(gained.tobytes(), sample_rate):
                    voiced_frames += 1
        else:
            if sd is None:
                raise RuntimeError("sounddevice is unavailable")
            with sd.InputStream(device=input_device, samplerate=sample_rate, channels=channels, dtype="int16", blocksize=frame_samples) as stream:
                for _ in range(max_frames):
                    frame, _overflowed = stream.read(frame_samples)
                    mono = frame[:, 0] if frame.ndim > 1 else frame
                    mono = np.asarray(mono, dtype=np.int16)
                    frames_out.append(mono.copy())
                    gained = np.clip(mono.astype(np.float64) * vad_pregain, -32767, 32767).astype(np.int16)
                    if vad.is_speech(gained.tobytes(), sample_rate):
                        voiced_frames += 1
        audio_i16 = np.concatenate(frames_out) if frames_out else np.zeros(0, dtype=np.int16)
        raw_path = path.replace(".wav", "_raw.wav")
        gain_path = path.replace(".wav", "_gain.wav")
        wav_write_int16(raw_path, audio_i16, sample_rate, channels=1)
        wake_gain = min(float(self.config.get("wake_input_gain", self.config.get("input_gain", 1.0))), float(self.config.get("max_input_gain", 16.0)))
        gained_i16 = apply_audio_gain_int16(audio_i16, wake_gain, max_peak=float(self.config.get("max_input_peak", 0.85)), logger=self.logger, label="wake-fallback-gain")
        wav_write_int16(gain_path, gained_i16, sample_rate, channels=1)
        wav_write_int16(path, audio_i16, sample_rate, channels=1)
        voice_ms = voiced_frames * frame_ms
        stats = audio_level_stats(audio_i16)
        ok = voice_ms >= min_voice_ms
        self.logger.info("wake-fallback recorded ok=%s voice_ms=%s path=%s peak=%.4f rms=%.4f", ok, voice_ms, path, stats["peak"], stats["rms"])
        return {"ok": ok, "path": path, "voice_ms": voice_ms, "stats": stats}


class TokenFirewall:
    FILLERS = {"eh", "mmm", "mm", "ah", "ok", "si", "aja", "este"}
    CANCEL_ALIASES = {
        "cancelar", "cancela", "cancele", "cancel", "canselar", "cansela", "kanselar",
        "yancelan", "pencilar", "cantele", "cantale", "salir", "terminar", "termina",
        "para", "parale", "alto", "detente", "detener", "no importa", "olvidalo", "cerrar", "cierra",
    }
    SYSTEM_STATUS_WORDS = {"estado", "esto", "este", "esta", "estatus"}
    OPENCLAW_STATUS_ALIASES = (
        "estado de openclaw",
        "estado de open cloud",
        "estado de open claw",
        "esta en el open clamp",
        "estadle de la open plan",
        "estamos de otro june",
        "estal y ropa el pleno",
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
        "estaba en el sistema": "system_status",
        "esto es del sistema": "system_status",
        "esto del sistema": "system_status",
        "este es del sistema": "system_status",
        "esta es del sistema": "system_status",
        "estoy del sistema": "system_status",
        "estado del sistema": "system_status",
        "estado sistema": "system_status",
        "estatus del sistema": "system_status",
        "estado del servidor": "system_status",
        "estado servidor": "system_status",
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
    def decision(route: str, raw_text: str, normalized_text: str, action: str | None = None, reason: str | None = None, requires_confirmation: bool = False, matched_alias: str | None = None, fuzzy_score: float | None = None) -> RouteDecision:
        return RouteDecision(route, normalized_text, action=action, reason=reason, requires_confirmation=requires_confirmation, raw_text=raw_text, normalized_text=normalized_text, matched_alias=matched_alias, fuzzy_score=fuzzy_score)

    def match_cancel_alias(self, text: str) -> tuple[str | None, float]:
        if not text:
            return None, 0.0
        words = text.split()
        best_alias = None
        best_score = 0.0
        for alias in self.CANCEL_ALIASES:
            score = 1.0 if text == alias else difflib.SequenceMatcher(None, text, alias).ratio()
            if score > best_score:
                best_alias = alias
                best_score = score
        if len(words) <= 3 and best_score >= 0.62:
            return best_alias, best_score
        return None, best_score

    def match_openclaw_status(self, text: str) -> str | None:
        if "openclaw" in text:
            if any(keyword in text for keyword in ("estado", "estatus", "revisar", "verifica", "sistema", "servidor")):
                return "keyword_openclaw_status"
        for alias in self.OPENCLAW_STATUS_ALIASES:
            normalized_alias = self.normalize(alias)
            if text == normalized_alias or difflib.SequenceMatcher(None, text, normalized_alias).ratio() >= 0.82:
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
        assistant_command = AssistantCommandParser.parse(raw_text)
        if assistant_command:
            action = str(assistant_command.get("action"))
            if action in {"identity", "set_alarm", "set_reminder", "list_reminders", "cancel_alarm", "cancel_all_reminders", "clear_memory", "cancel_alarm_permanent", "skip_alarm_once", "cancel_all_alarms", "music_play_track", "music_play_track_by_artist", "music_now_playing", "music_next", "music_stop", "music_pending_track_answer"}:
                return self.decision("local", raw_text, text, action=action, reason="assistant_core", matched_alias=action)
            if action.startswith("unsupported_"):
                return self.decision("local", raw_text, text, action=action, reason="assistant_core_unsupported", matched_alias=action)
        cancel_alias, cancel_score = self.match_cancel_alias(text)
        if cancel_alias:
            reason = "cancel_alias" if cancel_score >= 1.0 else "cancel_fuzzy_alias"
            return self.decision("local", raw_text, text, action="cancel", reason=reason, matched_alias=cancel_alias, fuzzy_score=cancel_score)
        if "sistema" in words and any(word in self.SYSTEM_STATUS_WORDS for word in words):
            return self.decision("local", raw_text, text, action="system_status", reason="system_status_keyword", matched_alias="sistema")
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
        if action == "openclaw_status":
            return {"ok": True, "speak": "Estado local disponible en logs; consulta administrativa preparada."}
        if action == "system_status":
            return {"ok": True, "speak": "El gateway de voz está activo. OpenClaw está accesible."}
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

    @property
    def dry_run(self) -> bool:
        return bool(self.config.get("dry_run", True))

    @property
    def max_prompt_chars(self) -> int:
        return int(self.config.get("max_prompt_chars", 2000))

    def validate_prompt(self, text: str) -> tuple[bool, str, str | None]:
        clean = (text or "").strip()
        if not clean:
            return False, "", "empty openclaw prompt; text not sent"
        if len(clean) > self.max_prompt_chars:
            return False, clean, f"openclaw prompt too long ({len(clean)} > {self.max_prompt_chars}); text not sent"
        return True, clean, None

    def write_prompt_audit(self, prompt: str, response: str = "", error: str = "") -> None:
        write_text_file("/logs/last_openclaw_prompt.txt", prompt)
        write_text_file("/logs/last_openclaw_response.txt", response)
        write_text_file("/logs/last_openclaw_error.txt", error)

    def send_prompt(self, text: str) -> dict[str, Any]:
        if not self.config.get("enabled", True):
            return {"ok": False, "error": "openclaw disabled"}
        if not self.breaker.allow():
            return {"ok": False, "error": "openclaw circuit breaker open"}
        valid, prompt, error = self.validate_prompt(text)
        if not valid:
            self.write_prompt_audit(prompt, error=error or "invalid prompt")
            return {"ok": False, "error": error or "invalid openclaw prompt"}
        if self.dry_run:
            self.logger.info("openclaw dry-run confirmed=true dry_run=true prompt=%r", prompt)
            self.write_prompt_audit(prompt, response="dry_run=true", error="")
            return {"ok": True, "dry_run": True, "confirmed": True, "prompt": prompt, "speak": "Modo prueba. No envié nada."}
        if websocket is None:
            self.write_prompt_audit(prompt, error="websocket-client unavailable")
            return {"ok": False, "error": "websocket-client unavailable"}
        rpc_method = self.config.get("rpc_method")
        if not rpc_method:
            self.logger.error("OpenClaw RPC method not configured; refusing to send prompt")
            error = "OpenClaw todavía no tiene método RPC configurado."
            self.write_prompt_audit(prompt, error=error)
            return {"ok": False, "error": error}
        url = self.config.get("url", "ws://openclaw:18789")
        timeout = float(self.config.get("timeout_seconds", 120))
        payload = {"method": rpc_method, "params": {"agentId": self.config.get("agent_default", "main"), "message": text}}
        raw = ""
        ws = None
        try:
            ws = websocket.create_connection(url, timeout=timeout)
            ws.send(json.dumps(payload))
            raw = ws.recv()
            self.breaker.success()
            self.write_prompt_audit(prompt, response=raw, error="")
            return {"ok": True, "raw": raw}
        except Exception as exc:
            self.breaker.failure()
            self.logger.warning("openclaw request failed: %s", exc)
            self.write_prompt_audit(prompt, response=raw, error=str(exc))
            return {"ok": False, "error": str(exc)}
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def send_text(self, text: str) -> dict[str, Any]:
        return self.send_prompt(text)

    def discover(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "connected": False,
            "auth": "unknown",
            "available_methods": [],
            "guessed_methods": [],
            "required_scopes": [],
            "recommendation": "leave openclaw.rpc_method=null until a documented writable method and scope are available",
        }
        if websocket is None:
            result.update({"auth": "fail", "error": "websocket-client unavailable"})
            return result
        url = self.config.get("url", "ws://openclaw:18790")
        timeout = float(self.config.get("timeout_seconds", 120))
        ws = None
        try:
            ws = websocket.create_connection(url, timeout=min(timeout, 15.0))
            result["connected"] = True
            try:
                first = ws.recv()
            except Exception as exc:
                first = ""
                result["first_event_error"] = str(exc)
            if first:
                result["first_event"] = first[:1000]
                lower = first.lower()
                if "missing scope" in lower:
                    result["auth"] = "fail"
                    scopes = re.findall(r"operator\.[a-z]+", lower)
                    result["required_scopes"] = sorted(set(scopes))
                elif "connect.challenge" in lower:
                    result["auth"] = "challenge"
                    result["guessed_methods"] = ["connect", "agent", "agent.wait", "sessions.create", "sessions.send", "sessions.list"]
                    connect_payload = {
                        "id": "voice-gateway-discover",
                        "method": "connect",
                        "params": {"client": {"id": "gateway-client", "mode": "backend"}},
                    }
                    try:
                        ws.send(json.dumps(connect_payload))
                        reply = ws.recv()
                        result["connect_reply"] = reply[:1000]
                        reply_lower = reply.lower()
                        if "missing scope" in reply_lower:
                            result["auth"] = "fail"
                            scopes = re.findall(r"operator\.[a-z]+", reply_lower)
                            result["required_scopes"] = sorted(set(scopes))
                        elif reply.strip():
                            result["auth"] = "ok"
                        else:
                            result["auth"] = "unknown"
                    except Exception as exc:
                        result["auth"] = "fail"
                        result["connect_error"] = str(exc)
                else:
                    result["auth"] = "unknown"
            return result
        except Exception as exc:
            result.update({"connected": False, "auth": "fail", "error": str(exc)})
            return result
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass


class WakeWordClient:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.root_config = config
        self.config = config.get("wakeword", {})
        self.audio_config = config.get("audio", {})
        self.logger = logger

    def wait_for_wake(self, timeout: float | None = None, debug: bool = False) -> bool:
        if not self.config.get("enabled", True):
            self.logger.info("wakeword disabled")
            return False
        if self.config.get("provider", "wyoming") != "wyoming":
            self.logger.warning("WakeWord adapter not fully implemented: unsupported provider=%s", self.config.get("provider"))
            return False
        if sd is None:
            self.logger.warning("wakeword unavailable: sounddevice is unavailable")
            return False
        try:
            return asyncio.run(self._wait_for_wake(timeout, debug=debug))
        except Exception as exc:
            self.logger.warning("wakeword failed: %s", exc)
            return False

    async def _wait_for_wake(self, timeout: float | None = None, debug: bool = False) -> bool:
        uri = self.config.get("uri", "tcp://voice-wakeword:10400")
        configured_timeout = float(self.config.get("timeout_seconds", 30))
        wait_timeout = configured_timeout if timeout is None else float(timeout)
        name = str(self.config.get("name", "hey_jarvis") or "").strip()
        names = [name] if name else None
        client = AsyncClient.from_uri(uri)
        if debug:
            self.logger.info("wake-debug connecting uri=%s", uri)
        await asyncio.wait_for(client.connect(), timeout=min(wait_timeout, configured_timeout))
        try:
            self.logger.info("wakeword listening uri=%s name=%s timeout=%ss", uri, name or "any", wait_timeout)
            await client.write_event(Detect(names=names).event())
            if debug:
                self.logger.info("wake-debug Detect sent names=%s", names)
            stop_event = asyncio.Event()
            detector = asyncio.create_task(self._read_detection(client, name, stop_event, debug=debug))
            streamer = asyncio.create_task(self._stream_microphone(client, wait_timeout, stop_event, debug=debug))
            done, pending = await asyncio.wait({detector, streamer}, timeout=wait_timeout + 1.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                stop_event.set()
                for task in pending:
                    task.cancel()
                self.logger.info("wakeword timeout")
                if debug:
                    self.logger.info("wake-debug timeout")
                return False
            result = False
            for task in done:
                result = bool(task.result())
            stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            return result
        finally:
            await client.disconnect()
            if debug:
                self.logger.info("wake-debug disconnected")

    async def _read_detection(self, client: AsyncClient, expected_name: str, stop_event: asyncio.Event, debug: bool = False) -> bool:
        while not stop_event.is_set():
            event = await client.read_event()
            if event is None:
                if debug:
                    self.logger.info("wake-debug event=None")
                return False
            if debug:
                self.logger.info("wake-debug event type=%s data=%s", event.type, event.data)
            if Detection.is_type(event.type):
                detection = Detection.from_event(event)
                detected_name = detection.name or ""
                self.logger.info("wakeword detection name=%s", detected_name or "unknown")
                if not expected_name or detected_name == expected_name:
                    return True
            if NotDetected.is_type(event.type):
                self.logger.info("wakeword not detected")
                return False
        return False

    async def _stream_microphone(self, client: AsyncClient, timeout: float, stop_event: asyncio.Event, debug: bool = False) -> bool:
        sample_rate = int(self.audio_config.get("sample_rate", 16000))
        channels = int(self.audio_config.get("channels", 1))
        frame_ms = int(self.audio_config.get("frame_ms", 30))
        input_device = self.audio_config.get("input_device")
        gain = min(float(self.audio_config.get("wake_input_gain", self.audio_config.get("input_gain", 1.0))), float(self.audio_config.get("max_input_gain", 16.0)))
        frame_samples = max(1, int(sample_rate * frame_ms / 1000))
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
        loop = asyncio.get_running_loop()
        chunks_sent = 0
        sec_started = time.monotonic()
        raw_peaks: list[float] = []
        raw_rms: list[float] = []
        gain_peaks: list[float] = []
        gain_rms: list[float] = []

        def enqueue_audio(indata: bytes, _frames: int, _time_info: Any, status: Any) -> None:
            if status:
                self.logger.debug("wakeword audio status=%s", status)
            data = bytes(indata)
            def put_nowait() -> None:
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(data)
            loop.call_soon_threadsafe(put_nowait)

        await client.write_event(AudioStart(rate=sample_rate, width=2, channels=channels).event())
        if debug:
            self.logger.info("wake-debug AudioStart sent rate=%s width=2 channels=%s gain=%.2f", sample_rate, channels, gain)
        deadline = time.monotonic() + timeout
        try:
            with sd.RawInputStream(device=input_device, samplerate=sample_rate, channels=channels, dtype="int16", blocksize=frame_samples, callback=enqueue_audio):
                while not stop_event.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.logger.info("wakeword timeout")
                        return False
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=min(0.25, remaining))
                    except asyncio.TimeoutError:
                        continue
                    raw_i16 = np.frombuffer(chunk, dtype=np.int16)
                    gained_i16 = apply_audio_gain_int16(raw_i16, gain)
                    raw_stats = audio_level_stats(raw_i16)
                    gain_stats = audio_level_stats(gained_i16)
                    raw_peaks.append(raw_stats["peak"])
                    raw_rms.append(raw_stats["rms"])
                    gain_peaks.append(gain_stats["peak"])
                    gain_rms.append(gain_stats["rms"])
                    await client.write_event(AudioChunk(rate=sample_rate, width=2, channels=channels, audio=gained_i16.tobytes()).event())
                    chunks_sent += 1
                    if time.monotonic() - sec_started >= 1.0:
                        avg_raw_peak = float(np.mean(raw_peaks)) if raw_peaks else 0.0
                        avg_raw_rms = float(np.mean(raw_rms)) if raw_rms else 0.0
                        avg_gain_peak = float(np.mean(gain_peaks)) if gain_peaks else 0.0
                        avg_gain_rms = float(np.mean(gain_rms)) if gain_rms else 0.0
                        self.logger.info(
                            "wake audio chunks=%s raw_peak=%.4f raw_rms=%.4f gain_peak=%.4f gain_rms=%.4f gain=%.2f",
                            chunks_sent,
                            avg_raw_peak,
                            avg_raw_rms,
                            avg_gain_peak,
                            avg_gain_rms,
                            gain,
                        )
                        if avg_gain_rms < 0.01:
                            self.logger.warning("wake audio level is still very low after gain: rms=%.4f", avg_gain_rms)
                        raw_peaks.clear()
                        raw_rms.clear()
                        gain_peaks.clear()
                        gain_rms.clear()
                        sec_started = time.monotonic()
        finally:
            try:
                await client.write_event(AudioStop().event())
                if debug:
                    self.logger.info("wake-debug AudioStop sent chunks=%s", chunks_sent)
            except Exception as exc:
                self.logger.debug("wakeword audio stop failed: %s", exc)
        return False


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




def validate_wav_for_stt(path: str, max_duration: float = 5.0, max_peak: float = 0.98) -> dict[str, Any]:
    try:
        with wave.open(path, "rb") as wav:
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            frames = wav.getnframes()
            data = wav.readframes(frames)
        duration = frames / float(rate) if rate else 0.0
        issues = []
        if rate != 16000:
            issues.append(f"sample_rate={rate} expected=16000")
        if width != 2:
            issues.append(f"sample_width={width} expected=2")
        if channels != 1:
            issues.append(f"channels={channels} expected=1")
        if duration > max_duration:
            issues.append(f"duration={duration:.2f}s > max={max_duration}s")
        if duration < 0.1:
            issues.append(f"duration={duration:.2f}s too_short")
        pcm = np.frombuffer(data, dtype=np.int16) if width == 2 else np.array([], dtype=np.int16)
        if pcm.size > 0:
            peak = float(np.max(np.abs(pcm))) / 32768.0
            rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) / 32768.0
            silent_frames = int(np.sum(np.abs(pcm) < 100))
            silent_pct = silent_frames / pcm.size * 100 if pcm.size else 100
            if peak >= max_peak:
                issues.append(f"saturated peak={peak:.3f}")
            if silent_pct > 95:
                issues.append(f"mostly_silent={silent_pct:.0f}%")
        else:
            peak = 0.0
            rms = 0.0
        return {"valid": len(issues) == 0, "issues": issues, "rate": rate, "width": width, "channels": channels, "duration": round(duration, 3), "frames": frames}
    except Exception as exc:
        return {"valid": False, "issues": [repr(exc)], "rate": 0, "width": 0, "channels": 0, "duration": 0, "frames": 0}

class STTClient:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.root_config = config
        self.config = config.get("stt", {})
        self.audio_config = config.get("audio", {})
        self.logger = logger

    def transcribe_wav(self, path: str, timeout: float | None = None) -> str:
        start = time.monotonic()
        effective_timeout = timeout if timeout is not None else float(self.config.get("timeout_seconds", 12))
        try:
            text = asyncio.run(self._transcribe_wav(path, timeout=effective_timeout))
            latency_ms = int((time.monotonic() - start) * 1000)
            self.logger.info("stt result chars=%s latency_ms=%s path=%s", len(text), latency_ms, path)
            return text.strip()
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            self.logger.warning("stt failed latency_ms=%s path=%s error=%r timeout=%.1f", latency_ms, path, exc, effective_timeout)
            return ""

    async def _transcribe_wav(self, path: str, timeout: float | None = None) -> str:
        uri = self.config.get("uri", "tcp://voice-whisper:10300")
        host, port = parse_tcp_uri(uri)
        timeout = timeout if timeout is not None else float(self.config.get("timeout_seconds", 12))
        language = self.config.get("language", "es")
        with wave.open(path, "rb") as wav:
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            data = wav.readframes(wav.getnframes())
        if self.config.get("pre_gain_enabled", False):
            gain = min(float(self.audio_config.get("stt_input_gain", self.audio_config.get("input_gain", 1.0))), float(self.audio_config.get("max_input_gain", 16.0)))
            pcm = np.frombuffer(data, dtype=np.int16)
            data = apply_audio_gain_int16(pcm, gain, logger=self.logger, label="stt pre-gain").tobytes()
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
        self.wakeword = WakeWordClient(config, logger)
        self.memory = ConversationMemory(config, logger)
        self.tts_stop_event = threading.Event()
        self.tts_lock = threading.RLock()
        self.music_player = MusicAlarmPlayer(config, logger)
        self.music_library = MusicLibrary(config, logger)
        self.queue_player = MusicPlayer(config, logger, self.music_library)
        self.scheduler = ReminderScheduler(config, logger, speak_callback=self.speak_text, music_player=self.music_player)
        self.followup_turns = 0
        self._last_wake_remainder = None

    @property
    def conversation_config(self) -> dict[str, Any]:
        return self.config.get("conversation", {}) if isinstance(self.config.get("conversation"), dict) else {}

    @property
    def confirmation_config(self) -> dict[str, Any]:
        return self.config.get("confirmation", {}) if isinstance(self.config.get("confirmation"), dict) else {}

    def wake_ack_text(self) -> str:
        return str(self.conversation_config.get("wake_ack_text", "Te escucho."))

    def unknown_text(self) -> str:
        return str(self.conversation_config.get("unknown_text", "No entendí, repite por favor."))

    def concise(self, text: str) -> str:
        return make_concise_response(text, self.config)

    def detect_wake(self, provider: str = "wyoming") -> bool:
        provider = (provider or "wyoming").strip().lower()
        self.logger.info("wake provider=%s", provider)
        if provider == "wyoming":
            return self.wakeword.wait_for_wake()
        if provider == "stt":
            return self.wait_for_wake_stt_fallback()
        if provider == "auto":
            if self.wakeword.wait_for_wake():
                return True
            self.logger.info("wake provider=auto wyoming timeout; trying stt fallback")
            return self.wait_for_wake_stt_fallback()
        self.logger.warning("unknown wake provider=%s; using wyoming", provider)
        return self.wakeword.wait_for_wake()

    def wait_for_wake_stt_fallback(self) -> bool:
        wake_config = self.config.get("wakeword", {}) if isinstance(self.config.get("wakeword"), dict) else {}
        if not wake_config.get("fallback_stt_enabled", False):
            self.logger.info("wake fallback stt disabled")
            return False
        timeout = float(wake_config.get("fallback_stt_timeout_seconds", 30))
        window_seconds = float(wake_config.get("fallback_stt_window_seconds", 2))
        min_voice_ms = int(wake_config.get("fallback_stt_min_voice_ms", 300))
        stt_timeout = float(self.config.get("stt", {}).get("wake_timeout_seconds", 8))
        phrases = [TokenFirewall.normalize(str(item)) for item in wake_config.get("fallback_stt_phrases", [])]
        if not phrases:
            phrases = ["hey jarvis", "jarvis", "oye jarvis", "asistente", "oye asistente", "sam", "sum", "samantha", "oye sam", "oye sum", "oye samantha"]
        deadline = time.monotonic() + timeout
        attempt = 0
        path = "/logs/wake_fallback_utterance.wav"
        self.logger.info("wake provider=stt timeout=%.1fs window=%.1fs stt_timeout=%.1fs phrases=%s", timeout, window_seconds, stt_timeout, phrases)
        while time.monotonic() < deadline:
            attempt += 1
            try:
                record = self.audio.record_wake_fallback_window(path, window_seconds, min_voice_ms)
            except Exception as exc:
                self.logger.warning("wake fallback recording failed attempt=%s error=%r", attempt, exc)
                time.sleep(0.3)
                continue
            if not record.get("ok"):
                self.logger.info("wake fallback attempt=%s no_voice path=%s", attempt, path)
                continue
            validation = validate_wav_for_stt(path, max_duration=5.0)
            if not validation["valid"]:
                self.logger.warning("wake fallback WAV invalid attempt=%s issues=%s", attempt, validation["issues"])
                continue
            text = self.stt.transcribe_wav(path, timeout=stt_timeout)
            normalized = TokenFirewall.normalize(text)
            if self.is_likely_tts_loop(normalized):
                self.logger.warning("wake fallback discarded possible_tts_echo text=%r", text)
                continue
            matched, score, reason = self.match_wake_phrase(normalized, phrases)
            self.logger.info(
                "wake fallback attempt=%s path=%s raw_text=%r normalized_text=%r matched=%r fuzzy_score=%.3f reason=%s",
                attempt,
                path,
                text,
                normalized,
                matched,
                score,
                reason,
            )
            if matched:
                self.logger.info("wake fallback detected raw_text=%r normalized_text=%r phrase=%s fuzzy_score=%.3f reason=%s", text, normalized, matched, score, reason)
                remainder = normalized
                for phrase in phrases:
                    if phrase and normalized.startswith(phrase):
                        remainder = normalized[len(phrase):].strip()
                        break
                self._last_wake_remainder = remainder if remainder else None
                return True
            self._last_wake_remainder = None
        self.logger.info("wake fallback timeout")
        return False

    @staticmethod
    def match_wake_phrase(text: str, phrases: list[str]) -> tuple[str | None, float, str]:
        if not text:
            return None, 0.0, "empty_text"
        normalized_phrases = [phrase for phrase in phrases if phrase]
        for phrase in sorted(normalized_phrases, key=len, reverse=True):
            if text == phrase:
                if phrase == "sam":
                    return "sam", 1.0, "sam_exact"
                return phrase, 1.0, "exact"
        if "sam" in normalized_phrases:
            if text == "oye sam":
                return "sam", 1.0, "sam_oye_phrase"
        best_phrase = None
        best_score = 0.0
        for phrase in normalized_phrases:
            if not phrase:
                continue
            if phrase in {"sam", "oye sam"}:
                score = difflib.SequenceMatcher(None, text, phrase).ratio()
            else:
                score = 1.0 if phrase in text else difflib.SequenceMatcher(None, text, phrase).ratio()
            if score > best_score:
                best_phrase = phrase
                best_score = score
        if best_phrase == "sam":
            return ("sam", best_score, "sam_fuzzy_strict") if best_score >= 0.90 else (None, best_score, "sam_fuzzy_rejected")
        if best_score >= 0.72:
            reason = "phrase_contains" if best_phrase and best_phrase in text else "fuzzy"
            return best_phrase, best_score, reason
        return None, best_score, "below_threshold"

    def transition(self, state: State) -> None:
        self.logger.info("state %s -> %s", self.state, state)
        self.state = state

    def boot(self) -> None:
        ensure_audio_output_unmuted(self.logger)
        ensure_mic_gain(self.logger)
        self.audio.ensure_input_gain()
        self.transition(State.HEALTHCHECK)
        self.health.log_results()
        self.audio.log_devices()
        self.transition(State.PASSIVE_LISTENING)

    def process_text(self, raw_text: str, confirmation: str | None = None) -> dict[str, Any]:
        self.transition(State.TOKEN_FIREWALL)
        decision = self.firewall.classify(raw_text)
        self.log_firewall_decision(decision)
        return self.handle_decision(decision, speak=False, confirmation=confirmation)

    def classify_confirmation(self, text: str) -> tuple[bool | None, str]:
        normalized = TokenFirewall.normalize(text)
        cfg = self.confirmation_config
        yes_aliases = [TokenFirewall.normalize(str(item)) for item in cfg.get("yes_aliases", [])]
        no_aliases = [TokenFirewall.normalize(str(item)) for item in cfg.get("no_aliases", [])]
        if not yes_aliases:
            yes_aliases = ["si", "claro", "correcto", "confirma", "envialo", "mandalo", "dale"]
        if not no_aliases:
            no_aliases = ["no", "cancelar", "cancela", "salir", "no importa", "olvidalo"]
        if not normalized:
            return None, normalized
        yes_set = set(yes_aliases)
        for alias in yes_aliases:
            if normalized == alias:
                self.logger.info("confirmation yes exact match normalized=%r alias=%r", normalized, alias)
                return True, normalized
        for alias in yes_aliases:
            if alias in normalized:
                self.logger.info("confirmation yes contains match normalized=%r alias=%r", normalized, alias)
                return True, normalized
        for alias in yes_aliases:
            score = difflib.SequenceMatcher(None, normalized, alias).ratio()
            if score >= 0.75:
                self.logger.info("confirmation yes fuzzy match normalized=%r alias=%r score=%.3f", normalized, alias, score)
                return True, normalized
        for alias in no_aliases:
            if normalized == alias:
                self.logger.info("confirmation no exact match normalized=%r alias=%r", normalized, alias)
                return False, normalized
        explicit_no_prefixes = ("no ", "no,")
        if any(normalized.startswith(p) for p in explicit_no_prefixes):
            self.logger.info("confirmation no prefix match normalized=%r", normalized)
            return False, normalized
        if normalized in no_aliases:
            return False, normalized
        return None, normalized

    def capture_confirmation_response(self) -> str:
        self.transition(State.RECORDING_USER)
        try:
            record_result = self.audio.record_once()
        except Exception as exc:
            self.logger.warning("openclaw confirmation recording failed: %s", exc)
            return ""
        if not record_result.get("ok"):
            self.logger.info("openclaw confirmation discarded before STT: %s", record_result)
            return ""
        self.transition(State.TRANSCRIBING)
        return self.stt.transcribe_wav(str(record_result["path"]))

    def confirm_openclaw_prompt(self, prompt: str, speak: bool, confirmation: str | None) -> tuple[bool, str]:
        write_text_file("/logs/pending_openclaw_prompt.txt", prompt)
        if not self.config.get("openclaw", {}).get("require_confirmation", True):
            return True, "confirmation_disabled"
        response = confirmation
        if response is None and speak:
            self.speak_text("¿Quieres enviarlo a OpenClaw?")
            response = self.capture_confirmation_response()
        confirmed, normalized = self.classify_confirmation(response or "")
        self.logger.info("openclaw confirmation response=%r normalized=%r confirmed=%s", response, normalized, confirmed)
        return confirmed is True, normalized

    def log_firewall_decision(self, decision: RouteDecision) -> None:
        self.logger.info(
            "firewall raw_text=%r normalized_text=%r route=%s action=%s reason=%s matched_alias=%s fuzzy_score=%s",
            decision.raw_text,
            decision.normalized_text,
            decision.route,
            decision.action,
            decision.reason,
            decision.matched_alias,
            decision.fuzzy_score,
        )

    def handle_decision(self, decision: RouteDecision, speak: bool = False, confirmation: str | None = None) -> dict[str, Any]:
        if decision.route == "discard":
            self.logger.info("route discard reason=%s", decision.reason)
            return {"ok": True, "discarded": True, "reason": decision.reason}
        if decision.route == "local":
            self.transition(State.LOCAL_ACTION)
            if decision.action in {"openclaw_status", "system_status"}:
                ok = self.health.check_all().get("openclaw", {}).get("ok") is True
                if decision.action == "openclaw_status":
                    result = {"ok": ok, "speak": "OpenClaw está accesible." if ok else "OpenClaw no está accesible."}
                else:
                    result = {"ok": True, "speak": "Todo está activo." if ok else "Gateway activo. OpenClaw no está accesible."}
            elif decision.action in {"identity", "set_alarm", "set_reminder", "list_reminders", "cancel_alarm", "cancel_all_reminders", "clear_memory", "unsupported_alarm", "cancel_alarm_permanent", "skip_alarm_once", "cancel_all_alarms", "music_play_track", "music_play_track_by_artist", "music_now_playing", "music_next", "music_stop", "music_pending_track_answer"}:
                result = self.handle_assistant_action(decision)
            else:
                result = self.local.run(decision.action or "unknown", decision.text)
                if decision.action in {"cancel", "stop"}:
                    self.scheduler.cancel_active_alarm()
                    self.tts_stop_event.set()
                    if self.config.get("conversation_memory", {}).get("clear_on_cancel", True):
                        self.memory.clear()
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
            valid, prompt, validation_error = self.openclaw.validate_prompt(decision.text)
            if not valid:
                result = {"ok": False, "error": validation_error or "invalid openclaw prompt"}
                self.openclaw.write_prompt_audit(prompt, error=str(result["error"]))
                if speak:
                    self.speak_text("No envié eso a OpenClaw.")
                return result
            confirmed, confirmation_text = self.confirm_openclaw_prompt(prompt, speak=speak, confirmation=confirmation)
            if not confirmed:
                self.openclaw.write_prompt_audit(prompt, error="cancelled_or_unconfirmed")
                if speak:
                    self.speak_text("Cancelado.")
                return {"ok": True, "cancelled": True, "confirmed": False, "confirmation_text": confirmation_text, "speak": "Cancelado."}
            result = self.openclaw.send_prompt(prompt)
            result["confirmed"] = True
            if speak:
                if result.get("dry_run"):
                    self.speak_text("Modo prueba. No envié nada.")
                elif result.get("ok"):
                    self.speak_text("OpenClaw recibió la solicitud.")
                elif "método RPC" in str(result.get("error", "")) or "rpc_method" in str(result.get("error", "")):
                    self.speak_text("OpenClaw todavía no tiene método RPC configurado.")
                else:
                    self.speak_text("No pude contactar OpenClaw.")
            return result
        return {"ok": False, "error": "unknown route"}

    def handle_assistant_action(self, decision: RouteDecision) -> dict[str, Any]:
        parsed = AssistantCommandParser.parse(decision.raw_text or decision.text) or {"action": decision.action}
        action = str(parsed.get("action"))
        if action == "identity":
            return {"ok": True, "speak": "Soy Samantha."}
        if action == "unsupported_alarm":
            return {"ok": True, "speak": parsed.get("error", "Solo soporto alarmas diarias o recordatorios en cierto tiempo.")}
        if action in {"music_play_track", "music_play_track_by_artist"}:
            track_query = str(parsed.get("track_query", "")).strip()
            artist_query = str(parsed.get("artist_query", "") or "").strip() or None
            matches = self.music_library.search_tracks(track_query, artist_query=artist_query)
            if not matches:
                return {"ok": True, "speak": "No encontré esa canción."}
            if artist_query is None and len(matches) > 1 and matches[0].get("score", 0) - matches[1].get("score", 0) < 0.05:
                write_text_file("/logs/pending_music_request.json", json.dumps({"type": "track_disambiguation", "track_query": track_query, "options": matches[:5], "expires_at": time.time() + 45}, ensure_ascii=False))
                return {"ok": True, "pending": True, "speak": "Encontré varias. ¿De qué artista?"}
            track = matches[0]
            track_path = str(track.get("path", ""))
            if not track_path or not Path(track_path).exists():
                self.logger.warning("music track path missing or does not exist: %s", track_path)
                return {"ok": True, "speak": "No pude reproducirla."}
            queue = self.music_library.get_track_context_queue(str(track["id"]))
            valid_queue = [t for t in queue if Path(str(t.get("path", ""))).exists()]
            if not valid_queue:
                self.logger.warning("music queue empty after path validation for track=%s", track.get("id"))
                return {"ok": True, "speak": "No pude reproducirla."}
            result = self.queue_player.start_queue_process(valid_queue)
            if not result.get("ok"):
                self.logger.error("music start_queue_process failed: %r", result)
                write_text_file("/logs/last_music_error.txt", f"start_queue_process failed: {result}")
                return {"ok": True, "speak": "No pude reproducirla."}
            self._music_just_started = True
            title = track.get("title") or track.get("filename") or "canción"
            return {"ok": True, "track": track, "queue_length": len(valid_queue), "speak": f"Reproduciendo {title}."}
        if action == "music_now_playing":
            now = self.queue_player.queue_summary().get("now_playing")
            if not now:
                return {"ok": True, "speak": "No hay música sonando."}
            artist = now.get("artist") or now.get("album_artist") or now.get("folder_artist") or "artista desconocido"
            return {"ok": True, "now_playing": now, "speak": f"Está sonando {now.get('title')} de {artist}."}
        if action == "music_next":
            self.queue_player.request_next()
            return {"ok": True, "speak": "Siguiente."}
        if action == "music_stop":
            self.queue_player.request_stop()
            return {"ok": True, "speak": "Música detenida."}
        if action == "set_alarm":
            if parsed.get("missing") == "time":
                return {"ok": True, "speak": "¿A qué hora?"}
            time_of_day = str(parsed.get("time_of_day", ""))
            reminder_id = self.scheduler.add_daily_alarm(time_of_day, str(parsed.get("alarm_text", "")))
            return {"ok": True, "id": reminder_id, "speak": f"Listo, alarma diaria a las {time_of_day}."}
        if action == "set_reminder":
            if parsed.get("missing") == "time":
                return {"ok": True, "speak": "¿Cuándo te recuerdo?"}
            if parsed.get("missing") == "text":
                return {"ok": True, "speak": "¿Qué quieres que te recuerde?"}
            delay = int(parsed.get("delay_seconds", 0))
            if delay <= 0:
                return {"ok": True, "speak": "¿Cuándo te recuerdo?"}
            fire_at = self.scheduler.now() + dt.timedelta(seconds=delay)
            reminder_text = str(parsed.get("reminder_text", "")).strip()
            reminder_id = self.scheduler.add_one_shot_reminder(reminder_text, fire_at)
            minutes = max(1, round(delay / 60))
            unit = "minuto" if minutes == 1 else "minutos"
            return {"ok": True, "id": reminder_id, "fire_at": fire_at.isoformat(timespec="seconds"), "speak": f"Listo, te recuerdo en {minutes} {unit}."}
        if action == "list_reminders":
            items = self.scheduler.list_active_reminders()
            alarms = sum(1 for item in items if item.get("kind") == "alarm")
            reminders = len(items) - alarms
            return {"ok": True, "items": items, "speak": f"Tienes {reminders} recordatorios y {alarms} alarmas activos."}
        if action == "cancel_alarm":
            self.scheduler.cancel_active_alarm()
            self.tts_stop_event.set()
            return {"ok": True, "speak": "Cancelado."}
        if action == "cancel_alarm_permanent":
            time_of_day = str(parsed.get("time_of_day", ""))
            if not self.scheduler.cancel_alarm_permanent(time_of_day):
                return {"ok": True, "speak": "No encontré esa alarma."}
            return {"ok": True, "time_of_day": time_of_day, "speak": f"Listo, cancelé la alarma de las {time_of_day}."}
        if action == "skip_alarm_once":
            time_of_day = str(parsed.get("time_of_day", ""))
            tomorrow = self.scheduler.now().date() + dt.timedelta(days=1)
            if not self.scheduler.skip_alarm_once(time_of_day, tomorrow):
                return {"ok": True, "speak": "No encontré esa alarma."}
            return {"ok": True, "time_of_day": time_of_day, "skip_date": tomorrow.isoformat(), "speak": f"Listo, mañana no sonará la alarma de las {time_of_day}."}
        if action == "cancel_all_alarms":
            count = self.scheduler.cancel_all_alarms()
            self.scheduler.cancel_active_alarm()
            return {"ok": True, "disabled": count, "speak": "Listo, cancelé todas las alarmas."}
        if action == "cancel_all_reminders":
            count = self.scheduler.disable_all()
            self.scheduler.cancel_active_alarm()
            return {"ok": True, "disabled": count, "speak": "Listo, recordatorios borrados."}
        if action == "clear_memory":
            self.memory.clear()
            return {"ok": True, "speak": "Listo, memoria borrada."}
        return {"ok": False, "speak": "Acción local no reconocida."}

    def openclaw_dry_run(self, text: str) -> dict[str, Any]:
        decision = self.firewall.classify(text)
        self.log_firewall_decision(decision)
        if decision.route != "openclaw":
            return {"ok": False, "route": decision.route, "error": "text did not route to openclaw", "text": decision.text}
        valid, prompt, validation_error = self.openclaw.validate_prompt(decision.text)
        if not valid:
            return {"ok": False, "route": "openclaw", "error": validation_error}
        write_text_file("/logs/pending_openclaw_prompt.txt", prompt)
        confirmed, confirmation_text = self.confirm_openclaw_prompt(prompt, speak=False, confirmation="confirma")
        if not confirmed:
            self.openclaw.write_prompt_audit(prompt, error="cancelled_or_unconfirmed")
            return {"ok": True, "route": "openclaw", "cancelled": True, "confirmed": False, "confirmation_text": confirmation_text}
        self.logger.info("openclaw dry-run confirmed=true dry_run=true prompt=%r", prompt)
        self.openclaw.write_prompt_audit(prompt, response="dry_run=true", error="")
        return {"ok": True, "route": "openclaw", "dry_run": True, "confirmed": True, "text": prompt, "speak": "Modo prueba. No envié nada."}

    def openclaw_send_test(self, text: str) -> dict[str, Any]:
        if self.openclaw.dry_run:
            return {"ok": False, "error": "openclaw dry_run=true; send test blocked"}
        if not self.config.get("openclaw", {}).get("rpc_method"):
            return {"ok": False, "error": "openclaw rpc_method=null; send test blocked"}
        valid, prompt, validation_error = self.openclaw.validate_prompt(text)
        if not valid:
            return {"ok": False, "error": validation_error}
        write_text_file("/logs/pending_openclaw_prompt.txt", prompt)
        return self.openclaw.send_prompt(prompt)

    def speak_text(self, text: str) -> None:
        clean = self.concise(text)
        if not clean:
            return
        barge_cfg = self.config.get("barge_in", {}) if isinstance(self.config.get("barge_in"), dict) else {}
        chunk_chars = int(barge_cfg.get("tts_chunk_chars", 220)) if barge_cfg.get("enabled", True) else 10000
        chunks = self.split_tts_chunks(clean, max(40, chunk_chars))
        with self.tts_lock:
            self.tts_stop_event.clear()
            self.transition(State.SPEAKING)
            write_text_file("/logs/last_assistant_text.txt", clean)
            self.local.last_response = clean
            for idx, chunk in enumerate(chunks):
                if self.tts_stop_event.is_set():
                    self.logger.info("tts interrupted before chunk=%s", idx + 1)
                    self.tts_stop_event.clear()
                    break
                out_path = "/logs/last_tts.wav"
                self.tts.synthesize_to_wav(chunk, out_path)
                self.audio.play_wav(out_path)
            cooldown_ms = int(self.config.get("audio", {}).get("post_tts_mic_cooldown_ms", 700))
            if cooldown_ms > 0:
                self.logger.info("post-tts cooldown ms=%s", cooldown_ms)
                time.sleep(cooldown_ms / 1000.0)

    @staticmethod
    def split_tts_chunks(text: str, max_chars: int) -> list[str]:
        clean = (text or "").strip()
        if len(clean) <= max_chars:
            return [clean] if clean else []
        parts: list[str] = []
        remaining = clean
        while len(remaining) > max_chars:
            window = remaining[:max_chars]
            cut = max(window.rfind(". "), window.rfind(", "), window.rfind(" "))
            if cut < max_chars // 2:
                cut = max_chars
            parts.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            parts.append(remaining)
        return parts

    def is_likely_tts_loop(self, text: str) -> bool:
        last_spoken = read_text_file("/logs/last_assistant_text.txt")
        if not text or not last_spoken:
            return False
        ratio = difflib.SequenceMatcher(None, TokenFirewall.normalize(text), TokenFirewall.normalize(last_spoken)).ratio()
        if ratio >= 0.86:
            self.logger.warning("discarding possible TTS loop similarity=%.3f text=%r", ratio, text)
            return True
        return False

    def voice_turn_once(self, text: str | None = None, confirmation: str | None = None, speak_unknown: bool = True) -> dict[str, Any]:
        if text is None:
            self.transition(State.RECORDING_USER)
            record_result = self.audio.record_once()
            if not record_result.get("ok"):
                self.transition(State.TOKEN_FIREWALL)
                self.logger.info("voice-turn discarded before STT: %s", record_result)
                return {"ok": True, "route": "discard", "reason": "silence", "recording": record_result}
            self.transition(State.TRANSCRIBING)
            text = self.stt.transcribe_wav(str(record_result["path"]))
            if not text:
                self.logger.info("voice-turn discarded: empty STT")
                if speak_unknown:
                    self.speak_text(self.unknown_text())
                return {"ok": True, "route": "discard", "reason": "empty_stt", "recording": record_result}
        else:
            record_result = None
        write_text_file("/logs/last_user_text.txt", text)
        if self.is_likely_tts_loop(text):
            return {"ok": True, "route": "discard", "reason": "possible_tts_echo", "text": text, "recording": record_result}
        self.transition(State.TOKEN_FIREWALL)
        decision = self.firewall.classify(text)
        self.log_firewall_decision(decision)
        result = self.handle_decision(decision, speak=True, confirmation=confirmation)
        result.update({"route": decision.route, "text": decision.text})
        assistant_text = str(result.get("speak") or result.get("error") or "")
        self.memory.add_turn(text, decision.route, decision.action, assistant_text)
        if decision.reason == "low_value_short_text" and speak_unknown:
            self.speak_text(self.unknown_text())
        if record_result is not None:
            result["recording"] = record_result
        return result

    def wake_once(self, simulate_wake: bool = False, wake_provider: str = "wyoming") -> dict[str, Any]:
        self.transition(State.PASSIVE_LISTENING)
        detected = True if simulate_wake else self.detect_wake(wake_provider)
        if not detected:
            result = {"ok": True, "wake": False, "timeout": True}
            print(json.dumps(result, ensure_ascii=False))
            return result
        self.transition(State.WAKE_CONFIRMED)
        self.speak_text(self.wake_ack_text())
        result = self.voice_turn_once()
        result.update({"wake": True})
        print(json.dumps(result, ensure_ascii=False))
        return result

    def listen_loop(self, simulate_wake: bool = False, wake_provider: str = "wyoming") -> None:
        conversation = self.conversation_config
        followup_window_seconds = float(conversation.get("followup_window_seconds", 8))
        max_followup_turns = int(conversation.get("max_followup_turns", 2))
        self.boot()
        self.scheduler.start()
        try:
            while True:
                self.transition(State.PASSIVE_LISTENING)
                detected = True if simulate_wake else self.detect_wake(wake_provider)
                if not detected:
                    if simulate_wake:
                        return
                    continue
                self.transition(State.WAKE_CONFIRMED)
                inline_text = getattr(self, '_last_wake_remainder', None)
                if inline_text:
                    self.logger.info("wake inline command remainder=%r", inline_text)
                    first_result = self.process_text(inline_text)
                    print(json.dumps(first_result, ensure_ascii=False))
                    self._last_wake_remainder = None
                else:
                    self.speak_text(self.wake_ack_text())
                    first_result = self.voice_turn_once()
                    print(json.dumps(first_result, ensure_ascii=False))
                print(json.dumps(first_result, ensure_ascii=False))
                if self.should_close_followup(first_result):
                    if simulate_wake:
                        return
                    continue
                self.transition(State.FOLLOW_UP_WINDOW)
                self.followup_turns = 0
                while self.followup_turns < max_followup_turns:
                    started = time.monotonic()
                    result = self.voice_turn_once(speak_unknown=True)
                    print(json.dumps(result, ensure_ascii=False))
                    self.followup_turns += 1
                    if self.should_close_followup(result):
                        break
                    if time.monotonic() - started >= followup_window_seconds:
                        break
                if simulate_wake:
                    return
        except KeyboardInterrupt:
            self.logger.info("listen-loop interrupted")
        finally:
            if simulate_wake:
                self.scheduler.stop()

    def should_close_followup(self, result: dict[str, Any]) -> bool:
        action = result.get("action") or ""
        music_actions = {"music_play_track", "music_play_track_by_artist", "music_now_playing", "music_next", "music_stop", "music_pending_track_answer"}
        if action in music_actions or result.get("pending"):
            return True
        if hasattr(self, '_music_just_started') and self._music_just_started:
            self._music_just_started = False
            return True
        if result.get("reason") in {"silence", "empty_stt", "possible_tts_echo"}:
            return True
        text = TokenFirewall.normalize(str(result.get("text", "")))
        if result.get("route") == "local" and result.get("text") and result.get("speak") == "Cancelado.":
            return True
        if self.firewall.match_cancel_alias(text)[0]:
            return True
        if result.get("route") == "local" and text in self.firewall.CANCEL_ALIASES:
            return True
        return False

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
    parser.add_argument("--analyze-wav")
    parser.add_argument("--wake-debug-record", action="store_true")
    parser.add_argument("--wake-debug-stream", action="store_true")
    parser.add_argument("--mic-debug-record", action="store_true")
    parser.add_argument("--audio-input-test", action="store_true")
    parser.add_argument("--mic-sensitivity-test", action="store_true")
    parser.add_argument("--stt-once")
    parser.add_argument("--tts-once")
    parser.add_argument("--voice-turn-once", action="store_true")
    parser.add_argument("--wake-once", action="store_true")
    parser.add_argument("--listen-loop", action="store_true")
    parser.add_argument("--simulate-wake", action="store_true")
    parser.add_argument("--wake-provider", choices=("wyoming", "stt", "auto"), default="wyoming")
    parser.add_argument("--self-test-firewall", action="store_true")
    parser.add_argument("--process-text")
    parser.add_argument("--openclaw-dry-run")
    parser.add_argument("--openclaw-send-test")
    parser.add_argument("--openclaw-discover", action="store_true")
    parser.add_argument("--list-reminders", action="store_true")
    parser.add_argument("--add-reminder-test")
    parser.add_argument("--in-seconds", type=int, default=30)
    parser.add_argument("--add-daily-alarm-test")
    parser.add_argument("--clear-reminders", action="store_true")
    parser.add_argument("--clear-memory", action="store_true")
    parser.add_argument("--self-test-assistant-core", action="store_true")
    parser.add_argument("--list-alarm-music", action="store_true")
    parser.add_argument("--test-alarm-music", action="store_true")
    parser.add_argument("--skip-alarm-test")
    parser.add_argument("--tomorrow", action="store_true")
    parser.add_argument("--cancel-alarm-test")
    parser.add_argument("--music-scan", action="store_true")
    parser.add_argument("--music-stats", action="store_true")
    parser.add_argument("--music-search-artist")
    parser.add_argument("--music-list-albums", action="store_true")
    parser.add_argument("--stt-debug-wake", action="store_true")
    parser.add_argument("--stt-healthcheck-deep", action="store_true")
    parser.add_argument("--music-search-track")
    parser.add_argument("--artist")
    parser.add_argument("--music-play-track")
    parser.add_argument("--confirm-test")
    parser.add_argument("--music-queue", action="store_true")
    parser.add_argument("--music-stop", action="store_true")
    parser.add_argument("--music-run-queue", action="store_true")
    parser.add_argument("--tts-voice-test", action="store_true")
    parser.add_argument("--text")
    parser.add_argument("--confirmation")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logging(config)
    gateway = VoiceGateway(config, logger)

    if args.healthcheck_once:
        return 0 if gateway.health.log_results() else 1
    if args.music_run_queue:
        result = gateway.queue_player.play_queue_from_state()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.list_audio:
        gateway.audio.log_devices()
        return 0
    if args.play_test_tone:
        gateway.audio.play_test_tone()
        return 0
    if args.mic_debug_record:
        result = gateway.audio.wake_debug_record()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.audio_input_test:
        result = gateway.audio.audio_input_test(seconds=5.0)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.mic_sensitivity_test:
        ensure_mic_gain(logger)
        if sd is None:
            print(json.dumps({"ok": False, "error": "sounddevice unavailable"}, ensure_ascii=False))
            return 2
        sample_rate = int(config.get("audio", {}).get("sample_rate", 16000))
        input_device = config.get("audio", {}).get("input_device")
        frames_3s = int(sample_rate * 3)
        logger.info("mic-sensitivity-test recording 3s input_device=%s rate=%s", input_device, sample_rate)
        raw = sd.rec(frames_3s, samplerate=sample_rate, channels=1, dtype="int16", device=input_device)
        sd.wait()
        raw_i16 = np.asarray(raw, dtype=np.int16).reshape(-1)
        raw_stats = audio_level_stats(raw_i16)
        wake_gain = min(float(config.get("audio", {}).get("wake_input_gain", config.get("audio", {}).get("input_gain", 1.0))), float(config.get("audio", {}).get("max_input_gain", 16.0)))
        command_gain = min(float(config.get("audio", {}).get("command_input_gain", config.get("audio", {}).get("input_gain", 1.0))), float(config.get("audio", {}).get("max_input_gain", 16.0)))
        wake_i16 = apply_audio_gain_int16(raw_i16, wake_gain, max_peak=float(config.get("audio", {}).get("max_input_peak", 0.85)), logger=logger, label="mic-sensitivity-wake")
        command_i16 = apply_audio_gain_int16(raw_i16, command_gain, max_peak=float(config.get("audio", {}).get("max_input_peak", 0.85)), logger=logger, label="mic-sensitivity-command")
        result = {
            "ok": True,
            "input_device": input_device,
            "sample_rate": sample_rate,
            "raw": raw_stats,
            "wake_gain": wake_gain,
            "command_gain": command_gain,
            "wake_gained": audio_level_stats(wake_i16),
            "command_gained": audio_level_stats(command_i16),
            "assessment": "good" if raw_stats["rms"] > 0.01 else ("quiet" if raw_stats["rms"] > 0.002 else "silent"),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.record_once:
        result = gateway.audio.record_once()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.play_wav:
        gateway.audio.play_wav(args.play_wav)
        return 0
    if args.analyze_wav:
        print(json.dumps(analyze_wav_file(args.analyze_wav), ensure_ascii=False))
        return 0
    if args.wake_debug_record:
        print(json.dumps(gateway.audio.wake_debug_record(), ensure_ascii=False))
        return 0
    if args.wake_debug_stream:
        detected = gateway.wakeword.wait_for_wake(debug=True)
        print(json.dumps({"ok": True, "wake": detected, "timeout": not detected}, ensure_ascii=False))
        return 0
    if args.stt_debug_wake:
        ensure_mic_gain(logger)
        window_seconds = float(config.get("wakeword", {}).get("fallback_stt_window_seconds", 2))
        min_voice_ms = int(config.get("wakeword", {}).get("fallback_stt_min_voice_ms", 300))
        wake_gain = min(float(config.get("audio", {}).get("wake_input_gain", config.get("audio", {}).get("input_gain", 1.0))), float(config.get("audio", {}).get("max_input_gain", 16.0)))
        max_peak = float(config.get("audio", {}).get("max_input_peak", 0.85))
        logger.info("stt-debug-wake recording window=%.2fs min_voice_ms=%s gain=%.2f max_peak=%.2f", window_seconds, min_voice_ms, wake_gain, max_peak)
        path = "/logs/wake_fallback_utterance.wav"
        raw_path = "/logs/wake_fallback_utterance_raw.wav"
        gain_path = "/logs/wake_fallback_utterance_gain.wav"
        try:
            record = gateway.audio.record_wake_fallback_window(path, window_seconds, min_voice_ms)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": repr(exc)}, ensure_ascii=False))
            return 2
        if not record.get("ok"):
            print(json.dumps({"ok": False, "reason": "no_voice", "record": record}, ensure_ascii=False))
            return 2
        raw_stats = record.get("stats", {})
        validation = validate_wav_for_stt(path, max_duration=5.0)
        stt_timeout = float(config.get("stt", {}).get("wake_timeout_seconds", 8))
        stt_start = time.monotonic()
        text = gateway.stt.transcribe_wav(path, timeout=stt_timeout)
        stt_latency_ms = int((time.monotonic() - stt_start) * 1000)
        normalized = TokenFirewall.normalize(text)
        result = {
            "ok": True,
            "raw_peak": raw_stats.get("peak", 0),
            "raw_rms": raw_stats.get("rms", 0),
            "gain": wake_gain,
            "gain_peak": float(np.max(np.abs(np.frombuffer(Path(path).read_bytes() if Path(path).exists() else b"\x00\x00", dtype=np.int16)[:1000]))) / 32768.0 if Path(path).exists() else 0,
            "duration": validation.get("duration", 0),
            "stt_latency_ms": stt_latency_ms,
            "stt_text": text,
            "normalized_text": normalized,
            "wav_validation": validation,
            "gain_value": wake_gain,
            "voice_ms": record.get("voice_ms", 0),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0 if text else 2
    if args.stt_healthcheck_deep:
        uri = config.get("stt", {}).get("uri", "tcp://voice-whisper:10300")
        host, port = parse_tcp_uri(uri)
        connection_ok = False
        connection_latency = 0
        try:
            start = time.monotonic()
            ok, err = tcp_check(host, port, timeout=3.0)
            connection_latency = int((time.monotonic() - start) * 1000)
            connection_ok = ok
        except Exception as exc:
            err = repr(exc)
        chunk_path = "/logs/last_utterance.wav"
        stt_ok = False
        stt_text = ""
        stt_latency_ms = 0
        if Path(chunk_path).exists():
            validation = validate_wav_for_stt(chunk_path, max_duration=30.0)
            stt_timeout = float(config.get("stt", {}).get("wake_timeout_seconds", 8))
            try:
                stt_start = time.monotonic()
                stt_text = gateway.stt.transcribe_wav(chunk_path, timeout=stt_timeout)
                stt_latency_ms = int((time.monotonic() - stt_start) * 1000)
                stt_ok = bool(stt_text)
            except Exception as exc:
                stt_text = ""
                stt_latency_ms = int((time.monotonic() - stt_start) * 1000)
        result = {
            "stt_uri": uri,
            "connection_ok": connection_ok,
            "connection_latency_ms": connection_latency,
            "connection_error": err if not connection_ok else None,
            "stt_ok": stt_ok,
            "stt_text": stt_text,
            "stt_latency_ms": stt_latency_ms,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0 if connection_ok else 1
    if args.stt_once:
        text = gateway.stt.transcribe_wav(args.stt_once)
        print(text)
        return 0 if text else 2
    if args.tts_once:
        gateway.speak_text(args.tts_once)
        return 0
    if args.tts_voice_test:
        phrases = ["Hola, soy Samantha.", "Listo, te recuerdo en 10 minutos.", "Reproduciendo música.", "Todo está activo."]
        for phrase in phrases:
            gateway.speak_text(phrase)
        tts_cfg = config.get("tts", {}) if isinstance(config.get("tts"), dict) else {}
        style_cfg = config.get("tts_style", {}) if isinstance(config.get("tts_style"), dict) else {}
        print(json.dumps({
            "ok": True,
            "configured_voice": tts_cfg.get("current_voice", "es_ES-sharvard-medium"),
            "voice_profile": style_cfg.get("voice_profile"),
            "preferred_gender": tts_cfg.get("preferred_gender"),
            "fallback_keep_current_voice": tts_cfg.get("fallback_keep_current_voice", True),
            "voice_piper_changed": False,
            "reason": "no local female Piper voice found; kept current voice",
        }, ensure_ascii=False))
        return 0
    if args.voice_turn_once:
        result = gateway.voice_turn_once(text=args.text, confirmation=args.confirmation)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") or result.get("route") == "discard" else 2
    if args.wake_once:
        result = gateway.wake_once(simulate_wake=args.simulate_wake, wake_provider=args.wake_provider)
        return 0 if result.get("ok") else 2
    if args.listen_loop:
        gateway.listen_loop(simulate_wake=args.simulate_wake, wake_provider=args.wake_provider)
        return 0
    if args.self_test_firewall:
        samples = [
            "Estado de open cloud",
            "Está en el open clamp",
            "Estadle de la open plan",
            "Esto es del sistema",
            "Esto del sistema",
            "Estado del sistema",
            "estado del sistema",
            "estado sistema",
            "estatus del sistema",
            "estado del servidor",
            "estado servidor",
            "estaba en el sistema",
            "Estamos de otro June",
            "Estal y ropa el pleno",
            "cancelar",
            "cancele",
            "cantele",
            "cantale",
            "salir",
            "terminar",
            "para",
            "parale",
            "alto",
            "detente",
            "no importa",
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
    if args.openclaw_discover:
        print(json.dumps(gateway.openclaw.discover(), ensure_ascii=False))
        return 0
    if args.openclaw_dry_run is not None:
        result = gateway.openclaw_dry_run(args.openclaw_dry_run)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.openclaw_send_test is not None:
        result = gateway.openclaw_send_test(args.openclaw_send_test)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.list_reminders:
        print(json.dumps(gateway.scheduler.list_active_reminders(), ensure_ascii=False))
        return 0
    if args.add_reminder_test is not None:
        fire_at = gateway.scheduler.now() + dt.timedelta(seconds=max(1, args.in_seconds))
        reminder_id = gateway.scheduler.add_one_shot_reminder(args.add_reminder_test, fire_at)
        print(json.dumps({"ok": True, "id": reminder_id, "fire_at": fire_at.isoformat(timespec="seconds")}, ensure_ascii=False))
        return 0
    if args.add_daily_alarm_test is not None:
        reminder_id = gateway.scheduler.add_daily_alarm(args.add_daily_alarm_test)
        print(json.dumps({"ok": True, "id": reminder_id}, ensure_ascii=False))
        return 0
    if args.clear_reminders:
        print(json.dumps({"ok": True, "disabled": gateway.scheduler.disable_all()}, ensure_ascii=False))
        return 0
    if args.clear_memory:
        gateway.memory.clear()
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0
    if args.list_alarm_music:
        files = gateway.music_player.list_music_files()
        print(json.dumps({"music_dir": gateway.music_player.config.get("alarm_music_dir", "/media/alarm-music"), "count": len(files), "files": files[:20]}, ensure_ascii=False))
        return 0
    if args.test_alarm_music:
        selected = gateway.music_player.choose_music_file()
        if not selected:
            print(json.dumps({"ok": False, "error": "no alarm music files", "file": None}, ensure_ascii=False))
            return 2
        stop_event = threading.Event()
        try:
            result = gateway.music_player.play_file(selected, stop_event, 20)
        except KeyboardInterrupt:
            stop_event.set()
            result = {"ok": True, "cancelled": True}
        result["file"] = selected
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.skip_alarm_test is not None:
        date_value = gateway.scheduler.now().date() + dt.timedelta(days=1 if args.tomorrow else 0)
        ok = gateway.scheduler.skip_alarm_once(args.skip_alarm_test, date_value)
        print(json.dumps({"ok": ok, "time_of_day": args.skip_alarm_test, "skip_date": date_value.isoformat()}, ensure_ascii=False))
        return 0 if ok else 2
    if args.cancel_alarm_test is not None:
        ok = gateway.scheduler.cancel_alarm_permanent(args.cancel_alarm_test)
        print(json.dumps({"ok": ok, "time_of_day": args.cancel_alarm_test}, ensure_ascii=False))
        return 0 if ok else 2
    if args.music_scan:
        result = gateway.music_library.scan_to_db()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.music_stats:
        result = gateway.music_library.stats()
        result["configured"] = gateway.music_library.music_dir.exists()
        result["extensions"] = sorted(gateway.music_library.extensions)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.music_search_artist is not None:
        results = gateway.music_library.search_artists(args.music_search_artist)
        print(json.dumps(results[:20], ensure_ascii=False))
        return 0
    if args.music_list_albums:
        artist = getattr(args, 'artist', None)
        results = gateway.music_library.list_albums(artist)
        print(json.dumps(results, ensure_ascii=False))
        return 0
    if args.music_search_track is not None:
        print(json.dumps(gateway.music_library.search_tracks(args.music_search_track, artist_query=args.artist)[:10], ensure_ascii=False))
        return 0
    if args.music_play_track is not None:
        matches = gateway.music_library.search_tracks(args.music_play_track, artist_query=args.artist)
        if not matches:
            print(json.dumps({"ok": False, "error": "track not found"}, ensure_ascii=False))
            return 2
        queue = gateway.music_library.get_track_context_queue(str(matches[0]["id"]))
        result = gateway.queue_player.start_queue_process(queue)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    if args.music_queue:
        print(json.dumps(gateway.queue_player.queue_summary(), ensure_ascii=False))
        return 0
    if args.music_stop:
        gateway.queue_player.request_stop()
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0
    if args.confirm_test is not None:
        test_text = args.confirm_test
        confirmed, normalized = gateway.classify_confirmation(test_text)
        result = {"input": test_text, "normalized": normalized, "decision": "yes" if confirmed is True else ("no" if confirmed is False else "unknown"), "matched_alias": None, "score": None}
        print(json.dumps(result, ensure_ascii=False))
        return 0 if confirmed is True else (2 if confirmed is False else 1)
    if args.self_test_assistant_core:
        checks = []
        samples = {
            "daily_alarm": "despiértame todos los días a las 7",
            "daily_alarm_morning": "despiértame todos los días a las 7 de la mañana",
            "reminder_10": "recuérdame en 10 minutos que revise el servidor",
            "reminder_half": "recuérdame en media hora que apague la compu",
            "local_route": "qué recordatorios tengo",
            "cancel_alarm": "detén la alarma",
            "cancel_alarm_permanent": "cancela la alarma de las 7 a partir de ahora",
            "skip_alarm_once": "cancela la alarma de las 7 solo mañana",
            "skip_alarm_no_suenes": "no suenes mañana a las 7",
            "cancel_all_alarms": "cancela todas las alarmas",
            "music_track_artist": "reproduce Doomsday de MF Doom",
            "music_track_artist_pon": "pon Doomsday de MF Doom",
            "music_track_artist_tyler": "reproduce See You Again de Tyler the Creator",
            "music_track": "reproduce Earfquake",
            "music_track_song": "pon la canción Earfquake",
            "music_now_playing": "qué canción es",
            "music_next": "siguiente",
        }
        for name, sample in samples.items():
            parsed = AssistantCommandParser.parse(sample)
            decision = gateway.firewall.classify(sample)
            checks.append({"name": name, "parsed": parsed, "route": decision.route, "action": decision.action})
        concise = make_concise_response("Claro que sí, esto es una respuesta larga. Tiene otra frase. Tiene una tercera frase que debe salir.", config)
        memory = ConversationMemory({"conversation_memory": {"enabled": True, "max_turns": 2, "storage_path": "/tmp/voice_gateway_memory_self_test.json"}}, logger)
        memory.add_turn("uno", "local", "test", "respuesta uno")
        memory.add_turn("dos", "local", "test", "respuesta dos")
        memory.add_turn("tres", "local", "test", "respuesta tres")
        memory_count = len(memory.turns)
        memory.clear()
        cancel_alias = gateway.firewall.match_cancel_alias("salir")[0]
        wake_samples = ["asistente", "sam", "samantha", "oye sam", "oye samantha", "sal"]
        wake_phrases = [TokenFirewall.normalize(str(item)) for item in config.get("wakeword", {}).get("fallback_stt_phrases", [])]
        wake_checks = []
        for sample in wake_samples:
            normalized = TokenFirewall.normalize(sample)
            matched, score, reason = gateway.match_wake_phrase(normalized, wake_phrases)
            wake_checks.append({"raw_text": sample, "normalized_text": normalized, "matched": matched, "fuzzy_score": score, "reason": reason})
        music_dir = str(config.get("scheduler", {}).get("alarm_music_dir", "/media/alarm-music"))
        result = {"ok": True, "checks": checks, "wake_checks": wake_checks, "music_dir": music_dir, "music_dir_configured": bool(music_dir), "concise": concise, "memory_count": memory_count, "cancel_alias": cancel_alias}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    gateway.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
