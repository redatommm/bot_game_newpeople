import telebot
import os
import random
import logging
import sqlite3
import csv
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

API_TOKEN = os.getenv('TELEGRAM_TOKEN') or '7601370339:AAH_tTzX6GUwkExnxIAUJ5144DZCzUCAGQE'
bot = telebot.TeleBot(API_TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[logging.FileHandler('bot.log', encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

users = {}
tasks = [
    {'id': 1, 'name': 'Подпишись (АЧ и Новые люди)', 'reward': 10},
    {'id': 2, 'name': 'Лайк на пост/видео', 'reward': 5},
    {'id': 3, 'name': 'Комментарий к посту/видео', 'reward': 7},
    {'id': 4, 'name': 'Выложить пост', 'reward': 15},
    {'id': 5, 'name': 'Участие в акции', 'reward': 20},
    {'id': 6, 'name': 'Приведи друга', 'reward': 100},
    {'id': 7, 'name': 'Ответить на вопрос', 'reward': 8},
    {'id': 8, 'name': 'Найди агитматериал и сфоткайся', 'reward': 12},
    {'id': 9, 'name': 'Цвет настроения (сфоткаться с цветом)', 'reward': 10},
    {'id': 10, 'name': 'Повесить наболконник на 3 месяца', 'reward': 30},
    {'id': 11, 'name': 'Пройди опрос', 'reward': 10},
    {'id': 12, 'name': 'Прими участие в акции «Живое общение»', 'reward': 20},
    {'id': 13, 'name': 'Снять рилс про 100 решений от НЛ', 'reward': 25},
]
prizes = [
    {'name': 'ТГ премиум на 3 месяца', 'cost': 1290},
    {'name': 'ТГ премиум на 6 месяцев', 'cost': 1790},
    {'name': 'ТГ премиум на 12 месяцев', 'cost': 2990},
    {'name': 'Футболка НЛ (мерч)', 'cost': 800},
    {'name': 'Кепка НЛ (мерч)', 'cost': 800},
    {'name': 'Толстовка НЛ (мерч)', 'cost': 1300},
    {'name': 'Футболка с любым принтом', 'cost': 800},
    {'name': 'Кепка с любым принтом', 'cost': 800},
    {'name': 'Толстовка с любым принтом', 'cost': 1300},
    {'name': 'Подарочная карта (в процессе запуска)', 'cost': 0},
]
admin_id = 790005263 # сюда можно вписать свой user_id для поддержки
support_messages = []

# --- Глобальное состояние для админ-режима (in-memory, на сессию) ---
admin_states = {}

# --- Инициализация БД ---
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        age INTEGER,
        city TEXT,
        balance INTEGER DEFAULT 0,
        ref_code TEXT,
        invited_by TEXT,
        tasks_done TEXT,
        ref_friends TEXT,
        ref_progress TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# --- Вспомогательные функции для работы с БД ---
def get_user(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()
    if not row:
        # Новый пользователь
        c.execute('''INSERT INTO users (user_id, balance, ref_code, tasks_done, ref_friends, ref_progress)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (user_id, 0, str(user_id), '', '', ''))
        conn.commit()
        c.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
        row = c.fetchone()
    user = {
        'user_id': row[0],
        'full_name': row[1] or '',
        'age': row[2] or '',
        'city': row[3] or '',
        'balance': row[4],
        'ref_code': row[5],
        'invited_by': row[6],
        'tasks_done': set(map(int, row[7].split(','))) if row[7] else set(),
        'ref_friends': set(map(int, row[8].split(','))) if row[8] else set(),
        'ref_progress': eval(row[9]) if row[9] else {},
    }
    conn.close()
    return user

def save_user(user):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''UPDATE users SET full_name=?, age=?, city=?, balance=?, ref_code=?, invited_by=?,
                 tasks_done=?, ref_friends=?, ref_progress=? WHERE user_id=?''',
              (user['full_name'], user['age'], user['city'], user['balance'], user['ref_code'], user['invited_by'],
               ','.join(map(str, user['tasks_done'])), ','.join(map(str, user['ref_friends'])), str(user['ref_progress']), user['user_id']))
    conn.commit()
    conn.close()

def show_menu(user_id):
    # Если админ и не в режиме админ-панели — добавить кнопку
    if user_id == admin_id and not admin_states.get(user_id, False):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📋 Список заданий", callback_data="menu_tasks"),
            InlineKeyboardButton("🎁 Обменять дубли на призы", callback_data="menu_prizes"),
            InlineKeyboardButton("💰 Мой баланс дублей", callback_data="menu_balance"),
            InlineKeyboardButton("👥 Реферальная программа", callback_data="menu_ref"),
            InlineKeyboardButton("ℹ️ Про игру", callback_data="menu_about"),
            InlineKeyboardButton("📜 Правила", callback_data="menu_rules"),
            InlineKeyboardButton("🆘 Служба поддержки", callback_data="menu_support"),
            InlineKeyboardButton("👑 Админ-панель", callback_data="menu_admin")
        )
        bot.send_message(user_id, "\u2B50 Главное меню:", reply_markup=markup)
        return
    # Если админ и в режиме админ-панели
    if user_id == admin_id and admin_states.get(user_id, False):
        show_admin_menu(user_id)
        return
    # Обычный пользователь
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 Список заданий", callback_data="menu_tasks"),
        InlineKeyboardButton("🎁 Обменять дубли на призы", callback_data="menu_prizes"),
        InlineKeyboardButton("💰 Мой баланс дублей", callback_data="menu_balance"),
        InlineKeyboardButton("👥 Реферальная программа", callback_data="menu_ref"),
        InlineKeyboardButton("ℹ️ Про игру", callback_data="menu_about"),
        InlineKeyboardButton("📜 Правила", callback_data="menu_rules"),
        InlineKeyboardButton("🆘 Служба поддержки", callback_data="menu_support")
    )
    bot.send_message(user_id, "\u2B50 Главное меню:", reply_markup=markup)

def show_admin_menu(user_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "📊 Статистика", "👤 Пользователи",
        "📥 Выгрузка", "📨 Обращения",
        "⬅️ В меню игрока"
    )
    bot.send_message(user_id, "<b>👑 Админ-панель:</b>", reply_markup=markup, parse_mode='HTML')

# --- Регистрация ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user['full_name']:
        bot.send_message(user_id, "\u2705 Ты уже зарегистрирован!", parse_mode='HTML')
        show_menu(user_id)
        return
    user['balance'] += 10
    save_user(user)
    bot.send_message(
        user_id,
        "<b>👋 Привет! Я — Тренер, твой проводник в игре!</b>\n\n"
        "Добро пожаловать в увлекательное путешествие, где, выполняя задания, ты сможешь заработать <b>Дубли</b> и обменять их на реальные призы!\n\n"
        "<b>+10 дублей</b> за старт!\n\nКак тебя зовут? (ФИ)",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(message, reg_full_name)

def reg_full_name(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    user['full_name'] = message.text
    save_user(user)
    bot.send_message(user_id, "Сколько тебе лет?")
    bot.register_next_step_handler(message, reg_age)

def reg_age(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not message.text.isdigit():
        bot.send_message(user_id, "Пожалуйста, введи число.")
        bot.register_next_step_handler(message, reg_age)
        return
    user['age'] = int(message.text)
    save_user(user)
    bot.send_message(user_id, "Из какого ты города? (по прописке)")
    bot.register_next_step_handler(message, reg_city)

def reg_city(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    user['city'] = message.text
    user['balance'] += 25
    save_user(user)
    bot.send_message(
        user_id,
        "<b>Поздравляем, игрок зарегистрирован!</b>\n\n+25 дублей за регистрацию.\n\nПоехали!",
        parse_mode='HTML'
    )
    show_menu(user_id)

# --- Меню ---
@bot.message_handler(func=lambda m: m.text == "💰 Мой баланс дублей")
def show_balance(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    bot.send_message(
        user_id,
        f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0",
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: m.text == "ℹ️ Про игру")
def about_game(message):
    text = (
        "<b>О проекте</b>\n\n"
        "Выполняй задания в течение 3 месяцев, зарабатывай <b>дубли</b> и обменивай их на реальные призы!\n\n"
        "<b>Типы заданий:</b>\n• Ежедневные\n• Еженедельные\n\n"
        "<b>За что начисляются дубли:</b>\n"
        "• Выполнение заданий\n"
        "• Приведи друга\n"
        "• Ежедневный вход в игру\n\n"
        "<i>Остались вопросы? Напиши в службу поддержки!</i>"
    )
    bot.send_message(message.from_user.id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "📜 Правила")
def rules(message):
    text = (
        "<b>Правила игры и обмена дублей на призы</b>\n\n"
        "1️⃣ <b>Рассказывай всем об этой игре!</b>\n"
        "2️⃣ <b>Смотри правило №1</b>\n\n"
        "<b>Запрещено:</b> оскорбления, мат, пошлость (в т.ч. визуальная).\n\n"
        "<b>Обмен дублей на призы:</b>\n"
        "• Минимум для обмена — 400 дублей\n"
        "• Призы — смотри во вкладке <b>Обменять дубли на призы</b>\n"
        "• Можно обменять дубли на товар с маркетплейса (Озон/ВБ), если дублей не меньше стоимости товара."
    )
    bot.send_message(message.from_user.id, text, parse_mode='HTML')

# --- Задания ---
@bot.message_handler(func=lambda m: m.text == "📋 Список заданий")
def task_list(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    markup = telebot.types.InlineKeyboardMarkup()
    for task in tasks:
        done = task['id'] in user['tasks_done']
        btn_text = f"{'✅' if done else '🔲'} {task['name']} (+{task['reward']} дублей)"
        if not done:
            markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"do_task_{task['id']}"))
        else:
            markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data="done"))
    bot.send_message(user_id, "<b>Выбери задание для выполнения:</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('do_task_'))
def do_task(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    task_id = int(call.data.split('_')[-1])
    if task_id in user['tasks_done']:
        bot.answer_callback_query(call.id, "Задание уже выполнено!")
        return
    user['tasks_done'].add(task_id)
    reward = next((t['reward'] for t in tasks if t['id'] == task_id), 0)
    user['balance'] += reward
    bot.answer_callback_query(call.id, f"Задание выполнено! +{reward} дублей")
    bot.edit_message_text(f"<b>Задание выполнено!</b> +{reward} дублей", user_id, call.message.message_id, parse_mode='HTML')
    # Реферальный прогресс
    if user['invited_by']:
        inviter = get_user(int(user['invited_by']))
        inviter['ref_progress'][user_id] = inviter['ref_progress'].get(user_id, 0) + 1
        # Если друг выполнил 3 задания — начислить 100 дублей
        if inviter['ref_progress'][user_id] == 3:
            inviter['balance'] += 100
            inviter['ref_friends'].add(user_id)
            bot.send_message(inviter['ref_code'], f"🎉 Твой друг <b>{user['full_name']}</b> выполнил 3 задания! Тебе начислено <b>100 дублей</b>.", parse_mode='HTML')

# --- Рефералы ---
@bot.message_handler(func=lambda m: m.text == "👥 Реферальная программа")
def referral(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    ref_link = f"/start {user['ref_code']}"
    text = (
        "<b>Реферальная программа</b>\n\n"
        "Приведи друга и получи <b>100 дублей</b>!\n"
        f"<b>Ссылка для друга:</b> <code>{ref_link}</code>\n\n"
        "<b>ВАЖНО!</b> Дубли начисляются после того, как друг выполнит 3 задания."
    )
    bot.send_message(user_id, text, parse_mode='HTML')

@bot.message_handler(commands=['start'])
def start_with_ref(message):
    # Обработка реферального кода
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
        user_id = message.from_user.id
        user = get_user(user_id)
        if not user['invited_by'] and ref_code != str(user_id):
            user['invited_by'] = ref_code
    send_welcome(message)

# --- Обмен призов ---
@bot.message_handler(func=lambda m: m.text == "🎁 Обменять дубли на призы")
def exchange_prizes(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0\n\n"
    text += "<b>Доступные призы:</b>\n"
    for prize in prizes:
        if prize['cost'] > 0:
            text += f"• {prize['name']} — <b>{prize['cost']} дублей</b>\n"
        else:
            text += f"• {prize['name']}\n"
    text += "\nЧтобы обменять дубли на приз, напиши: <code>ПРИЗ &lt;название&gt;</code>\n"
    text += "Чтобы обменять дубли на товар с маркетплейса, напиши: <code>МАРКЕТ &lt;ссылка&gt; &lt;стоимость&gt;</code>"
    bot.send_message(user_id, text, parse_mode='HTML')

@bot.message_handler(regexp=r'^ПРИЗ (.+)')
def buy_prize(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    prize_name = message.text[5:].strip()
    prize = next((p for p in prizes if prize_name.lower() in p['name'].lower()), None)
    if not prize:
        bot.send_message(user_id, "❌ Такого приза нет.")
        return
    if user['balance'] < prize['cost']:
        bot.send_message(user_id, "❌ Недостаточно дублей!")
        return
    user['balance'] -= prize['cost']
    bot.send_message(user_id, f"🎉 Поздравляем! Ты обменял <b>{prize['cost']}</b> дублей на приз: <b>{prize['name']}</b>", parse_mode='HTML')

@bot.message_handler(regexp=r'^МАРКЕТ (.+) (\d+)')
def buy_market(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    parts = message.text.split()
    link = parts[1]
    try:
        cost = int(parts[2])
    except Exception:
        bot.send_message(user_id, "Некорректная стоимость.")
        return
    if user['balance'] < cost:
        bot.send_message(user_id, "❌ Недостаточно дублей!")
        return
    user['balance'] -= cost
    bot.send_message(user_id, f"🎉 Поздравляем! Ты обменял <b>{cost}</b> дублей на товар с маркетплейса: {link}", parse_mode='HTML')

# --- Поддержка ---
@bot.message_handler(func=lambda m: m.text == "🆘 Служба поддержки")
def support(message):
    bot.send_message(message.from_user.id, "✉️ Напиши свой вопрос, и мы обязательно ответим! Просто отправь сообщение.")
    bot.register_next_step_handler(message, save_support)

def save_support(message):
    user_id = message.from_user.id
    support_messages.append({'user_id': user_id, 'text': message.text})
    if admin_id:
        bot.send_message(admin_id, f"Вопрос от пользователя {user_id}: {message.text}")
    bot.send_message(user_id, "Спасибо! Ваш вопрос отправлен в поддержку.")

@bot.message_handler(commands=['export_users'])
def export_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users')
    rows = c.fetchall()
    conn.close()
    filename = 'users_export.csv'
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'full_name', 'age', 'city', 'balance', 'ref_code', 'invited_by', 'tasks_done', 'ref_friends', 'ref_progress'])
        for row in rows:
            writer.writerow(row)
    with open(filename, 'rb') as f:
        bot.send_document(admin_id, f, caption='Выгрузка пользователей')

# --- Обработка кнопок админ-панели ---
@bot.message_handler(func=lambda m: m.text == "📥 Выгрузка")
def admin_export_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    export_users(message)

@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
def admin_stats(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM users WHERE balance >= 400')
    rich = c.fetchone()[0]
    conn.close()
    bot.send_message(admin_id, f"Всего пользователей: <b>{total}</b>\n\nС балансом 400+ дублей: <b>{rich}</b>", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "👤 Пользователи")
def admin_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT user_id, full_name, balance FROM users LIMIT 20')
    rows = c.fetchall()
    conn.close()
    text = '<b>Первые 20 пользователей:</b>\n'
    for row in rows:
        text += f"ID: <code>{row[0]}</code> | {row[1]} | 💰 {row[2]} дублей\n"
    bot.send_message(admin_id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "📨 Обращения")
def admin_support(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    if not support_messages:
        bot.send_message(admin_id, "Нет новых обращений.")
        return
    text = '<b>Последние обращения:</b>\n'
    for msg in support_messages[-10:]:
        text += f"ID: <code>{msg['user_id']}</code> — {msg['text']}\n"
    bot.send_message(admin_id, text, parse_mode='HTML')

# --- Переключение режимов для админа ---
@bot.message_handler(func=lambda m: m.text == "👑 Админ-панель")
def to_admin_panel(message):
    if message.from_user.id != admin_id:
        return
    admin_states[admin_id] = True
    show_admin_menu(admin_id)

@bot.message_handler(func=lambda m: m.text == "⬅️ В меню игрока")
def to_user_menu(message):
    if message.from_user.id != admin_id:
        return
    admin_states[admin_id] = False
    show_menu(admin_id)

# --- Обработка инлайн-кнопок главного меню ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_'))
def handle_main_menu(call):
    user_id = call.from_user.id
    data = call.data
    if data == "menu_tasks":
        task_list(call)
    elif data == "menu_prizes":
        exchange_prizes(call)
    elif data == "menu_balance":
        show_balance(call)
    elif data == "menu_ref":
        referral(call)
    elif data == "menu_about":
        about_game(call)
    elif data == "menu_rules":
        rules(call)
    elif data == "menu_support":
        support(call)
    elif data == "menu_admin" and user_id == admin_id:
        admin_states[admin_id] = True
        show_admin_menu(admin_id)
    bot.answer_callback_query(call.id)

# --- Для совместимости: все функции, которые раньше принимали message, теперь должны принимать message или call ---
def get_message_user_id(message):
    return message.from_user.id if hasattr(message, 'from_user') else message.message.chat.id

if __name__ == "__main__":
    logger.info('Бот запущен!')
    print('Бот запущен!')
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logger.error(f'Ошибка при запуске бота: {e}')
        print(f'Ошибка при запуске бота: {e}') 