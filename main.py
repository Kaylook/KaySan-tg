import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = "8537061583:AAGgn9wqkMsdv5mKfVPEiisI530_eXSa288"
DB_FILE = "users.db"
PAYMENT_PHONE = "+79151220413"
TARIFF_PRICE = 150
ADMIN_ID = 5304263604  # 🔴 ЗАМЕНИТЕ на цифровой ID аккаунта @Kaylushik
PROMO_CODE = "DU198GAS2G245SAS"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ---------- БАЗА ДАННЫХ ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            reg_date TEXT,
            subscription_start TEXT,
            subscription_end TEXT,
            status TEXT DEFAULT 'registered',
            last_notified TEXT,
            xray_key TEXT,
            wg_key TEXT
        )
    """)

    existing_cols = [col[1] for col in cur.execute("PRAGMA table_info(users)").fetchall()]
    for col, default in [('status', "'registered'"), ('subscription_start', "NULL"),
                         ('subscription_end', "NULL"), ('last_notified', "NULL"),
                         ('xray_key', "NULL"), ('wg_key', "NULL"), ('username', "NULL")]:
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {default}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            payment_date TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (ADMIN_ID,))
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users (user_id, username, reg_date, subscription_start, subscription_end, status, xray_key, wg_key)
            VALUES (?, 'Admin', ?, '2026-03-14', '2099-12-31', 'active', 'ADMIN', 'ADMIN')
        """, (ADMIN_ID, datetime.now().strftime("%Y-%m-%d")))
    else:
        cur.execute("""
            UPDATE users SET status='active', subscription_start='2026-03-14', subscription_end='2099-12-31', 
            xray_key='ADMIN', wg_key='ADMIN' WHERE user_id = ?
        """, (ADMIN_ID,))

    conn.commit()
    conn.close()
    logging.info("База данных инициализирована")


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- КЛАВИАТУРЫ ----------
def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Активировать подписку", callback_data="activate_subscription")
    builder.button(text="🎁 Применить промокод", callback_data="show_promo_hint")
    return builder.as_markup()


def get_active_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Мои ключи", callback_data="show_keys")
    if user_id == ADMIN_ID:
        builder.button(text="⚙️ Админ-панель", callback_data="show_admin_panel")
    else:
        builder.button(text="❌ Отменить подписку", callback_data="cancel_subscription")
    return builder.as_markup()


def get_admin_panel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Список клиентов", callback_data="show_clients_list")
    return builder.as_markup()


def get_payment_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оплатил", callback_data="payment_done")
    return builder.as_markup()


def get_admin_payment_keyboard(user_id, payment_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"admin_confirm_{user_id}_{payment_id}")
    builder.button(text="❌ Отказ", callback_data=f"admin_decline_{user_id}_{payment_id}")
    return builder.as_markup()


def get_retry_payment_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Попробовать снова", callback_data="activate_subscription")
    return builder.as_markup()


# ---------- БОТ ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
admin_states = {}


# ---------- КОМАНДЫ ----------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Не указан"

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (user_id, username, reg_date, status) VALUES (?, ?, ?, 'registered')",
                (user_id, username, datetime.now().strftime("%Y-%m-%d"))
            )
            conn.commit()
        await show_personal_cabinet(message)
    finally:
        conn.close()


@dp.message(Command("cabinet"))
async def cmd_cabinet(message: Message):
    await show_personal_cabinet(message)


async def show_personal_cabinet(message: Message):
    user_id = message.from_user.id
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
        if not user: return

        status_text = {
            'registered': 'Не начата',
            'pending_payment': 'Ожидает оплаты',
            'awaiting_confirmation': 'Проверка оплаты',
            'active': 'Активна',
            'cancelled': 'Отменена'
        }.get(user['status'], 'Неизвестно')

        text = f"👤 <b>Личный кабинет</b>\n\n"
        text += f"📅 Дата начала: {user['subscription_start'] or 'Не начата'}\n"
        text += f"💰 Тариф: {TARIFF_PRICE}₽/месяц\n"
        text += f"📆 Следующая оплата: {user['subscription_end'] or '—'}\n"
        text += f"🔑 Статус: {status_text}"

        if user['status'] == 'registered':
            await message.answer(text, reply_markup=get_start_keyboard(), parse_mode="HTML")
        elif user['status'] == 'active':
            await message.answer(text, reply_markup=get_active_keyboard(user_id), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=get_retry_payment_keyboard(), parse_mode="HTML")
    finally:
        conn.close()


# ---------- ПРОМОКОД ----------
@dp.message(F.text == PROMO_CODE)
async def handle_promo(message: Message):
    user_id = message.from_user.id
    if user_id in admin_states: return

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
        if not user: return

        today = datetime.now().strftime("%Y-%m-%d")
        cur.execute(
            "UPDATE users SET status = 'active', subscription_start = ?, subscription_end = '2090-01-01' WHERE user_id = ?",
            (user['subscription_start'] or today, user_id))
        conn.commit()
        await message.answer("🎉 Промокод активирован! Ваша подписка действует до 01.01.2090. Стоимость: 0₽.")
        await show_personal_cabinet(message)
    finally:
        conn.close()


# ---------- ВВОД КЛЮЧЕЙ АДМИНОМ ----------
@dp.message(~F.command)
async def handle_admin_keys(message: Message):
    if message.from_user.id != ADMIN_ID: return
    if message.from_user.id not in admin_states: return

    state = admin_states[message.from_user.id]
    user_id = state['user_id']
    if state['action'] == 'awaiting_finish': return

    conn = get_db()
    try:
        cur = conn.cursor()
        if state['action'] == 'send_xray_key':
            cur.execute("UPDATE users SET xray_key = ? WHERE user_id = ?", (message.text, user_id))
            conn.commit()
            admin_states[message.from_user.id] = {'action': 'send_wg_key', 'user_id': user_id}
            await message.answer("✅ XRay ключ сохранен. Теперь отправьте WireGuard ключ:")
        elif state['action'] == 'send_wg_key':
            cur.execute("UPDATE users SET wg_key = ? WHERE user_id = ?", (message.text, user_id))
            conn.commit()
            admin_states[message.from_user.id] = {'action': 'awaiting_finish', 'user_id': user_id}

            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Завершить выдачу", callback_data="finish_issuance")
            await message.answer("✅ WireGuard ключ сохранен.", reply_markup=builder.as_markup())
    finally:
        conn.close()


# ---------- ОБРАБОТКА КНОПОК ----------
@dp.callback_query(F.data == "show_keys")
async def cb_show_keys(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
        if not user or user['status'] != 'active':
            await callback.answer("❌ Нет активной подписки", show_alert=True)
            return

        xray = "ADMIN" if user_id == ADMIN_ID else (user['xray_key'] or "Не выдан")
        wg = "ADMIN" if user_id == ADMIN_ID else (user['wg_key'] or "Не выдан")

        text = f"🔑 <b>Ваши ключи доступа</b>\n\n"
        text += f"📱 <b>Инструкция:</b>\n"
        text += f"1. Установите приложение AmneziaVPN\n"
        text += f"2. Нажмите кнопку \"+\"\n"
        text += f"3. Вставьте нужный ключ в поле\n\n"
        text += f"🌐 <b>XRay ключ:</b>\n<code>{xray}</code>\n\n"
        text += f"🛡️ <b>WireGuard ключ:</b>\n<code>{wg}</code>"

        await callback.message.answer(text, parse_mode="HTML")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data == "show_admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    await callback.message.answer("⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
                                  reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "show_clients_list")
async def cb_clients_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, username, subscription_start, subscription_end, status, xray_key, wg_key FROM users WHERE user_id != ?",
            (ADMIN_ID,))
        users = cur.fetchall()

        if not users:
            await callback.message.answer("📋 Клиентов в базе нет.")
            await callback.answer()
            return

        text = "📋 <b>Список клиентов:</b>\n\n"
        for u in users:
            ud = dict(u)
            text += f"👤 ID: {ud['user_id']} | @{ud['username'] or 'нет'}\n"
            text += f"📅 Начало: {ud['subscription_start'] or '—'} | Конец: {ud['subscription_end'] or '—'}\n"
            text += f"🔑 Статус: {ud['status']}\n"
            text += f"🔹 XRay: {ud['xray_key'][:30] + '...' if ud['xray_key'] and len(ud['xray_key']) > 30 else ud['xray_key'] or '—'}\n"
            text += f"🔹 WG: {ud['wg_key'][:30] + '...' if ud['wg_key'] and len(ud['wg_key']) > 30 else ud['wg_key'] or '—'}\n"
            text += "─────────────────\n"

        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await callback.message.answer(chunk, parse_mode="HTML")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data == "cancel_subscription")
async def cb_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id == ADMIN_ID:
        await callback.answer("❌ Администратор не может отменить подписку", show_alert=True)
        return

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
        cur.execute("UPDATE users SET status = 'cancelled' WHERE user_id = ?", (user_id,))
        conn.commit()

        await callback.message.edit_text("❌ Подписка отменена")

        admin_text = f"🚫 <b>Подписка отменена</b>\n\n"
        admin_text += f"👤 Пользователь: {user['username']} (ID: {user_id})\n"
        admin_text += f"📅 Дата окончания: {user['subscription_end'] or 'Не установлена'}"
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data == "activate_subscription")
async def cb_activate(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET status = 'pending_payment' WHERE user_id = ?", (user_id,))
        conn.commit()

        text = f"💳 <b>Активация подписки</b>\n\n"
        text += f"💰 Стоимость: {TARIFF_PRICE}₽\n"
        text += f"📞 Оплата по номеру: <code>{PAYMENT_PHONE}</code>\n\n"
        text += f"После оплаты нажмите кнопку ниже"
        await callback.message.edit_text(text, reply_markup=get_payment_keyboard(), parse_mode="HTML")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data == "show_promo_hint")
async def cb_promo_hint(callback: CallbackQuery):
    await callback.message.answer("🎁 Отправьте промокод в чат с ботом, чтобы активировать вечную подписку бесплатно.")
    await callback.answer()


@dp.callback_query(F.data == "payment_done")
async def cb_payment_done(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET status = 'awaiting_confirmation' WHERE user_id = ?", (user_id,))
        cur.execute("INSERT INTO payments (user_id, amount, payment_date) VALUES (?, ?, ?)",
                    (user_id, TARIFF_PRICE, datetime.now().strftime("%Y-%m-%d")))
        payment_id = cur.lastrowid
        conn.commit()

        await callback.message.edit_text(
            "⏳ <b>Оплата отправлена на проверку</b>\n\nОжидайте подтверждения администратора...", parse_mode="HTML")

        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()

        admin_text = f"🔔 <b>Новая оплата!</b>\n\n"
        admin_text += f"👤 Пользователь: {user['username']} (ID: {user_id})\n"
        admin_text += f"💰 Сумма: {TARIFF_PRICE}₽\n"
        admin_text += f"📅 Дата: {datetime.now().strftime('%Y-%m-%d')}"
        await bot.send_message(ADMIN_ID, admin_text, reply_markup=get_admin_payment_keyboard(user_id, payment_id),
                               parse_mode="HTML")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data == "renewal_paid")
async def cb_renewal_paid(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET status = 'awaiting_confirmation' WHERE user_id = ?", (user_id,))
        cur.execute("INSERT INTO payments (user_id, amount, payment_date) VALUES (?, ?, ?)",
                    (user_id, TARIFF_PRICE, datetime.now().strftime("%Y-%m-%d")))
        payment_id = cur.lastrowid
        conn.commit()

        await callback.message.edit_text(
            "⏳ <b>Оплата отправлена на проверку</b>\n\nОжидайте подтверждения администратора...", parse_mode="HTML")

        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()

        admin_text = f"🔔 <b>Запрос на продление подписки!</b>\n\n"
        admin_text += f"👤 Пользователь: {user['username']} (ID: {user_id})\n"
        admin_text += f"💰 Сумма: {TARIFF_PRICE}₽\n"
        admin_text += f"📅 Дата: {datetime.now().strftime('%Y-%m-%d')}"
        await bot.send_message(ADMIN_ID, admin_text, reply_markup=get_admin_payment_keyboard(user_id, payment_id),
                               parse_mode="HTML")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data.startswith("admin_confirm_"))
async def cb_admin_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split("_")
    target_user_id, payment_id = int(parts[2]), int(parts[3])

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE payments SET status = 'confirmed' WHERE id = ? AND user_id = ?",
                    (payment_id, target_user_id))
        cur.execute("SELECT COUNT(*) FROM payments WHERE user_id = ? AND status = 'confirmed'", (target_user_id,))
        confirmed_count = cur.fetchone()[0]

        if confirmed_count == 1:
            # Первая активация
            today = datetime.now()
            end_date = today + timedelta(days=30)
            cur.execute(
                "UPDATE users SET status = 'active', subscription_start = ?, subscription_end = ? WHERE user_id = ?",
                (today.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), target_user_id))
            await callback.message.edit_text("✅ Оплата подтверждена. Теперь отправьте XRay ключ:")
            admin_states[callback.from_user.id] = {'action': 'send_xray_key', 'user_id': target_user_id}
        else:
            # Продление
            cur.execute("SELECT subscription_end FROM users WHERE user_id = ?", (target_user_id,))
            user = cur.fetchone()
            current_end = datetime.strptime(user['subscription_end'], "%Y-%m-%d")
            new_end = max(current_end, datetime.now()) + timedelta(days=30)
            cur.execute("UPDATE users SET status = 'active', subscription_end = ? WHERE user_id = ?",
                        (new_end.strftime("%Y-%m-%d"), target_user_id))
            await callback.message.edit_text(f"✅ Продление подтверждено. Новая дата: {new_end.strftime('%Y-%m-%d')}")

        conn.commit()

        cur.execute("SELECT * FROM users WHERE user_id = ?", (target_user_id,))
        user = cur.fetchone()

        if confirmed_count == 1:
            user_text = f"✅ <b>Оплата подтверждена!</b>\n\nВаша подписка активирована.\n📅 Начало: {user['subscription_start']}\n📅 Окончание: {user['subscription_end']}\n\nАдминистратор отправит вам ключи в ближайшее время."
        else:
            user_text = f"✅ <b>Продление успешно!</b>\n\nВаша подписка продлена до {user['subscription_end']}.\nКлючи не менялись, можете продолжать пользоваться VPN."

        await bot.send_message(target_user_id, user_text, parse_mode="HTML")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data.startswith("admin_decline_"))
async def cb_admin_decline(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split("_")
    target_user_id, payment_id = int(parts[2]), int(parts[3])

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE payments SET status = 'declined' WHERE id = ?", (payment_id,))
        cur.execute("SELECT COUNT(*) FROM payments WHERE user_id = ? AND status = 'confirmed'", (target_user_id,))
        if cur.fetchone()[0] == 0:
            cur.execute("UPDATE users SET status = 'pending_payment' WHERE user_id = ?", (target_user_id,))
        conn.commit()

        await bot.send_message(target_user_id,
                               "❌ <b>Оплата не подтверждена</b>\n\nПроверьте данные и попробуйте снова.",
                               reply_markup=get_retry_payment_keyboard(), parse_mode="HTML")
        await callback.message.edit_text("❌ Оплата отклонена")
        await callback.answer()
    finally:
        conn.close()


@dp.callback_query(F.data == "finish_issuance")
async def cb_finish_issuance(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    state = admin_states.get(callback.from_user.id)
    if not state or state.get('action') != 'awaiting_finish':
        await callback.answer("❌ Нет активного процесса", show_alert=True)
        return

    user_id = state['user_id']
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE payments SET status = 'completed' WHERE user_id = ? AND status = 'confirmed'", (user_id,))
        conn.commit()

        await bot.send_message(
            user_id,
            "✅ <b>Всё успешно!</b>\n\nВам выданы ключи доступа.\nПосмотреть их можно в разделе 🔑 <b>Мои ключи</b>.",
            parse_mode="HTML"
        )
        await callback.message.edit_text(f"✅ Ключи выданы пользователю {user_id}. Подписка активирована.")
        del admin_states[callback.from_user.id]

        await show_personal_cabinet(callback.message)
        await callback.answer()
    finally:
        conn.close()


# ---------- АДМИН: ПОИСК ----------
@dp.message(Command("search"))
async def cmd_search(message: Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /search user_id или username")
        return

    search_query = args[1]
    conn = get_db()
    try:
        cur = conn.cursor()
        if search_query.isdigit():
            cur.execute("SELECT * FROM users WHERE user_id = ?", (int(search_query),))
        else:
            cur.execute("SELECT * FROM users WHERE username LIKE ?", (f"%{search_query}%",))
        user = cur.fetchone()
        if not user:
            await message.answer("❌ Пользователь не найден")
            return

        cur.execute("SELECT * FROM payments WHERE user_id = ? ORDER BY payment_date DESC", (user['user_id'],))
        payments = cur.fetchall()

        user_dict = dict(user)
        text = f"👤 <b>Информация о пользователе</b>\n\n"
        text += f"ID: {user_dict['user_id']}\nUsername: {user_dict['username']}\nСтатус: {user_dict['status']}\n"
        text += f"Начало: {user_dict['subscription_start'] or '—'}\nОкончание: {user_dict['subscription_end'] or '—'}\n"
        text += f"XRay: {user_dict['xray_key'][:50] + '...' if user_dict['xray_key'] and len(user_dict['xray_key']) > 50 else user_dict['xray_key'] or 'Не выдан'}\n"
        text += f"WireGuard: {user_dict['wg_key'][:50] + '...' if user_dict['wg_key'] and len(user_dict['wg_key']) > 50 else user_dict['wg_key'] or 'Не выдан'}\n"
        if payments:
            text += f"\n💳 <b>Платежи:</b>\n" + "\n".join(
                f"- {p['payment_date']}: {p['amount']}₽ ({p['status']})" for p in payments)
        await message.answer(text, parse_mode="HTML")
    finally:
        conn.close()


# ---------- ПРОВЕРКА ПРОДЛЕНИЙ ----------
async def check_renewals():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE status = 'active' AND subscription_end = ? AND user_id != ?",
                    (today, ADMIN_ID))
        users = cur.fetchall()

        for user in users:
            if user['last_notified'] == today:
                continue

            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Оплатил", callback_data="renewal_paid")

            text = f"🔔 <b>Внимание! Подписка истекает сегодня!</b>\n\n"
            text += f"💰 Стоимость продления: {TARIFF_PRICE}₽\n"
            text += f"📞 Оплата по номеру: <code>{PAYMENT_PHONE}</code>\n"
            text += f"📅 Дата окончания: {today}\n\n"
            text += f"После оплаты нажмите кнопку ниже."

            try:
                await bot.send_message(user['user_id'], text, reply_markup=builder.as_markup(), parse_mode="HTML")
                cur.execute("UPDATE users SET last_notified = ? WHERE user_id = ?", (today, user['user_id']))
                conn.commit()
                logging.info(f"Отправлено уведомление об истечении user {user['user_id']}")
            except Exception as e:
                logging.warning(f"Ошибка отправки user {user['user_id']}: {e}")
    finally:
        conn.close()


async def scheduler_task():
    await check_renewals()  # Запуск при старте
    while True:
        await asyncio.sleep(3600)  # Проверка каждый час
        await check_renewals()


# ---------- ЗАПУСК ----------
async def on_startup():
    asyncio.create_task(scheduler_task())
    logging.info("Бот запущен. Проверка продлений активна.")


async def main():
    init_db()
    dp.startup.register(on_startup)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())