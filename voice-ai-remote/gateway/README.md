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
- Implementa alarmas diarias y recordatorios de una sola vez con SQLite local en `/logs/reminders.sqlite3`.
- Las alarmas pueden reproducir música local aleatoria desde `/media/alarm-music` usando `ffmpeg` y el mismo `output_device` que TTS.
- Implementa memoria temporal en `/logs/conversation_memory.json`, limitada por `conversation_memory.max_turns`.
- Implementa respuestas cortas y TTS por chunks para una interrupción básica segura.
- Implementa fase manual de audio: desmuteo ALSA, tono de prueba, grabación VAD a WAV y reproducción WAV.
- Implementa STT y TTS reales por Wyoming usando `wyoming==1.8.0`:
  - STT: `voice-whisper:10300`
  - TTS: `voice-piper:10200`
- Implementa wake word real por Wyoming contra `voice-wakeword:10400` enviando audio PCM del micrófono y esperando `Detection`.

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
python /app/voice_gateway.py --wake-once
python /app/voice_gateway.py --wake-once --wake-provider stt
python /app/voice_gateway.py --wake-once --wake-provider auto
python /app/voice_gateway.py --wake-once --simulate-wake
python /app/voice_gateway.py --listen-loop --simulate-wake
python /app/voice_gateway.py --process-text "analiza este error del contenedor"
python /app/voice_gateway.py --openclaw-discover
python /app/voice_gateway.py --openclaw-dry-run "analiza este error del contenedor"
python /app/voice_gateway.py --openclaw-send-test "prueba explicita"
python /app/voice_gateway.py --list-reminders
python /app/voice_gateway.py --add-reminder-test "revisar logs" --in-seconds 30
python /app/voice_gateway.py --add-daily-alarm-test "07:00"
python /app/voice_gateway.py --clear-reminders
python /app/voice_gateway.py --clear-memory
python /app/voice_gateway.py --self-test-assistant-core
python /app/voice_gateway.py --list-alarm-music
python /app/voice_gateway.py --test-alarm-music
python /app/voice_gateway.py --skip-alarm-test "07:00" --tomorrow
python /app/voice_gateway.py --cancel-alarm-test "07:00"
python /app/voice_gateway.py --music-search-track "Doomsday"
python /app/voice_gateway.py --music-search-track "Doomsday" --artist "MF Doom"
python /app/voice_gateway.py --music-play-track "Doomsday" --artist "MF Doom"
python /app/voice_gateway.py --music-queue
python /app/voice_gateway.py --music-stop
```

## Wake Word

`--wake-once` conecta a `tcp://voice-wakeword:10400`, envía `Detect(names=["hey_jarvis"])`, hace streaming de audio desde `input_device: 4` a 16000 Hz y espera `Detection`. Si detecta wake word, habla `Te escucho.` y ejecuta un turno normal. Si expira el timeout, imprime JSON con `timeout` y no habla.

`--wake-provider` selecciona el detector de wake: `wyoming` usa openWakeWord, `stt` usa VAD + STT corto con frases como `asistente` u `oye asistente`, y `auto` intenta Wyoming primero y luego STT si no detecta. El fallback STT guarda el último intento en `/logs/wake_fallback_utterance.wav`.

`--listen-loop` usa el mismo wake word real y luego entra a ventana de follow-up. Para pruebas sin depender del modelo wake word, `--simulate-wake` mantiene el comportamiento de fase 0.7.

## Local Assistant Core

El parser de comandos es determinista por regex y no usa LLM ni servicios externos. Estos comandos siempre quedan en `route=local` y no van a OpenClaw.

Ejemplos soportados:

```text
despiértame todos los días a las 7
pon una alarma todos los días a las 7
alarma diaria a las 7 de la mañana
alarma todos los días a las 6 30
recuérdame en 10 minutos que revise el servidor
recuérdame en media hora que apague la compu
recuérdame en 1 hora y 30 minutos que revise docker
recordatorio en 5 minutos revisar logs
qué recordatorios tengo
cancela la alarma
cancela la alarma de las 7 a partir de ahora
cancela la alarma de las 7 solo mañana
no suenes mañana a las 7
cancela todas las alarmas
borra mis recordatorios
borra memoria
```

Las alarmas diarias se reprograman al siguiente día después de sonar. Los recordatorios de una sola vez se desactivan al dispararse. `salir`, `detente`, `alto`, `para` y `no importa` cancelan la alarma activa.

La carpeta de música se monta read-only en el stack:

```text
/mnt/datos/media/Musica/Mr interestelar -> /media/alarm-music
```

Si no hay música compatible o falla `ffmpeg`, la alarma usa TTS fallback con `Alarma.`.

El timezone por defecto es `America/Chicago`. Si el servidor está en otra zona horaria, cambia `scheduler.timezone` en `config.yaml`.

La interrupción de TTS es básica: el texto se divide en chunks y hay un `stop_event` interno. No se hace escucha agresiva sobre el propio TTS para evitar eco; la cancelación de alarmas es la ruta segura obligatoria.

## Música

El asistente puede buscar canciones por título y artista usando metadata de `ffprobe` (`title`, `artist`, `album_artist`) y fallback por carpeta/nombre de archivo.

Ejemplos:

```text
reproduce Doomsday de MF Doom
pon Doomsday de MF Doom
reproduce See You Again de Tyler the Creator
pon la canción See You Again
reproduce Earfquake
siguiente
qué canción es
detén la música
```

Cuando se reproduce una canción específica, la cola empieza con esa canción y continúa con canciones del mismo álbum, carpeta o artista. La cola se guarda en `/logs/music_queue.json`.

## OpenClaw

`--voice-turn-once` puede grabar con VAD, transcribir por Wyoming, pasar por `TokenFirewall`, responder localmente con Piper y descartar eco probable del último TTS.

Si la ruta es OpenClaw, el gateway guarda `/logs/pending_openclaw_prompt.txt` y pregunta siempre: `¿Quieres enviarlo a OpenClaw?`. Solo si la respuesta coincide con `confirmation.yes_aliases` continúa. Si la respuesta coincide con `confirmation.no_aliases`, viene vacía o no se entiende, responde `Cancelado.` y no envía nada.

Con `openclaw.dry_run: true`, una confirmación positiva tampoco envía nada: responde `Modo prueba. No envié nada a OpenClaw.` y audita el intento en `/logs/last_openclaw_prompt.txt`, `/logs/last_openclaw_response.txt` y `/logs/last_openclaw_error.txt`.

El envío real sigue bloqueado hasta configurar un `openclaw.rpc_method` probado. Si `rpc_method` está en `null`, `OpenClawClient.send_prompt()` rechaza con `OpenClaw todavía no tiene método RPC configurado.`.

`--openclaw-discover` solo hace diagnóstico seguro del WebSocket y handshake si es posible. No envía prompts, no modifica OpenClaw y deja `rpc_method=null` si no descubre un método seguro y documentado.

`--openclaw-dry-run "texto"` fuerza una prueba sin voz y sin envío real para validar firewall, confirmación lógica y auditoría. `--openclaw-send-test "texto"` solo intenta enviar si `dry_run=false` y `rpc_method` no es `null`.

## Persistencia Simple

```text
/logs/last_user_text.txt
/logs/last_assistant_text.txt
/logs/last_utterance.wav
/logs/last_tts.wav
/logs/pending_openclaw_prompt.txt
/logs/last_openclaw_prompt.txt
/logs/last_openclaw_response.txt
/logs/last_openclaw_error.txt
/logs/reminders.sqlite3
/logs/conversation_memory.json
/logs/music_queue.json
```
