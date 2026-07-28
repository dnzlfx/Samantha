# Voice Admin Runner

Contenedor opcional para acciones administrativas estrictamente allowlisted.

## Seguridad

- Monta `/var/run/docker.sock`; esto equivale a control administrativo del host Docker.
- Debe estar solo en `automatizacion_automation-internal`.
- No debe conectarse a `homelab`.
- Requiere header `x-voice-token` igual a `VOICE_ADMIN_TOKEN`.
- No ejecuta shell ni comandos arbitrarios.

## Acciones Permitidas

- `openclaw_status`
- `openclaw_logs_tail`
- `restart_openclaw`

`restart_openclaw` exige:

```text
CONFIRMO_REINICIAR_OPENCLAW
```

## Ejemplo

```bash
curl -sS -H "x-voice-token: $VOICE_ADMIN_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"action":"openclaw_status"}' \
  http://127.0.0.1:8088/action
```
