"""Компактная контекстная нейросеть Димасика на NumPy.

DimaCore — экспериментальная модель предсказания следующего токена, а не LLM.
"""
import json
import os
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
CONTEXT_SIZE = 12
MODEL_FORMAT_VERSION = 2


def tokenize(text):
    """Разбивает русский/английский текст на слова, числа и знаки пунктуации."""
    return re.findall(r"[а-яёa-z0-9]+|[.,!?;:]", str(text).lower())


def _softmax(logits):
    logits = np.asarray(logits, dtype=np.float64)
    logits = logits - np.max(logits)
    values = np.exp(np.clip(logits, -60.0, 0.0))
    total = values.sum()
    if not np.isfinite(total) or total <= 0:
        raise FloatingPointError("Не удалось вычислить распределение вероятностей.")
    return values / total


class DimasikBrain:
    """Загрузка, проверка и генерация текста моделью DimaCore."""

    def __init__(self, model_path=MODEL_PATH):
        self.model_path = Path(model_path)
        self.ready = False
        self.load_error = None
        self.vocab = []
        self.word_to_id = {}
        self.embeddings = None
        self.w1 = self.b1 = self.w2 = self.b2 = None
        self.rng = np.random.default_rng()
        self._load()

    def _load(self):
        """Загружает модель только после полной проверки форм и значений массивов."""
        self.ready = False
        self.load_error = None
        if not self.model_path.is_file():
            return
        try:
            vocab_path = self.model_path.with_name("vocab.json")
            with np.load(self.model_path, allow_pickle=False) as data:
                required = {"embeddings", "w1", "b1", "w2", "b2"}
                if not required.issubset(set(data.files)):
                    raise ValueError("В файле модели отсутствуют необходимые массивы.")

                if "vocab" in data.files:
                    vocab = data["vocab"].astype(str).tolist()
                else:
                    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))

                arrays = {name: np.asarray(data[name], dtype=np.float32)
                          for name in required}

            if not isinstance(vocab, list) or not vocab or not all(isinstance(x, str) for x in vocab):
                raise ValueError("Словарь модели имеет неправильный формат.")
            if len(set(vocab)) != len(vocab):
                raise ValueError("В словаре модели есть повторяющиеся токены.")
            if vocab[:3] != [UNK, BOS, EOS]:
                raise ValueError("В словаре отсутствуют обязательные специальные токены.")

            emb = arrays["embeddings"]
            w1, b1 = arrays["w1"], arrays["b1"]
            w2, b2 = arrays["w2"], arrays["b2"]
            if emb.ndim != 2 or emb.shape[0] != len(vocab) or emb.shape[1] < 1:
                raise ValueError("Размер матрицы эмбеддингов не совпадает со словарём.")
            if w1.ndim != 2 or w1.shape[0] != CONTEXT_SIZE * emb.shape[1]:
                raise ValueError("Неподходящий размер первого слоя (возможно, другая версия DimaCore).")
            hidden_size = w1.shape[1]
            if b1.shape != (hidden_size,):
                raise ValueError("Неподходящий размер смещения первого слоя.")
            if w2.shape != (hidden_size, len(vocab)) or b2.shape != (len(vocab),):
                raise ValueError("Неподходящий размер выходного слоя.")
            if not all(np.isfinite(array).all() for array in arrays.values()):
                raise ValueError("Модель содержит NaN или бесконечные значения.")

            self.vocab = vocab
            self.word_to_id = {word: i for i, word in enumerate(vocab)}
            self.embeddings = emb
            self.w1, self.b1 = w1, b1
            self.w2, self.b2 = w2, b2
            self.ready = True
        except (OSError, EOFError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.load_error = str(exc)
            self.ready = False
        except Exception as exc:
            # Повреждённые архивы NumPy и неожиданные ошибки декодирования
            # не должны завершать запуск графического приложения.
            self.load_error = f"{type(exc).__name__}: {exc}"
            self.ready = False

    def _next_logits(self, context):
        if not self.ready:
            raise RuntimeError("Модель DimaCore не загружена.")
        ids = [self.word_to_id.get(word, self.word_to_id[UNK])
               for word in context[-CONTEXT_SIZE:]]
        ids = [self.word_to_id[BOS]] * (CONTEXT_SIZE - len(ids)) + ids
        x = self.embeddings[np.asarray(ids, dtype=np.int64)].reshape(-1)
        hidden = np.tanh(x @ self.w1 + self.b1)
        logits = hidden @ self.w2 + self.b2
        if not np.isfinite(logits).all():
            raise FloatingPointError("Модель вернула некорректные значения.")
        return logits.astype(np.float64, copy=False)

    def answer(self, prompt, max_tokens=56):
        """Генерирует ограниченный по длине ответ с простым подавлением повторов."""
        if not self.ready:
            return ("Моё нейросетевое ядро пока не загружено или не обучено. "
                    "Проверь файлы модели или запусти train_brain.py.")
        prompt_tokens = tokenize(prompt)
        if not prompt_tokens:
            return "Скажи, что тебя интересует."
        try:
            token_limit = max(1, min(128, int(max_tokens)))
        except (TypeError, ValueError):
            token_limit = 56

        context = [BOS] + prompt_tokens[-CONTEXT_SIZE:]
        generated = []
        counts = {}
        temperature = 0.85
        punctuation = {".", ",", "!", "?", ";", ":"}

        for _ in range(token_limit):
            try:
                logits = self._next_logits(context).copy()
                logits[self.word_to_id[BOS]] = -np.inf
                logits[self.word_to_id[UNK]] = -np.inf
                if len(generated) < 4:
                    logits[self.word_to_id[EOS]] = -np.inf

                # Мягкий штраф за уже использованные токены уменьшает зацикливание.
                for token_id, count in counts.items():
                    logits[token_id] -= min(1.5, 0.35 * count)
                if generated and generated[-1] not in punctuation:
                    last_id = self.word_to_id.get(generated[-1])
                    if last_id is not None:
                        logits[last_id] -= 1.0

                logits /= temperature
                probs = _softmax(logits)
                top_k = min(24, len(probs))
                candidates = np.argpartition(probs, -top_k)[-top_k:]
                candidate_probs = probs[candidates]
                candidate_probs /= candidate_probs.sum()
                token_id = int(self.rng.choice(candidates, p=candidate_probs))
                token = self.vocab[token_id]
            except (FloatingPointError, ValueError, IndexError):
                break

            if token == EOS:
                break
            generated.append(token)
            counts[token_id] = counts.get(token_id, 0) + 1
            context.append(token)
            context = context[-CONTEXT_SIZE:]
            if token in (".", "!", "?") and len(generated) >= 6:
                break

        if not generated:
            return "Пока не могу сформулировать ответ. Попробуй задать вопрос иначе."
        result = " ".join(generated)
        result = re.sub(r"\\s+([.,!?;:])", r"\\1", result)
        result = re.sub(r"\\s+", " ", result).strip()
        return result[:1].upper() + result[1:]


def _make_examples(sentences, ids):
    examples = []
    for sentence in sentences:
        encoded = [ids.get(word, 0) for word in ([BOS] * CONTEXT_SIZE + sentence + [EOS])]
        for pos in range(CONTEXT_SIZE, len(encoded)):
            examples.append((encoded[pos - CONTEXT_SIZE:pos], encoded[pos]))
    return examples


def _loss_for_examples(examples, embeddings, w1, b1, w2, b2, batch_size=256):
    if not examples:
        return float("inf")
    losses = 0.0
    for start in range(0, len(examples), batch_size):
        batch = examples[start:start + batch_size]
        x_ids = np.asarray([item[0] for item in batch], dtype=np.int64)
        targets = np.asarray([item[1] for item in batch], dtype=np.int64)
        x = embeddings[x_ids].reshape(len(batch), -1)
        hidden = np.tanh(x @ w1 + b1)
        logits = hidden @ w2 + b2
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(np.clip(logits, -60.0, 0.0))
        probs /= probs.sum(axis=1, keepdims=True)
        losses += float(-np.log(np.maximum(probs[np.arange(len(batch)), targets], 1e-12)).sum())
    return losses / len(examples)


def _save_model(model_path, vocab, embeddings, w1, b1, w2, b2):
    """Атомарно сохраняет веса; словарь включён и в NPZ, и в JSON для старых версий."""
    model_path = Path(model_path)
    vocab_path = model_path.with_name("vocab.json")
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temp_model = model_path.with_name(model_path.name + ".tmp")
    temp_vocab = vocab_path.with_name(vocab_path.name + ".tmp")
    try:
        with temp_model.open("wb") as stream:
            np.savez_compressed(
                stream,
                format_version=np.asarray([MODEL_FORMAT_VERSION], dtype=np.int32),
                vocab=np.asarray(vocab, dtype=np.str_),
                embeddings=embeddings, w1=w1, b1=b1, w2=w2, b2=b2,
            )
        temp_vocab.write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_model, model_path)
        os.replace(temp_vocab, vocab_path)
    finally:
        for temp in (temp_model, temp_vocab):
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def train(data_path=None, epochs=60, embedding_size=48, hidden_size=192,
          learning_rate=0.002, model_path=None, validation_split=0.15,
          patience=10, seed=2026):
    """Обучает DimaCore, контролирует качество на отложенных предложениях."""
    data_path = Path(data_path or ROOT / "training_data.txt")
    model_path = Path(model_path or MODEL_PATH)
    raw_lines = data_path.read_text(encoding="utf-8").splitlines()
    sentences = [tokenize(line.strip()) for line in raw_lines if line.strip()]
    sentences = [tokens for tokens in sentences if tokens]
    if len(sentences) < 2:
        raise ValueError("Для обучения нужно минимум два непустых предложения.")

    epochs = max(1, min(500, int(epochs)))
    embedding_size = max(4, min(512, int(embedding_size)))
    hidden_size = max(8, min(1024, int(hidden_size)))
    learning_rate = float(learning_rate)
    if not np.isfinite(learning_rate) or not 0 < learning_rate <= 0.1:
        raise ValueError("learning_rate должен быть числом больше 0 и не больше 0.1.")
    validation_split = max(0.0, min(0.4, float(validation_split)))
    patience = max(1, int(patience))

    rng = np.random.default_rng(int(seed))
    order = rng.permutation(len(sentences))
    if validation_split > 0 and len(sentences) >= 5:
        val_count = max(1, int(round(len(sentences) * validation_split)))
        val_count = min(val_count, len(sentences) - 1)
        val_indices = order[:val_count]
        train_indices = order[val_count:]
        train_sentences = [sentences[int(i)] for i in train_indices]
        val_sentences = [sentences[int(i)] for i in val_indices]
    else:
        train_sentences, val_sentences = sentences, []

    all_tokens = {token for sentence in sentences for token in sentence}
    vocab = [UNK, BOS, EOS] + sorted(all_tokens - {UNK, BOS, EOS})
    ids = {word: i for i, word in enumerate(vocab)}
    train_examples = _make_examples(train_sentences, ids)
    val_examples = _make_examples(val_sentences, ids)
    total_examples = len(train_examples) + len(val_examples)
    if len(train_examples) < 10:
        raise ValueError("Недостаточно обучающих примеров: добавь более длинные или разнообразные предложения.")

    vocab_size = len(vocab)
    embeddings = rng.normal(0, 0.08, (vocab_size, embedding_size)).astype(np.float32)
    input_size = CONTEXT_SIZE * embedding_size
    w1 = rng.normal(0, np.sqrt(2.0 / input_size),
                    (input_size, hidden_size)).astype(np.float32)
    b1 = np.zeros(hidden_size, dtype=np.float32)
    w2 = rng.normal(0, 0.02, (hidden_size, vocab_size)).astype(np.float32)
    b2 = np.zeros(vocab_size, dtype=np.float32)

    params = [embeddings, w1, b1, w2, b2]
    first_moments = [np.zeros_like(p) for p in params]
    second_moments = [np.zeros_like(p) for p in params]
    step = 0
    batch_size = 64
    beta1, beta2 = 0.9, 0.999
    best_loss = float("inf")
    best_params = None
    epochs_without_improvement = 0

    for epoch in range(epochs):
        permutation = rng.permutation(len(train_examples))
        for start in range(0, len(permutation), batch_size):
            indices = permutation[start:start + batch_size]
            batch = [train_examples[int(i)] for i in indices]
            x_ids = np.asarray([item[0] for item in batch], dtype=np.int64)
            targets = np.asarray([item[1] for item in batch], dtype=np.int64)
            batch_n = len(batch)

            x = embeddings[x_ids].reshape(batch_n, -1)
            hidden = np.tanh(x @ w1 + b1)
            logits = hidden @ w2 + b2
            logits -= logits.max(axis=1, keepdims=True)
            probs = np.exp(np.clip(logits, -60.0, 0.0))
            probs /= probs.sum(axis=1, keepdims=True)
            probs[np.arange(batch_n), targets] -= 1.0
            probs /= batch_n

            grad_w2 = hidden.T @ probs
            grad_b2 = probs.sum(axis=0)
            grad_hidden = probs @ w2.T
            grad_z1 = grad_hidden * (1.0 - hidden * hidden)
            grad_w1 = x.T @ grad_z1
            grad_b1 = grad_z1.sum(axis=0)
            grad_x = (grad_z1 @ w1.T).reshape(batch_n, CONTEXT_SIZE, embedding_size)
            grad_embeddings = np.zeros_like(embeddings)
            np.add.at(grad_embeddings, x_ids.reshape(-1), grad_x.reshape(-1, embedding_size))
            grads = [grad_embeddings, grad_w1, grad_b1, grad_w2, grad_b2]

            # Ограничиваем общую норму градиента до обновления Adam.
            grad_norm = float(np.sqrt(sum(float(np.sum(g * g)) for g in grads)))
            if not np.isfinite(grad_norm):
                raise FloatingPointError("Во время обучения получен некорректный градиент.")
            if grad_norm > 5.0:
                scale = 5.0 / (grad_norm + 1e-12)
                grads = [g * scale for g in grads]

            step += 1
            for i, (param, grad) in enumerate(zip(params, grads)):
                first_moments[i] = beta1 * first_moments[i] + (1.0 - beta1) * grad
                second_moments[i] = beta2 * second_moments[i] + (1.0 - beta2) * (grad * grad)
                m_hat = first_moments[i] / (1.0 - beta1 ** step)
                v_hat = second_moments[i] / (1.0 - beta2 ** step)
                param -= learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)

        train_loss = _loss_for_examples(train_examples, *params[:1], *params[1:])
        monitored_loss = (_loss_for_examples(val_examples, *params)
                          if val_examples else train_loss)
        if not np.isfinite(monitored_loss):
            raise FloatingPointError("Ошибка обучения: функция потерь стала некорректной.")

        if monitored_loss < best_loss - 1e-5:
            best_loss = monitored_loss
            best_params = [param.copy() for param in params]
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1

        if (epoch + 1) == 1 or (epoch + 1) % 10 == 0:
            label = "val_loss" if val_examples else "train_loss"
            print(f"Epoch {epoch + 1}/{epochs} - train_loss: {train_loss:.4f}; {label}: {monitored_loss:.4f}")

        if epochs_without_improvement >= patience:
            print(f"Early stopping: нет улучшения {patience} эпох.")
            break

    if best_params is None:
        raise RuntimeError("Обучение не создало пригодную версию модели.")
    _save_model(model_path, vocab, *best_params)
    return len(vocab), total_examples


if __name__ == "__main__":
    vocab_size, example_count = train()
    print(f"Training complete. Vocabulary: {vocab_size}; training pairs: {example_count}.")
