import ctypes
import json
import queue
import subprocess
import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import pyttsx3
import requests
import sounddevice as sd
from vosk import KaldiRecognizer, Model

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
VOSK_MODEL = ROOT / "models" / "vosk-model-small-ru-0.22"
OLLAMA_URL = "http://127.0.0.1:11434"
SAMPLE_RATE = 16000
audio_queue = queue.Queue(maxsize=80)
history = deque(maxlen=16)
UI_APP = None

DEFAULTS = {
    "assistant_name": "Димасик",
    "wake_words": ["димасик", "димас", "димон"],
    "ollama_model": "qwen2.5:3b",
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
OLLAMA_MODEL = str(CONFIG.get("ollama_model", "qwen2.5:3b"))
WAKE_WORDS = tuple(CONFIG["wake_words"])
tts = pyttsx3.init()
tts.setProperty("rate", max(100, min(250, int(CONFIG.get("voice_rate", 172)))))
tts.setProperty("volume", max(0.0, min(1.0, float(CONFIG.get("voice_volume", 1.0)))))


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


def ollama_ready():
    try:
        return requests.get(OLLAMA_URL + "/api/tags", timeout=3).ok
    except requests.RequestException:
        return False


def ask_local_ai(prompt):
    history.append({"role": "user", "content": prompt})
    transcript = "\n".join(
        ("Пользователь: " if x["role"] == "user" else ASSISTANT_NAME + ": ") + x["content"]
        for x in history
    )
    system = (
        "Ты " + ASSISTANT_NAME + ", локальный русскоязычный помощник Windows. "
        + str(CONFIG.get("personality", DEFAULTS["personality"]))
        + " Учитывай историю разговора. Не выдумывай выполненные действия. "
        "Если не знаешь — честно скажи.\n\n"
    )
    try:
        r = requests.post(OLLAMA_URL + "/api/generate", json={
            "model": OLLAMA_MODEL,
            "prompt": system + transcript + "\n" + ASSISTANT_NAME + ":",
            "stream": False,
            "options": {"temperature": 0.7, "num_ctx": 4096}
        }, timeout=(5, 180))
        r.raise_for_status()
        answer = r.json().get("response", "").strip()
        if answer:
            history.append({"role": "assistant", "content": answer})
            return answer
        return "Модель не прислала ответ."
    except requests.Timeout:
        return "Ответ занимает слишком много времени. Попробуй спросить короче."
    except requests.RequestException:
        return "Локальная модель недоступна. Проверь, запущена ли Ollama."


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
        self.root.geometry("920x680")
        self.root.minsize(720, 540)
        self.root.configure(bg=self.BG)
        self.running = threading.Event()
        self.worker = None
        self.model = None
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(250, self.initialize)

    def _build(self):
        header = tk.Frame(self.root, bg=self.PANEL, padx=22, pady=18)
        header.pack(fill="x")
        left = tk.Frame(header, bg=self.PANEL)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="◈  " + ASSISTANT_NAME, bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(left, text="ЛОКАЛЬНЫЙ ГОЛОСОВОЙ ПОМОЩНИК", bg=self.PANEL,
                 fg=self.MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(3, 0))
        self.status = tk.Label(header, text="●  Запуск...", bg=self.PANEL, fg=self.ACCENT,
                               font=("Segoe UI", 10, "bold"))
        self.status.pack(side="right", padx=(8, 0))
        body = tk.Frame(self.root, bg=self.BG, padx=20, pady=16)
        body.pack(fill="both", expand=True)
        self.chat = tk.Text(body, bg=self.PANEL, fg=self.TEXT, insertbackground=self.TEXT,
                            relief="flat", wrap="word", padx=18, pady=16,
                            font=("Segoe UI", 11), state="disabled", spacing1=5, spacing3=9)
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("system", foreground=self.MUTED, font=("Segoe UI", 9))
        self.chat.tag_configure("user", foreground=self.ACCENT, font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("assistant", foreground=self.GREEN, font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("body", foreground=self.TEXT, lmargin1=8, lmargin2=8)
        self._append("СИСТЕМА", "Привет! Я Димасик. Напиши сообщение или включи микрофон.", "system")
        controls = tk.Frame(body, bg=self.BG)
        controls.pack(fill="x", pady=(12, 0))
        self.entry = tk.Entry(controls, bg=self.PANEL2, fg=self.TEXT, insertbackground=self.TEXT,
                              relief="flat", font=("Segoe UI", 12), highlightthickness=1,
                              highlightbackground="#263653", highlightcolor=self.ACCENT)
        self.entry.pack(side="left", fill="x", expand=True, ipady=12, padx=(0, 8))
        self.entry.bind("<Return>", lambda event: self.send_text())
        self.send_btn = tk.Button(controls, text="Отправить", command=self.send_text,
                                  bg=self.ACCENT, fg="#06111e", activebackground="#83d9ff",
                                  relief="flat", font=("Segoe UI", 10, "bold"), padx=16, pady=10,
                                  cursor="hand2")
        self.send_btn.pack(side="left")
        bottom = tk.Frame(body, bg=self.BG)
        bottom.pack(fill="x", pady=(12, 0))
        self.mic_btn = tk.Button(bottom, text="▶  Включить микрофон", command=self.toggle_listening,
                                 bg=self.PANEL2, fg=self.TEXT, activebackground="#263653",
                                 relief="flat", font=("Segoe UI", 10, "bold"), padx=14, pady=10,
                                 cursor="hand2")
        self.mic_btn.pack(side="left")
        tk.Button(bottom, text="⚙  Настройки", command=self.open_settings,
                  bg=self.PANEL2, fg=self.TEXT, activebackground="#263653", relief="flat",
                  font=("Segoe UI", 10), padx=14, pady=10, cursor="hand2").pack(side="left", padx=8)
        tk.Button(bottom, text="Очистить чат", command=self.clear_chat,
                  bg=self.PANEL2, fg=self.MUTED, activebackground="#263653", relief="flat",
                  font=("Segoe UI", 10), padx=14, pady=10, cursor="hand2").pack(side="right")
        tk.Label(self.root, text="Работает локально • Vosk + Ollama • Настройки хранятся на этом компьютере",
                 bg=self.BG, fg="#667995", font=("Segoe UI", 8), pady=8).pack()

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
        if ollama_ready():
            self.set_status("Готов к работе", self.GREEN)
            self._append("СИСТЕМА", "Готов к работе. Нажми «Включить микрофон» или напиши сообщение.", "system")
        else:
            self.set_status("Голос готов • Ollama не найдена", "#f4c76b")
            self._append("СИСТЕМА", "Распознавание речи готово, но Ollama пока недоступна. Установи Ollama и модель qwen2.5:3b, чтобы получать ответы ИИ.", "system")

    def send_text(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append("ТЫ", text, "user")
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
        self.running.set()
        self.mic_btn.configure(text="■  Выключить микрофон")
        self.set_status("Слушаю ключевое слово «" + ASSISTANT_NAME + "»")
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
                self.set_status("Ошибка микрофона", "#ff7777")
                self.root.after(0, lambda e=str(exc): self._append("ОШИБКА", e, "system"))
                time.sleep(1)
        self.root.after(0, lambda: self.mic_btn.configure(text="▶  Включить микрофон"))

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
