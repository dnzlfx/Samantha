#!/usr/bin/env bash
set -u

section() { printf '\n==== %s ====\n' "$1"; }
run() { printf '\n$ %s\n' "$*"; "$@" 2>&1 || true; }

section "Docker networks"
run docker network ls
run docker network inspect automatizacion_automation-internal
run docker network inspect homelab

section "Host resources"
run df -h
run free -h
run uptime

section "Audio devices and group"
run ls -l /dev/snd
run getent group audio
run arecord -l
run aplay -l

section "Docker containers"
run docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

section "Ports in use"
run ss -ltnp

section "Voice container DNS and TCP checks"
if docker ps --format '{{.Names}}' | grep -qx 'voice-gateway'; then
  run docker exec voice-gateway getent hosts openclaw
  run docker exec voice-gateway getent hosts n8n
  run docker exec voice-gateway getent hosts voice-piper
  run docker exec voice-gateway getent hosts voice-whisper
  run docker exec voice-gateway getent hosts voice-wakeword
  run docker exec voice-gateway python /app/voice_gateway.py --healthcheck-once
  run docker exec voice-gateway arecord -l
  run docker exec voice-gateway aplay -l
else
  printf 'voice-gateway is not running; skipping container DNS/TCP checks.\n'
fi

section "Recent logs"
for c in voice-piper voice-whisper voice-wakeword voice-gateway voice-admin-runner; do
  if docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
    run docker logs "$c" --tail 80
  else
    printf '%s does not exist yet.\n' "$c"
  fi
done
