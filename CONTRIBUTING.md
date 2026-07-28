# Contribuir a Samantha

## Entorno local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt    # incluye requirements.txt + tooling
```

Samantha necesita [Ollama](https://ollama.com) corriendo localmente. Los modelos por
nivel de RAM están en `SETUP.md`.

## Antes de abrir un PR

Los tres comandos que corre CI. Si pasan localmente, pasan en Actions:

```bash
ruff check .                                  # lint
ruff format --check core/command_safety.py tests/   # formato (archivos nuevos)
pytest                                        # tests
```

Con coverage:

```bash
pytest --cov=core --cov=modules --cov-report=term-missing
```

## Convenciones

- **Formato**: `ruff format` sobre los archivos que toques. No reformatees archivos
  ajenos a tu cambio — un diff de estilo masivo hace inservible `git blame`.
- **Lint**: la config de `ruff` en `pyproject.toml` arranca con un set corto de reglas
  (`F`, `E9`, `W6`, `B006`, `B008`). Al añadir reglas, arregla las violaciones existentes
  en el mismo PR o el siguiente queda bloqueado.
- **Idioma**: UX en español (prompts, salida de CLI, docs). Código y comentarios en inglés.
- **Tests**: todo cambio de lógica no trivial lleva un test. `unittest` o `pytest`; ambos
  corren bajo `pytest`. Los tests mockean `requests`/Ollama en vez de pegarle a servicios
  reales. Si un test necesita una dependencia opcional, envuélvelo con
  `@unittest.skipIf(importlib.util.find_spec("x") is None, ...)`.
- **Commits**: en imperativo, con el ámbito al frente — `fix(homelab): ...`, `test(intent): ...`.

## Ejecución de comandos: el gate de seguridad

Cualquier ruta que ejecute comandos (local o SSH) pasa por dos niveles: los comandos SAFE
se auto-ejecutan, los DANGEROUS piden confirmación explícita. La decisión vive en
`core/command_safety.py` — un único helper usado por `modules/homelab.py` y `jarvis.py`.

Al añadir una ruta de ejecución nueva, **úsalo**. No escribas otro prefix-match: un
allowlist por prefijo sin rechazar operadores de shell permite `cat /etc/passwd; rm -rf /`
(ese era el bug que motivó el módulo). Los tests de regresión están en
`tests/test_command_safety.py`.

## Estructura

```
sam.py            entrypoint (re-exec al venv en ~/.local/share/samantha-venv)
core/             sistemas base: LLM routing, memoria SQLite, sandbox, búsqueda, safety
modules/          features, una responsabilidad por archivo
ui/               dashboard Rich y manejo de input
tests/            unittest/pytest, sin llamadas de red
jarvis.py         predecesor de un solo archivo — referencia, no lo extiendas
```
