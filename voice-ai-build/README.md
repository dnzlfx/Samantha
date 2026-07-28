# Voice AI Stack

Arquitectura modular para asistente de voz bidireccional conectado a OpenClaw.

## Arquitectura

```text
Micrófono
  -> voice-gateway (/dev/snd)
  -> voice-wakeword (Wyoming openWakeWord)
  -> VAD local en gateway (webrtcvad, fase adapter)
  -> voice-whisper (faster-whisper tiny-int8)
  -> Token Firewall
  -> Router de intención
       -> comando local
       -> n8n para automatizaciones no críticas
       -> OpenClaw solo con texto útil
  -> voice-piper (TTS local)
  -> bocinas
  -> follow-up temporal
  -> escucha pasiva
```

## Redes

La red solicitada `automation-internal` existe en Compose como red interna del proyecto `automatizacion`, pero el nombre real Docker es:

```text
automatizacion_automation-internal
```

`openclaw` y `n8n` están conectados a esa red y también a `homelab`. Los nuevos stacks usan solo `automatizacion_automation-internal` y no agregan `homelab`.

## Estructura

```text
/opt/voice-ai/
  admin-runner/
  checks/
  gateway/
  logs/
  n8n/
  openwakeword/
  piper/
  stacks/
  whisper/
```

## Orden De Despliegue

1. Construir imágenes locales:

```bash
docker build -t local/voice-gateway:0.1 /opt/voice-ai/gateway
docker build -t local/voice-admin-runner:0.1 /opt/voice-ai/admin-runner
```

2. Levantar motores de voz:

```bash
docker compose -f /opt/voice-ai/stacks/voice-ai-core.yml up -d
```

3. Levantar gateway:

```bash
docker compose -f /opt/voice-ai/stacks/voice-gateway.yml up -d
```

4. Opcional: levantar admin-runner con token fuerte:

```bash
export VOICE_ADMIN_TOKEN='cambia-esto'
docker compose -f /opt/voice-ai/stacks/voice-admin-runner.yml up -d
```

También puedes pegar cada YAML en Portainer como stack. No pegues `openclaw`, `n8n` ni `stand` en estos stacks.

## Variables De Entorno

Gateway hacia n8n:

```text
VOICE_WEBHOOK_TOKEN
```

n8n workflow:

```text
VOICE_WEBHOOK_TOKEN
ADMIN_RUNNER_TOKEN
DISCORD_WEBHOOK_URL (opcional)
```

Admin runner:

```text
VOICE_ADMIN_TOKEN
```

## Workflow n8n

Importa:

```text
/opt/voice-ai/n8n/voice-gateway-actions.json
```

Webhook esperado:

```text
POST /webhook/voice-gateway-action
```

El workflow valida `x-voice-token` contra `VOICE_WEBHOOK_TOKEN`.

## Pruebas

```bash
/opt/voice-ai/checks/verify_voice_ai.sh
docker exec voice-gateway python /app/voice_gateway.py --self-test-firewall
docker exec voice-gateway python /app/voice_gateway.py --list-audio
docker exec voice-gateway python /app/voice_gateway.py --process-text 'estado de openclaw'
docker exec voice-gateway python /app/voice_gateway.py --process-text 'analiza este error del contenedor'
```

## Grupo Audio

El grupo `audio` del host tiene GID `12`. El stack usa:

```yaml
group_add:
  - "12"
```

Si cambia, actualiza `/opt/voice-ai/stacks/voice-gateway.yml` con:

```bash
getent group audio
```

## Seguridad Del Docker Socket

`voice-admin-runner` monta `/var/run/docker.sock`. Esto da control administrativo del host Docker. Por eso:

- No se conecta a `homelab`.
- Solo expone `127.0.0.1:8088` si se publica.
- Requiere `x-voice-token`.
- Solo permite acciones allowlisted.
- No ejecuta shell libre.

## Qué NO Tocar

- No recrear `openclaw`.
- No recrear `n8n`.
- No recrear `stand`.
- No editar el Compose principal salvo necesidad explícita y backup previo.
- No mandar audio a OpenClaw.
- No poner n8n en la ruta crítica de voz.
- No usar Whisper large en este hardware.

## Troubleshooting

- `automation-internal not found`: usa el nombre Docker real `automatizacion_automation-internal`.
- `voice-gateway` no ve audio: revisa `/dev/snd`, `group_add`, `arecord -l`, `aplay -l`.
- `voice-whisper` tarda: primera descarga/model load puede tardar; usa `tiny-int8`.
- `OpenClaw adapter is configured for healthchecks only`: falta confirmar método RPC WebSocket real antes de enviar prompts desde gateway. Esto es intencional para no enviar basura ni usar protocolo incorrecto.

## Próximo Paso Técnico

Implementar el adapter real del protocolo Wyoming para streaming de wake word, STT y TTS, y confirmar el método RPC estable del Gateway OpenClaw para envío de texto desde `voice-gateway`.
