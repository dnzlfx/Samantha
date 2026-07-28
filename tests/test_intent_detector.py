import unittest

from modules.intent_detector import Intent, IntentDetector


class ExtractEntityTests(unittest.TestCase):
    """Regression: `extract_entity` was defined twice; the stale second
    definition shadowed the one with noise-word cleaning and CRYPTO support."""

    def setUp(self):
        self.detector = IntentDetector()

    def test_weather_entity_strips_noise_words(self):
        entity = self.detector.extract_entity("que clima es en san luis potosi", Intent.WEATHER)
        self.assertEqual(entity, "san luis potosi")

    def test_crypto_intent_is_handled(self):
        self.assertEqual(self.detector.extract_entity("precio bitcoin", Intent.CRYPTO), "bitcoin")

    def test_defined_once(self):
        import ast
        import inspect

        import modules.intent_detector as module

        tree = ast.parse(inspect.getsource(module))
        names = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "extract_entity"
        ]
        self.assertEqual(len(names), 1, "extract_entity must not be redefined")


if __name__ == "__main__":
    unittest.main()
