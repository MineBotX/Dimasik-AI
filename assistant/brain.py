"""DimaCore 2.0: компактная контекстная attention-сеть на NumPy.

Это экспериментальная модель предсказания следующего токена, а не большая языковая модель.
"""
from __future__ import annotations

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
UNK = "<unk>"
BOS = "<bos>"
EOS = "<eos>"
CONTEXT_SIZE = 24
MODEL_FORMAT_VERSION = 3
PARAMETER_NAMES = (
    "embeddings", "position_embeddings", "wq", "wk", "wv", "wo",
    "relative_bias", "w1", "b1", "w2", "b2",
)


def tokenize(text: str) -> list[str]:
    """Нормализует регистр и выделяет русские/английские слова, числа и пунктуацию."""
    return re.findall(r"[а-яёa-z0-9]+|[.,!?;:]", str(text).lower())


def _softmax(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64)
    values = values - np.max(values, axis=-1, keepdims=True)
    exp = np.exp(np.clip(values, -60.0, 0.0))
    total = exp.sum(axis=-1, keepdims=True)
    if not np.isfinite(total).all() or np.any(total <= 0):
        raise FloatingPointError("Не удалось вычислить распределение вероятностей.")
    return exp / total


def _forward_batch(token_ids: np.ndarray, params: dict[str, np.ndarray], cache: bool = False):
    """Одноголовое attention последнего токена по окну контекста + residual MLP."""
    embeddings = params["embeddings"]
    x = embeddings[token_ids] + params["position_embeddings"][None, :, :]
    last = x[:, -1, :]
    q = last @ params["wq"]
    k = x @ params["wk"]
    v = x @ params["wv"]
    scale = 1.0 / np.sqrt(float(embeddings.shape[1]))
    scores = np.einsum("btd,bd->bt", k, q) * scale
    scores = scores + params["relative_bias"][None, :]
    attention = _softmax(scores)
    attended = np.einsum("bt,btd->bd", attention, v)
    fused = last + attended @ params["wo"]
    hidden = np.tanh(fused @ params["w1"] + params["b1"])
    logits = hidden @ params["w2"] + params["b2"]
    if not np.isfinite(logits).all():
        raise FloatingPointError("Модель вернула некорректные значения.")
    if not cache:
        return logits
    return logits, {
        "logits": logits, "token_ids": token_ids, "x": x, "last": last, "q": q, "k": k, "v": v,
        "attention": attention, "attended": attended, "fused": fused, "hidden": hidden,
    }


def _backward_batch(targets: np.ndarray, params: dict[str, np.ndarray], state: dict) -> dict[str, np.ndarray]:
    """Ручное обратное распространение для attention-блока и выходного классификатора."""
    x = state["x"]
    last = state["last"]
    q, k, v = state["q"], state["k"], state["v"]
    attention = state["attention"]
    attended, fused, hidden = state["attended"], state["fused"], state["hidden"]
    token_ids = state["token_ids"]
    batch_n, _, dim = x.shape

    probs = _softmax(state["logits"])
    probs[np.arange(batch_n), targets] -= 1.0
    probs /= batch_n

    grad_w2 = hidden.T @ probs
    grad_b2 = probs.sum(axis=0)
    grad_hidden = probs @ params["w2"].T
    grad_pre_hidden = grad_hidden * (1.0 - hidden * hidden)
    grad_fused = grad_pre_hidden @ params["w1"].T
    grad_w1 = fused.T @ grad_pre_hidden
    grad_b1 = grad_pre_hidden.sum(axis=0)

    grad_attended = grad_fused @ params["wo"].T
    grad_wo = attended.T @ grad_fused
    grad_attention = np.einsum("bd,btd->bt", grad_attended, v)
    grad_v = attention[:, :, None] * grad_attended[:, None, :]
    grad_scores = attention * (
        grad_attention - np.sum(grad_attention * attention, axis=1, keepdims=True)
    )
    scale = 1.0 / np.sqrt(float(dim))
    grad_q = np.einsum("bt,btd->bd", grad_scores, k) * scale
    grad_k = grad_scores[:, :, None] * q[:, None, :] * scale
    grad_wq = last.T @ grad_q
    grad_wk = np.einsum("btd,btk->dk", x, grad_k)
    grad_wv = np.einsum("btd,btk->dk", x, grad_v)

    grad_x = grad_k @ params["wk"].T + grad_v @ params["wv"].T
    grad_x[:, -1, :] += grad_fused + grad_q @ params["wq"].T
    grad_embeddings = np.zeros_like(params["embeddings"])
    np.add.at(grad_embeddings, token_ids.reshape(-1), grad_x.reshape(-1, dim))
    grad_position = grad_x.sum(axis=0)

    return {
        "embeddings": grad_embeddings,
        "position_embeddings": grad_position,
        "wq": grad_wq,
        "wk": grad_wk,
        "wv": grad_wv,
        "wo": grad_wo,
        "relative_bias": grad_scores.sum(axis=0),
        "w1": grad_w1,
        "b1": grad_b1,
        "w2": grad_w2,
        "b2": grad_b2,
    }


class DimasikBrain:
    """Загрузка, проверка и генерация текста моделью DimaCore 2.0."""

    def __init__(self, model_path=MODEL_PATH):
        self.model_path = Path(model_path)
        self.ready = False
        self.load_error = None
        self.vocab: list[str] = []
        self.word_to_id: dict[str, int] = {}
        self.params: dict[str, np.ndarray] = {}
        self.rng = np.random.default_rng()
        self._load()

    def _load(self) -> None:
        """Загружает веса только после проверки версии, форм и численных значений."""
        self.ready = False
        self.load_error = None
        if not self.model_path.is_file():
            return
        try:
            with np.load(self.model_path, allow_pickle=False) as data:
                if "format_version" not in data.files:
                    raise ValueError("У файла модели отсутствует версия формата.")
                version = int(np.asarray(data["format_version"]).reshape(-1)[0])
                if version != MODEL_FORMAT_VERSION:
                    raise ValueError(
                        f"Найдена DimaCore {version}. Для DimaCore 2.0 установи новую сборку "
                        "или переобучи модель командой python train_brain.py."
                    )
                required = set(PARAMETER_NAMES) | {"vocab", "format_version"}
                if not required.issubset(set(data.files)):
                    raise ValueError("В файле DimaCore 2.0 отсутствуют необходимые массивы.")
                vocab = data["vocab"].astype(str).tolist()
                params = {name: np.asarray(data[name], dtype=np.float32) for name in PARAMETER_NAMES}

            if not isinstance(vocab, list) or not vocab or not all(isinstance(x, str) for x in vocab):
                raise ValueError("Словарь модели имеет неправильный формат.")
            if len(set(vocab)) != len(vocab) or vocab[:3] != [UNK, BOS, EOS]:
                raise ValueError("Словарь должен начинаться с <unk>, <bos>, <eos> и не содержать повторов.")

            emb = params["embeddings"]
            if emb.ndim != 2 or emb.shape[0] != len(vocab) or emb.shape[1] < 4:
                raise ValueError("Размер эмбеддингов не совпадает со словарём.")
            dim = emb.shape[1]
            if params["position_embeddings"].shape != (CONTEXT_SIZE, dim):
                raise ValueError("Неподходящая форма позиционных эмбеддингов.")
            for name in ("wq", "wk", "wv", "wo"):
                if params[name].shape != (dim, dim):
                    raise ValueError(f"Неподходящая форма attention-матрицы {name}.")
            if params["relative_bias"].shape != (CONTEXT_SIZE,):
                raise ValueError("Неподходящая форма относительного позиционного смещения.")
            w1, b1, w2, b2 = (params[name] for name in ("w1", "b1", "w2", "b2"))
            if w1.ndim != 2 or w1.shape[0] != dim:
                raise ValueError("Неподходящая форма первого слоя.")
            hidden = w1.shape[1]
            if b1.shape != (hidden,) or w2.shape != (hidden, len(vocab)) or b2.shape != (len(vocab),):
                raise ValueError("Неподходящие формы выходного слоя.")
            if not all(np.isfinite(array).all() for array in params.values()):
                raise ValueError("Модель содержит NaN или бесконечные значения.")

            self.vocab = vocab
            self.word_to_id = {word: i for i, word in enumerate(vocab)}
            self.params = params
            self.ready = True
        except (OSError, EOFError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.load_error = str(exc)
            self.ready = False
        except Exception as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            self.ready = False

    def _encode_context(self, context) -> np.ndarray:
        ids = [self.word_to_id.get(str(word), self.word_to_id[UNK]) for word in context[-CONTEXT_SIZE:]]
        ids = [self.word_to_id[BOS]] * (CONTEXT_SIZE - len(ids)) + ids
        return np.asarray([ids], dtype=np.int64)

    def _next_logits(self, context) -> np.ndarray:
        if not self.ready:
            raise RuntimeError("Модель DimaCore не загружена.")
        logits = _forward_batch(self._encode_context(context), self.params)[0]
        return logits.astype(np.float64, copy=False)

    def answer(self, prompt, max_tokens=56, temperature=0.72, top_p=0.9) -> str:
        """Генерирует короткий ответ с nucleus sampling и подавлением повторов."""
        if not self.ready:
            return (
                "Моё нейросетевое ядро пока не загружено или не обучено. "
                "Проверь файлы модели или запусти train_brain.py."
            )
        prompt_tokens = tokenize(prompt)
        if not prompt_tokens:
            return "Скажи, что тебя интересует."
        try:
            token_limit = max(1, min(128, int(max_tokens)))
            temperature = max(0.1, min(2.0, float(temperature)))
            top_p = max(0.1, min(1.0, float(top_p)))
        except (TypeError, ValueError):
            token_limit, temperature, top_p = 56, 0.72, 0.9

        context = [BOS] + prompt_tokens[-CONTEXT_SIZE:]
        generated: list[str] = []
        counts: dict[int, int] = {}
        punctuation = {".", ",", "!", "?", ";", ":"}
        for _ in range(token_limit):
            try:
                logits = self._next_logits(context).copy()
                logits[self.word_to_id[BOS]] = -np.inf
                logits[self.word_to_id[UNK]] = -np.inf
                if len(generated) < 3:
                    logits[self.word_to_id[EOS]] = -np.inf
                for token_id, count in counts.items():
                    logits[token_id] -= min(2.0, 0.5 * count)
                if generated and generated[-1] not in punctuation:
                    last_id = self.word_to_id.get(generated[-1])
                    if last_id is not None:
                        logits[last_id] -= 1.2
                if len(generated) >= 2:
                    previous_pair = (generated[-2], generated[-1])
                    for index in range(len(generated) - 1):
                        if (generated[index], generated[index + 1]) == previous_pair and index + 2 < len(generated):
                            repeated = self.word_to_id.get(generated[index + 2])
                            if repeated is not None:
                                logits[repeated] -= 1.5

                probs = _softmax(logits / temperature)
                order = np.argsort(probs)[::-1]
                ordered_probs = probs[order]
                cumulative = np.cumsum(ordered_probs)
                keep = cumulative - ordered_probs < top_p
                keep[0] = True
                candidates = order[keep]
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
        result = re.sub(r"\s+([.,!?;:])", r"\1", result)
        result = re.sub(r"\s+", " ", result).strip()
        return result[:1].upper() + result[1:]


def _make_examples(sentences, ids):
    examples = []
    for sentence in sentences:
        encoded = [ids.get(word, 0) for word in ([BOS] * CONTEXT_SIZE + sentence + [EOS])]
        for pos in range(CONTEXT_SIZE, len(encoded)):
            examples.append((encoded[pos - CONTEXT_SIZE:pos], encoded[pos]))
    return examples


def _loss_for_examples(examples, params, batch_size=256):
    if not examples:
        return float("inf")
    losses = 0.0
    for start in range(0, len(examples), batch_size):
        batch = examples[start:start + batch_size]
        x_ids = np.asarray([item[0] for item in batch], dtype=np.int64)
        targets = np.asarray([item[1] for item in batch], dtype=np.int64)
        logits = _forward_batch(x_ids, params)
        probs = _softmax(logits)
        losses += float(-np.log(np.maximum(probs[np.arange(len(batch)), targets], 1e-12)).sum())
    return losses / len(examples)


def _save_model(model_path, vocab, params):
    """Атомарно сохраняет DimaCore 2.0 и встроенный словарь."""
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temp_model = model_path.with_name(model_path.name + ".tmp")
    try:
        with temp_model.open("wb") as stream:
            np.savez_compressed(
                stream,
                format_version=np.asarray([MODEL_FORMAT_VERSION], dtype=np.int32),
                vocab=np.asarray(vocab, dtype=np.str_),
                **params,
            )
        os.replace(temp_model, model_path)
    finally:
        try:
            temp_model.unlink()
        except FileNotFoundError:
            pass


def train(data_path=None, epochs=60, embedding_size=48, hidden_size=128,
          learning_rate=0.0015, model_path=None, validation_split=0.15,
          patience=10, seed=2026):
    """Обучает DimaCore 2.0 с attention, Adam, clipping и early stopping."""
    data_path = Path(data_path or ROOT / "training_data.txt")
    model_path = Path(model_path or MODEL_PATH)
    raw_lines = data_path.read_text(encoding="utf-8").splitlines()
    sentences = [tokenize(line.strip()) for line in raw_lines if line.strip()]
    sentences = [tokens for tokens in sentences if tokens]
    if len(sentences) < 2:
        raise ValueError("Для обучения нужно минимум два непустых предложения.")

    epochs = max(1, min(500, int(epochs)))
    embedding_size = max(8, min(256, int(embedding_size)))
    hidden_size = max(16, min(512, int(hidden_size)))
    learning_rate = float(learning_rate)
    if not np.isfinite(learning_rate) or not 0 < learning_rate <= 0.05:
        raise ValueError("learning_rate должен быть числом больше 0 и не больше 0.05.")
    validation_split = max(0.0, min(0.4, float(validation_split)))
    patience = max(1, int(patience))

    rng = np.random.default_rng(int(seed))
    order = rng.permutation(len(sentences))
    if validation_split > 0 and len(sentences) >= 5:
        val_count = min(max(1, int(round(len(sentences) * validation_split))), len(sentences) - 1)
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
    dim = embedding_size
    params = {
        "embeddings": rng.normal(0, 0.06, (vocab_size, dim)).astype(np.float32),
        "position_embeddings": rng.normal(0, 0.02, (CONTEXT_SIZE, dim)).astype(np.float32),
        "wq": rng.normal(0, 1.0 / np.sqrt(dim), (dim, dim)).astype(np.float32),
        "wk": rng.normal(0, 1.0 / np.sqrt(dim), (dim, dim)).astype(np.float32),
        "wv": rng.normal(0, 1.0 / np.sqrt(dim), (dim, dim)).astype(np.float32),
        "wo": rng.normal(0, 1.0 / np.sqrt(dim), (dim, dim)).astype(np.float32),
        "relative_bias": np.zeros(CONTEXT_SIZE, dtype=np.float32),
        "w1": rng.normal(0, np.sqrt(2.0 / dim), (dim, hidden_size)).astype(np.float32),
        "b1": np.zeros(hidden_size, dtype=np.float32),
        "w2": rng.normal(0, 0.02, (hidden_size, vocab_size)).astype(np.float32),
        "b2": np.zeros(vocab_size, dtype=np.float32),
    }
    names = list(PARAMETER_NAMES)
    first_moments = {name: np.zeros_like(params[name]) for name in names}
    second_moments = {name: np.zeros_like(params[name]) for name in names}
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
            _logits, state = _forward_batch(x_ids, params, cache=True)
            grads = _backward_batch(targets, params, state)

            grad_norm = float(np.sqrt(sum(float(np.sum(g * g)) for g in grads.values())))
            if not np.isfinite(grad_norm):
                raise FloatingPointError("Во время обучения получен некорректный градиент.")
            if grad_norm > 1.0:
                scale = 1.0 / (grad_norm + 1e-12)
                grads = {name: grad * scale for name, grad in grads.items()}

            step += 1
            for name in names:
                grad = grads[name]
                first_moments[name] = beta1 * first_moments[name] + (1.0 - beta1) * grad
                second_moments[name] = beta2 * second_moments[name] + (1.0 - beta2) * (grad * grad)
                m_hat = first_moments[name] / (1.0 - beta1 ** step)
                v_hat = second_moments[name] / (1.0 - beta2 ** step)
                # Небольшой AdamW weight decay только для матриц весов.
                decay = 1e-4 * params[name] if name in {"wq", "wk", "wv", "wo", "w1", "w2"} else 0.0
                params[name] -= learning_rate * (m_hat / (np.sqrt(v_hat) + 1e-8) + decay)

        train_loss = _loss_for_examples(train_examples, params)
        monitored_loss = _loss_for_examples(val_examples, params) if val_examples else train_loss
        if not np.isfinite(monitored_loss):
            raise FloatingPointError("Ошибка обучения: функция потерь стала некорректной.")
        if monitored_loss < best_loss - 1e-5:
            best_loss = monitored_loss
            best_params = {name: value.copy() for name, value in params.items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
        if (epoch + 1) == 1 or (epoch + 1) % 10 == 0:
            label = "val_loss" if val_examples else "train_loss"
            print(f"DimaCore 2.0 Epoch {epoch + 1}/{epochs} - train_loss: {train_loss:.4f}; {label}: {monitored_loss:.4f}")
        if epochs_without_improvement >= patience:
            print(f"Early stopping: no improvement for {patience} epochs.")
            break

    if best_params is None:
        raise RuntimeError("Обучение не создало пригодную версию модели.")
    _save_model(model_path, vocab, best_params)
    return len(vocab), total_examples


if __name__ == "__main__":
    vocab_size, example_count = train()
    print(
        f"DimaCore 2.0 training complete. Vocabulary: {vocab_size}; "
        f"training pairs: {example_count}."
    )
