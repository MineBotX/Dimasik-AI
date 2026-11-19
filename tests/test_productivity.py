import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from assistant.productivity import ProductivityStore, parse_reminder, safe_calculate


class CalculatorTests(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(safe_calculate("(2 + 3) * 4 / 2"), 10)

    def test_supports_power_and_unary(self):
        self.assertEqual(safe_calculate("-2^3"), -8)

    def test_rejects_python_execution(self):
        with self.assertRaises(ValueError):
            safe_calculate("__import__('os').system('echo unsafe')")

    def test_rejects_division_by_zero(self):
        with self.assertRaises(ValueError):
            safe_calculate("10 / 0")


class ReminderTests(unittest.TestCase):
    def test_relative_reminder(self):
        now = datetime(2026, 11, 19, 12, 0)
        message, due = parse_reminder("Напомни через 15 минут проверить чайник", now)
        self.assertEqual(message, "проверить чайник")
        self.assertEqual(due, now + timedelta(minutes=15))

    def test_clock_reminder_moves_to_tomorrow_when_time_passed(self):
        now = datetime(2026, 11, 19, 18, 0)
        _message, due = parse_reminder("Напомни в 09:30 позвонить", now)
        self.assertEqual(due, datetime(2026, 11, 20, 9, 30))


class ProductivityStoreTests(unittest.TestCase):
    def test_notes_tasks_and_reminders_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductivityStore(Path(directory) / "work.sqlite3")
            note_id = store.add_note("Пароль от Wi-Fi не сохранять")  # plain private note, not auto-shared
            self.assertEqual(store.list_notes()[0][0], note_id)
            task_id = store.add_task("Проверить проект")
            self.assertTrue(store.complete_task(task_id))
            self.assertEqual(store.list_tasks(), [])
            due = datetime.now() - timedelta(minutes=1)
            reminder_id = store.add_reminder("Проверить задачу", due)
            self.assertEqual(store.due_reminders()[0][0], reminder_id)
            store.mark_reminder_notified(reminder_id)
            self.assertEqual(store.due_reminders(), [])

    def test_command_router(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductivityStore(Path(directory) / "work.sqlite3")
            self.assertIn("4", store.handle_command("посчитай 2 + 2"))
            self.assertIn("сохранена", store.handle_command("запомни заметку Купить молоко"))
            self.assertIn("Купить молоко", store.handle_command("покажи заметки"))
            self.assertIsNone(store.handle_command("Привет, как дела?"))


if __name__ == "__main__":
    unittest.main()
