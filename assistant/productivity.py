"""Локальные заметки, задачи, напоминания и безопасный калькулятор Димасика."""
from __future__ import annotations

import ast
import math
import operator
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path


_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_calculate(expression: str) -> float | int:
    """Вычисляет только арифметику; произвольный Python-код не исполняется."""
    expression = str(expression or "").strip().replace(",", ".").replace("^", "**")
    if not expression or len(expression) > 120:
        raise ValueError("Введи короткое математическое выражение.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Не удалось разобрать пример. Используй цифры и знаки + - * / ( ).") from exc

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("Слишком большая степень.")
            value = _ALLOWED_OPERATORS[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            value = _UNARY_OPERATORS[type(node.op)](visit(node.operand))
        else:
            raise ValueError("Разрешены только числа, скобки и арифметические операции.")
        if isinstance(value, complex) or not math.isfinite(float(value)) or abs(value) > 1e100:
            raise ValueError("Результат выходит за допустимый диапазон.")
        return value

    try:
        return visit(tree)
    except ZeroDivisionError as exc:
        raise ValueError("На ноль делить нельзя.") from exc
    except OverflowError as exc:
        raise ValueError("Слишком большое число.") from exc


def parse_reminder(prompt: str, now: datetime | None = None):
    """Распознаёт напоминания «через N минут/часов/дней» и «в 18:30»."""
    text = str(prompt or "").strip()
    now = now or datetime.now()
    match = re.match(
        r"^(?:напомни(?:\s+мне)?|поставь\s+напоминание(?:\s+мне)?)\s+"
        r"через\s+(\d{1,5})\s*(секунд\w*|сек\.?|минут\w*|мин\.?|час\w*|дн\w*|дней|сут\w*)\s+(.+)$",
        text, re.IGNORECASE,
    )
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        message = match.group(3).strip(" .,!?:;")
        if not message:
            raise ValueError("Напиши, о чём нужно напомнить.")
        if amount < 1:
            raise ValueError("Укажи положительное время.")
        if unit.startswith(("сек",)):
            due = now + timedelta(seconds=amount)
        elif unit.startswith(("мин",)):
            due = now + timedelta(minutes=amount)
        elif unit.startswith("час"):
            due = now + timedelta(hours=amount)
        else:
            due = now + timedelta(days=amount)
        return message[:500], due

    match = re.match(
        r"^(?:напомни(?:\s+мне)?|поставь\s+напоминание(?:\s+мне)?)\s+"
        r"(?:сегодня\s+)?в\s+(\d{1,2}):(\d{2})\s+(.+)$",
        text, re.IGNORECASE,
    )
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("Время должно быть в формате ЧЧ:ММ.")
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        return match.group(3).strip(" .,!?:;")[:500], due

    if text.lower().startswith(("напомни", "поставь напоминание")):
        raise ValueError("Пример: «Напомни через 20 минут проверить духовку» или «Напомни в 18:30 позвонить».")
    return None


class ProductivityStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    due REAL NOT NULL,
                    notified INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due, notified);
            """)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def add_note(self, content: str) -> int:
        content = str(content).strip()[:8000]
        if not content:
            raise ValueError("Заметка пустая.")
        with closing(self._connect()) as db, db:
            cursor = db.execute("INSERT INTO notes(content, created) VALUES (?, ?)", (content, time.time()))
            return int(cursor.lastrowid)

    def list_notes(self, limit=20):
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT id, content, created FROM notes ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()

    def delete_note(self, note_id: int) -> bool:
        with closing(self._connect()) as db, db:
            cur = db.execute("DELETE FROM notes WHERE id = ?", (int(note_id),))
            return cur.rowcount > 0

    def add_task(self, content: str) -> int:
        content = str(content).strip()[:1000]
        if not content:
            raise ValueError("Напиши текст задачи.")
        with closing(self._connect()) as db, db:
            cur = db.execute(
                "INSERT INTO tasks(content, created) VALUES (?, ?)", (content, time.time())
            )
            return int(cur.lastrowid)

    def list_tasks(self, include_done=False, limit=50):
        with closing(self._connect()) as db:
            sql = "SELECT id, content, done, created FROM tasks"
            if not include_done:
                sql += " WHERE done = 0"
            return db.execute(sql + " ORDER BY done, id DESC LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()

    def complete_task(self, task_id: int) -> bool:
        with closing(self._connect()) as db, db:
            cur = db.execute("UPDATE tasks SET done = 1 WHERE id = ?", (int(task_id),))
            return cur.rowcount > 0

    def add_reminder(self, content: str, due: datetime) -> int:
        content = str(content).strip()[:500]
        if not content:
            raise ValueError("Напиши, о чём нужно напомнить.")
        with closing(self._connect()) as db, db:
            cur = db.execute(
                "INSERT INTO reminders(content, due, created) VALUES (?, ?, ?)",
                (content, due.timestamp(), time.time()),
            )
            return int(cur.lastrowid)

    def due_reminders(self, now=None):
        current = (now or datetime.now()).timestamp()
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT id, content, due FROM reminders WHERE due <= ? AND notified = 0 ORDER BY due",
                (current,),
            ).fetchall()

    def mark_reminder_notified(self, reminder_id: int):
        with closing(self._connect()) as db, db:
            db.execute("UPDATE reminders SET notified = 1 WHERE id = ?", (int(reminder_id),))

    def list_reminders(self, limit=30):
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT id, content, due, notified FROM reminders ORDER BY due LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()

    def handle_command(self, prompt: str):
        """Обрабатывает только явно распознанные команды; возвращает None для обычного чата."""
        text = str(prompt or "").strip()
        lowered = text.lower()

        if lowered.startswith(("посчитай ", "вычисли ", "сколько будет ", "калькулятор ")):
            expression = re.sub(r"^(посчитай|вычисли|сколько будет|калькулятор)\s+", "", text, flags=re.I)
            result = safe_calculate(expression)
            return f"{expression} = {result:g}" if isinstance(result, float) else f"{expression} = {result}"

        reminder = parse_reminder(text)
        if reminder:
            content, due = reminder
            reminder_id = self.add_reminder(content, due)
            return f"Напоминание №{reminder_id} сохранено на {due.strftime('%d.%m.%Y в %H:%M')}: {content}"

        if lowered.startswith(("добавь заметку ", "сохрани заметку ", "запомни заметку ", "заметка:")):
            content = re.sub(r"^(добавь заметку|сохрани заметку|запомни заметку|заметка:)\s*", "", text, flags=re.I)
            note_id = self.add_note(content)
            return f"Заметка №{note_id} сохранена локально на этом компьютере."

        if lowered in ("покажи заметки", "мои заметки", "список заметок"):
            items = self.list_notes()
            if not items:
                return "Пока нет сохранённых заметок."
            return "Твои заметки:\n" + "\n".join(
                f"№{item[0]}: {item[1][:500]}" for item in items
            )

        match = re.match(r"^(?:удали|удалить) заметку\s+(\d+)\s*$", text, re.I)
        if match:
            return "Заметка удалена." if self.delete_note(int(match.group(1))) else "Заметка с таким номером не найдена."

        if lowered.startswith(("добавь задачу ", "создай задачу ", "новая задача ")):
            content = re.sub(r"^(добавь задачу|создай задачу|новая задача)\s*", "", text, flags=re.I)
            task_id = self.add_task(content)
            return f"Задача №{task_id} добавлена."

        if lowered in ("покажи задачи", "мои задачи", "список задач", "что у меня запланировано"):
            items = self.list_tasks()
            if not items:
                return "Активных задач нет."
            return "Активные задачи:\n" + "\n".join(f"№{row[0]}: {row[1]}" for row in items)

        match = re.match(r"^(?:выполнил|готово|закрой|заверши) задачу\s+(\d+)\s*$", text, re.I)
        if match:
            return "Отметил задачу выполненной." if self.complete_task(int(match.group(1))) else "Задача с таким номером не найдена."

        if lowered in ("покажи напоминания", "мои напоминания", "список напоминаний"):
            items = [item for item in self.list_reminders() if not item[3]]
            if not items:
                return "Активных напоминаний нет."
            return "Твои напоминания:\n" + "\n".join(
                f"№{row[0]} — {datetime.fromtimestamp(row[2]).strftime('%d.%m.%Y %H:%M')}: {row[1]}"
                for row in items
            )
        return None
