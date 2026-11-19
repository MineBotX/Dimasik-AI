"""Offline starter code generator for common beginner programming requests.

This module uses reviewed templates, not free-form neural code prediction.
It never executes generated code.
"""
import re
import textwrap
import ast


def is_code_request(prompt):
    text = str(prompt or "").lower()
    return bool(re.search(
        r"\b(напиши|создай|сгенерируй|сделай|разработай|покажи)\b.{0,70}\b("
        r"код|программ\w*|скрипт\w*|сайт\w*|калькулятор\w*|игр\w*|бот\w*|api)\b|"
        r"\b(write|generate|create|build)\b.{0,70}\b(code|script|program|website|calculator|api)\b",
        text,
    )) or text.strip().startswith(("код на ", "программа на ", "сайт на "))


def _language(text):
    if re.search(r"\b(html|сайт|веб[- ]страниц|страниц[ау] сайта)\b", text):
        return "html"
    if re.search(r"\b(язык\s*)?(javascript|js)\b", text):
        return "javascript"
    if re.search(r"\b(c\+\+|cpp)\b", text):
        return "cpp"
    if re.search(r"\b(java)\b", text):
        return "java"
    return "python"


def _python_calculator():
    return textwrap.dedent('''\
        """Простой консольный калькулятор."""
        def calculate(a: float, operator: str, b: float) -> float:
            if operator == "+":
                return a + b
            if operator == "-":
                return a - b
            if operator == "*":
                return a * b
            if operator == "/":
                if b == 0:
                    raise ZeroDivisionError("На ноль делить нельзя.")
                return a / b
            raise ValueError("Неизвестная операция.")

        def main() -> None:
            print("Калькулятор. Для выхода введи q.")
            while True:
                first = input("Первое число: ").strip()
                if first.lower() == "q":
                    break
                try:
                    a = float(first)
                    operator = input("Операция (+, -, *, /): ").strip()
                    b = float(input("Второе число: ").strip())
                    print("Результат:", calculate(a, operator, b))
                except (ValueError, ZeroDivisionError) as error:
                    print("Ошибка:", error)

        if __name__ == "__main__":
            main()
    ''').strip()


def _python_guess_game():
    return textwrap.dedent('''\
        """Игра: угадай число от 1 до 100."""
        import random

        def main() -> None:
            secret = random.randint(1, 100)
            attempts = 0
            print("Я загадал число от 1 до 100.")
            while True:
                raw = input("Твоя догадка (или q для выхода): ").strip()
                if raw.lower() == "q":
                    print("Загаданное число:", secret)
                    return
                try:
                    guess = int(raw)
                except ValueError:
                    print("Введи целое число.")
                    continue
                if not 1 <= guess <= 100:
                    print("Число должно быть от 1 до 100.")
                    continue
                attempts += 1
                if guess < secret:
                    print("Моё число больше.")
                elif guess > secret:
                    print("Моё число меньше.")
                else:
                    print(f"Верно! Попыток: {attempts}.")
                    return

        if __name__ == "__main__":
            main()
    ''').strip()


def _python_todo():
    return textwrap.dedent('''\
        """Консольный список задач с сохранением в JSON."""
        import json
        from pathlib import Path

        DATA_FILE = Path("tasks.json")

        def load_tasks() -> list[str]:
            try:
                data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, list) and all(isinstance(x, str) for x in data) else []
            except (OSError, json.JSONDecodeError):
                return []

        def save_tasks(tasks: list[str]) -> None:
            DATA_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

        def main() -> None:
            tasks = load_tasks()
            while True:
                print("\\n1 — показать задачи\\n2 — добавить\\n3 — удалить\\n0 — выход")
                choice = input("Выбери действие: ").strip()
                if choice == "1":
                    for index, task in enumerate(tasks, 1):
                        print(f"{index}. {task}")
                    if not tasks:
                        print("Список пуст.")
                elif choice == "2":
                    task = input("Новая задача: ").strip()
                    if task:
                        tasks.append(task)
                        save_tasks(tasks)
                elif choice == "3":
                    try:
                        index = int(input("Номер задачи: ")) - 1
                        removed = tasks.pop(index)
                        save_tasks(tasks)
                        print("Удалено:", removed)
                    except (ValueError, IndexError):
                        print("Нет задачи с таким номером.")
                elif choice == "0":
                    break
                else:
                    print("Неизвестная команда.")

        if __name__ == "__main__":
            main()
    ''').strip()


def _python_api():
    return textwrap.dedent('''\
        """Минимальный JSON API на стандартной библиотеке Python."""
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def send_json(self, status: int, data: dict) -> None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/health":
                    self.send_json(200, {"ok": True, "service": "my-local-api"})
                else:
                    self.send_json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                if self.path != "/echo":
                    self.send_json(404, {"error": "Not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 16_384:
                        self.send_json(400, {"error": "Invalid body size"})
                        return
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("Expected a JSON object")
                    self.send_json(200, {"received": payload})
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    self.send_json(400, {"error": str(error)})

            def log_message(self, format: str, *args) -> None:
                print("[API]", format % args)

        if __name__ == "__main__":
            # Loopback: API доступен только с этого компьютера.
            server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
            print("API: http://127.0.0.1:8765")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    ''').strip()


def _html_page():
    return textwrap.dedent('''\
        <!doctype html>
        <html lang="ru">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Мой сайт</title>
          <style>
            * { box-sizing: border-box; }
            body {
              margin: 0; font-family: Arial, sans-serif; color: #172033;
              background: #f3f6fb; line-height: 1.6;
            }
            header { padding: 24px; background: #172b4d; color: white; }
            main { max-width: 900px; margin: 40px auto; padding: 24px; }
            .card {
              padding: 28px; background: white; border-radius: 16px;
              box-shadow: 0 8px 28px rgba(20, 40, 70, .08);
            }
            .button {
              display: inline-block; padding: 12px 18px; border-radius: 8px;
              background: #1769e0; color: white; text-decoration: none;
            }
            @media (max-width: 600px) { main { margin: 16px auto; padding: 12px; } }
          </style>
        </head>
        <body>
          <header><strong>Мой сайт</strong></header>
          <main>
            <section class="card">
              <h1>Добро пожаловать!</h1>
              <p>Замени этот текст своим описанием и добавь нужные разделы.</p>
              <a class="button" href="mailto:hello@example.com">Связаться</a>
            </section>
          </main>
        </body>
        </html>
    ''').strip()


def _js_calculator():
    return textwrap.dedent('''\
        // Безопасный калькулятор без eval().
        function calculate(first, operator, second) {
          const a = Number(first);
          const b = Number(second);
          if (!Number.isFinite(a) || !Number.isFinite(b)) {
            throw new TypeError("Введите два корректных числа.");
          }
          switch (operator) {
            case "+": return a + b;
            case "-": return a - b;
            case "*": return a * b;
            case "/":
              if (b === 0) throw new RangeError("На ноль делить нельзя.");
              return a / b;
            default: throw new Error("Неизвестная операция.");
          }
        }

        console.log(calculate(10, "+", 5)); // 15
    ''').strip()


def _cpp_calculator():
    return textwrap.dedent('''\
        #include <iostream>
        using namespace std;

        int main() {
            double a, b;
            char operation;
            cout << "Первое число: ";
            if (!(cin >> a)) return 1;
            cout << "Операция (+, -, *, /): ";
            cin >> operation;
            cout << "Второе число: ";
            if (!(cin >> b)) return 1;

            switch (operation) {
                case '+': cout << a + b; break;
                case '-': cout << a - b; break;
                case '*': cout << a * b; break;
                case '/':
                    if (b == 0) {
                        cerr << "На ноль делить нельзя.\\n";
                        return 1;
                    }
                    cout << a / b;
                    break;
                default:
                    cerr << "Неизвестная операция.\\n";
                    return 1;
            }
            cout << endl;
            return 0;
        }
    ''').strip()


def _java_calculator():
    return textwrap.dedent('''\
        import java.util.Scanner;

        public class Main {
            public static void main(String[] args) {
                Scanner input = new Scanner(System.in);
                System.out.print("Первое число: ");
                double a = input.nextDouble();
                System.out.print("Операция (+, -, *, /): ");
                char operation = input.next().charAt(0);
                System.out.print("Второе число: ");
                double b = input.nextDouble();

                switch (operation) {
                    case '+': System.out.println(a + b); break;
                    case '-': System.out.println(a - b); break;
                    case '*': System.out.println(a * b); break;
                    case '/':
                        if (b == 0) {
                            System.out.println("На ноль делить нельзя.");
                        } else {
                            System.out.println(a / b);
                        }
                        break;
                    default: System.out.println("Неизвестная операция.");
                }
                input.close();
            }
        }
    ''').strip()


def generate_code(prompt):
    """Return a reviewed starter solution for supported tasks, or ask for details."""
    text = str(prompt or "").strip()
    lowered = text.lower()
    language = _language(lowered)

    is_calculator = any(word in lowered for word in ("калькулятор", "calculator"))
    is_game = any(word in lowered for word in ("угадай число", "угадыван", "guessing game"))
    is_todo = any(word in lowered for word in ("список задач", "todo", "to-do", "задачник"))
    is_api = any(word in lowered for word in ("api", "сервер", "http server", "веб-сервер"))
    is_website = any(word in lowered for word in ("сайт", "веб-страниц", "landing page", "лендинг"))
    is_hello = any(word in lowered for word in ("привет мир", "hello world", "выведи привет"))

    if language == "html" or is_website:
        language, code, title = "html", _html_page(), "Адаптивная HTML-страница"
    elif is_calculator and language == "javascript":
        code, title = _js_calculator(), "Калькулятор на JavaScript"
    elif is_calculator and language == "cpp":
        code, title = _cpp_calculator(), "Калькулятор на C++"
    elif is_calculator and language == "java":
        code, title = _java_calculator(), "Калькулятор на Java"
    elif is_calculator:
        language, code, title = "python", _python_calculator(), "Консольный калькулятор на Python"
    elif is_game and language == "python":
        code, title = _python_guess_game(), "Игра «Угадай число» на Python"
    elif is_todo and language == "python":
        code, title = _python_todo(), "Список задач на Python"
    elif is_api and language == "python":
        code, title = _python_api(), "Локальный JSON API на Python"
    elif is_hello and language == "python":
        code, title = 'print("Привет, мир!")', "Программа «Привет, мир!» на Python"
    else:
        options = (
            "Пока у меня есть проверенные заготовки для калькулятора, игры «Угадай число», "
            "списка задач, простого локального API и HTML-страницы. "
            "Для другой программы напиши, что она должна делать, на каком языке и какие данные "
            "получает/возвращает. Я не стану выдавать случайный текст за рабочий код."
        )
        return options

    if language == "python":
        # Syntax-check generated Python before showing it to the user.
        ast.parse(code)
    return f"{title}. Код ниже — локальная заготовка; я его не запускал.\n\n```{language}\n{code}\n```\n\nМогу доработать его под твои точные требования."
