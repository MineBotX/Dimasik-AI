import tempfile
import unittest
from pathlib import Path

import numpy as np

from assistant.brain import (
    BOS, CONTEXT_SIZE, EOS, UNK, DimasikBrain, _save_model, tokenize, train,
)


class DimaCoreTests(unittest.TestCase):
    def test_tokenize_handles_russian_and_punctuation(self):
        self.assertEqual(tokenize("Привет, Димасик! 2026"), ["привет", ",", "димасик", "!", "2026"])

    def test_train_save_load_and_generate(self):
        samples = [
            "привет я димасик и я готов тебе помочь сегодня",
            "как дела у тебя сегодня я рад тебя видеть",
            "компьютер выполняет программы и хранит данные",
            "нейронная сеть учится на примерах текста",
            "перед ответом нужно проверить известные факты",
            "я могу объяснить простые вещи понятными словами",
            "если данных недостаточно я сообщу об этом честно",
            "обучение меняет параметры маленькой нейронной сети",
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data_path = root / "training_data.txt"
            model_path = root / "dimasik_brain.npz"
            data_path.write_text("\n".join(samples), encoding="utf-8")

            vocab_size, example_count = train(
                data_path=data_path,
                model_path=model_path,
                epochs=3,
                embedding_size=8,
                hidden_size=16,
                learning_rate=0.002,
                validation_split=0.25,
                patience=3,
                seed=7,
            )
            self.assertGreater(vocab_size, 3)
            self.assertGreater(example_count, 10)
            self.assertTrue(model_path.is_file())

            brain = DimasikBrain(model_path)
            self.assertTrue(brain.ready, brain.load_error)
            answer = brain.answer("привет", max_tokens=12)
            self.assertIsInstance(answer, str)
            self.assertTrue(answer.strip())
            self.assertLessEqual(len(tokenize(answer)), 12)

    def test_corrupt_model_fails_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            model_path = Path(folder) / "broken.npz"
            model_path.write_bytes(b"not a numpy archive")
            brain = DimasikBrain(model_path)
            self.assertFalse(brain.ready)
            self.assertIsNotNone(brain.load_error)
            self.assertIn("пока не загружено", brain.answer("привет").lower())

    def test_rejects_incompatible_tensor_shapes(self):
        with tempfile.TemporaryDirectory() as folder:
            model_path = Path(folder) / "bad_shape.npz"
            vocab = [UNK, BOS, EOS, "привет"]
            _save_model(
                model_path, vocab,
                np.zeros((4, 8), dtype=np.float32),
                np.zeros((5, 16), dtype=np.float32),  # should be CONTEXT_SIZE * 8
                np.zeros(16, dtype=np.float32),
                np.zeros((16, 4), dtype=np.float32),
                np.zeros(4, dtype=np.float32),
            )
            brain = DimasikBrain(model_path)
            self.assertFalse(brain.ready)
            self.assertIn("размер первого слоя", brain.load_error.lower())


if __name__ == "__main__":
    unittest.main()
