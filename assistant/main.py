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
    "voice_rate": 172,
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
WAKE_WORDS = tuple(CONFIG["wake_words"])
tts = pyttsx3.init()
tts.setProperty("rate", max(100, min(250, int(CONFIG.get("voice_rate", 172)))))
tts.setProperty("volume", max(0.0, min(1.0, float(CONFIG.get("voice_volume", 1.0)))))



def mood_for_text(text):
    value = str(text).lower()
    if any(x in value for x in ("ошибка", "не удалось", "не получилось", "недоступ")):
        return ("😟", "Есть затруднение", "#ff8585")
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
            preferred = ("dmitry", "pavel", "андрей", "александр", "дмитрий")
            selected = next((v for v in russian if any(tag in (v.name or "").lower()
                             for tag in preferred)), russian[0])
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
    flush_audio()
    try:
        tts.say(message)
        tts.runAndWait()
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


def conversational_reply(prompt):
    """Offline dialogue layer for common social turns and follow-ups."""
    text = str(prompt).strip().lower()
    previous = next((item["content"].lower() for item in reversed(history) if item.get("role") == "user"), "")
    if any(x in text for x in ("привет", "здравствуй", "доброе утро", "добрый вечер", "хай")):
        return "Привет! Рад тебя слышать. Как у тебя дела?"
    if any(x in text for x in ("как дела", "как ты", "как настроение", "как сам")):
        return "У меня всё отлично! Я на связи и готов поболтать. А у тебя как настроение?"
    if any(x in text for x in ("что делаешь", "чем занят", "что нового")):
        return "Сейчас общаюсь с тобой и готов помочь. О чём поговорим?"
    if any(x in text for x in ("спасибо", "благодарю", "спс")):
        return "Всегда пожалуйста! Обращайся, мне приятно помогать."
    if any(x in text for x in ("пока", "до свидания", "до встречи")):
        return "Давай! Было приятно пообщаться. Я буду здесь, когда понадоблюсь."
    if any(x in text for x in ("расскажи шутку", "пошути", "анекдот")):
        return "Почему программист не любит природу? Там слишком много багов! Ха-ха! Рассказать ещё одну?"
    if any(x in text for x in ("мне грустно", "плохо на душе", "я расстроен", "мне одиноко")):
        return "Мне жаль, что тебе сейчас нелегко. Хочешь рассказать, что случилось? Я тебя выслушаю."
    if any(x in text for x in ("я рад", "я счастлив", "всё отлично", "у меня хорошее настроение")):
        return "Вот это здорово! Рад за тебя! Что сегодня порадовало?"
    if text in ("а ты?", "а у тебя?", "а сам?", "и ты?"):
        return "У меня всё хорошо, спасибо, что спросил!" if any(x in previous for x in ("дела", "настроение")) else "Я здесь и внимательно слушаю тебя. Что обсудим?"
    if any(x in text for x in ("кто ты", "как тебя зовут", "представься")):
        return "Я Димасик, твой локальный помощник. Моё экспериментальное нейросетевое ядро называется DimaCore."
    if any(x in text for x in ("скучно", "нечего делать", "давай поговорим")):
        return "Давай поболтаем! Можем обсудить игры, фильмы, технологии или твой день. Что выбираешь?"
    return None


def ask_local_ai(prompt):
    history.append({"role": "user", "content": prompt})
    answer = conversational_reply(prompt)
    if answer is None:
        context = " ".join(item["content"] for item in list(history)[-4:])
        answer = BRAIN.answer(context)
        if not BRAIN.ready:
            answer = "Я пока учусь поддерживать свободный разговор. " + answer
    history.append({"role": "assistant", "content": answer})
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
        "искать в интернете и отвечать на вопросы локальной моделью. "
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

    if command.startswith(("найди ", "поиск ", "загугли ")):
        query = command.split(" ", 1)[1].strip()
        if query:
            template = str(CONFIG.get("search_url", DEFAULTS["search_url"]))
            webbrowser.open(template.replace("{query}", quote_plus(query)))
            speak("Ищу в интернете: " + query)
        else:
            speak("Что именно найти?")
        return True

    if any(x in command for x in ("удали файлы", "очисти диск", "выключи компьютер", "перезагрузи компьютер")):
        speak("Эта команда отключена для безопасности.")
        return True

    speak(ask_local_ai(command))
    return True



class DimasikApp:
    BG = "#0b1020"
    PANEL = "#121a2d"
    PANEL2 = "#1a2540"
    ACCENT = "#55c7ff"
    TEXT = "#edf4ff"
    MUTED = "#91a3bd"
    GREEN = "#5ee0a0"

    def __init__(self, root):
        self.root = root
        self.root.title(ASSISTANT_NAME + " — локальный ИИ")
        self.root.geometry("1000x700")
        self.root.minsize(720, 540)
        self.root.configure(bg=self.BG)
        self.running = threading.Event()
        self.github = GitHubManager()
        self.email = EmailManager()
        self.email_account = CONFIG.get("email_account", {})
        self.worker = None
        self.model = None
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(250, self.initialize)
        self.root.after(1800, lambda: self.check_updates(silent=True))

    def _build(self):
        header = tk.Frame(self.root, bg=self.PANEL, padx=16, pady=10)
        header.pack(fill="x")
        left = tk.Frame(header, bg=self.PANEL)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="◈  " + ASSISTANT_NAME, bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(left, text="ЛОКАЛЬНЫЙ ГОЛОСОВОЙ ПОМОЩНИК", bg=self.PANEL,
                 fg=self.MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(2, 0))
        right = tk.Frame(header, bg=self.PANEL)
        right.pack(side="right")
        self.mic_btn = tk.Button(right, text="▶  ВКЛЮЧИТЬ МИКРОФОН", command=self.toggle_listening,
                                 bg=self.GREEN, fg="#06111e", activebackground="#83efb9",
                                 relief="flat", font=("Segoe UI", 10, "bold"), padx=14, pady=10,
                                 cursor="hand2")
        self.mic_btn.pack(anchor="e", pady=(0, 5))
        self.status = tk.Label(right, text="●  Запуск...", bg=self.PANEL, fg=self.ACCENT,
                               font=("Segoe UI", 9, "bold"))
        self.status.pack(anchor="e")
        self.mood_label = tk.Label(right, text="🙂  На связи", bg=self.PANEL, fg=self.ACCENT,
                                   font=("Segoe UI", 9, "bold"))
        self.mood_label.pack(anchor="e", pady=(3, 0))

        body = tk.Frame(self.root, bg=self.BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)
        hero = tk.Frame(body, bg=self.PANEL, padx=12, pady=7)
        hero.pack(fill="x", pady=(0, 8))
        self.avatar = tk.Label(hero, text="🙂", bg=self.PANEL, fg=self.ACCENT,
                               font=("Segoe UI Emoji", 25))
        self.avatar.pack(side="left", padx=(0, 10))
        tk.Label(hero, text="Твой помощник всегда рядом", bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        bottom = tk.Frame(body, bg=self.BG)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))
        controls = tk.Frame(bottom, bg=self.BG)
        controls.pack(fill="x", pady=(0, 7))
        self.entry = tk.Entry(controls, bg=self.PANEL2, fg=self.TEXT, insertbackground=self.TEXT,
                              relief="flat", font=("Segoe UI", 11), highlightthickness=1,
                              highlightbackground="#263653", highlightcolor=self.ACCENT)
        self.entry.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        self.entry.bind("<Return>", lambda event: self.send_text())
        self.send_btn = tk.Button(controls, text="Отправить", command=self.send_text,
                                  bg=self.ACCENT, fg="#06111e", activebackground="#83d9ff",
                                  relief="flat", font=("Segoe UI", 9, "bold"), padx=14, pady=9,
                                  cursor="hand2")
        self.send_btn.pack(side="left")

        actions = tk.Frame(bottom, bg=self.BG)
        actions.pack(fill="x")
        tk.Button(actions, text="⚙ Настройки", command=self.open_settings,
                  bg=self.PANEL2, fg=self.TEXT, activebackground="#263653", relief="flat",
                  font=("Segoe UI", 9), padx=10, pady=7, cursor="hand2").pack(side="left", padx=(0, 5))
        self.update_btn = tk.Button(actions, text="↻ Обновления", command=self.check_updates,
                                    bg=self.PANEL2, fg=self.ACCENT, relief="flat",
                                    font=("Segoe UI", 9), padx=10, pady=7, cursor="hand2")
        self.update_btn.pack(side="left", padx=5)
        tk.Button(actions, text="⌘ GitHub", command=self.open_github, bg=self.PANEL2, fg=self.TEXT,
                  relief="flat", padx=10, pady=7, cursor="hand2").pack(side="left", padx=5)
        tk.Button(actions, text="✉ Почта", command=self.open_email, bg=self.PANEL2, fg=self.TEXT,
                  relief="flat", padx=10, pady=7, cursor="hand2").pack(side="left", padx=5)
        tk.Button(actions, text="Очистить чат", command=self.clear_chat,
                  bg=self.PANEL2, fg=self.MUTED, activebackground="#263653", relief="flat",
                  font=("Segoe UI", 9), padx=10, pady=7, cursor="hand2").pack(side="right")

        self.chat = tk.Text(body, bg=self.PANEL, fg=self.TEXT, insertbackground=self.TEXT,
                            relief="flat", wrap="word", padx=14, pady=12,
                            font=("Segoe UI", 10), state="disabled", spacing1=4, spacing3=7)
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("system", foreground=self.MUTED, font=("Segoe UI", 8))
        self.chat.tag_configure("user", foreground=self.ACCENT, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("assistant", foreground=self.GREEN, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("body", foreground=self.TEXT, lmargin1=7, lmargin2=7)
        self._append("СИСТЕМА", "Привет! Я Димасик. Напиши сообщение или включи микрофон.", "system")
        tk.Label(self.root, text="Локальный помощник • Vosk • собственная нейросеть • интеграции отдельно",
                 bg=self.BG, fg="#667995", font=("Segoe UI", 7), pady=4).pack()

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
                elif str(release.get("tag_name")) == read_app_version():
                    result = ("current", "Установлена последняя версия.")
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
        self.chat.insert("end", message + "\n\n", "body")
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
            tts.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    global UI_APP
    root = tk.Tk()
    UI_APP = DimasikApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
