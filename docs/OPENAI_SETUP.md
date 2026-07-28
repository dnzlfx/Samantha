# Samantha OpenAI Setup

## 1. Configura tu API Key

```bash
cd /home/chris/Samantha
cp .env.example .env
nano .env
```

Edita `.env` y agrega tu API key:
```bash
OPENAI_API_KEY=sk-proj-...
```

## 2. Uso

**Ollama (local, gratis):**
```bash
python sam.py
> cambiar llama3
```

**OpenAI (requiere API key, pago):**
```bash
python sam.py
> cambiar gpt-4
> cambiar gpt-3.5-turbo
```

**El sistema detecta automáticamente:**
- `gpt-*` → OpenAI
- Todo lo demás → Ollama

## 3. Ver modelos disponibles

```bash
> modelos

Ollama:
- llama3:latest
- codellama:latest

OpenAI:
- gpt-4
- gpt-4-turbo
- gpt-3.5-turbo
```

## 4. Costos OpenAI

- GPT-4: ~$0.03/1K input tokens, ~$0.06/1K output
- GPT-3.5-turbo: ~$0.0015/1K input tokens, ~$0.002/1K output

## 5. Fallback

Si falla OpenAI (sin API key, error), automáticamente usa Ollama.
