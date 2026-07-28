"""Samantha core modules."""

from .version import __version__

__all__ = [
    'ModelManager',
    '__version__',
    'Intent',
    'IntentDetector',
    'SearchEngine',
    'QueryOptimizer',
    'SandboxExecutor',
    'MemoryManager'
]


def __getattr__(name):
    """Load core components lazily so unrelated imports do not require all dependencies."""
    if name in {'ModelManager', 'Intent', 'IntentDetector'}:
        from .llm_manager import Intent, IntentDetector, ModelManager
        return {'ModelManager': ModelManager, 'Intent': Intent, 'IntentDetector': IntentDetector}[name]

    if name in {'SearchEngine', 'QueryOptimizer'}:
        from .search_engine import QueryOptimizer, SearchEngine
        return {'SearchEngine': SearchEngine, 'QueryOptimizer': QueryOptimizer}[name]

    if name == 'SandboxExecutor':
        from .sandbox import SandboxExecutor
        return SandboxExecutor

    if name == 'MemoryManager':
        from .memory import MemoryManager
        return MemoryManager

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
