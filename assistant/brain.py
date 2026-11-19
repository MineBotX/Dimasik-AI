"""Собственная экспериментальная языковая модель Димасика (word-level neural bigram)."""
import json
import math
import random
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "brain" / "dimasik_brain.npz"
VOCAB_PATH = ROOT / "brain" / "vocab.json"
UNK = "<unk>"


def tokenize(text):
    return re.findall(r"[а-яёa-z0-9]+|[.,!?;:]", str(text).lower())


class DimasikBrain:
    """Небольшая MLP-модель предсказания следующего токена по предыдущему."""

    def __init__(self, model_path=MODEL_PATH):
        self.model_path = Path(model_path)
        self.ready = False
        self.vocab = []
        self.word_to_id = {}
        self.weights = None
        self.bias = None
        self.embeddings = None
        self._load()

    def _load(self):
        if not self.model_path.exists():
            return
        try:
            vocab_path = self.model_path.with_name("vocab.json")
            self.vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
            self.word_to_id = {w: i for i, w in enumerate(self.vocab)}
            data = np.load(self.model_path)
            self.embeddings = data["embeddings"]
            self.weights = data["weights"]
            self.bias = data["bias"]
            self.ready = True
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            self.ready = False

    def answer(self, prompt, max_tokens=48):
        if not self.ready:
            return ("Моё собственное ядро пока не обучено. Добавь примеры в "
                    "training_data.txt и запусти train_brain.py.")
        words = tokenize(prompt)
        if not words:
            return "Скажи что-нибудь, я слушаю."
        ids = [self.word_to_id.get(w, 0) for w in words]
        generated = []
        current = ids[-1]
        for _ in range(max_tokens):
            hidden = np.tanh(self.embeddings[current])
            logits = hidden @ self.weights + self.bias
            logits -= np.max(logits)
            probs = np.exp(logits / 0.85)
            probs /= probs.sum()
            # Не даём модели бесконечно повторять один и тот же токен.
            if generated:
                probs[generated[-1]] *= 0.15
                probs /= probs.sum()
            current = int(np.random.choice(len(self.vocab), p=probs))
            if self.vocab[current] in (".", "!", "?") and len(generated) > 5:
                generated.append(current)
                break
            generated.append(current)
        result = " ".join(self.vocab[i] for i in generated)
        result = re.sub(r"\\s+([.,!?;:])", r"\\1", result)
        return result[:1].upper() + result[1:]


def train(data_path=None, epochs=120, embedding_size=48, learning_rate=0.04):
    data_path = Path(data_path or ROOT / "training_data.txt")
    text = data_path.read_text(encoding="utf-8")
    sentences = [tokenize(line) for line in text.splitlines() if line.strip()]
    tokens = [w for line in sentences for w in line]
    vocab = [UNK] + sorted(set(tokens))
    ids = {w: i for i, w in enumerate(vocab)}
    pairs = [(ids.get(line[i], 0), ids.get(line[i + 1], 0))
             for line in sentences for i in range(len(line) - 1)]
    if len(pairs) < 20:
        raise ValueError("Для обучения нужно хотя бы 20 пар слов. Добавь больше строк в training_data.txt.")
    rng = np.random.default_rng(7)
    embeddings = rng.normal(0, 0.12, (len(vocab), embedding_size))
    weights = rng.normal(0, 0.08, (embedding_size, len(vocab)))
    bias = np.zeros(len(vocab))
    for epoch in range(epochs):
        random.shuffle(pairs)
        for source, target in pairs:
            h = np.tanh(embeddings[source])
            logits = h @ weights + bias
            logits -= logits.max()
            p = np.exp(logits)
            p /= p.sum()
            p[target] -= 1.0
            grad_w = np.outer(h, p)
            grad_h = weights @ p
            grad_e = grad_h * (1 - h * h)
            weights -= learning_rate * grad_w
            bias -= learning_rate * p
            embeddings[source] -= learning_rate * grad_e
    out = ROOT / "brain"
    out.mkdir(exist_ok=True)
    np.savez_compressed(out / "dimasik_brain.npz",
                        embeddings=embeddings, weights=weights, bias=bias)
    (out / "vocab.json").write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
    return len(vocab), len(pairs)


if __name__ == "__main__":
    size, examples = train()
    print(f"Обучение завершено: словарь {size}, примеров {examples}.")
