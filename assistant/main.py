import ctypes
import json
import os
import queue
import subprocess
import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import pyttsx3
import requests
import sounddevice as sd
from vosk import KaldiRecognizer, Model
from brain import DimasikBrain
from github_manager import GitHubManager
from email_manager import EmailManager
from knowledge import LocalKnowledge
from crosshair_api import start_server as start_crosshair_api
from code_writer import is_code_request
from local_coder import LocalCoder
from dialogue import conversational_reply
from modern_widgets import RoundedButton, RoundedPanel
from image_generator import LocalImageGenerator, is_image_request

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
VOSK_MODEL = ROOT / "models" / "vosk-model-small-ru-0.22"
SAMPLE_RATE = 16000
audio_queue = queue.Queue(maxsize=80)
history = deque(maxlen=16)
UI_APP = None
RELEASE_API = "https://api.github.com/repos/MineBotX/Dimasik-AI/releases/tags/latest"

DEFAULTS = {
    "assistant_name": "Димасик",
    "wake_words": ["димасик", "димас", "димон"],
    "voice_rate": 165,
    "voice_name": "",
    "voice_volume": 1.0,
    "personality": "Дружелюбный, умный, с лёгким чувством юмора. Отвечай по-русски и обычно кратко.",
    "search_url": "https://www.google.com/search?q={query}",
    "websites": {
        "youtube": "https://www.youtube.com",
        "ютуб": "https://www.youtube.com",
        "гугл": "https://www.google.com",
        "почта": "https://mail.google.com",
        "почта gmail": "https://mail.google.com",
        "диск": "https://drive.google.com",
        "github": "https://github.com"
    },
    "apps": {
        "блокнот": ["notepad.exe"],
        "калькулятор": ["calc.exe"],
        "проводник": ["explorer.exe"],
        "paint": ["mspaint.exe"],
        "паинт": ["mspaint.exe"],
        "диспетчер задач": ["taskmgr.exe"],
        "панель управления": ["control.exe"],
        "wordpad": ["write.exe"]
    }
}


def load_config():
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                config.update(user)
        except (OSError, json.JSONDecodeError) as exc:
            print("Не удалось прочитать config.json:", exc)
    else:
        CONFIG_PATH.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    config["wake_words"] = [str(x).lower() for x in config.get("wake_words", DEFAULTS["wake_words"])]
    config["apps"] = config.get("apps") if isinstance(config.get("apps"), dict) else {}
    config["websites"] = config.get("websites") if isinstance(config.get("websites"), dict) else {}
    return config


CONFIG = load_config()
ASSISTANT_NAME = str(CONFIG.get("assistant_name", "Димасик"))
BRAIN = DimasikBrain()
KNOWLEDGE = LocalKnowledge(ROOT / "brain" / "knowledge.sqlite3")
CODE_WRITER = LocalCoder(ROOT)
IMAGE_GENERATOR = LocalImageGenerator(ROOT)
WAKE_WORDS = tuple(CONFIG["wake_words"])
tts = pyttsx3.init()
tts.setProperty("rate", max(100, min(250, int(CONFIG.get("voice_rate", 172)))))
tts.setProperty("volume", max(0.0, min(1.0, float(CONFIG.get("voice_volume", 1.0)))))



def mood_for_text(text):
    value = str(text).lower()
    if any(x in value for x in ("ошибка", "не удалось", "не получилось", "недоступ")):
        return ("😟", "Есть затруднение", "#ff8585")
    if any(x in value for x in ("грустно", "жаль", "одиноко", "расстроен", "нелегко")):
        return ("😢", "Сочувствую", "#8fa8ff")
    if any(x in value for x in ("удивительно", "неожиданно", "ого", "ничего себе")):
        return ("😮", "Удивлён", "#d7a0ff")
    if any(x in value for x in ("злюсь", "раздражает", "сердит")):
        return ("😠", "Серьёзно настроен", "#ff9b72")
    if any(x in value for x in ("готово", "отлично", "супер", "успеш", "открываю")):
        return ("😄", "Рад помочь!", "#65e6ad")
    if any(x in value for x in ("не знаю", "уточни", "что именно", "повтори")):
        return ("🤔", "Размышляю", "#ffd27a")
    if any(x in value for x in ("привет", "здравств", "доброе утро", "добрый вечер")):
        return ("😊", "Приветствую!", "#65d7ff")
    return ("🙂", "На связи", "#65d7ff")


def read_app_version():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


def flush_audio():
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def configure_voice():
    try:
        voices = tts.getProperty("voices") or []
        russian = [v for v in voices if any(tag in (str(v.id) + " " + str(v.name)).lower()
                    for tag in ("ru", "russian", "рус"))]
        if russian:
            preferred = ("pavel", "андрей", "alexander", "александр", "иван", "dmitry", "дмитрий")
            configured = str(CONFIG.get("voice_name", "")).strip().lower()
            selected = next((v for v in russian if configured and configured in (str(v.id) + " " + str(v.name)).lower()), None)
            selected = selected or next((v for tag in preferred for v in russian if tag in (v.name or "").lower()), russian[0])
            tts.setProperty("voice", selected.id)
            print("Голос:", selected.name)
        else:
            print("Русский голос не найден. Установи его в настройках речи Windows.")
    except Exception as exc:
        print("Не удалось выбрать голос:", exc)


def speak(message):
    message = str(message).strip()
    if not message:
        return
    print("\n" + ASSISTANT_NAME + ": " + message)
    if UI_APP is not None:
        UI_APP.set_mood(mood_for_text(message))
        UI_APP.post_message(ASSISTANT_NAME, message)
    # Source code is shown in the chat but is not read aloud token by token.
    if "\x60\x60\x60" in message:
        flush_audio()
        return
    flush_audio()
    try:
        # Change speaking tempo with the detected emotion.
        emotion, _label, _color = mood_for_text(message)
        base_rate = max(100, min(250, int(CONFIG.get("voice_rate", 165))))
        rate_shift = {"😄": 22, "😊": 14, "🤔": 8, "😟": -18, "😢": -24, "😮": 18, "😠": -8}.get(emotion, 0)
        tts.setProperty("rate", max(100, min(250, base_rate + rate_shift)))
        tts.setProperty("volume", max(0.0, min(1.0, float(CONFIG.get("voice_volume", 1.0)))))
        tts.say(message)
        tts.runAndWait()
        tts.setProperty("rate", base_rate)
    except Exception as exc:
        print("Ошибка озвучивания:", exc)
    flush_audio()


def audio_callback(indata, frames, callback_time, status):
    try:
        audio_queue.put_nowait(bytes(indata))
    except queue.Full:
        pass


def listen(model, prompt):
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    print("\n" + prompt)
    flush_audio()
    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16",
                           channels=1, callback=audio_callback):
        while True:
            data = audio_queue.get()
            if recognizer.AcceptWaveform(data):
                phrase = json.loads(recognizer.Result()).get("text", "").strip().lower()
                if phrase:
                    return phrase


def brain_ready():
    return BRAIN.ready


def _looks_like_question(prompt):
    value = str(prompt).strip().lower()
    if "?" in value:
        return True
    return value.startswith((
        "что ", "кто ", "где ", "когда ", "почему ", "зачем ", "как ",
        "сколько ", "какой ", "какая ", "какие ", "расскажи о ", "расскажи про ",
        "объясни ", "чем отличается ", "правда ли ", "what ", "who ", "where ",
        "when ", "why ", "how ", "which ", "tell me about "
    ))


def ask_local_ai(prompt):
    history.append({"role": "user", "content": prompt})
    normalized = str(prompt).strip()
    lowered = normalized.lower()

    # Generate original code with the local Granite model, not templates.
    if is_code_request(normalized):
        try:
            answer = CODE_WRITER.generate(normalized, conversation=list(history)[:-1])
        except Exception as exc:
            answer = "Не получилось запустить локальную модель для написания кода: " + str(exc)
        history.append({"role": "assistant", "content": answer})
        KNOWLEDGE.remember(prompt, answer, source="conversation")
        return answer

    # Generate images completely offline after the local model is installed.
    if is_image_request(normalized):
        try:
            if UI_APP is not None:
                UI_APP.set_status("Создаю изображение локально…", "#82aaff")
            image_path = IMAGE_GENERATOR.generate(normalized)
            answer = "Готово! Я создал изображение и сохранил его сюда:\n" + str(image_path)
            if UI_APP is not None:
                UI_APP.set_status("Изображение готово", "#65dfb5")
                UI_APP.post_image_preview(str(image_path))
        except Exception as exc:
            answer = "Не получилось создать изображение: " + str(exc)
            if UI_APP is not None:
                UI_APP.set_status("Не удалось создать изображение", "#ff8585")
        history.append({"role": "assistant", "content": answer})
        KNOWLEDGE.remember(prompt, answer, source="conversation")
        return answer

    # Handle greetings and identity questions before web search. They do not
    # require internet and should never fall through to the fact-search path.
    answer = conversational_reply(prompt, list(history)[:-1])
    if answer is not None:
        history.append({"role": "assistant", "content": answer})
        KNOWLEDGE.remember(prompt, answer, source="conversation")
        return answer

    explicit_prefixes = (
        "найди информацию о ", "поищи информацию о ",
        "найди в интернете ", "поищи в интернете ",
        "найди ", "поищи ", "загугли ", "поиск ",
        "search for ", "look up ",
    )
    explicit = next((prefix for prefix in explicit_prefixes if lowered.startswith(prefix)), None)
    query = normalized[len(explicit):].strip() if explicit else normalized

    # Для вопросов сначала пытаемся получить свежие источники из интернета.
    if explicit or _looks_like_question(query):
        result = KNOWLEDGE.search_web(query, limit=5)
        if result.get("online"):
            answer = KNOWLEDGE.format_web_answer(query, result["results"])
            KNOWLEDGE.remember(prompt, answer, source="web")
        else:
            memories = KNOWLEDGE.find_similar(query, limit=3)
            if memories:
                answer = KNOWLEDGE.format_memory_answer(memories)
            else:
                detail = str(result.get("error") or "").strip()
                fallback = str(CONFIG.get("search_url", "https://www.google.com/search?q={query}"))
                try:
                    browser_url = fallback.format(query=quote_plus(query))
                except (KeyError, ValueError):
                    browser_url = "https://www.google.com/search?q=" + quote_plus(query)
                answer = (
                    "Не удалось получить результаты из поисковых систем. "
                    "Проверь интернет-соединение или открой поиск вручную:\n"
                    + browser_url
                )
                if detail:
                    answer += "\nПодробности: " + detail
        history.append({"role": "assistant", "content": answer})
        return answer

    context = " ".join(item["content"] for item in list(history)[-4:])
    answer = BRAIN.answer(context)
    if not BRAIN.ready:
        answer = "Я пока учусь поддерживать свободный разговор. " + answer
    history.append({"role": "assistant", "content": answer})
    KNOWLEDGE.remember(prompt, answer, source="conversation")
    return answer

def launch_app(alias):
    command = CONFIG["apps"].get(alias)
    if not command:
        return False
    try:
        if isinstance(command, str):
            subprocess.Popen(command, shell=False)
        elif isinstance(command, list) and command and all(isinstance(x, str) for x in command):
            subprocess.Popen(command, shell=False)
        else:
            speak("Неправильная настройка приложения в config.json.")
            return True
        speak("Открываю " + alias + ".")
    except (OSError, ValueError) as exc:
        speak("Не получилось открыть " + alias + ": " + str(exc))
    return True


def open_folder(name):
    folders = {
        "загрузки": Path.home() / "Downloads",
        "документы": Path.home() / "Documents",
        "рабочий стол": Path.home() / "Desktop",
        "изображения": Path.home() / "Pictures",
        "музыка": Path.home() / "Music",
        "видео": Path.home() / "Videos",
    }
    path = folders[name]
    try:
        if path.exists():
            subprocess.Popen(["explorer.exe", str(path)])
            speak("Открываю папку " + name + ".")
        else:
            speak("Папка не найдена.")
    except OSError:
        speak("Не удалось открыть папку.")


def media_key(key):
    # Windows multimedia virtual-key codes.
    codes = {"громче": 0xAF, "тише": 0xAE, "без звука": 0xAD}
    ctypes.windll.user32.keybd_event(codes[key], 0, 0, 0)
    ctypes.windll.user32.keybd_event(codes[key], 0, 2, 0)
    speak("Готово." if key != "без звука" else "Переключил звук.")


def show_help():
    speak(
        "Я умею сообщать время и дату, открывать программы и папки, "
        "управлять громкостью, открывать сайты и настройки Windows, "
        "искать в интернете, писать типовой код на Python и создавать простые HTML-страницы. "
        "Для программирования скажи: напиши код калькулятора на Python. "
        "Сложные нестандартные проекты нужно описать подробнее. "
        "Я также умею создавать картинки локально: скажи «нарисуй картинку кота». "
        "Сначала загрузи модель изображений кнопкой внизу окна. "
        "Список пользовательских программ и сайтов можно менять в config.json."
    )


def execute_command(command):
    command = command.strip().lower()
    if not command:
        speak("Я не расслышал команду.")
        return True

    if command in ("стоп", "выход", "завершить работу", "пока"):
        speak("Хорошо. До встречи.")
        return False
    if command in ("помощь", "что ты умеешь", "список команд", "команды"):
        show_help()
        return True
    if command in ("очисти диалог", "забудь разговор", "сбрось память"):
        history.clear()
        speak("Контекст этого разговора очищен.")
        return True
    if any(x in command for x in ("который час", "сколько времени", "время")):
        speak("Сейчас " + datetime.now().strftime("%H:%M"))
        return True
    if any(x in command for x in ("какая дата", "какое сегодня число", "дата", "число")):
        speak("Сегодня " + datetime.now().strftime("%d.%m.%Y"))
        return True

    for folder in ("загрузки", "документы", "рабочий стол", "изображения", "музыка", "видео"):
        if ("открой " + folder) in command or ("папку " + folder) in command:
            open_folder(folder)
            return True

    for alias in sorted(CONFIG["apps"], key=len, reverse=True):
        if command in ("открой " + alias, "запусти " + alias, alias):
            launch_app(alias)
            return True

    for alias, url in CONFIG["websites"].items():
        if command in ("открой " + alias, "запусти " + alias, alias):
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                webbrowser.open(url)
                speak("Открываю " + alias + ".")
            else:
                speak("Адрес сайта в config.json должен начинаться с http или https.")
            return True

    if any(x in command for x in ("громче", "увеличь громкость")):
        media_key("громче")
        return True
    if any(x in command for x in ("тише", "уменьши громкость")):
        media_key("тише")
        return True
    if any(x in command for x in ("выключи звук", "без звука", "включи звук", "верни звук")):
        media_key("без звука")
        return True

    if "настройки windows" in command or command == "настройки":
        subprocess.Popen(["cmd", "/c", "start", "", "ms-settings:"])
        speak("Открываю настройки Windows.")
        return True
    if "параметры экрана" in command:
        subprocess.Popen(["cmd", "/c", "start", "", "ms-settings:display"])
        speak("Открываю параметры экрана.")
        return True
    if "параметры звука" in command:
        subprocess.Popen(["cmd", "/c", "start", "", "ms-settings:sound"])
        speak("Открываю параметры звука.")
        return True
    if "заблокируй компьютер" in command or command == "заблокируй экран":
        speak("Блокирую компьютер.")
        ctypes.windll.user32.LockWorkStation()
        return True

    if command.startswith(("найди в интернете ", "поищи в интернете ", "найди ", "поищи ", "поиск ", "загугли ")):
        query = command.split(" ", 1)[1].strip()
        if query:
            # Голосовой поиск использует тот же механизм, что и текстовый чат.
            speak(ask_local_ai("найди в интернете " + query))
        else:
            speak("Что именно найти?")
        return True

    if any(x in command for x in ("удали файлы", "очисти диск", "выключи компьютер", "перезагрузи компьютер")):
        speak("Эта команда отключена для безопасности.")
        return True

    speak(ask_local_ai(command))
    return True



class DimasikApp:
    BG = "#0a1020"
    PANEL = "#121c30"
    PANEL2 = "#1a2942"
    ACCENT = "#82aaff"
    TEXT = "#f1f5ff"
    MUTED = "#93a5bf"
    GREEN = "#65dfb5"
    BORDER = "#273956"

    def __init__(self, root):
        self.root = root
        self.root.title(ASSISTANT_NAME + " — локальный ИИ")
        self.root.geometry("1180x780")
        self.root.minsize(840, 640)
        self.root.configure(bg=self.BG)
        self.running = threading.Event()
        self.github = GitHubManager()
        self.email = EmailManager()
        self.email_account = CONFIG.get("email_account", {})
        self.worker = None
        self.model = None
        self._image_previews = []
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(250, self.initialize)
        self.root.after(1800, lambda: self.check_updates(silent=True))

    def _build(self):
        # Header card
        header = RoundedPanel(
            self.root, fill=self.PANEL, background=self.BG, radius=20,
            padding=12, border=self.BORDER, height=100,
        )
        header.pack(fill="x", padx=16, pady=(14, 6))
        header_content = header.content
        left = tk.Frame(header_content, bg=self.PANEL)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(
            left, text="◈  " + ASSISTANT_NAME, bg=self.PANEL, fg=self.TEXT,
            font=("Segoe UI", 21, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left, text="ЛОКАЛЬНЫЙ ГОЛОСОВОЙ ПОМОЩНИК", bg=self.PANEL,
            fg=self.MUTED, font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(header_content, bg=self.PANEL)
        right.pack(side="right", anchor="e")
        self.mic_btn = RoundedButton(
            right, text="🎙  ВКЛЮЧИТЬ МИКРОФОН", command=self.toggle_listening,
            bg=self.GREEN, fg="#071522", activebackground="#83ecc8",
            font=("Segoe UI", 10, "bold"), padx=17, pady=10, radius=14,
            border="#73e8c1", canvas_bg=self.PANEL,
        )
        self.mic_btn.pack(anchor="e", pady=(0, 5))
        self.status = tk.Label(
            right, text="●  Запуск...", bg=self.PANEL, fg=self.ACCENT,
            font=("Segoe UI", 9, "bold"),
        )
        self.status.pack(anchor="e")
        self.mood_label = tk.Label(
            right, text="🙂  На связи", bg=self.PANEL, fg=self.ACCENT,
            font=("Segoe UI", 9, "bold"),
        )
        self.mood_label.pack(anchor="e", pady=(3, 0))

        body = tk.Frame(self.root, bg=self.BG, padx=16, pady=8)
        body.pack(fill="both", expand=True)

        # Rounded assistant identity card
        hero = RoundedPanel(
            body, fill=self.PANEL, background=self.BG, radius=18,
            padding=9, border=self.BORDER, height=76,
        )
        hero.pack(fill="x", pady=(0, 10))
        self.avatar = tk.Label(
            hero.content, text="🤖", bg=self.PANEL, fg=self.ACCENT,
            font=("Segoe UI Emoji", 25),
        )
        self.avatar.pack(side="left", padx=(5, 12))
        hero_text = tk.Frame(hero.content, bg=self.PANEL)
        hero_text.pack(side="left", fill="y", pady=3)
        tk.Label(
            hero_text, text="Твой помощник всегда рядом", bg=self.PANEL,
            fg=self.TEXT, font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hero_text, text="Общайся, ищи информацию и создавай программы",
            bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(3, 0))

        # Bottom composer and action bar
        bottom = tk.Frame(body, bg=self.BG)
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        footer = RoundedPanel(
            bottom, fill=self.PANEL, background=self.BG, radius=18,
            padding=10, border=self.BORDER, height=124,
        )
        footer.pack(fill="x")
        controls = tk.Frame(footer.content, bg=self.PANEL)
        controls.pack(fill="x", pady=(0, 8))
        entry_shell = RoundedPanel(
            controls, fill=self.PANEL2, background=self.PANEL, radius=13,
            padding=5, border="#314565", height=48,
        )
        entry_shell.pack(side="left", fill="x", expand=True, padx=(0, 9))
        self.entry = tk.Entry(
            entry_shell.content, bg=self.PANEL2, fg=self.TEXT,
            insertbackground=self.TEXT, relief="flat", bd=0,
            font=("Segoe UI", 11), highlightthickness=0,
        )
        self.entry.pack(fill="both", expand=True, ipady=8, padx=8)
        self.entry.bind("<Return>", lambda event: self.send_text())
        self.send_btn = RoundedButton(
            controls, text="Отправить  ➤", command=self.send_text,
            bg=self.ACCENT, fg="#0b1425", activebackground="#a2c0ff",
            font=("Segoe UI", 9, "bold"), padx=17, pady=10, radius=12,
            border="#93b4ff", canvas_bg=self.PANEL,
        )
        self.send_btn.pack(side="left")

        actions = tk.Frame(footer.content, bg=self.PANEL)
        actions.pack(fill="x")
        common_button = {
            "bg": self.PANEL2,
            "fg": self.TEXT,
            "activebackground": "#2a3d5e",
            "font": ("Segoe UI", 9, "bold"),
            "padx": 12,
            "pady": 8,
            "radius": 11,
            "border": self.BORDER,
            "canvas_bg": self.PANEL,
        }
        RoundedButton(
            actions, text="⚙  Настройки", command=self.open_settings,
            **common_button,
        ).pack(side="left", padx=(0, 5))
        self.update_btn = RoundedButton(
            actions, text="↻  Обновления", command=self.check_updates,
            fg=self.ACCENT, **{k: v for k, v in common_button.items() if k != "fg"},
        )
        self.update_btn.pack(side="left", padx=5)
        RoundedButton(
            actions, text="⌘  GitHub", command=self.open_github,
            **common_button,
        ).pack(side="left", padx=5)
        RoundedButton(
            actions, text="✉  Почта", command=self.open_email,
            **common_button,
        ).pack(side="left", padx=5)
        self.coder_btn = RoundedButton(
            actions,
            text="✓  Кодовая модель установлена" if CODE_WRITER.model_installed
                  else "↓  Скачать модель кода (≈2,24 ГБ)",
            command=self.download_coder_model,
            fg=self.GREEN if CODE_WRITER.model_installed else self.ACCENT,
            **{k: v for k, v in common_button.items() if k != "fg"},
        )
        self.coder_btn.pack(side="left", padx=5)
        self.image_btn = RoundedButton(
            actions,
            text="🖼 Создать картинку" if IMAGE_GENERATOR.model_installed
                 else "🖼 Модель картинок",
            command=self.image_action,
            fg=self.GREEN if IMAGE_GENERATOR.model_installed else self.ACCENT,
            **{k: v for k, v in common_button.items() if k != "fg"},
        )
        self.image_btn.pack(side="left", padx=5)
        RoundedButton(
            actions, text="Очистить чат", command=self.clear_chat,
            bg="#202b42", fg=self.MUTED, activebackground="#34445f",
            font=("Segoe UI", 9), padx=12, pady=8, radius=11,
            border=self.BORDER, canvas_bg=self.PANEL,
        ).pack(side="right")

        # Chat lives inside a rounded card; text remains selectable/copyable.
        chat_card = RoundedPanel(
            body, fill=self.PANEL, background=self.BG, radius=20,
            padding=8, border=self.BORDER, height=420,
        )
        chat_card.pack(fill="both", expand=True)
        self.chat = tk.Text(
            chat_card.content, bg=self.PANEL, fg=self.TEXT,
            insertbackground=self.TEXT, relief="flat", bd=0,
            wrap="word", padx=14, pady=12, font=("Segoe UI", 10),
            state="disabled", spacing1=5, spacing3=8,
            selectbackground="#34527a", selectforeground="#ffffff",
        )
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("system", foreground=self.MUTED, font=("Segoe UI", 8))
        self.chat.tag_configure("user", foreground=self.ACCENT, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("assistant", foreground=self.GREEN, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("body", foreground=self.TEXT, lmargin1=8, lmargin2=8)
        self.chat.tag_configure(
            "code", foreground="#b7f3d8", background="#0c1423",
            font=("Cascadia Code", 9), lmargin1=18, lmargin2=18,
            spacing1=5, spacing3=5,
        )
        self._append(
            "СИСТЕМА",
            "Привет! Я Димасик. Напиши сообщение или включи микрофон.",
            "system",
        )
        tk.Label(
            self.root,
            text="Локальный помощник  •  Vosk  •  DimaCore  •  Granite  •  Stable Diffusion",
            bg=self.BG, fg="#647896", font=("Segoe UI", 8), pady=5,
        ).pack()

    def image_action(self):
        if not IMAGE_GENERATOR.model_installed:
            self.download_image_model()
            return
        prompt = simpledialog.askstring(
            "Создать изображение",
            "Опиши, что нужно нарисовать:",
            parent=self.root,
        )
        if prompt and prompt.strip():
            self.entry.delete(0, "end")
            self.entry.insert(0, "Нарисуй " + prompt.strip())
            self.send_text()

    def download_image_model(self):
        if IMAGE_GENERATOR.model_installed:
            messagebox.showinfo("Модель изображений", "Модель Stable Diffusion уже установлена.")
            return
        if not messagebox.askyesno(
            "Скачать локальную модель изображений",
            "Будет скачана Stable Diffusion 1.5 Q4_0 размером около 1,75 ГБ. "
            "Для проверки файла и генерации нужно около 3 ГБ свободного места. "
            "Желательно иметь 8 ГБ оперативной памяти или больше. "
            "После загрузки изображения создаются только на этом компьютере, без облака и оплаты. "
            "Продолжить?",
        ):
            return
        self.image_btn.configure(state="disabled", text="Загрузка модели: 0%")
        threading.Thread(target=self._download_image_worker, daemon=True).start()

    def _download_image_worker(self):
        error = None

        def progress(percent, downloaded, total):
            label = f"Загрузка картинок: {percent}% ({downloaded / 1_000_000_000:.2f} / {total / 1_000_000_000:.2f} ГБ)"
            self.root.after(0, lambda value=label: self.image_btn.configure(text=value))

        try:
            IMAGE_GENERATOR.download_model(progress=progress)
        except Exception as exc:
            error = str(exc)

        def finish():
            if error:
                self.image_btn.configure(
                    state="normal", text="↻ Повторить загрузку", fg=self.ACCENT
                )
                messagebox.showerror("Модель изображений", error)
            else:
                self.image_btn.configure(
                    state="normal", text="🖼 Создать картинку", fg=self.GREEN
                )
                messagebox.showinfo(
                    "Модель изображений",
                    "Stable Diffusion установлена и проверена. Теперь можно создавать картинки без интернета.",
                )
        self.root.after(0, finish)

    def post_image_preview(self, image_path):
        self.root.after(0, lambda path=image_path: self._insert_image_preview(path))

    def _insert_image_preview(self, image_path):
        try:
            preview = tk.PhotoImage(file=image_path)
            shrink = max(1, (max(preview.width(), preview.height()) + 319) // 320)
            if shrink > 1:
                preview = preview.subsample(shrink, shrink)
            self._image_previews.append(preview)
            preview_button = tk.Button(
                self.chat,
                image=preview,
                command=lambda path=image_path: self._open_generated_image(path),
                bg=self.PANEL,
                activebackground=self.PANEL,
                relief="flat",
                bd=0,
                cursor="hand2",
            )
            self.chat.configure(state="normal")
            self.chat.insert("end", "\n")
            self.chat.window_create("end", window=preview_button, padx=8, pady=5)
            self.chat.insert(
                "end",
                "\nНажми на изображение, чтобы открыть оригинал.\nФайл: " + image_path + "\n",
                "body",
            )
            self.chat.configure(state="disabled")
            self.chat.see("end")
        except Exception as exc:
            self._append(
                "СИСТЕМА",
                "Не удалось показать предпросмотр. Файл сохранён: "
                + image_path + "\n" + str(exc),
                "system",
            )

    @staticmethod
    def _open_generated_image(image_path):
        try:
            os.startfile(image_path)
        except (AttributeError, OSError):
            webbrowser.open(Path(image_path).resolve().as_uri())

    def download_coder_model(self):
        if CODE_WRITER.model_installed:
            messagebox.showinfo("Модель кода", "Модель Granite уже установлена.")
            return
        if not messagebox.askyesno(
            "Скачать модель кода",
            "Будет скачана локальная модель Granite 4.2 3B размером около 2,24 ГБ. "
            "Она работает на этом компьютере и не требует платного API. "
            "Для загрузки нужен интернет и примерно 3 ГБ свободного места. Продолжить?",
        ):
            return
        self.coder_btn.configure(state="disabled", text="Загрузка модели: 0%")
        threading.Thread(target=self._download_coder_worker, daemon=True).start()

    def _download_coder_worker(self):
        result = None
        error = None

        def progress(percent, downloaded, total):
            if total:
                label = f"Загрузка модели: {percent}% ({downloaded / 1_000_000_000:.2f} / {total / 1_000_000_000:.2f} ГБ)"
            else:
                label = f"Загрузка модели: {downloaded / 1_000_000_000:.2f} ГБ"
            self.root.after(0, lambda value=label: self.coder_btn.configure(text=value))

        try:
            CODE_WRITER.download_model(progress=progress)
            result = "Модель Granite загружена и проверена. Теперь Димасик может писать новый код локально."
        except Exception as exc:
            error = str(exc)

        def finish():
            if error:
                self.coder_btn.configure(state="normal", text="Повторить загрузку модели")
                messagebox.showerror("Модель кода", error)
            else:
                self.coder_btn.configure(
                    state="normal", text="Кодовая модель установлена", fg=self.GREEN
                )
                messagebox.showinfo("Модель кода", result)
        self.root.after(0, finish)

    def set_mood(self, mood):
        emoji, label, color = mood
        def apply():
            self.mood_label.configure(text=emoji + "  " + label, fg=color)
            self.avatar.configure(text=emoji, fg=color)
        self.root.after(0, apply)

    def check_updates(self, silent=False):
        self.update_btn.configure(state="disabled", text="Проверяю...")
        threading.Thread(target=self._check_updates_worker, args=(silent,), daemon=True).start()

    def _check_updates_worker(self, silent):
        try:
            r = requests.get(RELEASE_API, headers={"Accept": "application/vnd.github+json"}, timeout=12)
            if r.status_code == 404:
                result = ("none", "Пока нет опубликованного релиза с обновлением.")
            else:
                r.raise_for_status()
                release = r.json()
                asset = next((a for a in release.get("assets", []) if a.get("name") == "Dimasik-Windows-GUI-x64.zip"), None)
                if not asset:
                    result = ("none", "Архив обновления пока не найден.")
                else:
                    local_version = read_app_version()
                    release_body = str(release.get("body") or "")
                    release_version = ""
                    for line in release_body.splitlines():
                        if line.strip().lower().startswith("build:"):
                            release_version = line.split(":", 1)[1].strip()
                            break
                    if release_version and release_version == local_version:
                        result = ("current", "Установлена последняя версия.")
                    elif not release_version:
                        result = ("unknown", "У релиза нет номера сборки. Проверка станет доступна после следующей публикации.")
                    else:
                        result = ("available", asset.get("browser_download_url", ""))
        except Exception as exc:
            result = ("error", str(exc))
        def finish():
            self.update_btn.configure(state="normal", text="↻  Проверить обновления")
            kind, data = result
            if kind == "available":
                if messagebox.askyesno("Обновление", "Доступна новая версия Димасика. Установить сейчас? Приложение перезапустится."):
                    self._start_update(data)
            elif not silent:
                messagebox.showinfo("Обновления", data)
        self.root.after(0, finish)

    def _start_update(self, url):
        script = ROOT / "update.ps1"
        if not script.exists():
            messagebox.showerror("Обновление", "Не найден update.ps1. Скачай новый комплект приложения.")
            return
        subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-DownloadUrl", url, "-TargetDir", str(ROOT), "-ProcessId", str(os.getpid())], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.close()

    def _append(self, who, message, tag):
        self.chat.configure(state="normal")
        self.chat.insert("end", who + "\n", tag)
        parts = str(message).split("\x60\x60\x60")
        for index, part in enumerate(parts):
            if index % 2:
                _language, separator, code = part.partition("\n")
                if not separator:
                    code = part
                self.chat.insert("end", code.rstrip() + "\n", "code")
            else:
                self.chat.insert("end", part, "body")
        self.chat.insert("end", "\n", "body")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def post_message(self, who, message):
        tag = "assistant" if who == ASSISTANT_NAME else "user"
        self.root.after(0, lambda: self._append(who, message, tag))

    def set_status(self, text, color=None):
        self.root.after(0, lambda: self.status.configure(text="●  " + text, fg=color or self.ACCENT))

    def initialize(self):
        configure_voice()
        if not VOSK_MODEL.is_dir():
            self.set_status("Не найдена модель речи", "#ff7777")
            self._append("СИСТЕМА", "Не найдена модель Vosk:\n" + str(VOSK_MODEL) +
                         "\nСкачай комплект с GitHub Actions, в котором есть папка models.", "system")
            return
        try:
            self.model = Model(str(VOSK_MODEL))
        except Exception as exc:
            self.set_status("Ошибка модели", "#ff7777")
            self._append("СИСТЕМА", "Не удалось загрузить модель речи: " + str(exc), "system")
            return
        if brain_ready():
            self.set_status("Готов к работе", self.GREEN)
            self._append("СИСТЕМА", "Готов к работе. Нажми «Включить микрофон» или напиши сообщение.", "system")
        else:
            self.set_status("Нужно обучение ядра", "#f4c76b")
            self._append("СИСТЕМА", "Распознавание речи готово. Моё собственное нейросетевое ядро ещё не обучено. Добавь примеры в training_data.txt и запусти train_brain.py.", "system")

    def send_text(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append("ТЫ", text, "user")
        self.set_mood(("🤔", "Обдумываю ответ", "#ffd27a"))
        self.send_btn.configure(state="disabled")
        threading.Thread(target=self._answer_text, args=(text,), daemon=True).start()

    def _answer_text(self, text):
        try:
            execute_command(text)
        finally:
            self.root.after(0, lambda: self.send_btn.configure(state="normal"))

    def toggle_listening(self):
        if self.running.is_set():
            self.running.clear()
            self.mic_btn.configure(text="▶  Включить микрофон")
            self.set_status("Микрофон выключен", self.MUTED)
            return
        if self.model is None:
            messagebox.showwarning("Димасик", "Модель распознавания речи не загружена. Проверь папку models.")
            return
        try:
            device = sd.query_devices(kind="input")
            if not device or int(device.get("max_input_channels", 0)) < 1:
                raise RuntimeError("Windows не обнаружила устройство записи.")
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16",
                                   channels=1, callback=audio_callback):
                pass
        except Exception as exc:
            devices = sd.query_devices()
            inputs = [f"{i}: {d['name']} (каналов: {d['max_input_channels']})"
                      for i, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]
            details = "\n".join(inputs) or "Входные устройства не найдены."
            messagebox.showerror("Не удалось включить микрофон",
                f"{exc}\n\nПроверь разрешение Windows для микрофона и выбери устройство записи по умолчанию.\n\nНайденные устройства:\n{details}")
            self.set_status("Микрофон недоступен", "#ff7777")
            return
        self.running.set()
        self.mic_btn.configure(text="■  Выключить микрофон")
        self.set_status("Слушаю ключевое слово «" + ASSISTANT_NAME + "»")
        self.set_mood(("👂", "Внимательно слушаю", self.ACCENT))
        self.worker = threading.Thread(target=self._listen_loop, daemon=True)
        self.worker.start()

    def _listen_loop(self):
        while self.running.is_set():
            try:
                phrase = listen(self.model, "Ожидаю ключевое слово")
                if not self.running.is_set():
                    break
                self.root.after(0, lambda p=phrase: self._append("РАСПОЗНАНО", p, "system"))
                wake = next((word for word in WAKE_WORDS if word in phrase), None)
                if not wake:
                    continue
                command = phrase.replace(wake, "", 1).strip(" ,.!?;:")
                if not command:
                    self.set_status("Слушаю команду...", self.GREEN)
                    command = listen(self.model, "Говори, я слушаю")
                if command:
                    self.post_message("ТЫ", command)
                    if not execute_command(command):
                        self.running.clear()
                        break
                self.set_status("Слушаю ключевое слово «" + ASSISTANT_NAME + "»")
            except Exception as exc:
                self.running.clear()
                self.set_status("Ошибка микрофона", "#ff7777")
                self.root.after(0, lambda e=str(exc): messagebox.showerror(
                    "Ошибка микрофона", f"Не удалось продолжить запись: {e}\n\nПроверь разрешения Windows: Параметры → Конфиденциальность и безопасность → Микрофон."))
                break
        self.root.after(0, lambda: self.mic_btn.configure(text="▶  Включить микрофон"))


    def open_github(self):
        win = tk.Toplevel(self.root)
        win.title("GitHub — проекты")
        win.geometry("700x520")
        win.configure(bg=self.BG)
        tk.Label(win, text="Управление GitHub", bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(win, text="Токен хранится в защищённом хранилище Windows.",
                 bg=self.BG, fg=self.MUTED).pack(anchor="w", padx=20)
        bar = tk.Frame(win, bg=self.BG)
        bar.pack(fill="x", padx=20, pady=14)
        state = tk.Label(bar, text="Подключён" if self.github.connected else "Не подключён",
                         bg=self.BG, fg=self.GREEN if self.github.connected else "#ffbb66")
        state.pack(side="left")
        listing = tk.Listbox(win, bg=self.PANEL, fg=self.TEXT, relief="flat",
                             font=("Segoe UI", 10), selectbackground=self.ACCENT)
        listing.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        def connect():
            token = simpledialog.askstring("GitHub", "Вставь GitHub token с минимальными нужными правами:", show="*", parent=win)
            if not token:
                return
            try:
                user = self.github.connect(token)
                state.configure(text="Подключён: " + user.get("login", ""), fg=self.GREEN)
                load_repos()
            except Exception as exc:
                messagebox.showerror("GitHub", str(exc), parent=win)
        def load_repos():
            listing.delete(0, "end")
            try:
                repos = self.github.list_repositories()
                for repo in repos:
                    listing.insert("end", f"{repo['full_name']}  •  {repo.get('description') or 'Без описания'}")
                if not repos:
                    listing.insert("end", "Репозитории не найдены.")
            except Exception as exc:
                messagebox.showerror("GitHub", str(exc), parent=win)
        def disconnect():
            try:
                self.github.disconnect()
                state.configure(text="Не подключён", fg="#ffbb66")
                listing.delete(0, "end")
            except Exception as exc:
                messagebox.showerror("GitHub", str(exc), parent=win)
        tk.Button(bar, text="Подключить", command=connect, bg=self.ACCENT, fg="#06111e",
                  relief="flat", padx=12, pady=7).pack(side="left", padx=8)
        tk.Button(bar, text="Обновить список", command=load_repos, bg=self.PANEL2, fg=self.TEXT,
                  relief="flat", padx=12, pady=7).pack(side="left")
        tk.Button(bar, text="Отключить", command=disconnect, bg=self.PANEL2, fg=self.TEXT,
                  relief="flat", padx=12, pady=7).pack(side="right")
        if self.github.connected:
            load_repos()

    def open_email(self):
        win = tk.Toplevel(self.root)
        win.title("Почта — подключение")
        win.geometry("720x560")
        win.configure(bg=self.BG)
        tk.Label(win, text="Электронная почта", bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(win, text="Поддержка IMAP/SMTP. Используй пароль приложения, если он требуется провайдером.",
                 bg=self.BG, fg=self.MUTED, wraplength=660).pack(anchor="w", padx=20)
        form = tk.Frame(win, bg=self.BG)
        form.pack(fill="x", padx=20, pady=14)
        fields = {}
        defaults = {"Адрес": self.email_account.get("address", ""),
                    "IMAP сервер": self.email_account.get("imap_host", ""),
                    "SMTP сервер": self.email_account.get("smtp_host", ""),
                    "SMTP порт": str(self.email_account.get("smtp_port", 587))}
        for label, default in defaults.items():
            tk.Label(form, text=label, bg=self.BG, fg=self.MUTED).pack(anchor="w", pady=(5, 2))
            entry = tk.Entry(form, bg=self.PANEL, fg=self.TEXT, insertbackground=self.TEXT,
                             relief="flat", font=("Segoe UI", 11))
            entry.insert(0, default)
            entry.pack(fill="x", ipady=7)
            fields[label] = entry
        tk.Label(form, text="Пароль приложения (будет сохранён в хранилище Windows)",
                 bg=self.BG, fg=self.MUTED).pack(anchor="w", pady=(8, 2))
        password = tk.Entry(form, show="*", bg=self.PANEL, fg=self.TEXT, insertbackground=self.TEXT, relief="flat")
        password.pack(fill="x", ipady=7)
        def save():
            try:
                account = self.email.save_account(fields["Адрес"].get(), password.get(),
                    fields["IMAP сервер"].get(), fields["SMTP сервер"].get(),
                    int(fields["SMTP порт"].get() or 587))
                self.email_account = account
                CONFIG["email_account"] = account
                CONFIG_PATH.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
                messagebox.showinfo("Почта", "Настройки сохранены. Пароль хранится отдельно в Windows.", parent=win)
                load_mail()
            except Exception as exc:
                messagebox.showerror("Почта", str(exc), parent=win)
        tk.Button(form, text="Сохранить подключение", command=save, bg=self.ACCENT, fg="#06111e",
                  relief="flat", padx=12, pady=9).pack(anchor="w", pady=12)
        listing = tk.Listbox(win, bg=self.PANEL, fg=self.TEXT, relief="flat", font=("Segoe UI", 9))
        listing.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        def load_mail():
            listing.delete(0, "end")
            try:
                for item in self.email.list_messages(self.email_account):
                    listing.insert("end", f"{item['date']} | {item['from']} | {item['subject']}")
                    listing.insert("end", item["body"][:500].replace("\n", " "))
                    listing.insert("end", "—" * 50)
            except Exception as exc:
                messagebox.showerror("Почта", str(exc), parent=win)
        tk.Button(win, text="Проверить входящие", command=load_mail, bg=self.PANEL2, fg=self.TEXT,
                  relief="flat", padx=12, pady=8).pack(anchor="w", padx=20, pady=(0, 14))

    def open_settings(self):
        try:
            if not CONFIG_PATH.exists():
                CONFIG_PATH.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            subprocess.Popen(["notepad.exe", str(CONFIG_PATH)])
        except OSError as exc:
            messagebox.showerror("Настройки", str(exc))

    def clear_chat(self):
        history.clear()
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._append("СИСТЕМА", "История диалога очищена.", "system")

    def close(self):
        self.running.clear()
        try:
            CODE_WRITER.stop()
        except Exception:
            pass
        try:
            tts.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    global UI_APP
    if CONFIG.get("crosshair_api_enabled", True):
        try:
            api_host = str(CONFIG.get("crosshair_api_host", "127.0.0.1"))
            if api_host not in ("127.0.0.1", "localhost"):
                api_host = "127.0.0.1"
            api_server = start_crosshair_api(api_host, int(CONFIG.get("crosshair_api_port", 8765)))
            print(f"API генерации прицелов: http://{api_host}:{api_server.server_port}")
        except OSError as exc:
            print("Не удалось запустить API генерации прицелов:", exc)
    root = tk.Tk()
    UI_APP = DimasikApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
