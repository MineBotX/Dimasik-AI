import tempfile
import unittest
from pathlib import Path

import numpy as np

from assistant.brain import (
    BOS, CONTEXT_SIZE, EOS, MODEL_FORMAT_VERSION, PARAMETER_NAMES,
    DimasikBrain, _backward_batch, _forward_batch, _make_examples,
    _softmax, _save_model, tokenize, train,
)


def make_params(vocab_size=7, dim=8, hidden=12, seed=3):
    rng = np.random.default_rng(seed)
    return {
        "embeddings": rng.normal(0, .1, (vocab_size, dim)).astype(np.float32),
        "position_embeddings": rng.normal(0, .02, (CONTEXT_SIZE, dim)).astype(np.float32),
        "wq": rng.normal(0, .1, (dim, dim)).astype(np.float32),
        "wk": rng.normal(0, .1, (dim, dim)).astype(np.float32),
        "wv": rng.normal(0, .1, (dim, dim)).astype(np.float32),
        "wo": rng.normal(0, .1, (dim, dim)).astype(np.float32),
        "relative_bias": np.zeros(CONTEXT_SIZE, dtype=np.float32),
        "w1": rng.normal(0, .1, (dim, hidden)).astype(np.float32),
        "b1": np.zeros(hidden, dtype=np.float32),
        "w2": rng.normal(0, .1, (hidden, vocab_size)).astype(np.float32),
        "b2": np.zeros(vocab_size, dtype=np.float32),
    }


class DimaCore20Tests(unittest.TestCase):
    def test_tokenize_handles_russian_and_punctuation(self):
        self.assertEqual(
            tokenize("Привет, Димасик! 2026"),
            ["привет", ",", "димасик", "!", "2026"],
        )

    def test_attention_forward_and_backward_have_valid_shapes(self):
        params = make_params()
        x_ids = np.zeros((3, CONTEXT_SIZE), dtype=np.int64)
        targets = np.asarray([3, 4, 5], dtype=np.int64)
        logits, state = _forward_batch(x_ids, params, cache=True)
        self.assertEqual(logits.shape, (3, 7))
        grads = _backward_batch(targets, params, state)
        self.assertEqual(set(grads), set(PARAMETER_NAMES))
        for name in PARAMETER_NAMES:
            self.assertEqual(grads[name].shape, params[name].shape, name)
            self.assertTrue(np.isfinite(grads[name]).all(), name)

    def test_attention_gradient_matches_finite_difference(self):
        params = make_params(vocab_size=7, dim=8, hidden=12, seed=9)
        x_ids = np.random.default_rng(2).integers(
            0, 7, (2, CONTEXT_SIZE), dtype=np.int64
        )
        targets = np.asarray([3, 4], dtype=np.int64)
        _logits, state = _forward_batch(x_ids, params, cache=True)
        smoothing = 0.04
        grads = _backward_batch(targets, params, state, label_smoothing=smoothing)

        def loss():
            probs = _softmax(_forward_batch(x_ids, params))
            log_probs = np.log(np.maximum(probs, 1e-12))
            selected = log_probs[np.arange(2), targets]
            uniform = log_probs.mean(axis=1)
            return float(-((1.0 - smoothing) * selected + smoothing * uniform).mean())

        checks = (
            ("embeddings", (2, 3)),
            ("position_embeddings", (5, 3)),
            ("wq", (2, 3)),
            ("wk", (2, 3)),
            ("wv", (2, 3)),
            ("wo", (2, 3)),
            ("relative_bias", (5,)),
            ("w1", (2, 3)),
            ("b1", (3,)),
            ("w2", (3, 4)),
            ("b2", (4,)),
        )
        epsilon = 1e-3
        for name, index in checks:
            with self.subTest(parameter=name):
                original = float(params[name][index])
                params[name][index] = original + epsilon
                plus = loss()
                params[name][index] = original - epsilon
                minus = loss()
                params[name][index] = original
                numerical = (plus - minus) / (2 * epsilon)
                self.assertAlmostEqual(
                    float(grads[name][index]), numerical, delta=2e-3
                )

    def test_rare_targets_are_skipped_after_vocabulary_pruning(self):
        ids = {"<unk>": 0, "<bos>": 1, "<eos>": 2, "я": 3, "слово": 4}
        examples = _make_examples([["я", "редкое", "слово"]], ids)
        self.assertEqual(len(examples), 3)
        self.assertTrue(all(target != ids["<unk>"] for _context, target in examples))

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
                epochs=4,
                embedding_size=8,
                hidden_size=16,
                learning_rate=0.001,
                validation_split=0.25,
                patience=4,
                seed=7,
                min_token_frequency=2,
            )
            self.assertGreater(vocab_size, 3)
            self.assertGreater(example_count, 10)
            self.assertTrue(model_path.is_file())

            with np.load(model_path, allow_pickle=False) as saved:
                self.assertEqual(
                    int(saved["format_version"][0]), MODEL_FORMAT_VERSION
                )
                self.assertIn("position_embeddings", saved.files)
                self.assertIn("wq", saved.files)

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

    def test_rejects_incompatible_attention_shapes(self):
        with tempfile.TemporaryDirectory() as folder:
            model_path = Path(folder) / "bad_shape.npz"
            vocab = ["<unk>", "<bos>", "<eos>", "привет"]
            params = make_params(vocab_size=len(vocab))
            params["wq"] = np.zeros((7, 8), dtype=np.float32)
            _save_model(model_path, vocab, params)
            brain = DimasikBrain(model_path)
            self.assertFalse(brain.ready)
            self.assertIn("attention", brain.load_error.lower())

    def test_old_format_is_rejected_with_upgrade_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            model_path = Path(folder) / "old.npz"
            np.savez_compressed(
                model_path, format_version=np.asarray([2], dtype=np.int32)
            )
            brain = DimasikBrain(model_path)
            self.assertFalse(brain.ready)
            self.assertIn("переобучи", brain.load_error.lower())


if __name__ == "__main__":
    unittest.main()
