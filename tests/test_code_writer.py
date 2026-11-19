import unittest

from assistant.code_writer import is_code_request
from assistant.local_coder import LocalCoder, MODEL_SHA256, MODEL_URL


class CodeWriterTests(unittest.TestCase):
    def test_detects_russian_code_requests(self):
        prompts = [
            "Напиши код калькулятора на Python",
            "Создай программу для учёта расходов",
            "Сделай игру с инвентарём на Python",
            "Разработай веб-приложение для заметок",
            "Исправь функцию авторизации",
            "Добавь API для моего приложения",
            "Напиши на C++ парсер JSON",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(is_code_request(prompt))

    def test_ignores_normal_chat(self):
        for prompt in ("Как дела?", "Расскажи о Python", "Что такое API?"):
            with self.subTest(prompt=prompt):
                self.assertFalse(is_code_request(prompt))

    def test_prompt_contains_programming_instructions(self):
        messages = LocalCoder._messages("Создай REST API", conversation=[
            {"role": "user", "content": "Нужно на Python"},
            {"role": "assistant", "content": "Понял."},
        ])
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("самостоятельно создавать новый программный код", messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "Создай REST API"})
        self.assertTrue(any(item["role"] == "assistant" for item in messages[1:-1]))

    def test_model_download_is_pinned_and_hash_checked(self):
        self.assertIn("huggingface.co/ibm-granite/", MODEL_URL)
        self.assertEqual(len(MODEL_SHA256), 64)
        self.assertTrue(all(char in "0123456789abcdef" for char in MODEL_SHA256))


if __name__ == "__main__":
    unittest.main()
