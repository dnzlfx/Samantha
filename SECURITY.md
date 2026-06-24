# Política de Seguridad

## Reporte de vulnerabilidades
Si encuentras una vulnerabilidad, **no abras un issue público**: contacta en
privado al mantenedor (Chris-devv) por los canales de su perfil de GitHub.

## Manejo de secretos
Samantha **no contiene** credenciales en el repositorio:
- `OPENAI_API_KEY` y demás secretos van en `.env` (ignorado por git). Usa `.env.example`.
- Nunca subas `.env`, `config.json`, `*.db` ni grabaciones/datos personales.

## Alcance
Samantha tiene voz, visión y monitoreo de pantalla: ejecútala solo en equipos
de tu confianza y revisa los permisos de micrófono/cámara de tu SO.
