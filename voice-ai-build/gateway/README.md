# Voice Gateway

Base funcional para enrutar voz transcrita hacia acciones locales, n8n u OpenClaw.

Este contenedor no procesa audio con OpenClaw. OpenClaw solo recibe texto filtrado por `TokenFirewall` cuando la consulta es compleja y útil.

## Estado Actual

- Carga `config.yaml`.
- Escribe logs a consola y `/logs/voice-gateway.log`.
- Lista dispositivos de audio con PortAudio si `/dev/snd` y grupo `audio` están disponibles.
- Verifica TCP hacia `voice-piper`, `voice-whisper`, `voice-wakeword`, `openclaw` y `n8n`.
- Implementa máquina de estados base.
- Implementa `TokenFirewall` y router de intención.
- Implementa acciones locales mínimas.
- Implementa cliente n8n con token por header.
- Implementa cliente OpenClaw desacoplado con circuit breaker. Por seguridad, no envía texto hasta configurar `openclaw.rpc_method` con el método RPC real del gateway.
- Implementa fase manual de audio: desmuteo ALSA, tono de prueba, grabación VAD a WAV y reproducción WAV.
- Implementa STT y TTS reales por Wyoming usando `wyoming==1.8.0`:
  - STT: `voice-whisper:10300`
  - TTS: `voice-piper:10200`

## Dispositivos Confirmados

```yaml
audio:
  input_device: 4
  output_device: 6
  sample_rate: 16000
  output_sample_rate: 48000
```

- Input: `GENERAL WEBCAM USB Audio`, 16000 Hz.
- Output: device `6`, 48000 Hz.
- Al iniciar y antes de reproducir se intenta desmutear `Master`, `Speaker`, `Headphone`, `PCM` y desactivar `Auto-Mute Mode` con `amixer` sin shell libre.

## Comandos Útiles

```bash
python /app/voice_gateway.py --healthcheck-once
python /app/voice_gateway.py --list-audio
python /app/voice_gateway.py --play-test-tone
python /app/voice_gateway.py --record-once
python /app/voice_gateway.py --stt-once /logs/last_utterance.wav
python /app/voice_gateway.py --tts-once "Hola, soy tu asistente de voz local"
python /app/voice_gateway.py --play-wav /logs/last_utterance.wav
python /app/voice_gateway.py --self-test-firewall
python /app/voice_gateway.py --voice-turn-once
python /app/voice_gateway.py --voice-turn-once --text "estado de openclaw"
python /app/voice_gateway.py --process-text "analiza este error del contenedor"
```

## Pendiente Del Loop Completo

Wake word queda para la siguiente fase. `--voice-turn-once` ya puede grabar con VAD, transcribir por Wyoming, pasar por `TokenFirewall`, responder localmente con Piper y descartar eco probable del último TTS. Si la ruta es OpenClaw y `openclaw.rpc_method` sigue en `null`, se rechaza explícitamente con `OpenClaw RPC method not configured; refusing to send prompt` y se habla: `OpenClaw todavía no tiene método RPC configurado`.

## Persistencia Simple

```text
/logs/last_user_text.txt
/logs/last_assistant_text.txt
/logs/last_utterance.wav
/logs/last_tts.wav
```
