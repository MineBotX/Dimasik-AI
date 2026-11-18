import ctypes
import json
import queue
import subprocess
import time
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import pyttsx3
import requests
import sounddevice as sd
from vosk import KaldiRecognizer, Model

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
VOSK_MODEL = ROOT / "models" / "vosk-model-small-ru-0.22"
OLLAMA_URL = "http://127.0.0.1:11434"
SAMPLE_RATE = 16000
audio_queue = queue.Queue(maxsize=80)
history = deque(maxlen=16)

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


def main():
    print("====================================")
    print("       " + ASSISTANT_NAME.upper() + " — ЛОКАЛЬНЫЙ ИИ")
    print("====================================")
    print("Настройки: " + str(CONFIG_PATH))
    configure_voice()
    if not VOSK_MODEL.is_dir():
        print("Не найдена модель распознавания:", VOSK_MODEL)
        input("Нажми Enter для выхода...")
        return
    try:
        model = Model(str(VOSK_MODEL))
    except Exception as exc:
        print("Ошибка загрузки Vosk:", exc)
        input("Нажми Enter для выхода...")
        return

    if not ollama_ready():
        print("Запускаю локальный сервер Ollama...")
        try:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(15):
                if ollama_ready():
                    break
                time.sleep(1)
        except OSError:
            pass

    speak("Система готова. Скажи " + ASSISTANT_NAME + " и свою команду.")
    while True:
        try:
            phrase = listen(model, "Ожидаю ключевое слово: " + ASSISTANT_NAME)
            print("Распознано:", phrase)
            wake = next((word for word in WAKE_WORDS if word in phrase), None)
            if not wake:
                continue
            command = phrase.replace(wake, "", 1).strip(" ,.!?;:")
            if not command:
                speak("Да, слушаю.")
                command = listen(model, "Говори, я слушаю...")
            if not execute_command(command):
                break
        except KeyboardInterrupt:
            print("\nОстановка по Ctrl+C.")
            break
        except Exception as exc:
            print("Ошибка микрофона или распознавания:", exc)
            time.sleep(1)


if __name__ == "__main__":
    main()
