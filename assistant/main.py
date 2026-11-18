import json
import queue
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import pyttsx3
import requests
import sounddevice as sd
from vosk import KaldiRecognizer, Model

ROOT = Path(__file__).resolve().parents[1]
VOSK_MODEL = ROOT / "models" / "vosk-model-small-ru-0.22"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"
SAMPLE_RATE = 16000
WAKE_WORDS = ("димасик", "димас", "димон")
audio_queue = queue.Queue()

tts = pyttsx3.init()
tts.setProperty("rate", 175)
tts.setProperty("volume", 1.0)


def configure_voice():
    voices = tts.getProperty("voices")
    # Выбираем русский голос, если он установлен в Windows.
    for voice in voices:
        info = (str(voice.id) + " " + str(voice.name)).lower()
        if "ru" in info or "russian" in info or "рус" in info:
            tts.setProperty("voice", voice.id)
            print("Голос:", voice.name)
            return


def speak(message):
    print("\\nДимасик:", message)
    try:
        tts.say(message)
        tts.runAndWait()
    except Exception as exc:
        print("Не удалось озвучить ответ:", exc)


def audio_callback(indata, frames, callback_time, status):
    audio_queue.put(bytes(indata))


def listen(model):
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    print("\\nСлушаю. Обратись ко мне: «Димасик»...")
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=8000,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        while True:
            data = audio_queue.get()
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                phrase = result.get("text", "").strip().lower()
                if phrase:
                    return phrase


def ask_local_ai(prompt):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": (
                    "Ты Димасик — дружелюбный русскоязычный голосовой помощник. "
                    "Отвечай по-русски, естественно и кратко. "
                    "Не утверждай, что выполнил действие, если ты его не выполнял.\\n\\n"
                    "Пользователь: " + prompt
                ),
                "stream": False,
                "options": {"temperature": 0.6},
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except requests.RequestException:
        return "Не могу связаться с локальной моделью. Проверь, запущена ли Ollama."


def execute_command(command):
    command = command.strip().lower()

    if any(word in command for word in ("стоп", "выход", "завершить работу")):
        speak("Хорошо. До встречи.")
        return False

    if "время" in command:
        speak("Сейчас " + datetime.now().strftime("%H:%M"))
    elif "дата" in command or "число" in command:
        speak("Сегодня " + datetime.now().strftime("%d.%m.%Y"))
    elif "блокнот" in command:
        subprocess.Popen(["notepad.exe"])
        speak("Открываю блокнот.")
    elif "калькулятор" in command:
        subprocess.Popen(["calc.exe"])
        speak("Открываю калькулятор.")
    elif "проводник" in command:
        subprocess.Popen(["explorer.exe"])
        speak("Открываю проводник.")
    elif "paint" in command or "паинт" in command:
        subprocess.Popen(["mspaint.exe"])
        speak("Открываю Paint.")
    elif command.startswith("найди ") or command.startswith("поиск "):
        query = command.split(" ", 1)[1]
        webbrowser.open("https://www.google.com/search?q=" + quote_plus(query))
        speak("Открываю поиск в браузере.")
    else:
        answer = ask_local_ai(command)
        speak(answer or "Пока не знаю, что ответить." )

    return True


def main():
    configure_voice()
    if not VOSK_MODEL.exists():
        print("Не найдена модель Vosk:", VOSK_MODEL)
        input("Нажми Enter для выхода...")
        return

    try:
        model = Model(str(VOSK_MODEL))
    except Exception as exc:
        print("Ошибка загрузки Vosk:", exc)
        input("Нажми Enter для выхода...")
        return

    speak("Димасик запущен. Я слушаю.")
    while True:
        try:
            phrase = listen(model)
            print("Распознано:", phrase)
            wake = next((word for word in WAKE_WORDS if word in phrase), None)
            if not wake:
                continue

            command = phrase.replace(wake, "", 1).strip(" ,.!?")
            if not command:
                speak("Да, слушаю.")
                command = listen(model)
                print("Команда:", command)

            if not execute_command(command):
                break
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print("Ошибка:", exc)
            time.sleep(1)


if __name__ == "__main__":
    main()
