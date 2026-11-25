"""OpenAI-compatible HTTP API for Dimasik's local Granite model.

Run:
    python -m assistant.api_server create-key --name "Crosshair Service"
    python -m assistant.api_server serve --host 127.0.0.1 --port 8787

The API binds to loopback by default. Put a TLS reverse proxy/VPN in front of it
before allowing access from another machine or the public internet.
"""
from __future__ import annotations

import argparse
import hashlib
from contextlib import contextmanager
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Support both `python -m assistant.api_server` and PyInstaller's script-directory imports.
try:
    from .local_coder import LocalCoder
    from .brain import DimasikBrain
except ImportError:
    from local_coder import LocalCoder
    from brain import DimasikBrain

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "brain" / "api_keys.sqlite3"
PROFILE_PATH = ROOT / "brain" / "api_profile.json"
MAX_BODY = 64 * 1024
DEFAULT_RPM = 30
MODEL_ID = "dimasik"
MODEL_ALIASES = {"dimasik": "auto", "auto": "auto", "all": "auto", "granite": "granite", "dimacore": "dimacore"}
_coder = LocalCoder(ROOT)
_brain = DimasikBrain()
_rate_lock = threading.Lock()
_rate_events: dict[str, list[float]] = {}
# A single local Granite instance: reject excess work rather than queueing HTTP threads.
_inference_slot = threading.BoundedSemaphore(1)


@contextmanager
def _connection():
    conn = _db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_profile(name: str, purpose: str, task_prompt: str, model: str = "auto") -> None:
    """Persist a task-specific system prompt and inference mode locally."""
    if model not in MODEL_ALIASES and model not in MODEL_ALIASES.values():
        raise ValueError("Неизвестный режим модели API.")
    model = MODEL_ALIASES.get(model, model)
    name, purpose, task_prompt = str(name).strip()[:80], str(purpose).strip(), str(task_prompt).strip()
    if not purpose or len(purpose) > 4000 or not task_prompt or len(task_prompt) > 12000:
        raise ValueError("Описание задачи или системный промт пусты либо слишком длинные.")
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PROFILE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"name": name or "Мой API", "purpose": purpose,
        "task_prompt": task_prompt, "model": model}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PROFILE_PATH)


def load_profile() -> dict:
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("model") in MODEL_ALIASES.values():
            prompt = data.get("task_prompt")
            if isinstance(prompt, str) and prompt.strip():
                return {"task_prompt": prompt[:12000], "name": str(data.get("name", "Мой API"))[:80],
                        **({**({"model": data["model"]} if data.get("model") else {})} if data.get("model") else {})}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {"task_prompt": "", "name": "Димасик"}


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            prefix TEXT NOT NULL,
            secret_hash TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            rpm INTEGER NOT NULL DEFAULT 30,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_used_at TEXT
        )
    """)
    conn.commit()
    return conn


def create_key(name: str, rpm: int = DEFAULT_RPM) -> str:
    name = str(name).strip()
    if not name or len(name) > 80:
        raise ValueError("Название ключа должно содержать от 1 до 80 символов.")
    if not 1 <= int(rpm) <= 600:
        raise ValueError("Лимит RPM должен быть от 1 до 600.")
    token = "dm_live_" + secrets.token_urlsafe(32)
    prefix = token[:16]
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connection() as conn:
        conn.execute(
            "INSERT INTO api_keys (id, prefix, secret_hash, name, rpm) VALUES (?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, prefix, digest, name, int(rpm)),
        )
    return token


def revoke_key(prefix: str) -> bool:
    with _connection() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET active=0 WHERE prefix=? AND active=1", (prefix,)
        )
        return cur.rowcount > 0


def _authenticate(handler):
    header = handler.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.startswith("dm_live_"):
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connection() as conn:
        row = conn.execute(
            "SELECT id, prefix, rpm FROM api_keys WHERE active=1 AND secret_hash=?",
            (digest,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE api_keys SET last_used_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
    if row is None:
        return None
    return dict(row)


def _is_complex_request(text: str) -> bool:
    """Conservative router: keep short everyday prompts on DimaCore, send demanding work to Granite."""
    value = str(text).strip().lower()
    words = value.split()
    complex_markers = (
        "объясни подробно", "проанализируй", "сравни", "составь план", "напиши код",
        "исправь код", "программ", "разработ", "документ", "реферат", "эссе",
        "пошагово", "несколько вариантов", "рассчитай", "докажи", "исследуй",
        "таблиц", "json", "sql", "python", "алгоритм", "архитектур", "проект",
    )
    if len(value) > 220 or len(words) > 35:
        return True
    if any(marker in value for marker in complex_markers):
        return True
    if value.count("?") > 1 or any(token in value for token in (" и затем ", " после этого ", "сначала ", "потом ")):
        return True
    return False


def _allow_request(key: dict) -> bool:
    now = time.monotonic()
    with _rate_lock:
        events = [stamp for stamp in _rate_events.get(key["id"], []) if now - stamp < 60]
        if len(events) >= int(key["rpm"]):
            _rate_events[key["id"]] = events
            return False
        events.append(now)
        _rate_events[key["id"]] = events
        return True


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "DimasikAPI/1.0"

    def log_message(self, fmt, *args):
        # Avoid logging request headers or credentials.
        sys.stderr.write("[DimasikAPI] " + (fmt % args) + "\n")

    def _send(self, status: int, payload: dict, headers: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, code: str):
        self._send(status, {"error": {"message": message, "type": "api_error", "code": code}})

    def _authorized(self):
        key = _authenticate(self)
        if key is None:
            self._error(401, "Missing or invalid API key.", "invalid_api_key")
            return None
        if not _allow_request(key):
            self._send(
                429,
                {"error": {"message": "Rate limit exceeded. Try again shortly.",
                           "type": "rate_limit_error", "code": "rate_limit_exceeded"}},
                {"Retry-After": "60"},
            )
            return None
        return key

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"status": "ok", "service": "dimasik-api"})
            return
        if path == "/v1/models":
            if self._authorized() is None:
                return
            self._send(200, {
                "object": "list",
                "data": [
                    {"id": "dimacore", "object": "model", "created": 0, "owned_by": "dimasik"},
                    {"id": "granite", "object": "model", "created": 0, "owned_by": "ibm-granite"},
                    {"id": "all", "object": "model", "created": 0, "owned_by": "dimasik"},
                    {"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "dimasik"},
                ],
            })
            return
        self._error(404, "Endpoint not found.", "not_found")

    def do_POST(self):
        if urlparse(self.path).path != "/v1/chat/completions":
            self._error(404, "Endpoint not found.", "not_found")
            return
        key = self._authorized()
        if key is None:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "Invalid Content-Length.", "invalid_request")
            return
        if self.headers.get("Transfer-Encoding"):
            self._error(400, "Transfer-Encoding is not supported; send Content-Length.", "invalid_request")
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._error(415, "Content-Type must be application/json.", "unsupported_media_type")
            return
        if length < 1 or length > MAX_BODY:
            self._error(413, "Request body must be between 1 byte and 64 KiB.",
                        "request_too_large")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "Body must be valid UTF-8 JSON.", "invalid_json")
            return
        if not isinstance(payload, dict):
            self._error(400, "JSON body must be an object.", "invalid_request")
            return
        if payload.get("stream", False) is not False:
            self._error(400, "Streaming is not supported; set stream=false.", "unsupported_parameter")
            return
        requested_model = str(payload.get("model", "")).lower()
        selected_model = MODEL_ALIASES.get(requested_model) if requested_model else None
        if requested_model and selected_model is None:
            self._error(404, "Unknown model. Use dimacore, granite, all, or dimasik.", "model_not_found")
            return
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages or len(messages) > 20:
            self._error(400, "messages must be a non-empty array with at most 20 items.",
                        "invalid_messages")
            return
        conversation = []
        last_user = None
        for item in messages:
            if not isinstance(item, dict):
                self._error(400, "Each message must be an object.", "invalid_messages")
                return
            role = item.get("role")
            content = item.get("content")
            if role not in ("user", "assistant", "system") or not isinstance(content, str):
                self._error(400, "Only string user, assistant, and system messages are supported.",
                            "invalid_messages")
                return
            if len(content) > 24000:
                self._error(400, "A message exceeds the 24000 character limit.",
                            "message_too_long")
                return
            # Client system messages are intentionally ignored: callers cannot
            # replace Dimasik's safety/personality instructions.
            if role in ("user", "assistant"):
                conversation.append({"role": role, "content": content})
                if role == "user":
                    last_user = content
        if not conversation or conversation[-1]["role"] != "user" or not conversation[-1]["content"].strip():
            self._error(400, "The final message must be a non-empty user message.",
                        "invalid_messages")
            return
        raw_max_tokens = payload.get("max_tokens", 512)
        if isinstance(raw_max_tokens, bool) or not isinstance(raw_max_tokens, int) or raw_max_tokens < 1:
            self._error(400, "max_tokens must be a positive integer.", "invalid_max_tokens")
            return
        try:
            max_tokens = int(raw_max_tokens)
        except (TypeError, ValueError):
            self._error(400, "max_tokens must be an integer.", "invalid_max_tokens")
            return
        max_tokens = max(64, min(2048, max_tokens))
        history = conversation[:-1][-8:]
        if not _inference_slot.acquire(blocking=False):
            self._send(503, {"error": {"message": "The local model is busy. Retry shortly.", "type": "server_busy", "code": "model_busy"}}, {"Retry-After": "5"})
            return
        started = time.monotonic()
        try:
            profile = load_profile()
            mode = selected_model or profile.get("model", "auto")
            task_prompt = profile["task_prompt"]
            if mode == "auto":
                mode = "granite" if _is_complex_request(last_user) else "dimacore"
                if mode == "dimacore" and not _brain.ready:
                    mode = "granite"
            if mode == "dimacore":
                if not _brain.ready:
                    raise RuntimeError("DimaCore не обучен или файл brain/dimasik_brain.npz отсутствует.")
                answer = _brain.answer(last_user, max_tokens=min(128, max_tokens))
            elif mode == "granite":
                answer = _coder.generate_chat(
                    last_user, conversation=history, max_tokens=max_tokens,
                    task_prompt=task_prompt,
                )
            else:
                if not _brain.ready:
                    raise RuntimeError("Для режима all нужно обученное ядро DimaCore.")
                core_hint = _brain.answer(last_user, max_tokens=48)
                combined_prompt = (
                    "Дополнительный черновик экспериментального ядра DimaCore (может содержать ошибки; "
                    "проверяй его и не копируй вслепую):\\n" + core_hint +
                    "\\n\\nСформируй точный, полезный итоговый ответ на исходный запрос."
                )
                answer = _coder.generate_chat(
                    last_user, conversation=history + [{"role": "assistant", "content": combined_prompt}],
                    max_tokens=max_tokens, task_prompt=task_prompt,
                )
        except Exception as exc:
            self.log_error("Model request failed: %s", type(exc).__name__)
            self._error(503, "Dimasik's local model is unavailable. Check that Granite is installed.",
                        "model_unavailable")
            return
        finally:
            _inference_slot.release()
        elapsed = int((time.monotonic() - started) * 1000)
        self._send(200, {
            "id": "chatcmpl-" + uuid.uuid4().hex,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": mode,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "dimasik": {"latency_ms": elapsed},
        })

    def log_error(self, fmt, *args):
        sys.stderr.write("[DimasikAPI] ERROR " + (fmt % args) + "\n")


def start_server(host: str = "127.0.0.1", port: int = 8787):
    if not 1 <= int(port) <= 65535:
        raise ValueError("Port must be between 1 and 65535.")
    if host not in ("127.0.0.1", "localhost", "::1") and os.environ.get(
        "DIMASIK_ALLOW_REMOTE_BIND"
    ) != "1":
        raise RuntimeError(
            "Remote binding is disabled by default. For a protected reverse proxy/VPN, "
            "set DIMASIK_ALLOW_REMOTE_BIND=1 explicitly."
        )
    server = ThreadingHTTPServer((host, int(port)), ApiHandler)
    server.daemon_threads = True
    return server


def serve(host: str = "127.0.0.1", port: int = 8787):
    server = start_server(host, port)
    print(f"Dimasik API listening on http://{host}:{port}")
    print("Use HTTPS via a trusted reverse proxy before exposing it outside this computer.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Dimasik API...")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Dimasik OpenAI-compatible API")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-key", help="Create an API key (shown once)")
    create.add_argument("--name", required=True)
    create.add_argument("--rpm", type=int, default=DEFAULT_RPM)
    revoke = sub.add_parser("revoke-key", help="Revoke a key by its displayed prefix")
    revoke.add_argument("--prefix", required=True)
    run = sub.add_parser("serve", help="Start the HTTP API")
    run.add_argument("--host", default=os.environ.get("DIMASIK_API_HOST", "127.0.0.1"))
    run.add_argument("--port", type=int, default=int(os.environ.get("DIMASIK_API_PORT", "8787")))
    args = parser.parse_args()
    if args.command == "create-key":
        print("\nСкопируйте ключ сейчас — повторно показать его нельзя:\n")
        print(create_key(args.name, args.rpm))
        print("\nНе публикуйте ключ в клиентском приложении или репозитории.")
    elif args.command == "revoke-key":
        print("Ключ отключён." if revoke_key(args.prefix) else "Активный ключ с таким префиксом не найден.")
    else:
        serve(args.host, args.port)


if __name__ == "__main__":
    main()
