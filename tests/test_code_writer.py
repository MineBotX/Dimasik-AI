import ast
import unittest

from assistant.code_writer import generate_code, is_code_request


class CodeWriterTests(unittest.TestCase):
    def test_detects_russian_code_requests(self):
        self.assertTrue(is_code_request("Напиши код калькулятора на Python"))
        self.assertTrue(is_code_request("Сделай игру угадай число на Python"))
        self.assertTrue(is_code_request("Создай сайт на HTML"))
        self.assertFalse(is_code_request("Как дела?"))

    def test_python_templates_are_valid_syntax(self):
        prompts = [
            "Напиши код калькулятора на Python",
            "Напиши игру угадай число на Python",
            "Создай список задач на Python",
            "Сделай простой API сервер на Python",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                result = generate_code(prompt)
                self.assertIn("```python", result)
                code = result.split("```python", 1)[1].split("```", 1)[0]
                ast.parse(code)

    def test_generates_html_website(self):
        result = generate_code("Создай простой сайт на HTML")
        self.assertIn("```html", result)
        self.assertIn("<!doctype html>", result.lower())
        self.assertIn("</html>", result.lower())

    def test_generates_cpp_calculator(self):
        result = generate_code("Напиши калькулятор на C++")
        self.assertIn("```cpp", result)
        self.assertIn("#include <iostream>", result)

    def test_unknown_task_does_not_invent_code(self):
        result = generate_code("Напиши сложную систему управления космическим кораблём")
        self.assertIn("опиши подробнее", result.lower())


if __name__ == "__main__":
    unittest.main()
