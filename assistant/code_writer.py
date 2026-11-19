"""Определение запросов на создание и изменение программного кода."""
import re


_CODE_REQUEST = re.compile(
    r"\\b(напиши|создай|сгенерируй|сделай|разработай|реализуй|добавь|исправь|"
    r"перепиши|оптимизируй|переделай)\\b.{0,120}\\b("
    r"код|программ\\w*|приложен\\w*|скрипт\\w*|сайт\\w*|веб[- ]страниц\\w*|"
    r"калькулятор\\w*|игр\\w*|бот\\w*|функци\\w*|класс\\w*|api|"
    r"модул\\w*|сервис\\w*|страниц\\w*|компонент\\w*|алгоритм\\w*|систем\\w*)\\b|"
    r"\\b(write|create|generate|build|implement|fix|refactor)\\b.{0,120}\\b("
    r"code|program|app|application|script|website|webpage|function|class|module|api|bot)\\b",
    re.IGNORECASE,
)


def is_code_request(prompt):
    """Recognize code-writing and code-editing instructions in Russian or English."""
    text = str(prompt or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if _CODE_REQUEST.search(lowered):
        return True
    return lowered.startswith((
        "код на ", "программа на ", "сайт на ", "функция на ",
        "напиши на python ", "напиши на javascript ", "напиши на c++ ",
    ))
