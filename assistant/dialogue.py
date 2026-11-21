"""Offline conversation replies for common social turns."""
from __future__ import annotations


def conversational_reply(prompt: str, history=None, *, roast_enabled=False, roast_level="medium"):
    """Return a short offline reply to common social turns, or None.

    History is an optional sequence of {"role": ..., "content": ...} entries.
    """
    text = str(prompt).strip().lower()
    items = list(history or ())
    previous = next(
        (
            str(item.get("content", "")).lower()
            for item in reversed(items)
            if item.get("role") == "user"
        ),
        "",
    )
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
        return (
            "У меня всё хорошо, спасибо, что спросил!"
            if any(x in previous for x in ("дела", "настроение"))
            else "Я здесь и внимательно слушаю тебя. Что обсудим?"
        )
    if any(x in text for x in ("кто ты", "как тебя зовут", "представься")):
        return "Я Димасик, твой локальный помощник. Моё экспериментальное нейросетевое ядро называется DimaCore."
    if any(x in text for x in ("скучно", "нечего делать", "давай поговорим")):
        return "Давай поболтаем! Можем обсудить игры, фильмы, технологии или твой день. Что выбираешь?"
    if roast_enabled:
        # Keep canned social replies consistent with the selectable banter mode.
        serious_topics = (
            "мне грустно", "плохо на душе", "я расстроен", "мне одиноко",
            "мне страшно", "умер", "потерял близкого", "депресс",
        )
        if not any(term in text for term in serious_topics):
            roast_lines = {
                "light": "Ну ты и затейник 😄",
                "medium": "Ну ты и кадр, чёрт побери 😄",
                "strong": "Ну ты и ходячий пиздец, конечно 😄",
            }
            answer += " " + roast_lines.get(str(roast_level).lower(), roast_lines["medium"])
    return answer
