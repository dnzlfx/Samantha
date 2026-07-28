# Samantha - Asistente Multimodal

Asistente de IA con voz, visión, monitoreo de pantalla y toma de decisiones autónoma.

Versión: 1.3.0

## 🚀 Inicio Rápido

Requiere [Ollama](https://ollama.com) corriendo local. Modelos por nivel de RAM en `SETUP.md`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python sam.py
```

**Voice mode OFF por defecto.** Usar `--voice` para habilitar.

Voz y visión traen dependencias del sistema aparte: `./install_voice.sh`, `./install_vision.sh`.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Para contribuir, ver [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 🎤 Comandos de Voz

### Activación
Di **"Sam"** para activar. Escucharás "Sí, señor" y luego habla tu comando.

### Interrumpir
Di **"Sam"** mientras habla para interrumpir y dar nuevo comando.

### 📺 Screen Monitoring (Nuevo!)
- **"Sam, empieza a ver escritorio"** - Monitorea pantalla
- **"Sam, qué ves"** - Describe pantalla actual
- **"Sam, qué tengo que hacer"** - Analiza y da instrucciones
- **"Sam, así está bien?"** - Verifica si cambios son correctos
- **"Sam, deja de ver"** - Detiene monitoreo

### Comandos Visuales
- **"Sam, qué estoy sosteniendo"** - Analiza objeto en mano
- **"Sam, lee la pantalla"** - OCR de pantalla
- **"Sam, así?"** - Pregunta de seguimiento con contexto

### Comandos Generales
- **"Sam, quién es [persona]"** - Biografía
- **"Sam, qué clima hace"** - Clima actual
- **"Sam, [pregunta]"** - Cualquier cosa

---

## 📋 Comandos de Texto

### Sistema
- `salir` - Guardar y salir
- `limpiar` - Limpiar historial
- `modelos` - Ver modelos disponibles
- `cambiar <modelo>` - Cambiar modelo

### APIs Automáticas
- `clima` - Clima actual
- `crypto` - Precios de criptomonedas  
- `miip` - Tu IP pública
- `noticias` - Noticias recientes

---

## ✨ Características

**🧠 Intent Detection**
- 21 intents con auto-ejecución
- Multi-intent en una query
- Sin confirmaciones necesarias

**🎤 Voice**
- Wake word: "Sam"
- STT: Google (online)
- TTS: gTTS (online)
- Interrupción instantánea

**👁️ Vision**
- llava para análisis
- OpenCV para cámara
- Tesseract para OCR
- Memoria de contexto visual

**📺 Screen Monitoring**
- Monitoreo continuo de escritorio
- Análisis bajo demanda (optimizado)
- Guidance en tiempo real
- Verificación de cambios

---

## 🔧 Instalación

### Dependencias Voice
```bash
./install_voice.sh
```

### Dependencias Vision + Screen
```bash
./install_vision.sh
sudo pacman -S scrot  # Para screenshots
```

---

## 💡 Casos de Uso

### Co-Pilot Visual
```
"Sam, empieza a ver escritorio"
[Abre terminal con error]
"Sam, qué tengo que hacer para arreglar esto"
→ "Veo un error de permisos. Ejecuta: sudo chmod..."
[Sigues instrucciones]
"Sam, así está bien?"
→ "Sí, el error desapareció. Está correcto."
```

### Debugging Asistido
```
"Sam, empieza a ver escritorio"
[Código con bug]
"Sam, qué ves"
→ Describe código y error
"Sam, qué hago"
→ Da solución paso a paso
```

---

## ⚙️ Configuración

**Micrófono:**
Sistema usa PulseAudio/PipeWire automáticamente.

**Energy Threshold:** 200 (dinámico)

**Wake Word:** Configurable en `modules/voice.py`

**Screenshot Interval:** 30 segundos (configurable en `modules/screen_monitor.py`)

---

## 📁 Estructura

```
sam.py                  - Entrypoint y main loop
core/
  llm_manager.py        - Routing de modelos Ollama por intent
  memory.py             - Memoria SQLite (~/.samantha/sam_brain.db)
  sandbox.py            - Ejecución aislada de código
  search_engine.py      - Búsqueda web (DuckDuckGo)
  command_safety.py     - Gate SAFE/DANGEROUS de comandos
modules/
  voice.py              - Voice (wake word, STT, TTS)
  vision.py             - Vision (llava, camera, OCR)
  screen_monitor.py     - Screen monitoring
  intent_detector.py    - Intent detection (21 intents)
  integrations.py       - APIs externas (clima, crypto, Telegram)
  homelab.py            - SSH a servidores del home lab
ui/                     - Dashboard Rich e input
tests/                  - unittest/pytest, sin red
```

---

## 🐛 Troubleshooting

**Voice no funciona:**
- Verificar micrófono: `pactl list sources`
- Verificar dependencias: `pip list | grep SpeechRecognition`

**Vision no funciona:**
- Camera: `ls /dev/video*`
- llava: `ollama list | grep llava`

**Screen monitoring no funciona:**
- scrot: `which scrot`
- Permisos de pantalla

**Latencia alta:**
- Reducir volumen para evitar feedback
- Usar audífonos
- Verificar CPU usage
- Aumentar screenshot interval (screen_monitor.py)

---

Documentación completa en `docs/`
