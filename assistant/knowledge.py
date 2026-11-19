"""Private local memory and cautious online retrieval for Dimasik."""
import re
import sqlite3
import time

import requests
from search_backend import parse_search_results


class LocalKnowledge:
    """SQLite conversation memory stored only on this computer."""

    STOP = {
        "что", "это", "как", "где", "когда", "почему", "зачем", "кто", "или",
        "для", "при", "про", "над", "под", "его", "она", "они", "мне", "меня",
        "тебя", "твой", "твоя", "могу", "можно", "есть", "быть", "будет",
        "расскажи", "объясни", "пожалуйста", "димасик", "найди", "интернете"
    }

    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created REAL NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created)")

    @staticmethod
    def _tokens(text):
        return {
            token for token in re.findall(r"[а-яёa-z0-9]{2,}", str(text).lower())
            if token not in LocalKnowledge.STOP
        }

    def remember(self, question, answer, source="conversation"):
        question = str(question).strip()[:2000]
        answer = str(answer).strip()[:6000]
        if not question or not answer:
            return
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO memories(question, answer, source, created) VALUES (?, ?, ?, ?)",
                (question, answer, source, time.time())
            )

    def find_similar(self, query, limit=3):
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT question, answer, source, created FROM memories ORDER BY created DESC LIMIT 1500"
            ).fetchall()
        ranked = []
        for question, answer, source, created in rows:
            tokens = self._tokens(question)
            if not tokens:
                continue
            score = len(query_tokens & tokens) / max(1, len(query_tokens | tokens))
            if score >= 0.22:
                ranked.append((score, question, answer, source, created))
        ranked.sort(key=lambda item: (item[0], item[4]), reverse=True)
        return ranked[:limit]

    def search_web(self, query, limit=5):
        """Search public engines with fallbacks; no API key or paid service is used."""
        query = str(query or "").strip()
        if not query:
            return {"online": False, "results": [], "error": "Пустой поисковый запрос."}

        engines = (
            ("DuckDuckGo", "https://html.duckduckgo.com/html/", "duckduckgo"),
            ("Bing", "https://www.bing.com/search", "bing"),
            ("DuckDuckGo Lite", "https://lite.duckduckgo.com/lite/", "duckduckgo"),
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        }
        errors = []
        limit = max(1, min(10, int(limit)))

        for engine_name, endpoint, parser_name in engines:
            try:
                response = requests.get(
                    endpoint,
                    params={"q": query},
                    headers=headers,
                    timeout=(5, 12),
                )
                response.raise_for_status()
                results = parse_search_results(response.text, parser_name, limit=limit)
                if results:
                    return {
                        "online": True,
                        "results": results,
                        "engine": engine_name,
                    }
                errors.append(f"{engine_name}: страница открылась, но выдачу распознать не удалось")
            except requests.RequestException as exc:
                errors.append(f"{engine_name}: {exc.__class__.__name__}")
            except (ValueError, TypeError) as exc:
                errors.append(f"{engine_name}: {exc.__class__.__name__}")

        return {
            "online": False,
            "results": [],
            "error": "; ".join(errors) or "Поисковые системы не вернули результаты.",
        }

    @staticmethod
    def format_web_answer(query, results):
        lines = [f"По запросу «{query}» нашёл такие материалы:"]
        for index, item in enumerate(results, 1):
            snippet = item.get("snippet") or "В поисковой выдаче нет краткого описания."
            lines.append(f"{index}. {item['title']}\n{snippet}\nИсточник: {item['url']}")
        lines.append(
            "Это выдержки из поисковой выдачи, а не проверенная истина. "
            "Для важных решений открой источники и сравни несколько независимых публикаций."
        )
        return "\n\n".join(lines)

    @staticmethod
    def format_memory_answer(memories):
        lines = ["Интернета сейчас нет. Нашёл похожие сведения в локальной памяти:"]
        for _score, question, answer, source, _created in memories:
            label = "прошлый разговор" if source == "conversation" else "ранее найденный материал"
            lines.append(f"Вопрос: {question}\nОтвет: {answer}\nТип записи: {label}")
        lines.append("Это сохранённые записи, а не обязательно актуальные или проверенные факты.")
        return "\n\n".join(lines)
