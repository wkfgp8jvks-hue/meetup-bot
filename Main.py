import logging
import os
from datetime import datetime, timedelta
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# Хранилище событий: chat_id -> { name, options: set of datetime, exclusions: {user_id: set of datetime} }
events = {}

# Словарь месяцев для парсинга
MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
}

def parse_date_time(date_str: str) -> datetime | None:
    """
    Парсит строку вида "31 января 20:00" или "1 февраля 18:30"
    Возвращает datetime или None, если не удалось.
    """
    date_str = date_str.strip().lower()
    # Регулярка: день + месяц + время
    match = re.match(r'(\d{1,2})\s+([а-яё]+)\s+(\d{1,2}):(\d{2})', date_str)
    if not match:
        return None

    day = int(match.group(1))
    month_word = match.group(2)
    hour = int(match.group(3))
    minute = int(match.group(4))

    if month_word not in MONTHS:
        return None

    month = MONTHS[month_word]
    year = datetime.now().year

    try:
        dt = datetime(year, month, day, hour, minute)
        # Если дата уже прошла в этом году — попробуем следующий год
        if dt < datetime.now() - timedelta(minutes=10):
            dt = datetime(year + 1, month, day, hour, minute)
        return dt
    except ValueError:
        return None

def format_datetime(dt: datetime) -> str:
    """Форматирует datetime как '31 января 20:00'"""
    month_name = list(MONTHS.keys())[dt.month - 1]
    return f"{dt.day} {month_name} {dt.hour:02d}:{dt.minute:02d}"

async def event_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args or " | " not in " ".join(context.args):
        await update.message.reply_text(
            "Используй: /event Название | 31 января 20:00, 1 февраля 18:00\n"
            "Поддерживаются только русские названия месяцев."
        )
        return

    input_str = " ".join(context.args)
    name, times_str = input_str.split(" | ", 1)
    raw_options = [t.strip() for t in times_str.split(",") if t.strip()]

    valid_datetimes = set()
    invalid_examples = []

    for raw in raw_options:
        dt = parse_date_time(raw)
        if dt:
            valid_datetimes.add(dt)
        else:
            invalid_examples.append(raw)

    if not valid_datetimes:
        await update.message.reply_text("Не удалось распознать ни одну дату. Проверьте формат.")
        return

    events[chat_id] = {
        "name": name,
        "options": valid_datetimes,
        "exclusions": {}
    }

    opts_list = "\n".join(f"- {format_datetime(dt)}" for dt in sorted(valid_datetimes))
    warning = ""
    if invalid_examples:
        warning = "\n\n⚠️ Не распознано: " + ", ".join(invalid_examples)

    await update.message.reply_text(
        f"Событие «{name}» создано!\n"
        f"Чтобы исключить время, напиши:\n"
        f"`/exclude 31 января 20:00`\n\n"
        f"Доступные варианты:\n{opts_list}{warning}",
        parse_mode="Markdown"
    )

async def exclude_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in events:
        await update.message.reply_text("Сначала создайте событие через /event")
        return
    if not context.args:
        await update.message.reply_text("Пример: /exclude 31 января 20:00")
        return
    raw_time = " ".join(context.args)
    dt = parse_date_time(raw_time)
    if not dt:
        await update.message.reply_text("Не удалось распознать дату. Используйте формат: 31 января 20:00")
        return

    event = events[chat_id]
    if dt in event["options"]:
        user_id = update.effective_user.id
        event["exclusions"].setdefault(user_id, set()).add(dt)
        await update.message.reply_text(f"Вы исключили: {format_datetime(dt)}")
    else:
        # Может, пользователь хочет исключить то, чего нет? Предложим добавить.
        await update.message.reply_text(
            f"Такого варианта нет.\n"
            f"Хотите предложить его? Напишите: `/add {raw_time}`",
            parse_mode="Markdown"
        )

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in events:
        await update.message.reply_text("Сначала создайте событие через /event")
        return
    if not context.args:
        await update.message.reply_text("Пример: /add 2 февраля 19:00")
        return
    raw_time = " ".join(context.args)
    dt = parse_date_time(raw_time)
    if not dt:
        await update.message.reply_text("Не удалось распознать дату. Формат: 1 февраля 18:00")
        return

    event = events[chat_id]
    event["options"].add(dt)
    await update.message.reply_text(f"Добавлено: {format_datetime(dt)}")

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in events:
        await update.message.reply_text("Нет активного события.")
        return

    event = events[chat_id]
    available = event["options"].copy()
    for excl_set in event["exclusions"].values():
        available -= excl_set

    if available:
        sorted_available = sorted(available)
        res = "\n".join(f"✅ {format_datetime(dt)}" for dt in sorted_available)
        await update.message.reply_text(f"Все могут в:\n\n{res}")
    else:
        await update.message.reply_text("❌ Общего времени нет.")
    del events[chat_id]

def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        raise ValueError("TELEGRAM_TOKEN не задан!")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("event", event_cmd))
    app.add_handler(CommandHandler("exclude", exclude_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
