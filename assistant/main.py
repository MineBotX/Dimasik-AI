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
VOSK_MODEL = ROOT / "models" / "vosk-model-small-ru-0.22"
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:3b"
SAMPLE_RATE = 16000
WAKE_WORDS = ("димасик", "димас", "димон")
audio_queue = queue.Queue(maxsize=80)
history = deque(maxlen=12)

tts = pyttsx3.init()
tts.setProperty("rate", 172)
tts.setProperty("volume", 1.0)


def flush_audio():
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def configure_voice():
    try:
        voices = tts.getProperty("voices") or []
        russian = []
        for voice in voices:
            info = (str(voice.id) + " " + str(voice.name)).lower()
            if any(tag in info for tag in ("ru", "russian", "рус")):
                russian.append(voice)
        if russian:
            # На Windows имена голосов часто содержат имя и язык.
            # Пол мужского голоса не всегда доступен через pyttsx3.
            selected = next(
                (v for v in russian if any(tag in (v.name or "").lower()
                 for tag in ("dmitry", "pavel", "андрей", "александр", "дмитрий"))),
                russian[0],
            )
            tts.setProperty("voice", selected.id)
            print("Выбран голос:", selected.name)
        else:
            print("Русский голос Windows не найден. Установи русский голос в настройках речи Windows.")
    except Exception as exc:
        print("Не удалось выбрать голос:", exc)


def speak(message):
    message = str(message).strip()
    if not message:
        return
    print("\nДимасик: " + message)
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


def listen(model, prompt="Слушаю..."):
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    print("\n" + prompt)
    flush_audio()
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=4000,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        while True:
            data = audio_queue.get()
            if recognizer.AcceptWaveform(data):
                phrase = json.loads(recognizer.Result()).get("text", "").strip().lower()
                if phrase:
                    return phrase


def ollama_ready():
    try:
        r = requests.get(OLLAMA_URL + "/api/tags", timeout=3)
        return r.ok
    except requests.RequestException:
        return False


def ask_local_ai(prompt):
    history.append({"role": "user", "content": prompt})
    conversation = "\n".join(
        ("Пользователь: " if item["role"] == "user" else "Димасик: ") + item["content"]
        for item in history
    )
    full_prompt = (
        "Ты Димасик — умный, дружелюбный русскоязычный помощник для Windows. "
        "Отвечай естественно, по-русски и обычно кратко. Учитывай историю диалога. "
        "Не говори, что выполнил действие на компьютере, если программа его не выполнила. "
        "Если не знаешь ответа, честно скажи об этом.\n\n" + conversation + "\nДимасик:"
    )
    try:
        response = requests.post(
            OLLAMA_URL + "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.65, "num_ctx": 4096},
            },
            timeout=(5, 180),
        )
        response.raise_for_status()
        answer = response.json().get("response", "").strip()
        if answer:
            history.append({"role": "assistant", "content": answer})
            return answer
        return "Модель вернула пустой ответ."
    except requests.Timeout:
        return "Я задумался слишком надолго. Попробуй задать вопрос покороче."
    except requests.RequestException:
        return "Не могу подключиться к локальной Ollama. Проверь, запущена ли она."


def open_app(command, exe, spoken_name):
    try:
        subprocess.Popen([exe])
        speak("Открываю " + spoken_name + ".")
    except OSError:
        speak("Не получилось открыть " + spoken_name + ".")


def execute_command(command):
    command = command.strip().lower()
    if not command:
        speak("Я не расслышал команду.")
        return True

    if command in ("стоп", "выход", "завершить работу", "пока, димасик"):
        speak("Хорошо. До встречи.")
        return False

    if any(x in command for x in ("который час", "сколько времени", "время")):
        speak("Сейчас " + datetime.now().strftime("%H:%M"))
    elif any(x in command for x in ("какое сегодня число", "какая дата", "дата", "число")):
        speak("Сегодня " + datetime.now().strftime("%d.%m.%Y"))
    elif "блокнот" in command:
        open_app(command, "notepad.exe", "блокнот")
    elif "калькулятор" in command or "посчитай" == command[:8]:
        open_app(command, "calc.exe", "калькулятор")
    elif "проводник" in command or "открой файлы" in command:
        open_app(command, "explorer.exe", "проводник")
    elif "paint" in command or "паинт" in command:
        open_app(command, "mspaint.exe", "Paint")
    elif "диспетчер задач" in command:
        open_app(command, "taskmgr.exe", "диспетчер задач")
    elif "браузер" in command or "интернет" == command:
        webbrowser.open("https://www.google.com")
        speak("Открываю браузер.")
    elif command.startswith(("найди ", "поиск ", "загугли ")):
        query = command.split(" ", 1)[1].strip()
        if query:
            webbrowser.open("https://www.google.com/search?q=" + quote_plus(query))
            speak("Ищу в интернете: " + query)
        else:
            speak("Что именно найти?")
    elif "очисти историю" in command or "удали файлы" in command or "выключи компьютер" in command:
        speak("Я не выполняю такие действия голосом без отдельного безопасного подтверждения.")
    else:
        speak(ask_local_ai(command))
    return True


def main():
    print("====================================")
    print("       ДИМАСИК — ЛОКАЛЬНЫЙ ИИ")
    print("====================================")
    configure_voice()

    if not VOSK_MODEL.is_dir():
        print("Не найдена модель распознавания:", VOSK_MODEL)
        input("Нажми Enter для выхода...")
        return

    try:
        model = Model(str(VOSK_MODEL))
    except Exception as exc:
        print("Не удалось загрузить Vosk:", exc)
        input("Нажми Enter для выхода...")
        return

    if not ollama_ready():
        print("Ollama не отвечает. Пробую запустить её...")
        try:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(15):
                if ollama_ready():
                    break
                time.sleep(1)
        except OSError:
            pass

    if not ollama_ready():
        print("Внимание: локальная ИИ-модель пока недоступна. Команды Windows всё равно работают.")

    speak("Система запущена. Скажи Димасик, а затем свою команду.")
    while True:
        try:
            phrase = listen(model, "Ожидаю ключевое слово: Димасик...")
            print("Распознано:", phrase)
            wake = next((word for word in WAKE_WORDS if word in phrase), None)
            if not wake:
                continue

            command = phrase.replace(wake, "", 1).strip(" ,.!?;:")
            if not command:
                speak("Да, слушаю.")
                command = listen(model, "Говори, я слушаю...")
                print("Команда:", command)

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
