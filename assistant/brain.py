"""Контекстная языковая нейросеть Димасика на NumPy.

Это небольшая учебная модель с окном из нескольких предыдущих токенов,
эмбеддингами и двумя полносвязными слоями. Она не является LLM уровня ChatGPT.
"""
import json
import random
import re
import sys
from pathlib import Path

import numpy as np

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parents[1]

MODEL_PATH = ROOT / "brain" / "dimasik_brain.npz"
VOCAB_PATH = ROOT / "brain" / "vocab.json"
UNK = "<unk>"
BOS = "<bos>"
EOS = "<eos>"
CONTEXT_SIZE = 8


def tokenize(text):
    return re.findall(r"[а-яёa-z0-9]+|[.,!?;:]", str(text).lower())


class DimasikBrain:
    """Генератор текста, учитывающий до восьми последних токенов."""

    def __init__(self, model_path=MODEL_PATH):
        self.model_path = Path(model_path)
        self.ready = False
        self.vocab = []
        self.word_to_id = {}
        self.embeddings = None
        self.w1 = self.b1 = self.w2 = self.b2 = None
        self._load()

    def _load(self):
        if not self.model_path.exists():
            return
        try:
            vocab_path = self.model_path.with_name("vocab.json")
            self.vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
            self.word_to_id = {word: i for i, word in enumerate(self.vocab)}
            with np.load(self.model_path) as data:
                self.embeddings = data["embeddings"]
                self.w1, self.b1 = data["w1"], data["b1"]
                self.w2, self.b2 = data["w2"], data["b2"]
            expected = (CONTEXT_SIZE, self.embeddings.shape[1])
            self.ready = self.embeddings.ndim == 2 and self.w1.shape[0] == expected[0] * expected[1]
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            self.ready = False

    def _next_logits(self, context):
        ids = [self.word_to_id.get(word, 0) for word in context[-CONTEXT_SIZE:]]
        ids = [self.word_to_id[BOS]] * (CONTEXT_SIZE - len(ids)) + ids
        x = self.embeddings[np.asarray(ids)].reshape(-1)
        hidden = np.tanh(x @ self.w1 + self.b1)
        return hidden @ self.w2 + self.b2

    def answer(self, prompt, max_tokens=56):
        if not self.ready:
            return ("Моё нейросетевое ядро пока не обучено. "
                    "Нужна повторная установка или запуск train_brain.py.")
        prompt_tokens = tokenize(prompt)
        if not prompt_tokens:
            return "Скажи, что тебя интересует."
        # Берём последние слова запроса, но не выдаём весь запрос за ответ.
        context = [BOS] + prompt_tokens[-CONTEXT_SIZE:]
        generated = []
        rng = np.random.default_rng()
        for _ in range(max_tokens):
            logits = self._next_logits(context)
            logits[self.word_to_id[ BOS ]] = -1e9
            logits[self.word_to_id[UNK]] = -1e9
            logits /= 0.8
            logits -= np.max(logits)
            probs = np.exp(np.clip(logits, -40, 40))
            probs /= probs.sum()
            token_id = int(rng.choice(len(self.vocab), p=probs))
            token = self.vocab[token_id]
            if token == EOS:
                break
            generated.append(token)
            context.append(token)
            context = context[-CONTEXT_SIZE:]
            if token in (".", "!", "?") and len(generated) >= 8:
                break
        if not generated:
            return "Пока не могу сформулировать ответ. Попробуй задать вопрос иначе."
        result = " ".join(generated)
        result = re.sub(r"\s+([.,!?;:])", r"\1", result)
        result = re.sub(r"\s+", " ", result).strip()
        return result[:1].upper() + result[1:]


def train(data_path=None, epochs=45, embedding_size=32, hidden_size=128, learning_rate=0.003):
    """Обучает модель предсказывать следующий токен по окну из 8 токенов."""
    data_path = Path(data_path or ROOT / "training_data.txt")
    lines = [line.strip() for line in data_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    sentences = []
    for line in lines:
        tokens = tokenize(line)
        if tokens:
            sentences.append([BOS] * CONTEXT_SIZE + tokens + [EOS])
    tokens_all = [token for sentence in sentences for token in sentence]
    vocab = [UNK, BOS, EOS] + sorted(set(tokens_all) - {UNK, BOS, EOS})
    ids = {word: i for i, word in enumerate(vocab)}
    examples = []
    for sentence in sentences:
        encoded = [ids.get(word, 0) for word in sentence]
        for pos in range(CONTEXT_SIZE, len(encoded)):
            examples.append((encoded[pos - CONTEXT_SIZE:pos], encoded[pos]))
    if len(examples) < 100:
        raise ValueError("Недостаточно обучающих примеров: добавь больше предложений в training_data.txt.")

    rng = np.random.default_rng(2026)
    vocab_size = len(vocab)
    embeddings = rng.normal(0, 0.08, (vocab_size, embedding_size)).astype(np.float32)
    input_size = CONTEXT_SIZE * embedding_size
    w1 = rng.normal(0, np.sqrt(2 / input_size), (input_size, hidden_size)).astype(np.float32)
    b1 = np.zeros(hidden_size, dtype=np.float32)
    w2 = rng.normal(0, 0.02, (hidden_size, vocab_size)).astype(np.float32)
    b2 = np.zeros(vocab_size, dtype=np.float32)

    params = [embeddings, w1, b1, w2, b2]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    step = 0
    batch_size = 64

    for epoch in range(epochs):
        random.Random(1000 + epoch).shuffle(examples)
        total_loss = 0.0
        for start in range(0, len(examples), batch_size):
            batch = examples[start:start + batch_size]
            x_ids = np.asarray([item[0] for item in batch], dtype=np.int64)
            targets = np.asarray([item[1] for item in batch], dtype=np.int64)
            batch_n = len(batch)
            x = embeddings[x_ids].reshape(batch_n, -1)
            h = np.tanh(x @ w1 + b1)
            logits = h @ w2 + b2
            logits -= logits.max(axis=1, keepdims=True)
            probs = np.exp(np.clip(logits, -40, 40))
            probs /= probs.sum(axis=1, keepdims=True)
            total_loss += float(-np.log(np.maximum(probs[np.arange(batch_n), targets], 1e-9)).sum())

            probs[np.arange(batch_n), targets] -= 1.0
            probs /= batch_n
            grad_w2 = h.T @ probs
            grad_b2 = probs.sum(axis=0)
            grad_h = probs @ w2.T
            grad_z1 = grad_h * (1.0 - h * h)
            grad_w1 = x.T @ grad_z1
            grad_b1 = grad_z1.sum(axis=0)
            grad_x = (grad_z1 @ w1.T).reshape(batch_n, CONTEXT_SIZE, embedding_size)
            grad_embeddings = np.zeros_like(embeddings)
            np.add.at(grad_embeddings, x_ids.reshape(-1), grad_x.reshape(-1, embedding_size))
            grads = [grad_embeddings, grad_w1, grad_b1, grad_w2, grad_b2]

            step += 1
            for i, (param, grad) in enumerate(zip(params, grads)):
                m[i] = 0.9 * m[i] + 0.1 * grad
                v[i] = 0.999 * v[i] + 0.001 * (grad * grad)
                m_hat = m[i] / (1 - 0.9 ** step)
                v_hat = v[i] / (1 - 0.999 ** step)
                param -= learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)

        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch + 1}/{epochs} - loss: {total_loss / len(examples):.4f}")

    out = ROOT / "brain"
    out.mkdir(exist_ok=True)
    np.savez_compressed(out / "dimasik_brain.npz",
                        embeddings=embeddings, w1=w1, b1=b1, w2=w2, b2=b2)
    (out / "vocab.json").write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
    return len(vocab), len(examples)


if __name__ == "__main__":
    vocab_size, example_count = train()
    print(f"Training complete. Vocabulary: {vocab_size}; examples: {example_count}.")
