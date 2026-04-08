import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

# Загрузка переменных из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = "users.db"
REG_CODE = "OPKS912"
PAYMENT_PHONE = "+79151220413"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ---------- БАЗА ДАННЫХ ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            reg_date TEXT NOT NULL,
            last_notified TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- БОТ ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(f"👋 Привет! Отправьте код `{REG_CODE}` для активации ежемесячных напоминаний об оплате.")


@dp.message()
async def handle_registration(message: Message):
    if message.text.strip() != REG_CODE:
        return

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = ?", (message.from_user.id,))
        if cur.fetchone():
            await message.answer("✅ Вы уже активировали подписку. Напоминания приходят каждый месяц.")
            return

        today = datetime.now().strftime("%Y-%m-%d")
        cur.execute("INSERT INTO users (user_id, reg_date) VALUES (?, ?)", (message.from_user.id, today))
        conn.commit()
        await message.answer(
            "✅ Код принят! Подписка активирована.\n🔔 Напоминания об оплате будут приходить каждый месяц в эту дату.")
        logging.info(f"Новый пользователь: {message.from_user.id}")
    finally:
        conn.close()


# ---------- ФОНОВАЯ РАССЫЛКА ----------
async def check_and_send_reminders():
    """Проверяет пользователей и отправляет уведомления, если сегодня день оплаты"""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    current_day = now.day
    current_month = now.month

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id, reg_date, last_notified FROM users")
        users = cur.fetchall()

        for user in users:
            reg_date = datetime.strptime(user["reg_date"], "%Y-%m-%d")

            # Пропускаем, если ещё не наступил день регистрации в этом месяце
            if current_day != reg_date.day:
                continue

            # Проверяем, отправляли ли уже в этом месяце
            last_not = user["last_notified"]
            if last_not and datetime.strptime(last_not, "%Y-%m-%d").month == current_month:
                continue

            # Отправка
            try:
                await bot.send_message(
                    user["user_id"],
                    f"🔔 *Напоминание об оплате*\n\n"
                    f"Пора продлить подписку. Оплата по номеру:\n"
                    f"📞 `{PAYMENT_PHONE}`\n\n"
                    f"Спасибо, что пользуетесь нашим сервисом!"
                )
                cur.execute("UPDATE users SET last_notified = ? WHERE user_id = ?", (today_str, user["user_id"]))
                conn.commit()
                logging.info(f"Отправлено напоминание пользователю {user['user_id']}")
            except Exception as e:
                logging.warning(f"Не удалось отправить пользователю {user['user_id']}: {e}")
    finally:
        conn.close()


async def scheduler_task():
    """Запускается при старте бота. Проверяет рассылку раз в минуту в 10:00"""
    while True:
        now = datetime.now()
        if now.hour == 10 and now.minute == 0:  # Время проверки (можно изменить)
            await check_and_send_reminders()
        await asyncio.sleep(60)


# ---------- ЗАПУСК ----------
async def on_startup():
    asyncio.create_task(scheduler_task())
    logging.info("Бот запущен. Фоновая проверка активирована.")


async def main():
    init_db()
    dp.startup.register(on_startup)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())