import telebot
import os
import random
import logging
import sqlite3
import csv
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import threading
from datetime import datetime
import re

API_TOKEN = os.getenv('TELEGRAM_TOKEN') or '7675723384:AAH6U5eib6lC82AOlfeHDA55aEPBfENerLg'
bot = telebot.TeleBot(API_TOKEN)

# --- Указать username своего бота ---
BOT_USERNAME = 'Gorod_budushego_bot'  # ЗАМЕНИ на username своего бота без @

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
GROUP_ID = -1002519704761
TOPIC_ID = 3
admin_id = 790005263 # сюда можно вписать свой user_id для поддержки
support_messages = []

# --- Глобальное состояние для админ-режима (in-memory, на сессию) ---
admin_states = {}

# --- Инициализация БД ---
def init_db():
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            age INTEGER,
            city TEXT,
            balance INTEGER DEFAULT 0,
            ref_code TEXT,
            invited_by TEXT,
            ref_friends TEXT,
            ref_progress TEXT,
            username TEXT,
            last_daily TEXT,
            tasks_done TEXT
        )''')
        try:
            c.execute('ALTER TABLE users ADD COLUMN username TEXT')
        except Exception:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN last_daily TEXT')
        except Exception:
            pass
        # --- Новая таблица для заявок на задания ---
        c.execute('''CREATE TABLE IF NOT EXISTS pending_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_id INTEGER,
            proof_type TEXT,
            proof_data TEXT,
            status TEXT
        )''')
        conn.commit()

init_db()

# --- Вспомогательные функции для работы с БД ---
def get_user(user_id, username=None):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
        row = c.fetchone()
        if not row:
            # Новый пользователь
            c.execute('''INSERT INTO users (user_id, balance, ref_code, tasks_done, ref_friends, ref_progress, username, last_daily)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                      (user_id, 0, str(user_id), '', '', '', username or '', ''))
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
            'ref_friends': set(map(int, row[7].split(','))) if row[7] else set(),
            'ref_progress': eval(row[8]) if row[8] else {},
            'username': row[9] if len(row) > 9 else '',
            'last_daily': row[10] if len(row) > 10 else '',
            'tasks_done': set(map(int, row[11].split(','))) if row[11] and row[11] != '{}' else set(),
        }
    return user

def save_user(user):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('''UPDATE users SET full_name=?, age=?, city=?, balance=?, ref_code=?, invited_by=?,
                     ref_friends=?, ref_progress=?, username=?, last_daily=?, tasks_done=? WHERE user_id=?''',
                  (user['full_name'], user['age'], user['city'], user['balance'], user['ref_code'], user['invited_by'],
                   ','.join(map(str, user['ref_friends'])), str(user['ref_progress']), user.get('username',''), user.get('last_daily',''), ','.join(map(str, user['tasks_done'])), user['user_id']))
        conn.commit()

def get_user_by_ref_code(ref_code):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE ref_code=?', (ref_code,))
        row = c.fetchone()
    if not row:
        return None
    return {
        'user_id': row[0],
        'full_name': row[1] or '',
        'age': row[2] or '',
        'city': row[3] or '',
        'balance': row[4],
        'ref_code': row[5],
        'invited_by': row[6],
        'ref_friends': set(map(int, row[7].split(','))) if row[7] else set(),
        'ref_progress': eval(row[8]) if row[8] else {},
    }

def send_temp_message(chat_id, text, delay=5, **kwargs):
    msg = bot.send_message(chat_id, text, **kwargs)
    threading.Timer(delay, lambda: safe_delete_message(chat_id, msg.message_id)).start()
    return msg

def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass

# --- Меню и разделы ---
def show_section(call, text, markup):
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=markup,
            parse_mode='HTML'
        )
        logging.info(f"edit_message_text: {text[:30]}...")
    except Exception as e:
        logging.error(f"Ошибка edit_message_text: {e}")
        msg = bot.send_message(call.from_user.id, text, reply_markup=markup, parse_mode='HTML')
        logging.info(f"send_message: {text[:30]}...")
        try:
            bot.answer_callback_query(call.id, "Пожалуйста, работайте с этим сообщением.")
        except:
            pass

# --- Главное меню ---
def main_menu_reply_markup(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if user_id == admin_id:
        markup.add(
            KeyboardButton("📋 Список заданий"),
            KeyboardButton("🎁 Обменять дубли на призы"),
            KeyboardButton("💰 Мой баланс дублей"),
            KeyboardButton("👥 Реферальная программа"),
            KeyboardButton("ℹ️ Про игру"),
            KeyboardButton("📜 Правила"),
            KeyboardButton("🆘 Служба поддержки"),
            KeyboardButton("👑 Админ-панель")
        )
    else:
        markup.add(
            KeyboardButton("📋 Список заданий"),
            KeyboardButton("🎁 Обменять дубли на призы"),
            KeyboardButton("💰 Мой баланс дублей"),
            KeyboardButton("👥 Реферальная программа"),
            KeyboardButton("ℹ️ Про игру"),
            KeyboardButton("📜 Правила"),
            KeyboardButton("🆘 Служба поддержки")
        )
    return markup

def return_to_main_menu(call=None, user_id=None):
    text = "\u2B50 Главное меню:"
    if call is not None:
        user_id = call.from_user.id
        markup = main_menu_reply_markup(user_id)
        bot.send_message(user_id, text, reply_markup=markup)
        bot.answer_callback_query(call.id)
    elif user_id is not None:
        markup = main_menu_reply_markup(user_id)
        bot.send_message(user_id, text, reply_markup=markup)
        logging.info(f"send_message для возврата в меню: user_id={user_id}")
    else:
        logging.error('return_to_main_menu: не передан call и user_id!')

# --- Приветствие и старт ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    # --- Ежедневный бонус ---
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    hour = now.hour
    if hour < 5:
        part_of_day = 'доброй ночи'
    elif hour < 12:
        part_of_day = 'доброе утро'
    elif hour < 18:
        part_of_day = 'добрый день'
    else:
        part_of_day = 'добрый вечер'
    if user.get('last_daily','') != today:
        user['balance'] += 5
        user['last_daily'] = today
        save_user(user)
        bot.send_message(user_id, f'👋 {part_of_day.capitalize()}! За ежедневный вход — тебе +5 дублей!')
    # Если старт с реферальным кодом
    ref_name = ''
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
        if not user['invited_by'] and ref_code != str(user_id):
            user['invited_by'] = ref_code
            save_user(user)
            inviter = get_user_by_ref_code(ref_code)
            if inviter:
                if 'ref_friends' not in inviter or not inviter['ref_friends']:
                    inviter['ref_friends'] = set()
                if 'ref_progress' not in inviter or not inviter['ref_progress']:
                    inviter['ref_progress'] = {}
                inviter['ref_friends'].add(user_id)
                inviter['ref_progress'][user_id] = 0
                save_user(inviter)
                username = user.get('username')
                username_str = f" (@{username})" if username else ""
                bot.send_message(inviter['user_id'], f"К вам присоединился {user['full_name']}{username_str}. Его прогресс: 0/3")
        inviter = get_user_by_ref_code(user['invited_by']) if user['invited_by'] else None
        if inviter:
            ref_name = f"\n\n<b>Тебя пригласил:</b> {inviter['full_name']}"
    if user['full_name']:
        # Сразу показываем список заданий вместо главного меню
        task_list(message)
        return
    text = (
        "<b>👋 Привет! Я — Тренер, твой проводник в игре!</b>\n\n"
        "Меня зовут Владимир Владимирович, но все зовут просто Тренер.\n\n"
        "<b>Добро пожаловать в увлекательное путешествие, в котором, выполняя задания, ты сможешь заработать <u>Дубли</u>, которые сможешь обменять на реальные призы!</b>\n\n"
        "Готов начать? Жми кнопку ниже!"
        f"{ref_name}"
    )
    markup = main_menu_reply_markup(user_id)
    inline = InlineKeyboardMarkup()
    inline.add(InlineKeyboardButton("🚀 Готов начать", callback_data="start_game"))
    bot.send_message(user_id, text, reply_markup=inline, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == 'start_game')
def start_game_callback(call):
    user_id = call.from_user.id
    user = get_user(user_id, call.from_user.username)
    if user['full_name']:
        return_to_main_menu(call, user_id)
        return
    user['balance'] += 10
    save_user(user)
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="<b>+10 дублей!</b>\n\nДавай зарегистрируемся, чтобы я мог дарить тебе призы!\n\nКак тебя зовут? (ФИ)",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(call.message, reg_full_name)

def reg_full_name(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    name = message.text.strip()
    # Валидация: минимум 2 слова, только буквы и пробелы
    if len(name.split()) < 2 or not re.match(r'^[А-Яа-яA-Za-zЁё\- ]+$', name):
        bot.send_message(user_id, "Пожалуйста, введи ФИО (минимум 2 слова, только буквы). Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_full_name)
        return
    name = ' '.join([part.capitalize() for part in name.split()])
    user['full_name'] = name
    save_user(user)
    bot.send_message(user_id, "Сколько тебе лет?")
    bot.register_next_step_handler(message, reg_age)

def reg_age(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    if not message.text.isdigit():
        send_temp_message(user_id, "Пожалуйста, введи число.")
        bot.register_next_step_handler(message, reg_age)
        return
    age = int(message.text)
    if age < 10 or age > 100:
        bot.send_message(user_id, "Возраст должен быть от 10 до 100. Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_age)
        return
    user['age'] = age
    save_user(user)
    bot.send_message(user_id, "Из какого ты города по прописке?")
    bot.register_next_step_handler(message, reg_city)

def reg_city(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    city = message.text.strip().lower().replace('ё', 'е')
    # Валидация: только буквы, минимум 2 буквы
    if not re.match(r'^[а-яa-z\- ]{2,}$', city, re.IGNORECASE):
        bot.send_message(user_id, "Пожалуйста, введи корректное название города (только буквы, минимум 2 буквы). Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_city)
        return
    # Обработка Ростова-на-Дону
    rostov_variants = [
        'ростов', 'ростов на дону', 'ростов-на-дону', 'ростов-на-дону',
        'ростов н д', 'ростов н/д', 'ростов-на-дону', 'г ростов', 'г. ростов', 'г. ростов-на-дону', 'г ростов-на-дону'
    ]
    if any(city.replace('-', ' ').replace('—', ' ').replace('.', '').replace('г ', '').replace('г.', '').strip() == v for v in rostov_variants):
        city = 'Ростов-на-Дону'
    else:
        city = ' '.join([part.capitalize() for part in city.split()])
    user['city'] = city
    user['balance'] += 25
    save_user(user)
    bot.send_message(
        user_id,
        "<b>Поздравляем, игрок зарегистрирован!</b>\n\n+25 дублей за регистрацию.\n\nПоехали!",
        parse_mode='HTML'
    )
    return_to_main_menu(None, user_id)

# --- Меню ---
@bot.message_handler(func=lambda m: m.text == "💰 Мой баланс дублей")
def show_balance(message, back_btn=False):
    user_id = message.from_user.id if hasattr(message, 'from_user') else message.message.chat.id
    user = get_user(user_id, message.from_user.username)
    text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0"
    if back_btn:
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=back_markup())
    else:
        bot.send_message(user_id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "ℹ️ Про игру")
def about_game(message, back_btn=False):
    text = (
        "<b>О проекте</b>\n\n"
        "Выполняй задания в течение 3 месяцев, зарабатывай <b>дубли</b> и обменивай их на реальные призы!\n\n"
        "<b>Типы заданий:</b>\n• Ежедневные\n• Еженедельные\n\n"
        "<b>За что начисляются дубли:</b>\n"
        "• Выполнение заданий\n"
        "• Ежедневный вход в игру\n\n"
        "<i>Остались вопросы? Напиши в службу поддержки!</i>"
    )
    if back_btn:
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=back_markup())
    else:
        bot.send_message(message.from_user.id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "📜 Правила")
def rules(message, back_btn=False):
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
    if back_btn:
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=back_markup())
    else:
        bot.send_message(message.from_user.id, text, parse_mode='HTML')

# --- Задания ---
@bot.message_handler(func=lambda m: m.text == "📋 Список заданий")
def task_list(message, back_btn=False):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    markup = telebot.types.InlineKeyboardMarkup()
    for task in tasks:
        done = task['id'] in user['tasks_done']
        btn_text = f"{'✅' if done else '🔲'} {task['name']} (+{task['reward']} дублей)"
        markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"do_task_{task['id']}"))
    if back_btn:
        markup.add(telebot.types.InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_menu"))
    bot.send_message(user_id, "<b>Выбери задание для выполнения:</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('do_task_'))
def do_task(call):
    user_id = call.from_user.id
    user = get_user(user_id, call.from_user.username)
    task_id = int(call.data.split('_')[-1])
    # Просим пруф с кнопкой отмены
    bot.answer_callback_query(call.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_proof"))
    bot.edit_message_text(f"<b>Пришли пруф выполнения задания:</b>\n{next((t['name'] for t in tasks if t['id']==task_id),'')}\n\nМожно фото, скрин или текст.",
                         call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
    # Сохраняем task_id в user_data для отмены
    if not hasattr(bot, 'user_data'):
        bot.user_data = {}
    bot.user_data[user_id] = {'task_id': task_id, 'msg_id': call.message.message_id}
    bot.register_next_step_handler(call.message, handle_proof, task_id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_proof')
def cancel_proof(call):
    user_id = call.from_user.id
    # Очищаем user_data
    if hasattr(bot, 'user_data') and user_id in bot.user_data:
        del bot.user_data[user_id]
    bot.clear_step_handler_by_chat_id(user_id)
    bot.edit_message_text("❌ Отменено. Возвращаю в меню.", call.message.chat.id, call.message.message_id)
    return_to_main_menu(call, user_id)

def handle_proof(message, task_id):
    user_id = message.from_user.id
    proof_type = None
    proof_data = None
    if message.content_type == 'photo':
        proof_type = 'photo'
        proof_data = message.photo[-1].file_id
    elif message.content_type == 'text':
        proof_type = 'text'
        proof_data = message.text
    elif message.content_type == 'document':
        proof_type = 'document'
        proof_data = message.document.file_id
    else:
        send_temp_message(user_id, "❌ Пришли фото, документ или текст!")
        bot.register_next_step_handler(message, handle_proof, task_id)
        return
    add_pending_task(user_id, task_id, proof_type, proof_data)
    send_temp_message(user_id, "✅ Задание отправлено на проверку! Пока оно проверяется, ты можешь выполнять другие задания.", delay=10)
    # Уведомить модераторов в группе/теме
    task_name = next((t['name'] for t in tasks if t['id']==task_id),'')
    user = get_user(user_id, message.from_user.username)
    username = user.get('username')
    if username:
        username_str = f" (@{username})"
    else:
        username_str = ""
    text = f"<b>Проверка задания:</b>\nПользователь: <a href='tg://user?id={user_id}'>{user['full_name']}</a>{username_str}\nЗадание: <b>{task_name}</b>"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Принять", callback_data=f"approve_{user_id}_{task_id}"),
               InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user_id}_{task_id}"))
    if proof_type == 'photo':
        bot.send_photo(GROUP_ID, proof_data, caption=text, parse_mode='HTML', reply_markup=markup, message_thread_id=TOPIC_ID)
    elif proof_type == 'document':
        bot.send_document(GROUP_ID, proof_data, caption=text, parse_mode='HTML', reply_markup=markup, message_thread_id=TOPIC_ID)
    else:
        bot.send_message(GROUP_ID, text + f"\n\nПруф: {proof_data}", parse_mode='HTML', reply_markup=markup, message_thread_id=TOPIC_ID)

# --- Рефералы ---
@bot.message_handler(func=lambda m: m.text == "👥 Реферальная программа")
def referral(message, back_btn=False):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user['ref_code']}"
    text = (
        "<b>Реферальная программа</b>\n\n"
        "Приведи друга и получи <b>100 дублей</b>!\n"
        "<b>Ссылка для друга:</b>\n"
        f"<code>{ref_link}</code>\n"
        "<i>Скопируй ссылку и отправь другу — пусть заходит!</i>\n\n"
        "<b>ВАЖНО!</b> Дубли начисляются после того, как друг выполнит 3 задания.\n"
    )
    # Список друзей и прогресс
    markup = InlineKeyboardMarkup()
    if user['ref_friends']:
        text += "\n<b>Твои приглашённые:</b>\n"
        for fid in user['ref_friends']:
            fuser = get_user(fid, message.from_user.username)
            done = user['ref_progress'].get(fid, 0)
            username = fuser.get('username')
            if username:
                link = f'<a href="https://t.me/{username}">{fuser["full_name"]}</a>'
            else:
                link = fuser["full_name"]
            text += f"• {link} — <b>{done}/3 заданий</b>\n"
    else:
        text += "\nУ тебя пока нет приглашённых друзей."
    if back_btn:
        markup.add(InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_menu"))
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=markup)
        bot.send_message(user_id, ref_link)
    else:
        markup.add(InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_menu"))
        bot.send_message(user_id, text, parse_mode='HTML', reply_markup=markup)
        bot.send_message(user_id, ref_link)

# --- Обмен призов ---
@bot.message_handler(func=lambda m: m.text == "🎁 Обменять дубли на призы")
def exchange_prizes(message, back_btn=False):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0\n\n<b>Доступные призы:</b>\n"
    for prize in prizes:
        if prize['cost'] > 0:
            text += f"• {prize['name']} — <b>{prize['cost']} дублей</b>\n"
        else:
            text += f"• {prize['name']}\n"
    text += "\nЧтобы обменять дубли на приз, напиши: <code>ПРИЗ &lt;название&gt;</code>\n"
    text += "Чтобы обменять дубли на товар с маркетплейса, напиши: <code>МАРКЕТ &lt;ссылка&gt; &lt;стоимость&gt;</code>"
    if back_btn:
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=back_markup())
    else:
        bot.send_message(user_id, text, parse_mode='HTML')

@bot.message_handler(regexp=r'^ПРИЗ (.+)')
def buy_prize(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    prize_name = message.text[5:].strip()
    prize = next((p for p in prizes if prize_name.lower() in p['name'].lower()), None)
    if not prize:
        send_temp_message(user_id, "❌ Такого приза нет.")
        return
    if user['balance'] < prize['cost']:
        send_temp_message(user_id, "❌ Недостаточно дублей!")
        return
    user['balance'] -= prize['cost']
    bot.send_message(user_id, f"🎉 Поздравляем! Ты обменял <b>{prize['cost']}</b> дублей на приз: <b>{prize['name']}</b>", parse_mode='HTML')

@bot.message_handler(regexp=r'^МАРКЕТ (.+) (\d+)')
def buy_market(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
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
def support(message, back_btn=False):
    bot.send_message(message.from_user.id, "✉️ Напиши свой вопрос, и мы обязательно ответим! Просто отправь сообщение.")
    bot.register_next_step_handler(message, save_support)

def save_support(message):
    user_id = message.from_user.id
    support_messages.append({'user_id': user_id, 'text': message.text})
    if admin_id:
        bot.send_message(admin_id, f"Вопрос от пользователя {user_id}: {message.text}")
    send_temp_message(user_id, "Спасибо! Ваш вопрос отправлен в поддержку.", delay=10)

@bot.message_handler(commands=['export_users'])
def export_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users')
        rows = c.fetchall()
    filename = 'users_export.csv'
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'full_name', 'age', 'city', 'balance', 'ref_code', 'invited_by', 'ref_friends', 'ref_progress', 'tasks_done'])
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
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM users WHERE balance >= 400')
        rich = c.fetchone()[0]
    bot.send_message(admin_id, f"Всего пользователей: <b>{total}</b>\n\nС балансом 400+ дублей: <b>{rich}</b>", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "👤 Пользователи")
def admin_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, full_name, balance FROM users LIMIT 20')
        rows = c.fetchall()
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
    show_admin_panel(message)

@bot.message_handler(func=lambda m: m.text == "⬅️ В меню игрока")
def to_user_menu(message):
    if message.from_user.id != admin_id:
        return
    admin_states[admin_id] = False
    return_to_main_menu(None, message.from_user.id)

# --- Обработка инлайн-кнопок главного меню ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_') or call.data == 'back_to_menu')
def handle_main_menu(call):
    user_id = call.from_user.id
    data = call.data
    logging.info(f"Callback: {data} от пользователя {user_id}")
    if data == "menu_tasks":
        text = "<b>Выбери задание для выполнения:</b>"
        markup = InlineKeyboardMarkup()
        for task in tasks:
            done = task['id'] in get_user(user_id)['tasks_done']
            btn_text = f"{'✅' if done else '🔲'} {task['name']} (+{task['reward']} дублей)"
            markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"do_task_{task['id']}"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_menu"))
        show_section(call, text, markup)
    elif data == "menu_prizes":
        user = get_user(user_id, call.from_user.username)
        text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0\n\n<b>Доступные призы:</b>\n"
        for prize in prizes:
            if prize['cost'] > 0:
                text += f"• {prize['name']} — <b>{prize['cost']} дублей</b>\n"
            else:
                text += f"• {prize['name']}\n"
        text += "\nЧтобы обменять дубли на приз, напиши: <code>ПРИЗ &lt;название&gt;</code>\n"
        text += "Чтобы обменять дубли на товар с маркетплейса, напиши: <code>МАРКЕТ &lt;ссылка&gt; &lt;стоимость&gt;</code>"
        markup = back_markup()
        show_section(call, text, markup)
    elif data == "menu_balance":
        user = get_user(user_id, call.from_user.username)
        text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0"
        markup = back_markup()
        show_section(call, text, markup)
    elif data == "menu_ref":
        # Создаём фейковый message-объект для передачи в referral
        class FakeMessage:
            def __init__(self, from_user, message):
                self.from_user = from_user
                self.message = message
        fake_message = FakeMessage(call.from_user, call.message)
        referral(fake_message, back_btn=True)
    elif data == "menu_about":
        text = "<b>О проекте</b>\n\n"
        text += "Выполняй задания в течение 3 месяцев, зарабатывай <b>дубли</b> и обменивай их на реальные призы!\n\n"
        text += "<b>Типы заданий:</b>\n• Ежедневные\n• Еженедельные\n\n"
        text += "<b>За что начисляются дубли:</b>\n"
        text += "• Выполнение заданий\n"
        text += "• Ежедневный вход в игру\n\n"
        text += "<i>Остались вопросы? Напиши в службу поддержки!</i>"
        markup = back_markup()
        show_section(call, text, markup)
    elif data == "menu_rules":
        text = "<b>Правила игры и обмена дублей на призы</b>\n\n"
        text += "1️⃣ <b>Рассказывай всем об этой игре!</b>\n"
        text += "2️⃣ <b>Смотри правило №1</b>\n\n"
        text += "<b>Запрещено:</b> оскорбления, мат, пошлость (в т.ч. визуальная).\n\n"
        text += "<b>Обмен дублей на призы:</b>\n"
        text += "• Минимум для обмена — 400 дублей\n"
        text += "• Призы — смотри во вкладке <b>Обменять дубли на призы</b>\n"
        text += "• Можно обменять дубли на товар с маркетплейса (Озон/ВБ), если дублей не меньше стоимости товара."
        markup = back_markup()
        show_section(call, text, markup)
    elif data == "menu_support":
        text = "✉️ Напиши свой вопрос, и мы обязательно ответим! Просто отправь сообщение."
        markup = back_markup()
        show_section(call, text, markup)
    elif data == "menu_admin" and user_id == admin_id:
        admin_states[admin_id] = True
        show_admin_panel(call)
        bot.answer_callback_query(call.id)
        return
    elif data == "back_to_menu":
        return_to_main_menu(call, user_id)
        return
    bot.answer_callback_query(call.id)

def show_admin_panel(call):
    text = "<b>👑 Админ-панель:</b>\n\nВыберите действие:"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton("👤 Пользователи", callback_data="admin_users"),
        InlineKeyboardButton("📥 Выгрузка", callback_data="admin_export"),
        InlineKeyboardButton("📨 Обращения", callback_data="admin_support"),
        InlineKeyboardButton("➕ Добавить дубли", callback_data="admin_add_balance"),
        InlineKeyboardButton("➖ Убрать дубли", callback_data="admin_sub_balance"),
        InlineKeyboardButton("❌ Удалить пользователя", callback_data="admin_delete_user"),
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        InlineKeyboardButton("⬅️ В меню игрока", callback_data="back_to_menu")
    )
    show_section(call, text, markup)

# --- Состояния для админских действий ---
admin_action_state = {}

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_') or call.data == 'back_to_menu')
def handle_admin_panel(call):
    user_id = call.from_user.id
    data = call.data
    if user_id != admin_id:
        bot.answer_callback_query(call.id, "⛔️ Нет доступа.")
        return
    if data == "admin_add_balance":
        bot.send_message(admin_id, "Введи ID пользователя и сколько добавить дублей (через пробел):")
        admin_action_state['action'] = 'add_balance'
        bot.register_next_step_handler_by_chat_id(admin_id, admin_balance_step)
        return
    elif data == "admin_sub_balance":
        bot.send_message(admin_id, "Введи ID пользователя и сколько убрать дублей (через пробел):")
        admin_action_state['action'] = 'sub_balance'
        bot.register_next_step_handler_by_chat_id(admin_id, admin_balance_step)
        return
    elif data == "admin_delete_user":
        bot.send_message(admin_id, "Введи ID пользователя для удаления:")
        admin_action_state['action'] = 'delete_user'
        bot.register_next_step_handler_by_chat_id(admin_id, admin_delete_user_step)
        return
    elif data == "admin_broadcast":
        bot.send_message(admin_id, "Введи текст рассылки:")
        admin_action_state['action'] = 'broadcast_text'
        bot.register_next_step_handler_by_chat_id(admin_id, admin_broadcast_step)
        return
    elif data == "admin_stats":
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM users')
            total = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM users WHERE balance >= 400')
            rich = c.fetchone()[0]
        text = f"Всего пользователей: <b>{total}</b>\n\nС балансом 400+ дублей: <b>{rich}</b>"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ В меню админа", callback_data="admin_panel"))
        show_section(call, text, markup)
    elif data == "admin_users":
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, full_name, balance FROM users LIMIT 20')
            rows = c.fetchall()
        text = '<b>Первые 20 пользователей:</b>\n'
        for row in rows:
            text += f"ID: <code>{row[0]}</code> | {row[1]} | 💰 {row[2]} дублей\n"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ В меню админа", callback_data="admin_panel"))
        show_section(call, text, markup)
    elif data == "admin_export":
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM users')
            rows = c.fetchall()
        filename = 'users_export.csv'
        import csv
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['user_id', 'full_name', 'age', 'city', 'balance', 'ref_code', 'invited_by', 'ref_friends', 'ref_progress', 'tasks_done'])
            for row in rows:
                writer.writerow(row)
        with open(filename, 'rb') as f:
            bot.send_document(admin_id, f, caption='Выгрузка пользователей')
        bot.answer_callback_query(call.id, "Выгрузка отправлена!")
    elif data == "admin_support":
        if not support_messages:
            text = "Нет новых обращений."
        else:
            text = '<b>Последние обращения:</b>\n'
            for msg in support_messages[-10:]:
                text += f"ID: <code>{msg['user_id']}</code> — {msg['text']}\n"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ В меню админа", callback_data="admin_panel"))
        show_section(call, text, markup)
    elif data == "admin_panel":
        show_admin_panel(call)
    elif data == "back_to_menu":
        return_to_main_menu(call)
    else:
        show_admin_panel(call)

# --- Добавление/убавление дублей ---
def admin_balance_step(message):
    if message.from_user.id != admin_id:
        return
    try:
        parts = message.text.strip().split()
        uid = int(parts[0])
        amount = int(parts[1])
    except Exception:
        bot.send_message(admin_id, "Формат: ID количество. Попробуй ещё раз.")
        bot.register_next_step_handler_by_chat_id(admin_id, admin_balance_step)
        return
    user = get_user(uid)
    if not user:
        bot.send_message(admin_id, "Пользователь не найден.")
        return
    if admin_action_state.get('action') == 'add_balance':
        user['balance'] += amount
        save_user(user)
        bot.send_message(admin_id, f"Пользователю {uid} добавлено {amount} дублей. Баланс: {user['balance']}")
    elif admin_action_state.get('action') == 'sub_balance':
        user['balance'] = max(0, user['balance'] - amount)
        save_user(user)
        bot.send_message(admin_id, f"У пользователя {uid} убрано {amount} дублей. Баланс: {user['balance']}")
    show_admin_panel(message)

# --- Удаление пользователя ---
def admin_delete_user_step(message):
    if message.from_user.id != admin_id:
        return
    try:
        uid = int(message.text.strip())
    except Exception:
        bot.send_message(admin_id, "Формат: только ID. Попробуй ещё раз.")
        bot.register_next_step_handler_by_chat_id(admin_id, admin_delete_user_step)
        return
    user = get_user(uid)
    if not user:
        bot.send_message(admin_id, "Пользователь не найден.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Подтвердить удаление", callback_data=f"admin_confirm_delete_{uid}"),
               InlineKeyboardButton("Отмена", callback_data="admin_panel"))
    bot.send_message(admin_id, f"Удалить пользователя {uid} ({user['full_name']})?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_confirm_delete_'))
def admin_confirm_delete(call):
    if call.from_user.id != admin_id:
        return
    uid = int(call.data.split('_')[-1])
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('DELETE FROM pending_tasks WHERE user_id=?', (uid,))
        c.execute('DELETE FROM users WHERE user_id=?', (uid,))
        conn.commit()
    bot.send_message(admin_id, f"Пользователь {uid} удалён.")
    show_admin_panel(call)

# --- Рассылка ---
def admin_broadcast_step(message):
    if message.from_user.id != admin_id:
        return
    text = message.text.strip()
    admin_action_state['broadcast_text'] = text
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Отправить всем", callback_data="admin_broadcast_send"),
               InlineKeyboardButton("❌ Отмена", callback_data="admin_panel"))
    bot.send_message(admin_id, f"Вот сообщение для рассылки:\n\n{text}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'admin_broadcast_send')
def admin_broadcast_send(call):
    if call.from_user.id != admin_id:
        return
    text = admin_action_state.get('broadcast_text')
    if not text:
        bot.send_message(admin_id, "Нет текста для рассылки.")
        return
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT user_id FROM users')
        user_ids = [row[0] for row in c.fetchall()]
    count = 0
    for uid in user_ids:
        try:
            bot.send_message(uid, text)
            count += 1
        except Exception:
            pass
    bot.send_message(admin_id, f"Рассылка отправлена {count} пользователям.")
    show_admin_panel(call)

# --- Админ-команда: кто кого пригласил ---
@bot.message_handler(commands=['ref_stats'])
def ref_stats(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, full_name, invited_by FROM users')
        rows = c.fetchall()
    text = '<b>Кто кого пригласил:</b>\n'
    for row in rows:
        if row[2]:
            inviter = get_user_by_ref_code(row[2])
            inviter_name = inviter['full_name'] if inviter else row[2]
            text += f"{row[1]} (ID {row[0]}) ← {inviter_name}\n"
    bot.send_message(admin_id, text, parse_mode='HTML')

def back_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_menu"))
    return markup

# --- Функции для работы с pending_tasks ---
def add_pending_task(user_id, task_id, proof_type, proof_data):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('INSERT INTO pending_tasks (user_id, task_id, proof_type, proof_data, status) VALUES (?, ?, ?, ?, ?)',
                  (user_id, task_id, proof_type, proof_data, 'pending'))
        conn.commit()

def get_pending_tasks():
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT id, user_id, task_id, proof_type, proof_data FROM pending_tasks WHERE status="pending"')
        rows = c.fetchall()
    return rows

def set_pending_task_status(task_id, status):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('UPDATE pending_tasks SET status=? WHERE id=?', (status, task_id))
        conn.commit()

# --- Обработка кнопок проверки ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_task_moderation(call):
    data = call.data
    action, user_id, task_id = data.split('_')
    user_id = int(user_id)
    task_id = int(task_id)
    # Найти заявку
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT id FROM pending_tasks WHERE user_id=? AND task_id=? AND status="pending"', (user_id, task_id))
        row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Заявка уже обработана")
        return
    pending_id = row[0]
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Вернуться к заданиям", callback_data="menu_tasks"))
    if action == 'approve':
        set_pending_task_status(pending_id, 'approved')
        user = get_user(user_id)
        reward = next((t['reward'] for t in tasks if t['id'] == task_id), 0)
        user['balance'] += reward
        save_user(user)
        user['tasks_done'].add(task_id)
        save_user(user)
        bot.send_message(user_id, f"✅ Задание <b>{next((t['name'] for t in tasks if t['id']==task_id),'')} </b> принято! +{reward} дублей\n\nМожешь выбрать следующее задание.", parse_mode='HTML', reply_markup=markup)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.answer_callback_query(call.id, "Задание принято")
    else:
        set_pending_task_status(pending_id, 'rejected')
        bot.send_message(user_id, f"❌ Задание <b>{next((t['name'] for t in tasks if t['id']==task_id),'')}</b> отклонено. Попробуй ещё раз!\n\nМожешь выбрать другое задание.", parse_mode='HTML', reply_markup=markup)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.answer_callback_query(call.id, "Отклонено")

# --- Админ-меню для проверки заданий ---
@bot.message_handler(func=lambda m: m.text == "📝 Проверка заданий")
def admin_pending_tasks(message):
    if message.from_user.id != admin_id:
        return
    tasks = get_pending_tasks()
    if not tasks:
        bot.send_message(admin_id, "Нет заявок на проверку.")
        return
    for row in tasks:
        pid, user_id, task_id, proof_type, proof_data = row
        user = get_user(user_id)
        task_name = next((t['name'] for t in tasks if t['id']==task_id),'')
        username = user.get('username')
        if username:
            username_str = f" (@{username})"
        else:
            username_str = ""
        text = f"Пользователь: <a href='tg://user?id={user_id}'>{user['full_name']}</a>{username_str}\nЗадание: <b>{task_name}</b>"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Принять", callback_data=f"approve_{user_id}_{task_id}"),
                   InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user_id}_{task_id}"))
        if proof_type == 'photo':
            bot.send_photo(admin_id, proof_data, caption=text, parse_mode='HTML', reply_markup=markup)
        elif proof_type == 'document':
            bot.send_document(admin_id, proof_data, caption=text, parse_mode='HTML', reply_markup=markup)
        else:
            bot.send_message(admin_id, text + f"\n\nПруф: {proof_data}", parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'done')
def already_done_callback(call):
    bot.answer_callback_query(call.id, "Вы уже выполнили это задание!")

if __name__ == "__main__":
    logger.info('Бот запущен!')
    print('Бот запущен!')
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logger.error(f'Ошибка при запуске бота: {e}')
        print(f'Ошибка при запуске бота: {e}') 