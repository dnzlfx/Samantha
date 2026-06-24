# Cómo contribuir a Samantha

## Entorno de desarrollo

```bash
git clone https://github.com/Chriss-devv/Samantha.git
cd Samantha
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # pon tu OPENAI_API_KEY (ignorado por git)
```

## Antes de abrir un Pull Request

1. **Compila**: `python -m compileall core modules ui *.py`
2. **Lint**: `ruff check .`
3. **Tests**: `pytest -q`
4. No incluyas secretos: `.env`, `config.json` y `*.db` están en `.gitignore`.

## Estilo
Python 3.11+, 4 espacios, líneas ≤ 100 col (ver `ruff.toml` / `.editorconfig`).
