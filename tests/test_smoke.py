"""Smoke tests para Samantha: garantizan que el codigo compila y que
los archivos de configuracion de ejemplo existen. No importan dependencias
pesadas (voz, vision, ollama)."""
import pathlib
import py_compile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = (".venv", ".venv-linux", "build", "dist", "__pycache__",
        "voice-ai-build", "voice-ai-remote")


def test_all_python_compiles():
    fallos = []
    for py in ROOT.rglob("*.py"):
        if any(p in py.parts for p in SKIP):
            continue
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as exc:  # pragma: no cover
            fallos.append(f"{py}: {exc}")
    assert not fallos, "Archivos que no compilan:\n" + "\n".join(fallos)


def test_env_example_existe():
    assert (ROOT / ".env.example").exists(), "Falta .env.example"
