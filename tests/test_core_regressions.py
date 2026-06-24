import unittest
from unittest.mock import Mock, patch

from core.llm_manager import Intent, ModelManager
from core.sandbox import SandboxExecutor


class ModelManagerGenerateTests(unittest.TestCase):
    def test_generate_non_streaming_returns_text(self):
        manager = ModelManager()
        manager.current_model = "test-model"

        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {"response": "hola"}

        with patch("core.llm_manager.requests.post", return_value=response) as post:
            result = manager.generate("saluda")

        self.assertEqual(result, "hola")
        post.assert_called_once()
        self.assertFalse(post.call_args.kwargs["stream"])


class SandboxAutoCorrectTests(unittest.TestCase):
    def test_auto_correct_uses_coding_model(self):
        class FakeModelManager:
            def __init__(self):
                self.models = {Intent.CODING: "coder-model"}
                self.current_model = "general-model"
                self.used_model = None

            def generate(self, prompt, model=None, temperature=0.7):
                self.used_model = model
                return "```python\nprint('ok')\n```"

        model_manager = FakeModelManager()
        executor = SandboxExecutor.__new__(SandboxExecutor)
        executor.model_manager = model_manager

        corrected = executor._auto_correct("print(ok)", "NameError")

        self.assertEqual(corrected, "print('ok')")
        self.assertEqual(model_manager.used_model, "coder-model")


if __name__ == "__main__":
    unittest.main()
