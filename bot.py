import telebot
import os
import random
import logging
import csv
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import threading
from datetime import datetime
import re
import json
import hashlib
from apscheduler.schedulers.background import BackgroundScheduler
import time
from export_to_gsheets import main as export_to_gsheets_main
from supabase import create_client, Client
import calendar
import requests

API_TOKEN = os.getenv('TELEGRAM_TOKEN') or '7675723384:AAH6U5eib6lC82AOlfeHDA55aEPBfENerLg'

# Инициализация бота
bot = telebot.TeleBot(API_TOKEN)



# --- Константы для панели модератора ---
TASKS_PANEL_CHAT_ID = -1002519704761
TASKS_PANEL_THREAD_ID = 142
MODERATOR_IDS = [790005263]  # добавь id своих модераторов

# --- Указать username своего бота ---
BOT_USERNAME = 'Gorod_budushego_bot'  # ЗАМЕНИ на username своего бота без @

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[logging.FileHandler('bot.log', encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

users = {}
TASKS_FILE = 'tasks.json'

SUPABASE_URL = "https://qnsfntkhaxtcmlfrlafz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFuc2ZudGtoYXh0Y21sZnJsYWZ6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTE4ODQxMDksImV4cCI6MjA2NzQ2MDEwOX0.wI-sZUCtEneBKZYLW0sLGZJ9XcZgCQkIfVrKjY7KN5Y"  # замени на свой anon/public key
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Переключатель: откуда брать задания ---
USE_SUPABASE_TASKS = False  # True — из Supabase, False — из tasks.json

def load_tasks():
    try:
        with open(TASKS_FILE, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
            changed = False
            for t in loaded:
                # Автозачистка префиксов в name
                orig = t['name']
                for prefix in ["daily ", "weekly ", "daily_", "weekly_"]:
                    if t['name'].startswith(prefix):
                        t['name'] = t['name'][len(prefix):]
                        changed = True
                if 'desc' not in t:
                    t['desc'] = ''
                    changed = True
            if changed:
                save_tasks(loaded)
            return loaded
    except Exception:
        return []

def get_fresh_tasks():
    if USE_SUPABASE_TASKS:
        res = supabase.table("tasks").select("*").execute()
        return res.data or []
    else:
        return load_tasks()

def save_tasks(tasks):
    if USE_SUPABASE_TASKS:
        # Можно реализовать сохранение в Supabase, если нужно
        pass
    else:
        with open(TASKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

tasks = load_tasks()

prizes = [
    {'id': 1, 'name': 'ТГ премиум на 3 месяца', 'cost': 1290},
    {'id': 2, 'name': 'ТГ премиум на 6 месяцев', 'cost': 1790},
    {'id': 3, 'name': 'ТГ премиум на 12 месяцев', 'cost': 2990},
    {'id': 4, 'name': 'Футболка НЛ (мерч)', 'cost': 800},
    {'id': 5, 'name': 'Кепка НЛ (мерч)', 'cost': 800},
    {'id': 6, 'name': 'Толстовка НЛ (мерч)', 'cost': 1300},
    {'id': 7, 'name': 'Футболка с любым принтом', 'cost': 800},
    {'id': 8, 'name': 'Кепка с любым принтом', 'cost': 800},
    {'id': 9, 'name': 'Толстовка с любым принтом', 'cost': 1300},
]
GROUP_ID = -1002519704761
TASKS_TOPIC_ID = 3
TOPIC_ID = 53
MARKETPLACE_TOPIC_ID = 53
SUPPORT_TOPIC_ID = 54
admin_id = 790005263 # сюда можно вписать свой user_id для поддержки
support_messages = []

# --- Глобальное состояние для админ-режима (in-memory, на сессию) ---
admin_states = {}

# --- Глобальное состояние для поддержки ---
support_states = set()

# Проверка на открытое обращение в поддержку
def has_open_support(user_id):
    return user_id in support_states

def block_if_open_support(message):
    user_id = message.from_user.id
    if has_open_support(user_id):
        bot.send_message(user_id, "У тебя уже есть открытое обращение в поддержку. Дождись ответа или отмени его.")
        return True
    return False

# Проверка на открытое задание
def has_open_task(user_id):
    return hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id')

def block_if_open_task(message):
    user_id = message.from_user.id
    if has_open_task(user_id):
        task_name = get_current_task_name(user_id)
        send_temp_message(user_id, f"Сначала выполните или отмените задание: <b>{task_name}</b>", parse_mode='HTML')
        return True
    return False

# --- Вспомогательные функции для работы с БД ---
def get_user(user_id, username=None):
    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if res.data:
        user = res.data[0]
        user['tasks_done'] = set(map(int, user['tasks_done'].split(','))) if user.get('tasks_done') else set()
        user['ref_friends'] = set(map(int, user['ref_friends'].split(','))) if user.get('ref_friends') else set()
        try:
            user['ref_progress'] = json.loads(user['ref_progress']) if user.get('ref_progress') else {}
        except (json.JSONDecodeError, TypeError):
            user['ref_progress'] = {}
        return user
    # если нет — создать
    user = {
        'user_id': user_id,
        'full_name': '',
        'age': 0,
        'city': '',
        'balance': 0,
        'ref_code': str(user_id),
        'invited_by': '',
        'tasks_done': '',
        'ref_friends': '',
        'ref_progress': json.dumps({}),
        'username': username or '',
        'last_daily': None,
        'daily_streak': 0,
        'weekly_earned': 0,
        'phone': '',
    }
    supabase.table("users").insert(user).execute()
    user['tasks_done'] = set()
    user['ref_friends'] = set()
    user['ref_progress'] = {}
    return user

def save_user(user):
    # tasks_done, ref_friends, ref_progress сериализуем
    user_db = user.copy()
    user_db['tasks_done'] = ','.join(map(str, user.get('tasks_done', set())))
    user_db['ref_friends'] = ','.join(map(str, user.get('ref_friends', set())))
    user_db['ref_progress'] = json.dumps(user.get('ref_progress', {}))
    supabase.table("users").update(user_db).eq("user_id", user['user_id']).execute()

def get_user_by_ref_code(ref_code):
    res = supabase.table("users").select("*").eq("ref_code", ref_code).execute()
    if not res.data:
        return None
    user = res.data[0]
    user['tasks_done'] = set(map(int, user['tasks_done'].split(','))) if user.get('tasks_done') else set()
    user['ref_friends'] = set(map(int, user['ref_friends'].split(','))) if user.get('ref_friends') else set()
    try:
        user['ref_progress'] = json.loads(user['ref_progress']) if user.get('ref_progress') else {}
    except (json.JSONDecodeError, TypeError):
        user['ref_progress'] = {}
    return user

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
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("📋 Список заданий"), KeyboardButton("🏆 Рейтинг недели"))
    markup.add(KeyboardButton("💰 Мой баланс дублей"), KeyboardButton("🎁 Обменять дубли на призы"))
    markup.add(KeyboardButton("👥 Реферальная программа"), KeyboardButton("🆘 Служба поддержки"))
    markup.add(KeyboardButton("ℹ️ Про игру"), KeyboardButton("📜 Правила"))
    if user_id == admin_id:
        markup.add(KeyboardButton("👑 Админ-панель"))
    return markup

def return_to_main_menu(call=None, user_id=None):
    if call is not None:
        user_id = call.from_user.id
        if hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id'):
            task_name = get_current_task_name(user_id)
            if task_name:
                send_temp_message(user_id, f"Сначала выполните или отмените задание: <b>{task_name}</b>", parse_mode='HTML')
            else:
                send_temp_message(user_id, "Сначала выполните или отмените текущее задание!")
            return
        bot.clear_step_handler_by_chat_id(user_id)
        markup = main_menu_reply_markup(user_id)
        bot.send_message(user_id, "\u2B50 Главное меню:", reply_markup=markup)
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
    elif user_id is not None:
        if hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id'):
            task_name = get_current_task_name(user_id)
            if task_name:
                send_temp_message(user_id, f"Сначала выполните или отмените задание: <b>{task_name}</b>", parse_mode='HTML')
            else:
                send_temp_message(user_id, "Сначала выполните или отмените текущее задание!")
            return
        bot.clear_step_handler_by_chat_id(user_id)
        markup = main_menu_reply_markup(user_id)
        bot.send_message(user_id, "\u2B50 Главное меню:", reply_markup=markup)
        logging.info(f"send_message для возврата в меню: user_id={user_id}")
    else:
        logging.error('return_to_main_menu: не передан call и user_id!')

# --- Приветствие и старт ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    # Обработка реферальных ссылок
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
        if ref_code.isdigit():
            ref_user = get_user_by_ref_code(ref_code)
            if ref_user and ref_user['user_id'] != user_id:
                # Сохраняем реферала
                user = get_user(user_id, message.from_user.username)
                if not user.get('invited_by'):
                    user['invited_by'] = ref_code
                    save_user(user)
                    # Добавляем в список друзей реферала
                    ref_user['ref_friends'].add(user_id)
                    if not isinstance(ref_user['ref_progress'], dict):
                        ref_user['ref_progress'] = {}
                    ref_user['ref_progress'][str(user_id)] = 0
                    save_user(ref_user)
    
    user = get_user(user_id, message.from_user.username)
    # Проверяем, завершена ли регистрация
    if not user.get('full_name') or not user.get('age') or not user.get('city') or not user.get('phone'):
        # Приветствие с подчёркнутым словом и инлайн-кнопкой
        text = (
            "👋 Привет! Я — Нейро Мэн, твой проводник по игре.\n\n"
            "Добро пожаловать в увлекательное путешествие, в котором, выполняя задания, ты сможешь получить __Дубли__, которые сможешь обменять на реальные призы!\n\n"
            "Готов начать? Жми кнопку ниже!"
        )
        # Экранируем спецсимволы для MarkdownV2
        text = text.replace('.', '\\.') \
                   .replace('!', '\\!') \
                   .replace('-', '\\-') \
                   .replace('(', '\\(') \
                   .replace(')', '\\)')
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("Начать играть", callback_data="start_game"))
        bot.send_message(user_id, text, reply_markup=markup, parse_mode="MarkdownV2")
        return
        # --- старый код регистрации ниже ---
        if not user.get('full_name'):
            bot.send_message(user_id, "Давай зарегистрируемся! Как тебя зовут? (Фамилия и Имя)")
            bot.register_next_step_handler(message, reg_full_name)
            return
        if not user.get('age'):
            bot.send_message(user_id, "Сколько тебе лет?")
            bot.register_next_step_handler(message, reg_age)
            return
        if not user.get('city'):
            ask_city(message)
            return
        if not user.get('phone'):
            ask_phone(message)
            return
        return
    # Если регистрация завершена — обычное меню
    return_to_main_menu(message)

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
        text="<b>+10 дублей!</b>\n\nДавай зарегистрируемся, чтобы я мог лучше тебя узнать!\n\nКак тебя зовут? (Фамилия и Имя)",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(call.message, reg_full_name)

def reg_full_name(message):
    if getattr(message.from_user, 'is_bot', False):
        print(f"reg_full_name: попытка регистрации от бота user_id={message.from_user.id}")
        return
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    if not getattr(message, 'text', None):
        bot.send_message(user_id, "Введи Фамилию и Имя (минимум 2 слова, только буквы). Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_full_name)
        return
    name = str(message.text).strip()
    if len(name.split()) < 2 or not re.match(r'^[А-Яа-яA-Za-zЁё\- ]+$', name):
        bot.send_message(user_id, "Введи Фамилию и Имя (минимум 2 слова, только буквы). Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_full_name)
        return
    name = ' '.join([part.capitalize() for part in name.split()])
    user['full_name'] = name
    print(f"reg_full_name: save_user {user_id}")
    save_user(user)
    bot.send_message(user_id, "Сколько тебе лет?")
    bot.register_next_step_handler(message, reg_age)

def reg_age(message):
    if getattr(message.from_user, 'is_bot', False):
        print(f"reg_age: попытка регистрации от бота user_id={message.from_user.id}")
        return
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    if not getattr(message, 'text', None):
        bot.send_message(user_id, "Введи возраст числом. Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_age)
        return
    if not str(message.text).isdigit():
        bot.send_message(user_id, "Введи возраст числом. Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_age)
        return
    try:
        age = int(message.text)
    except Exception as e:
        logger.error(f"Ошибка парсинга возраста: {message.text} ({e})")
        bot.send_message(user_id, "Введи возраст числом. Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_age)
        return
    if age < 10 or age > 100:
        bot.send_message(user_id, "Возраст должен быть от 10 до 100. Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_age)
        return
    user['age'] = age
    print(f"reg_age: save_user {user_id}")
    save_user(user)
    ask_city(message)

def ask_city(message):
    if getattr(message.from_user, 'is_bot', False):
        print(f"ask_city: попытка регистрации от бота user_id={message.from_user.id}")
        return
    user_id = message.from_user.id
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("Ростов-на-Дону", callback_data="city_rostov"),
        telebot.types.InlineKeyboardButton("Другой город", callback_data="city_other")
    )
    bot.send_message(user_id, "Выбери свой город:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["city_rostov", "city_other"])
def city_choice_callback(call):
    if getattr(call.from_user, 'is_bot', False):
        print(f"city_choice_callback: попытка регистрации от бота user_id={call.from_user.id}")
        return
    user_id = call.from_user.id
    user = get_user(user_id, call.from_user.username)
    if call.data == "city_rostov":
        user['city'] = "Ростов-на-Дону"
        print(f"city_choice_callback: save_user {user_id}")
        save_user(user)
        # Передаём фейковый message с нужными полями для ask_phone
        class FakeMessage:
            def __init__(self, from_user, chat):
                self.from_user = from_user
                self.chat = chat
        fake_message = FakeMessage(call.from_user, call.message.chat)
        ask_phone(fake_message)
    else:
        bot.edit_message_text("Введи свой город по прописке:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler_by_chat_id(user_id, reg_city_manual)

def reg_city_manual(message):
    if getattr(message.from_user, 'is_bot', False):
        print(f"reg_city_manual: попытка регистрации от бота user_id={message.from_user.id}")
        return
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    if not getattr(message, 'text', None):
        bot.send_message(user_id, "Введи корректное название города (только буквы, минимум 2 буквы). Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_city_manual)
        return
    city = str(message.text).strip().lower().replace('ё', 'е')
    if not re.match(r'^[а-яa-z\- ]{2,}$', city, re.IGNORECASE):
        bot.send_message(user_id, "Введи корректное название города (только буквы, минимум 2 буквы). Попробуй ещё раз:")
        bot.register_next_step_handler(message, reg_city_manual)
        return
    city = ' '.join([part.capitalize() for part in city.split()])
    user['city'] = city
    print(f"reg_city_manual: save_user {user_id}")
    save_user(user)
    ask_phone(message)

def ask_phone(message):
    if getattr(message.from_user, 'is_bot', False):
        print(f"ask_phone: попытка регистрации от бота user_id={message.from_user.id}")
        return
    user_id = message.from_user.id
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("📱 Отправить номер из Telegram", request_contact=True))
    markup.add(KeyboardButton("✍️ Ввести номер вручную"))
    bot.send_message(user_id, "Укажи свой номер телефона:", reply_markup=markup)
    bot.register_next_step_handler(message, handle_phone)

def handle_phone(message):
    if getattr(message.from_user, 'is_bot', False):
        print(f"handle_phone: попытка регистрации от бота user_id={message.from_user.id}")
        return
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    phone = None
    if hasattr(message, 'contact') and message.contact and getattr(message.contact, 'phone_number', None):
        phone = str(message.contact.phone_number)
    elif getattr(message, 'text', None) and "ввести" in message.text.lower():
        bot.send_message(user_id, "Введи номер телефона в формате +7XXXXXXXXXX:")
        bot.register_next_step_handler(message, handle_phone_manual)
        return
    elif getattr(message, 'text', None):
        phone = str(message.text).strip()
    if not phone or not re.match(r'^\+?\d{10,15}$', phone):
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(KeyboardButton("📱 Отправить номер из Telegram", request_contact=True))
        markup.add(KeyboardButton("✍️ Ввести номер вручную"))
        bot.send_message(user_id, "Укажи свой номер телефона через Telegram или введи вручную:", reply_markup=markup)
        bot.register_next_step_handler(message, handle_phone)
        return
    user['phone'] = phone
    user['balance'] += 25
    print(f"handle_phone: save_user {user_id}")
    save_user(user)
    first_name = str(user.get('full_name', '')).split()[1] if len(str(user.get('full_name', '')).split()) > 1 else str(user.get('full_name', '')).split()[0] if user.get('full_name', '') else ''
    bot.send_message(
        user_id,
        f"<b>Поздравляем, игрок «{first_name}» зарегистрирован!</b>\n\n+25 дублей за регистрацию.\n\nПоехали!",
        parse_mode='HTML'
    )
    bot.clear_step_handler_by_chat_id(user_id)
    return_to_main_menu(None, user_id)

def handle_phone_manual(message):
    if getattr(message.from_user, 'is_bot', False):
        print(f"handle_phone_manual: попытка регистрации от бота user_id={message.from_user.id}")
        return
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    if not getattr(message, 'text', None):
        bot.send_message(user_id, "Введи номер телефона в формате +7XXXXXXXXXX:")
        bot.register_next_step_handler(message, handle_phone_manual)
        return
    phone = str(message.text).strip()
    if not re.match(r'^\+?\d{10,15}$', phone):
        bot.send_message(user_id, "Введи номер телефона в формате +7XXXXXXXXXX:")
        bot.register_next_step_handler(message, handle_phone_manual)
        return
    user['phone'] = phone
    user['balance'] += 25
    print(f"handle_phone_manual: save_user {user_id}")
    save_user(user)
    first_name = str(user.get('full_name', '')).split()[1] if len(str(user.get('full_name', '')).split()) > 1 else str(user.get('full_name', '')).split()[0] if user.get('full_name', '') else ''
    bot.send_message(
        user_id,
        f"<b>Поздравляем, игрок «{first_name}» зарегистрирован!</b>\n\n+25 дублей за регистрацию.\n\nПоехали!",
        parse_mode='HTML'
    )
    bot.clear_step_handler_by_chat_id(user_id)
    return_to_main_menu(None, user_id)

# --- Меню ---
@bot.message_handler(func=lambda m: m.text == "💰 Мой баланс дублей")
def show_balance(message, back_btn=False):
    user_id = message.from_user.id if hasattr(message, 'from_user') else message.message.chat.id
    user = get_user(user_id, message.from_user.username)
    text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔥 Получить ежедневный бонус", callback_data="get_daily_bonus"))
    if back_btn:
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=markup)
    else:
        bot.send_message(user_id, text, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "ℹ️ Про игру")
def about_game(message, back_btn=False):
    text = (
        "<b>О проекте</b>\n\n"
        "Простая, но интересная игра, в которой ты можешь выполнять задания в течение 3 месяцев, получать <b>дубли</b> и обменивать их на реальные призы!\n\n"
        "С нами ты лучше изучишь город, поучаствуешь в творческих акциях, узнаешь много нового и классно проведёшь время.\n\n"
        "<b>Типы заданий:</b>\n• Ежедневные\n• Еженедельные\n\n"
        "<b>За что начисляются дубли:</b>\n"
        "• Выполнение заданий\n"
        "• Приглашение друзей в игру\n"
        "• Ежедневный вход в игру\n"
        "• Победа в недельном рейтинге\n\n"
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
        "• Дубли начисляются только после проверки задания модератором\n"
        "• За нарушения правил — дисквалификация без возврата дублей\n"
        "\nУдачи и честной игры!"
    )
    if back_btn:
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=back_markup())
    else:
        bot.send_message(message.from_user.id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "📋 Список заданий")
def task_list(message, back_btn=False):
    remind_daily_bonus(message.from_user.id)
    user_id = message.from_user.id
    # Защита: нельзя переходить, если есть незавершённое задание
    if hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id'):
        task_name = get_current_task_name(user_id)
        if task_name:
            send_temp_message(user_id, f"Сначала выполните или отмените задание: <b>{task_name}</b>", parse_mode='HTML')
        else:
            send_temp_message(user_id, "Сначала выполните или отмените текущее задание!")
        return
    bot.clear_step_handler_by_chat_id(user_id)
    global tasks
    tasks = get_fresh_tasks()
    user = get_user(user_id, message.from_user.username)
    # Категории
    daily = [t for t in tasks if t.get('category') == 'daily']
    weekly = [t for t in tasks if t.get('category') == 'weekly']
    # Ежедневные
    markup_daily = telebot.types.InlineKeyboardMarkup()
    daily_left = 0
    for task in daily:
        if task['id'] in user['tasks_done']:
            continue
        daily_left += 1
        name = task['name']
        btn_text = f"🔲 {name} (+{task['reward']} дублей)"
        markup_daily.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"do_task_{task['id']}"))
    if daily_left:
        text = "<b>Ежедневные задания:</b>"
        bot.send_message(user_id, text, reply_markup=markup_daily, parse_mode='HTML')
    else:
        bot.send_message(user_id, "<b>Все ежедневные задания выполнены!</b>", parse_mode='HTML')
    # Еженедельные
    markup_weekly = telebot.types.InlineKeyboardMarkup()
    weekly_left = 0
    for task in weekly:
        if task['id'] in user['tasks_done']:
            continue
        weekly_left += 1
        name = task['name']
        btn_text = f"🔲 {name} (+{task['reward']} дублей)"
        markup_weekly.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"do_task_{task['id']}"))
    if weekly_left:
        text = "<b>Еженедельные задания:</b>"
        bot.send_message(user_id, text, reply_markup=markup_weekly, parse_mode='HTML')
    else:
        bot.send_message(user_id, "<b>Все еженедельные задания выполнены!</b>", parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('do_task_'))
def do_task(call):
    user_id = call.from_user.id
    # --- Защита: нельзя открыть новое задание, пока не завершено предыдущее ---
    if hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id'):
        bot.answer_callback_query(call.id, "Сначала завершите или отмените текущее задание!")
        return
    user = get_user(user_id, call.from_user.username)
    try:
        task_id = int(call.data.split('_')[-1])
    except Exception as e:
        logger.error(f"Ошибка парсинга task_id в do_task: {call.data} ({e})")
        bot.answer_callback_query(call.id, "Ошибка данных. Сообщи админу!")
        return
    # Загружаем свежие задания
    global tasks
    tasks = get_fresh_tasks()
    # Просим пруф с кнопкой отмены
    bot.answer_callback_query(call.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_proof"))
    task = next((t for t in tasks if t['id']==task_id), None)
    desc = task['desc'] if task and task.get('desc') else ''
    task_name = task['name'] if task else ''
    text = f"<b>📝 Задание:</b> <b>{task_name}</b>"
    if desc:
        text += f"\n\n{desc}"
    text += "\n\n<em>📷 Пришли скриншот или фото, подтверждающее выполнение.</em>"
    # Сохраняем task_id в user_data для отмены
    if not hasattr(bot, 'user_data'):
        bot.user_data = {}
    bot.user_data[user_id] = {'task_id': task_id, 'msg_id': call.message.message_id}
    msg = bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)
    bot.register_next_step_handler(msg, handle_proof, task_id)

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
    # --- Принимаем только фото (скриншот/фото) как пруф ---
    if message.content_type != 'photo':
        send_temp_message(user_id, "Пожалуйста, пришли подтверждение выполнения задания или отмени его.")
        bot.register_next_step_handler(message, handle_proof, task_id)
        return
    proof_type = 'photo'
    proof_data = message.photo[-1].file_id
    add_pending_task(user_id, task_id, proof_type, proof_data)
    markup_return = InlineKeyboardMarkup()
    markup_return.add(InlineKeyboardButton("📋 Вернуться к заданиям", callback_data="menu_tasks"))
    send_temp_message(user_id, "✅ Задание отправлено на проверку! Пока оно проверяется, ты можешь выполнять другие задания.", delay=10, reply_markup=markup_return)
    # После отправки на проверку — удаляем task_id из user_data и сообщение с описанием задания
    if hasattr(bot, 'user_data') and user_id in bot.user_data:
        msg_id = bot.user_data[user_id].pop('msg_id', None)
        bot.user_data[user_id].pop('task_id', None)
        if msg_id:
            safe_delete_message(user_id, msg_id)
    # Загружаем свежие задания для получения актуального названия
    global tasks
    tasks = get_fresh_tasks()
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
        bot.send_photo(GROUP_ID, proof_data, caption=text, parse_mode='HTML', reply_markup=markup)
    elif proof_type == 'document':
        bot.send_document(GROUP_ID, proof_data, caption=text, parse_mode='HTML', reply_markup=markup)
    else:
        bot.send_message(GROUP_ID, text + f"\n\nПруф: {proof_data}", parse_mode='HTML', reply_markup=markup)

# --- Рефералы ---
@bot.message_handler(func=lambda m: m.text == "👥 Реферальная программа")
def referral(message, back_btn=False):
    if block_if_open_task(message):
        return
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user['ref_code']}"
    text = (
        "<b>Реферальная программа</b>\n\n"
        "Приведи друга и получи 50 дублей!\n\n"
        "Ссылка для друга в сообщении ниже\n"
        "Скопируй ссылку и отправь другу — пусть заходит!\n\n"
        "<b>ВАЖНО!</b> Дубли начисляются после того, как друг выполнит 3 задания.\n"
    )
    # Список друзей и прогресс
    markup = InlineKeyboardMarkup()
    if user['ref_friends']:
        text += "\n<b>Твои приглашённые:</b>\n"
        for fid in user['ref_friends']:
            fuser = get_user(fid)  # Убираем лишний параметр username
            # Фильтруем служебные ключи, оставляем только числовые значения
            done = 0
            for key, value in user['ref_progress'].items():
                if str(key) == str(fid) and isinstance(value, (int, float)):
                    done = int(value)
                    break
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
    if block_if_open_task(message):
        return
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0\n\n<b>Доступные призы:</b>\n"
    
    markup = InlineKeyboardMarkup(row_width=1)
    for prize in prizes:
        if prize['cost'] > 0:
            text += f"• {prize['name']} — <b>{prize['cost']} дублей</b>\n"
            if user['balance'] >= prize['cost']:
                markup.add(InlineKeyboardButton(f"🎁 {prize['name']}", callback_data=f"request_prize_{prize['id']}_{prize['cost']}"))
        else:
            text += f"• {prize['name']}\n"
    # Кнопка маркетплейса только если >= 400 дублей
    if user['balance'] >= 400:
        markup.add(InlineKeyboardButton("🛒 Обменять дубли на товар с маркетплейса", callback_data="marketplace_prize"))
    # Инфо-блок про маркетплейс (вернуть старую формулировку)
    text += "\n<b>Также можете обменять Дубли на товары с маркетплейсов, если дублей не меньше стоимости товара (минимум 400)</b>"
    text += "\n<i>Возможность обмена дублей на призы откроется после накопления 400 дублей.</i>"
    if back_btn:
        bot.edit_message_text(text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=markup)
    else:
        bot.send_message(user_id, text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'marketplace_prize')
def marketplace_prize_callback(call):
    remind_daily_bonus(call.from_user.id)
    user_id = call.from_user.id
    user = get_user(user_id, call.from_user.username)
    if user['balance'] < 400:
        bot.answer_callback_query(call.id, "Минимум для обмена — 400 дублей")
        return
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(telebot.types.KeyboardButton('❌ Отмена'))
    bot.send_message(user_id, "Пришли ссылку на товар, его название или скриншот, а также стоимость в дублях (например: https://ozon.ru/... 1200)", reply_markup=markup)
    bot.register_next_step_handler_by_chat_id(user_id, handle_marketplace_prize)

def handle_marketplace_prize(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    # Если отмена
    if message.text and message.text.strip() == '❌ Отмена':
        bot.send_message(user_id, "Заказ отменён.", reply_markup=telebot.types.ReplyKeyboardRemove())
        return_to_main_menu(None, user_id)
        return
    # Валидация: не принимать кнопки из меню и прочий мусор
    menu_texts = [
        "📋 Список заданий", "💰 Мой баланс дублей", "ℹ️ Про игру", "📜 Правила", "👥 Реферальная программа",
        "🎁 Обменять дубли на призы", "🆘 Служба поддержки", "⬅️ В меню игрока", "📝 Проверка заданий",
        "🛠 Управление заданиями", "📊 Статистика", "👤 Пользователи", "📥 Выгрузка", "📨 Обращения",
        "👑 Админ-панель", "🔙 В главное меню"
    ]
    if message.text in menu_texts:
        bot.send_message(user_id, "Пожалуйста, пришли ссылку, название или скриншот и стоимость дублями.", reply_markup=telebot.types.ReplyKeyboardRemove())
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(telebot.types.KeyboardButton('❌ Отмена'))
        bot.send_message(user_id, "Попробуй ещё раз:", reply_markup=markup)
        bot.register_next_step_handler(message, handle_marketplace_prize)
        return
    text = str(getattr(message, 'text', '') or '')
    cost = None
    link_or_name = None
    file_id = None
    if message.content_type == 'photo':
        link_or_name = '<скриншот>'
        file_id = message.photo[-1].file_id
        if getattr(message, 'caption', None):
            text = str(message.caption or '')
    parts = text.strip().split()
    for part in reversed(parts):
        if part.isdigit():
            cost = int(part)
            break
    if not cost:
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(telebot.types.KeyboardButton('❌ Отмена'))
        bot.send_message(user_id, "Пожалуйста, укажи стоимость дублями (например: https://ozon.ru/... 1200)", reply_markup=markup)
        bot.register_next_step_handler(message, handle_marketplace_prize)
        return
    if user['balance'] < cost:
        bot.send_message(user_id, "❌ Недостаточно дублей!", reply_markup=telebot.types.ReplyKeyboardRemove())
        return
    if not link_or_name:
        link_or_name = str(text.replace(str(cost), '').strip() or '')
    safe_full_name = str(user.get('full_name') or '')
    safe_link_or_name = str(link_or_name or '')
    # --- Supabase insert ---
    res = supabase.table("prize_requests").insert({
        'user_id': user_id,
        'prize_name': '[МАРКЕТПЛЕЙС]',
        'prize_cost': cost,
        'user_balance': user['balance'],
        'additional_info': safe_link_or_name,
        'status': 'pending',
        'created_at': datetime.now().isoformat()
    }).execute()
    request_id = res.data[0]['id'] if res.data and 'id' in res.data[0] else None
    user['balance'] -= cost
    save_user(user)
    desc = f"Пользователь: <a href='tg://user?id={user_id}'>{safe_full_name}</a>\nПриз с маркетплейса: {safe_link_or_name}\nСтоимость: {cost} дублей\nID заявки: {request_id}"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_marketplace_{request_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_marketplace_{request_id}")
    )
    if file_id:
        msg = bot.send_photo(GROUP_ID, file_id, caption=desc, parse_mode='HTML', reply_markup=markup)
    else:
        msg = bot.send_message(GROUP_ID, desc, parse_mode='HTML', reply_markup=markup)
    supabase.table("prize_requests").update({'group_message_id': msg.message_id}).eq("id", request_id).execute()
    bot.send_message(user_id, f"✅ Заявка на приз с маркетплейса отправлена! Списано: {cost} дублей. Ожидайте подтверждения.", reply_markup=telebot.types.ReplyKeyboardRemove())

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_support')
def cancel_support_callback(call):
    user_id = call.from_user.id
    support_states.discard(user_id)
    bot.clear_step_handler_by_chat_id(user_id)
    bot.edit_message_text("❌ Обращение в поддержку отменено.", call.message.chat.id, call.message.message_id)
    return_to_main_menu(call, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_marketplace_') or call.data.startswith('reject_marketplace_'))
def handle_marketplace_moderation(call):
    data = call.data
    approve = data.startswith('approve_marketplace_')
    request_id = int(data.split('_')[-1])
    res = supabase.table("prize_requests").select("user_id, prize_cost, group_message_id").eq("id", request_id).execute()
    if not res.data:
        bot.answer_callback_query(call.id, "Заявка не найдена")
        return
    user_id = res.data[0]['user_id']
    cost = res.data[0]['prize_cost']
    group_msg_id = res.data[0]['group_message_id']
    if approve:
        supabase.table("prize_requests").update({'status': 'approved'}).eq("id", request_id).execute()
        bot.send_message(user_id, "🎉 Ваша заявка на приз с маркетплейса одобрена! Ожидайте, с вами свяжутся для выдачи приза.")
        bot.edit_message_reply_markup(GROUP_ID, group_msg_id, reply_markup=None)
        bot.answer_callback_query(call.id, "Одобрено")
    else:
        supabase.table("prize_requests").update({'status': 'rejected'}).eq("id", request_id).execute()
        user = get_user(user_id)
        user['balance'] += cost
        save_user(user)
        bot.send_message(user_id, "❌ Ваша заявка на приз с маркетплейса отклонена. Дубли возвращены на баланс.")
        bot.edit_message_reply_markup(GROUP_ID, group_msg_id, reply_markup=None)
        bot.answer_callback_query(call.id, "Отклонено")



# --- Поддержка ---
@bot.message_handler(func=lambda m: m.text == "🆘 Служба поддержки")
def support(message, back_btn=False):
    if block_if_open_support(message):
        return
    user_id = message.from_user.id
    support_states.add(user_id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_support"))
    bot.send_message(user_id, "✉️ Напиши свой вопрос, и мы обязательно ответим! Просто отправь сообщение.", reply_markup=markup)
    bot.register_next_step_handler(message, save_support)

def save_support(message):
    user_id = message.from_user.id
    # --- Фильтрация: не сохранять команды/кнопки ---
    menu_texts = [
        "📋 Список заданий", "💰 Мой баланс дублей", "ℹ️ Про игру", "📜 Правила", "👥 Реферальная программа",
        "🎁 Обменять дубли на призы", "🆘 Служба поддержки", "⬅️ В меню игрока", "📝 Проверка заданий",
        "🛠 Управление заданиями", "📊 Статистика", "👤 Пользователи", "📥 Выгрузка", "📨 Обращения",
        "👑 Админ-панель", "🔙 В главное меню"
    ]
    # Если пользователь нажал кнопку вместо написания текста - показываем ошибку и продолжаем ждать текстовое сообщение
    if message.text in menu_texts or message.text.startswith("ПРИЗ ") or message.text.startswith("МАРКЕТ "):
        send_temp_message(user_id, "Пожалуйста, напиши свой вопрос или обращение обычным текстом.")
        bot.register_next_step_handler(message, save_support)
        return
    # Отправляем обращение в группу для модерации
    user = get_user(user_id, message.from_user.username)
    username = user.get('username')
    if username:
        username_str = f" (@{username})"
    else:
        username_str = ""
    
    text = f"<b>🆘 Обращение в поддержку:</b>\n\nПользователь: <a href='tg://user?id={user_id}'>{user['full_name']}</a>{username_str}\n\nСообщение:\n{message.text}"
    
    # Отправляем в группу и сохраняем ID сообщения
    try:
        msg = bot.send_message(GROUP_ID, text, parse_mode='HTML')
        support_messages.append({
            'user_id': user_id, 
            'text': message.text, 
            'group_message_id': msg.message_id,
            'timestamp': datetime.now().isoformat()
        })
        send_temp_message(user_id, "Спасибо! Ваш вопрос отправлен в поддержку. Ожидайте ответа.", delay=10)
    except Exception as e:
        logger.error(f"Ошибка отправки обращения в группу: {e}")
    send_temp_message(user_id, "Спасибо! Ваш вопрос отправлен в поддержку.", delay=10)
    support_states.discard(user_id)
    return_to_main_menu(None, user_id)

@bot.message_handler(commands=['export_users'])
def export_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    users, columns = get_all_users()
    filename = 'users_export.csv'
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for u in users:
            writer.writerow([u.get(col, '') for col in columns])
        f.flush()
        os.fsync(f.fileno())
    with open(filename, 'rb') as f:
        bot.send_document(admin_id, f, caption='Выгрузка пользователей')

# --- Обработка кнопок админ-панели ---
@bot.message_handler(func=lambda m: m.text == "📥 Выгрузка")
def admin_export_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    export_users(message)

@bot.message_handler(func=lambda m: m.text == "🏆 Рейтинг недели")
def weekly_rating(message):
    user_id = message.from_user.id
    # Всегда читаем актуальные данные из Supabase по балансу
    res = supabase.table('users').select('user_id,full_name,balance').order('balance', desc=True).order('user_id', desc=False).limit(100).execute()
    rows = res.data
    top = rows[:10]
    text = '<b>🏆 Топ-10 по балансу:</b>\n'
    for i, row in enumerate(top, 1):
        text += f"{i}. {row['full_name']} — {row['balance']} {plural_dubl(row['balance'])}\n"
    # Место пользователя
    place = next((i+1 for i, row in enumerate(rows) if row['user_id']==user_id), None)
    my_balance = next((row['balance'] for row in rows if row['user_id']==user_id), 0)
    if place:
        text += f"\n<b>Твоё место:</b> {place} из {len(rows)} (у тебя {my_balance} {plural_dubl(my_balance)})"
    else:
        text += "\nТы пока не в рейтинге."
    bot.send_message(user_id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
def admin_stats(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    res = supabase.table('users').select('user_id,balance').execute()
    rows = res.data
    total = len(rows)
    rich = sum(1 for row in rows if row['balance'] >= 400)
    bot.send_message(admin_id, f"Всего пользователей: <b>{total}</b>\n\nС балансом 400+ дублей: <b>{rich}</b>", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "👤 Пользователи")
def admin_users(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    res = supabase.table('users').select('user_id,full_name,balance').limit(20).execute()
    rows = res.data
    text = '<b>Первые 20 пользователей:</b>\n'
    for row in rows:
        text += f"ID: <code>{row['user_id']}</code> | {row['full_name']} | 💰 {row['balance']} дублей\n"
    bot.send_message(admin_id, text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "🏆 Топ рейтинг")
def admin_top_rating(message):
    if message.from_user.id != admin_id:
        bot.send_message(message.from_user.id, "⛔️ Нет доступа.")
        return
    res = supabase.table('users').select('user_id,full_name,balance').order('balance', desc=True).order('user_id', desc=False).limit(100).execute()
    rows = res.data
    text = '<b>🏆 Топ-10 по балансу:</b>\n'
    for i, row in enumerate(rows[:10], 1):
        text += f"{i}. {row['full_name']} — {row['balance']} {plural_dubl(row['balance'])}\n"
    place = next((i+1 for i, row in enumerate(rows) if row['user_id']==admin_id), None)
    my_balance = next((row['balance'] for row in rows if row['user_id']==admin_id), 0)
    if place:
        text += f"\n<b>Твоё место:</b> {place} из {len(rows)} (у тебя {my_balance} {plural_dubl(my_balance)})"
    else:
        text += "\nТы пока не в рейтинге."
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
        user = get_user(msg['user_id'])
        timestamp = msg.get('timestamp', 'Неизвестно')
        group_msg_id = msg.get('group_message_id', 'Не отправлено в группу')
        text += f"ID: <code>{msg['user_id']}</code> | {user['full_name']} | {timestamp}\n"
        text += f"Сообщение: {msg['text'][:50]}{'...' if len(msg['text']) > 50 else ''}\n"
        text += f"ID в группе: {group_msg_id}\n\n"
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
    if hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id'):
        bot.answer_callback_query(call.id, "Сначала завершите или отмените текущее задание!")
        return
    bot.clear_step_handler_by_chat_id(user_id)
    data = call.data
    logging.info(f"Callback: {data} от пользователя {user_id}")
    if data == "menu_tasks":
        # Новый UX: вызываем task_list
        class FakeMessage:
            def __init__(self, from_user):
                self.from_user = from_user
                self.text = "📋 Список заданий"
        fake_message = FakeMessage(call.from_user)
        task_list(fake_message)
        return
    elif data == "menu_rating":
        # Создаём фейковый message-объект для передачи в weekly_rating
        class FakeMessage:
            def __init__(self, from_user):
                self.from_user = from_user
        fake_message = FakeMessage(call.from_user)
        weekly_rating(fake_message)
        return
    elif data == "menu_prizes":
        user = get_user(user_id, call.from_user.username)
        text = f"<b>В твоем рюкзаке:</b> <code>{user['balance']}</code> дублей \U0001F4B0\n\n<b>Доступные призы:</b>\n"
        
        markup = InlineKeyboardMarkup(row_width=1)
        
        for prize in prizes:
            if prize['cost'] > 0:
                text += f"• {prize['name']} — <b>{prize['cost']} дублей</b>\n"
                # Добавляем кнопку только если у пользователя достаточно дублей
                if user['balance'] >= prize['cost']:
                    # Используем ID приза вместо названия для безопасного callback_data
                    markup.add(InlineKeyboardButton(f"🎁 {prize['name']}", callback_data=f"request_prize_{prize['id']}_{prize['cost']}"))
            else:
                text += f"• {prize['name']}\n"
        
        text += "\n<i>Выберите приз для обмена или напишите: <code>МАРКЕТ &lt;ссылка&gt; &lt;стоимость&gt;</code></i>"
        
        markup.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="back_to_menu"))
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
        text += "Выполняй задания в течение 3 месяцев, получай <b>дубли</b> и обменивай их на реальные призы!\n\n"
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
        text += "• Дубли начисляются только после проверки задания модератором\n"
        text += "• За нарушения правил — дисквалификация без возврата дублей\n"
        "\nУдачи и честной игры!"
        markup = back_markup()
        show_section(call, text, markup)
    elif data == "menu_support":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_support"))
        text = "✉️ Напиши свой вопрос, и мы обязательно ответим! Просто отправь сообщение."
        show_section(call, text, markup)
        # Регистрируем обработчик для получения сообщения
        bot.register_next_step_handler_by_chat_id(user_id, save_support)
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
        InlineKeyboardButton("🎁 Заявки на призы", callback_data="admin_prize_requests"),
        InlineKeyboardButton("➕ Добавить дубли", callback_data="admin_add_balance"),
        InlineKeyboardButton("➖ Убрать дубли", callback_data="admin_sub_balance"),
        InlineKeyboardButton("❌ Удалить пользователя", callback_data="admin_delete_user"),
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        InlineKeyboardButton("🛠 Управление заданиями", callback_data="tasks_admin_panel"),
        InlineKeyboardButton("🔄 Новая неделя", callback_data="admin_new_week"),
        InlineKeyboardButton("🏆 Топ рейтинг", callback_data="admin_top_rating"),
        InlineKeyboardButton("💰 Сброс балансов", callback_data="admin_reset_balances"),
        InlineKeyboardButton("⬅️ В меню игрока", callback_data="back_to_menu")
    )
    show_section(call, text, markup)

# --- Состояния для админских действий ---
admin_action_state = {}

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_') or call.data == 'back_to_menu')
def handle_admin_panel(call):
    user_id = call.from_user.id
    if hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id'):
        bot.answer_callback_query(call.id, "Сначала завершите или отмените текущее задание!")
        return
    bot.clear_step_handler_by_chat_id(user_id)
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
        res = supabase.table('users').select('user_id,balance').execute()
        rows = res.data
        total = len(rows)
        rich = sum(1 for row in rows if row['balance'] >= 400)
        text = f"Всего пользователей: <b>{total}</b>\n\nС балансом 400+ дублей: <b>{rich}</b>"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ В меню админа", callback_data="admin_panel"))
        show_section(call, text, markup)
    elif data == "admin_users":
        res = supabase.table('users').select('user_id,full_name,balance').limit(20).execute()
        rows = res.data
        text = '<b>Первые 20 пользователей:</b>\n'
        for row in rows:
            text += f"ID: <code>{row['user_id']}</code> | {row['full_name']} | 💰 {row['balance']} дублей\n"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ В меню админа", callback_data="admin_panel"))
        show_section(call, text, markup)
    elif data == "admin_export":
        res = supabase.table('users').select('*').execute()
        rows = res.data
        filename = 'users_export.csv'
        import csv
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['user_id', 'full_name', 'age', 'city', 'balance', 'ref_code', 'invited_by', 'ref_friends', 'ref_progress', 'tasks_done', 'weekly_earned'])
            for row in rows:
                writer.writerow([
                    row.get('user_id'), row.get('full_name'), row.get('age'), row.get('city'), row.get('balance'),
                    row.get('ref_code'), row.get('invited_by'), row.get('ref_friends'), row.get('ref_progress'),
                    row.get('tasks_done'), row.get('weekly_earned')
                ])
        with open(filename, 'rb') as f:
            bot.send_document(admin_id, f, caption='Выгрузка пользователей')
        bot.answer_callback_query(call.id, "Выгрузка отправлена!")
    elif data == "admin_new_week":
        supabase.table('users').update({'weekly_earned': 0}).neq('user_id', 0).execute()
        bot.answer_callback_query(call.id, "✅ Новая неделя началась! Рейтинг сброшен.")
        return
    elif data == "admin_top_rating":
        res = supabase.table('users').select('user_id,full_name,balance').order('balance', desc=True).order('user_id', desc=False).limit(100).execute()
        rows = res.data
        text = '<b>🏆 Топ-10 по балансу:</b>\n'
        for i, row in enumerate(rows[:10], 1):
            text += f"{i}. {row['full_name']} — {row['balance']} {plural_dubl(row['balance'])}\n"
        place = next((i+1 for i, row in enumerate(rows) if row['user_id']==user_id), None)
        my_balance = next((row['balance'] for row in rows if row['user_id']==user_id), 0)
        if place:
            text += f"\n<b>Твоё место:</b> {place} из {len(rows)} (у тебя {my_balance} {plural_dubl(my_balance)})"
        else:
            text += "\nТы пока не в рейтинге."
        bot.send_message(user_id, text, parse_mode='HTML')
        return
    elif data == "admin_reset_balances":
        supabase.table('users').update({'balance': 0}).neq('user_id', 0).execute()
        bot.send_message(admin_id, "✅ Все балансы сброшены на 0!")
        show_admin_panel(call)
        return
    elif data == "admin_support":
        if not support_messages:
            text = "Нет новых обращений."
        else:
            text = '<b>Последние обращения:</b>\n'
            for msg in support_messages[-10:]:
                user = get_user(msg['user_id'])
                timestamp = msg.get('timestamp', 'Неизвестно')
                group_msg_id = msg.get('group_message_id', 'Не отправлено в группу')
                text += f"ID: <code>{msg['user_id']}</code> | {user['full_name']} | {timestamp}\n"
                text += f"Сообщение: {msg['text'][:50]}{'...' if len(msg['text']) > 50 else ''}\n"
                text += f"ID в группе: {group_msg_id}\n\n"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ В меню админа", callback_data="admin_panel"))
        show_section(call, text, markup)
    elif data == "admin_prize_requests":
        requests = get_pending_prize_requests()
        if not requests:
            text = "Нет заявок на призы."
        else:
            text = '<b>🎁 Заявки на призы:</b>\n\n'
            for request in requests:
                user = get_user(request[1])  # user_id
                text += f"<b>Заявка #{request[0]}</b>\n"
                text += f"Пользователь: {user['full_name']} (ID: {request[1]})\n"
                text += f"Приз: {request[2]}\n"
                text += f"Стоимость: {request[3]} дублей\n"
                text += f"Баланс пользователя: {request[4]} дублей\n"
                text += f"Дата: {request[8]}\n\n"
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
        if len(parts) != 2:
            raise ValueError("Неверное количество аргументов")
        uid = int(parts[0])
        amount = int(parts[1])
    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка парсинга uid/amount в admin_balance_step: {message.text} ({e})")
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
    except Exception as e:
        logger.error(f"Ошибка парсинга uid в admin_delete_user_step: {message.text} ({e})")
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
    try:
        uid = int(call.data.split('_')[-1])
    except Exception as e:
        logger.error(f"Ошибка парсинга uid в admin_confirm_delete: {call.data} ({e})")
        bot.answer_callback_query(call.id, "Ошибка данных. Сообщи админу!")
        return
    supabase.table("pending_tasks").delete().eq("user_id", uid).execute()
    supabase.table("users").delete().eq("user_id", uid).execute()
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
    res = supabase.table("users").select("user_id").execute()
    user_ids = [row['user_id'] for row in res.data]
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
    supabase.table("pending_tasks").insert({
        'user_id': user_id,
        'task_id': task_id,
        'proof_type': proof_type,
        'proof_data': proof_data,
        'status': 'pending'
    }).execute()

def get_pending_tasks():
    res = supabase.table("pending_tasks").select("id, user_id, task_id, proof_type, proof_data").eq("status", "pending").execute()
    if not res.data:
        return []
    return [(row['id'], row['user_id'], row['task_id'], row['proof_type'], row['proof_data']) for row in res.data]

def set_pending_task_status(task_id, status):
    supabase.table("pending_tasks").update({'status': status}).eq("id", task_id).execute()

# --- Функции для работы с заявками на призы ---
def add_prize_request(user_id, prize_name, prize_cost, user_balance, additional_info=""):
    res = supabase.table("prize_requests").insert({
        'user_id': user_id,
        'prize_name': prize_name,
        'prize_cost': prize_cost,
        'user_balance': user_balance,
        'additional_info': additional_info,
        'status': 'pending',
        'created_at': datetime.now().isoformat()
    }).execute()
    # Возвращаем id заявки
    if res.data and 'id' in res.data[0]:
        return res.data[0]['id']
    return None

def get_pending_prize_requests():
    res = supabase.table("prize_requests").select("*").eq("status", "pending").order("created_at", desc=True).execute()
    return [tuple(row.values()) for row in res.data]

def set_prize_request_status(request_id, status, group_message_id=None):
    update_data = {'status': status}
    if group_message_id:
        update_data['group_message_id'] = group_message_id
    supabase.table("prize_requests").update(update_data).eq("id", request_id).execute()

# --- Обработка кнопок проверки ---
@bot.callback_query_handler(func=lambda call: (call.data.startswith('approve_') or call.data.startswith('reject_')) and not call.data.startswith('approve_prize_') and not call.data.startswith('reject_prize_') and not call.data.startswith('approve_marketplace_') and not call.data.startswith('reject_marketplace_'))
def handle_task_moderation(call):
    data = call.data
    try:
        action, user_id, task_id = data.split('_')
        user_id = int(user_id)
        task_id = int(task_id)
    except Exception as e:
        logger.error(f"Ошибка парсинга user_id/task_id в handle_task_moderation: {data} ({e})")
        bot.answer_callback_query(call.id, "Ошибка данных. Сообщи админу!")
        return
    # Найти заявку через Supabase
    res = supabase.table("pending_tasks").select("id").eq("user_id", user_id).eq("task_id", task_id).eq("status", "pending").execute()
    if not res.data:
        bot.answer_callback_query(call.id, "Заявка уже обработана")
        return
    pending_id = res.data[0]['id']
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Вернуться к заданиям", callback_data="menu_tasks"))
    if action == 'approve':
        set_pending_task_status(pending_id, 'approved')
        user = get_user(user_id)
        global tasks
        tasks = get_fresh_tasks()  # Загружаем свежие задания
        reward = next((t['reward'] for t in tasks if t['id'] == task_id), 0)
        user['balance'] += reward
        user['weekly_earned'] = user.get('weekly_earned', 0) + reward
        user['tasks_done'].add(task_id)
        save_user(user)
        if hasattr(bot, 'user_data') and user_id in bot.user_data:
            bot.user_data[user_id].pop('task_id', None)
        if user.get('invited_by'):
            inviter = get_user_by_ref_code(user['invited_by'])
            if inviter:
                if 'ref_progress' not in inviter or not isinstance(inviter['ref_progress'], dict):
                    inviter['ref_progress'] = {}
                if 'ref_progress' not in user or not isinstance(user['ref_progress'], dict):
                    user['ref_progress'] = {}
                inviter['ref_progress'][user_id] = inviter['ref_progress'].get(user_id, 0) + 1
                user['ref_progress'][user_id] = inviter['ref_progress'][user_id]
                save_user(inviter)
                save_user(user)
                if inviter['ref_progress'][user_id] == 3:
                    awarded_key = f"awarded_{user_id}"
                    if awarded_key not in inviter['ref_progress']:
                        inviter['balance'] += 50
                        inviter['ref_progress'][awarded_key] = True
                        save_user(inviter)
                        bot.send_message(inviter['user_id'], f"🎉 Твой друг {user['full_name']} выполнил 3 задания! +50 дублей.")
                        logger.info(f"Реферальная награда: {inviter['user_id']} получил 50 дублей за {user_id}")
        bot.send_message(user_id, f"✅ Задание подтверждено! +{reward} {plural_dubl(reward)}.", reply_markup=markup)
        bot.send_message(user_id, "Можешь выполнять другие задания!")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.answer_callback_query(call.id, "Задание принято")
    else:
        admin_action_state['reject_task'] = {
            'pending_id': pending_id,
            'user_id': user_id,
            'task_id': task_id,
            'call_message_id': call.message.message_id
        }
        bot.send_message(admin_id, "Укажите причину отклонения задания:", reply_markup=telebot.types.ForceReply(selective=False))
        bot.answer_callback_query(call.id, "Укажите причину отклонения")

# --- Обработка кнопок для заявок на призы ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_prize_') or call.data.startswith('reject_prize_'))
def handle_prize_moderation(call):
    data = call.data
    try:
        if data.startswith('approve_prize_'):
            action = 'approve_prize'
            request_id = int(data.split('_')[-1])
        elif data.startswith('reject_prize_'):
            action = 'reject_prize'
            request_id = int(data.split('_')[-1])
        else:
            raise ValueError("Неизвестный формат данных")
    except Exception as e:
        logger.error(f"Ошибка парсинга request_id в handle_prize_moderation: {data} ({e})")
        bot.answer_callback_query(call.id, "Ошибка данных. Сообщи админу!")
        return
    # Получаем информацию о заявке по id через Supabase
    res = supabase.table("prize_requests").select("*").eq("id", request_id).eq("status", "pending").execute()
    if not res.data:
        bot.answer_callback_query(call.id, "Заявка уже обработана")
        return
    request = res.data[0]
    user_id = request['user_id']
    prize_name = request['prize_name']
    prize_cost = request['prize_cost']
    if action == 'approve_prize':
        set_prize_request_status(request_id, 'approved')
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            logger.error(f"Ошибка удаления кнопок: {e}")
        bot.send_message(user_id, f"🎉 <b>Заявка на приз одобрена!</b>\n\nПриз: <b>{prize_name}</b>\n\nСкоро с вами свяжутся для получения приза.", parse_mode='HTML')
        bot.answer_callback_query(call.id, "Заявка одобрена")
    else:
        admin_action_state['reject_prize'] = {
            'request_id': request_id,
            'user_id': user_id,
            'prize_name': prize_name,
            'prize_cost': prize_cost,
            'call_message_id': call.message.message_id
        }
        bot.send_message(admin_id, "Укажите причину отклонения заявки на приз:", reply_markup=telebot.types.ForceReply(selective=False))
        bot.answer_callback_query(call.id, "Укажите причину отклонения")

# --- Админ-меню для проверки заданий ---
@bot.message_handler(func=lambda m: m.text == "📝 Проверка заданий")
def admin_pending_tasks(message):
    if message.from_user.id != admin_id:
        return
    pending_tasks = get_pending_tasks()
    if not pending_tasks:
        bot.send_message(admin_id, "Нет заявок на проверку.")
        return
    global tasks
    tasks = get_fresh_tasks()  # Загружаем свежие задания
    for row in pending_tasks:
        pid, user_id, task_id, proof_type, proof_data = row
        try:
            user_id = int(user_id)
            task_id = int(task_id)
        except Exception as e:
            logger.error(f"Ошибка парсинга user_id/task_id в admin_pending_tasks: {user_id}, {task_id} ({e})")
            return
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

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_support')
def cancel_support_callback(call):
    user_id = call.from_user.id
    support_states.discard(user_id)
    bot.clear_step_handler_by_chat_id(user_id)
    bot.edit_message_text("❌ Обращение в поддержку отменено.", call.message.chat.id, call.message.message_id)
    return_to_main_menu(call, user_id)





@bot.message_handler(func=lambda m: m.reply_to_message and 'reject_prize' in admin_action_state)
def handle_prize_reject_reason(message):
    if message.from_user.id != admin_id:
        return
    if 'reject_prize' not in admin_action_state:
        return
    reason = (message.text or '').strip()
    prize_data = admin_action_state.pop('reject_prize')
    request_id = prize_data['request_id']
    user_id = prize_data['user_id']
    prize_name = prize_data['prize_name']
    prize_cost = prize_data['prize_cost']
    call_message_id = prize_data['call_message_id']
    set_prize_request_status(request_id, 'rejected')
    user = get_user(user_id)
    user['balance'] += prize_cost
    save_user(user)
    if reason:
        rejection_text = f"❌ <b>Заявка на приз отклонена</b>\n\nПриз: <b>{prize_name}</b>\nПричина: {reason}\n\nДубли возвращены на баланс."
    else:
        rejection_text = f"❌ <b>Заявка на приз отклонена</b>\n\nПриз: <b>{prize_name}</b>\n\nДубли возвращены на баланс."
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎁 Обменять дубли на призы", callback_data="menu_prizes"))
    bot.send_message(user_id, rejection_text, parse_mode='HTML', reply_markup=markup)
    try:
        bot.edit_message_reply_markup(GROUP_ID, call_message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка удаления кнопок: {e}")
    bot.send_message(admin_id, f"✅ Заявка на приз отклонена. Причина: {reason if reason else 'без причины'}")

# --- Админ-панель управления заданиями ---
@bot.message_handler(func=lambda m: m.text == '🛠 Управление заданиями')
def admin_tasks_panel(message):
    if message.from_user.id != admin_id:
        return
    show_tasks_admin_panel(message)

def show_tasks_admin_panel(message_or_call):
    global tasks
    tasks = get_fresh_tasks()
    markup = telebot.types.InlineKeyboardMarkup()
    for t in tasks:
        try:
            name = str(t.get('name') or '')
            category = str(t.get('category') or '')
            markup.add(
                telebot.types.InlineKeyboardButton(
                    f"{name} ({'ежедневное' if category=='daily' else 'еженедельное'})",
                    callback_data=f"edit_task_{t['id']}"
                ),
                telebot.types.InlineKeyboardButton("❌", callback_data=f"delete_task_{t['id']}")
            )
        except Exception as e:
            print(f"Ошибка в задании {t}: {e}")
    markup.add(telebot.types.InlineKeyboardButton("➕ Добавить новое задание", callback_data="add_task"))
    thread_id = getattr(getattr(message_or_call, 'message', message_or_call), 'message_thread_id', None)
    chat_id = getattr(getattr(message_or_call, 'message', message_or_call), 'chat', None)
    if hasattr(message_or_call, 'message'):
        # Убираем message_thread_id из edit_message_text
        bot.edit_message_text("<b>Управление заданиями</b>", message_or_call.message.chat.id, message_or_call.message.message_id, reply_markup=markup, parse_mode='HTML')
    else:
        if thread_id:
            bot.send_message(chat_id.id, "<b>Управление заданиями</b>", reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)
        else:
            bot.send_message(message_or_call.from_user.id, "<b>Управление заданиями</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: re.match(r'^edit_task_\\d+$', call.data))
def edit_task_start(call):
    if call.from_user.id != admin_id:
        return
    task_id = int(call.data.split('_')[-1])
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        bot.answer_callback_query(call.id, "Задание не найдено")
        return
    text = f"<b>Редактирование задания:</b>\nНазвание: {task['name']}\nНаграда: {task['reward']}\nКатегория: {'ежедневное' if task['category']=='daily' else 'еженедельное'}"
    if task.get('desc'):
        text += f"\n\n<em>Описание:</em> {task['desc']}"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✏️ Изменить название", callback_data=f"edit_task_name_{task_id}"),
        telebot.types.InlineKeyboardButton("💰 Изменить награду", callback_data=f"edit_task_reward_{task_id}"),
        telebot.types.InlineKeyboardButton("🔄 Категорию", callback_data=f"edit_task_cat_{task_id}"),
        telebot.types.InlineKeyboardButton("📝 Описание", callback_data=f"edit_task_desc_{task_id}")
    )
    markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data="tasks_admin_panel"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == 'tasks_admin_panel')
def back_to_tasks_admin_panel(call):
    # Если это личка и админ — показываем админ-панель
    if call.message.chat.type == 'private' and call.from_user.id == admin_id:
        show_tasks_admin_panel(call)
    # Если это группа и нужная тема — показываем публичную панель
    elif call.message.chat.id == GROUP_ID and getattr(call.message, 'message_thread_id', None) == TASKS_PANEL_THREAD_ID:
        show_tasks_filter_panel(call.message)
    else:
        bot.answer_callback_query(call.id, 'Нет доступа или не та локация.')

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_task_name_'))
def edit_task_name(call):
    if call.from_user.id != admin_id:
        return
    task_id = int(call.data.split('_')[-1])
    bot.send_message(admin_id, "Введи новое название задания:")
    bot.register_next_step_handler_by_chat_id(admin_id, lambda m: save_task_name(m, task_id, call.message.message_id))

def save_task_name(message, task_id, msg_id):
    for t in tasks:
        if t['id'] == task_id:
            t['name'] = md_links_to_html(message.text)
            break
    save_tasks(tasks)
    bot.send_message(admin_id, "Название обновлено.")
    show_tasks_admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_task_reward_'))
def edit_task_reward(call):
    if call.from_user.id != admin_id:
        return
    task_id = int(call.data.split('_')[-1])
    bot.send_message(admin_id, "Введи новую награду (число):")
    bot.register_next_step_handler_by_chat_id(admin_id, lambda m: save_task_reward(m, task_id, call.message.message_id))

def save_task_reward(message, task_id, msg_id):
    try:
        reward = int(message.text.strip())
    except Exception:
        bot.send_message(admin_id, "Некорректное число. Попробуй ещё раз.")
        bot.register_next_step_handler_by_chat_id(admin_id, lambda m: save_task_reward(m, task_id, msg_id))
        return
    for t in tasks:
        if t['id'] == task_id:
            t['reward'] = reward
            break
    save_tasks(tasks)
    bot.send_message(admin_id, "Награда обновлена.")
    show_tasks_admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_task_cat_'))
def edit_task_cat(call):
    if call.from_user.id != admin_id:
        return
    task_id = int(call.data.split('_')[-1])
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("Ежедневное", callback_data=f"set_task_cat_daily_{task_id}"),
        telebot.types.InlineKeyboardButton("Еженедельное", callback_data=f"set_task_cat_weekly_{task_id}")
    )
    bot.edit_message_text("Выбери категорию:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_task_cat_'))
def set_task_cat(call):
    if call.from_user.id != admin_id:
        return
    cat, task_id = call.data.split('_')[-2:]
    if cat not in ("daily", "weekly"):
        cat = "daily"
    for t in tasks:
        if t['id'] == int(task_id):
            t['category'] = cat
            break
    save_tasks(tasks)
    bot.answer_callback_query(call.id, "Категория обновлена")
    show_tasks_admin_panel(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_task_'))
def delete_task(call):
    if call.from_user.id != admin_id:
        return
    task_id = int(call.data.split('_')[-1])
    global tasks
    tasks = [t for t in tasks if t['id'] != task_id]
    save_tasks(tasks)
    bot.answer_callback_query(call.id, "Задание удалено")
    show_tasks_admin_panel(call)

@bot.callback_query_handler(func=lambda call: call.data == 'add_task')
def add_task_start(call):
    if call.from_user.id != admin_id:
        return
    bot.send_message(admin_id, "Введи название нового задания:")
    bot.register_next_step_handler_by_chat_id(admin_id, add_task_name)

def add_task_name(message):
    name = md_links_to_html(message.text)
    admin_action_state['new_task_name'] = name
    bot.send_message(admin_id, "Введи награду (число):")
    bot.register_next_step_handler_by_chat_id(admin_id, lambda m: add_task_reward(m, name))

def add_task_reward(message, name):
    try:
        reward = int(message.text.strip())
    except Exception:
        bot.send_message(admin_id, "Некорректное число. Попробуй ещё раз.")
        bot.register_next_step_handler_by_chat_id(admin_id, lambda m: add_task_reward(m, name))
        return
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("Ежедневное", callback_data=f"add_task_cat_daily_{reward}"),
        telebot.types.InlineKeyboardButton("Еженедельное", callback_data=f"add_task_cat_weekly_{reward}")
    )
    bot.send_message(admin_id, "Выбери категорию:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_task_cat_'))
def add_task_cat(call):
    if call.from_user.id != admin_id:
        return
    parts = call.data.split('_')
    cat = parts[-2]
    reward = int(parts[-1])
    name = admin_action_state.get('new_task_name', '')
    new_id = max([t['id'] for t in tasks], default=0) + 1
    if cat not in ("daily", "weekly"):
        cat = "daily"
    admin_action_state['new_task'] = {'id': new_id, 'name': name, 'reward': reward, 'category': cat}
    bot.send_message(admin_id, "Введи описание задания (или оставь пустым):")
    bot.register_next_step_handler_by_chat_id(admin_id, save_new_task_with_desc)

def save_new_task_with_desc(message):
    global tasks
    desc = md_links_to_html(message.text)
    task = admin_action_state.pop('new_task', None)
    if not task:
        bot.send_message(admin_id, "Ошибка: не найдены параметры задания. Попробуй добавить заново.")
        return
    task['desc'] = desc
    tasks.append(task)
    save_tasks(tasks)
    tasks = get_fresh_tasks()
    bot.send_message(admin_id, "Задание добавлено! Список заданий обновлён.")
    show_tasks_admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_task_desc_'))
def edit_task_desc(call):
    if call.from_user.id != admin_id:
        return
    task_id = int(call.data.split('_')[-1])
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        bot.answer_callback_query(call.id, "Задание не найдено")
        return
    # Показываем force_reply для ввода нового описания
    msg = bot.send_message(admin_id, f"Введи новое описание для задания '{task['name']}' (или оставь пустым):", reply_markup=telebot.types.ForceReply(selective=False))
    # Сохраняем task_id в admin_action_state
    admin_action_state['edit_desc_task_id'] = task_id
    admin_action_state['edit_desc_msg_id'] = msg.message_id

@bot.message_handler(func=lambda m: m.reply_to_message and m.reply_to_message.message_id == admin_action_state.get('edit_desc_msg_id'))
def save_task_desc_force_reply(message):
    task_id = admin_action_state.pop('edit_desc_task_id', None)
    admin_action_state.pop('edit_desc_msg_id', None)
    if task_id is None:
        bot.send_message(admin_id, "Ошибка: не найдено задание для редактирования.")
        return
    for t in tasks:
        if t['id'] == task_id:
            t['desc'] = md_links_to_html(message.text)
            break
    save_tasks(tasks)
    bot.send_message(admin_id, "Описание обновлено.")
    show_tasks_admin_panel(message)

# --- Обработка причины отклонения задания ---
@bot.message_handler(func=lambda m: m.reply_to_message and 'reject_task' in admin_action_state)
def handle_task_reject_reason(message):
    reject_data = admin_action_state.pop('reject_task', None)
    if not reject_data:
        bot.send_message(admin_id, "Ошибка: не найдены данные для отклонения.")
        return
    
    pending_id = reject_data['pending_id']
    user_id = reject_data['user_id']
    task_id = reject_data['task_id']
    call_message_id = reject_data['call_message_id']
    reason = message.text.strip()
    
    # Отклоняем задание
    set_pending_task_status(pending_id, 'rejected')
    
    # Отправляем уведомление пользователю с причиной
    global tasks
    tasks = get_fresh_tasks()
    task_name = next((t['name'] for t in tasks if t['id'] == task_id), '')
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Вернуться к заданиям", callback_data="menu_tasks"))
    
    rejection_text = f"❌ Задание <b>{task_name}</b> отклонено.\n\n<b>Причина:</b> {reason}\n\nПопробуй ещё раз или выбери другое задание."
    bot.send_message(user_id, rejection_text, parse_mode='HTML', reply_markup=markup)
    
    # Снимаем защиту: удаляем task_id из user_data
    if hasattr(bot, 'user_data') and user_id in bot.user_data:
        bot.user_data[user_id].pop('task_id', None)
    
    # Убираем кнопки с сообщения в группе
    try:
        bot.edit_message_reply_markup(GROUP_ID, call_message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка удаления кнопок: {e}")
    
    bot.send_message(admin_id, f"✅ Задание отклонено. Причина: {reason}")

@bot.message_handler(func=lambda m: m.reply_to_message and 'reject_prize' in admin_action_state)
def handle_prize_reject_reason(message):
    if message.from_user.id != admin_id:
        return
    
    if 'reject_prize' not in admin_action_state:
        return
    
    reason = message.text.strip()
    if not reason:
        bot.send_message(admin_id, "Укажите причину отклонения:")
        bot.register_next_step_handler_by_chat_id(admin_id, handle_prize_reject_reason)
        return
    
    # Получаем данные из состояния
    prize_data = admin_action_state.pop('reject_prize')
    request_id = prize_data['request_id']
    user_id = prize_data['user_id']
    prize_name = prize_data['prize_name']
    prize_cost = prize_data['prize_cost']
    call_message_id = prize_data['call_message_id']
    
    # Отклоняем заявку на приз
    set_prize_request_status(request_id, 'rejected')
    
    # Возвращаем дубли пользователю
    user = get_user(user_id)
    user['balance'] += prize_cost
    save_user(user)
    
    # Отправляем уведомление пользователю
    rejection_text = f"❌ <b>Заявка на приз отклонена</b>\n\nПриз: <b>{prize_name}</b>\nПричина: {reason}\n\nДубли возвращены на баланс."
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎁 Обменять дубли на призы", callback_data="menu_prizes"))
    bot.send_message(user_id, rejection_text, parse_mode='HTML', reply_markup=markup)
    
    # Убираем кнопки с сообщения в группе
    try:
        bot.edit_message_reply_markup(GROUP_ID, call_message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка удаления кнопок: {e}")
    
    bot.send_message(admin_id, f"✅ Заявка на приз отклонена. Причина: {reason}")

@bot.callback_query_handler(func=lambda call: call.data == 'admin_delete_user')
def admin_delete_user_start(call):
    if call.from_user.id != admin_id:
        return
    bot.send_message(admin_id, "Введи ID пользователя для удаления:")
    bot.register_next_step_handler_by_chat_id(admin_id, admin_delete_user_step)

def admin_delete_user_step(message):
    if message.from_user.id != admin_id:
        return
    try:
        uid = int(message.text.strip())
    except Exception as e:
        logger.error(f"Ошибка парсинга uid в admin_delete_user_step: {message.text} ({e})")
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
    try:
        uid = int(call.data.split('_')[-1])
    except Exception as e:
        logger.error(f"Ошибка парсинга uid в admin_confirm_delete: {call.data} ({e})")
        bot.answer_callback_query(call.id, "Ошибка данных. Сообщи админу!")
        return
    supabase.table("pending_tasks").delete().eq("user_id", uid).execute()
    supabase.table("users").delete().eq("user_id", uid).execute()
    bot.send_message(admin_id, f"Пользователь {uid} удалён.")
    show_admin_panel(call)



# --- Механика ежедневного входа ---
@bot.message_handler(func=lambda m: m.text == "🔥 Ежедневный вход")
def daily_entry(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username)
    today = datetime.now().date()
    last = None
    try:
        last = datetime.strptime(user.get('last_daily',''), '%Y-%m-%d').date() if user.get('last_daily') else None
    except Exception:
        last = None
    streak = user.get('daily_streak', 0)
    if last == today:
        # Гарантируем, что streak не 0, если уже был вход
        if not streak:
            streak = 1
        bot.send_message(user_id, f"Сегодня ты уже получал дубли! Текущий прогресс: {streak}/7.")
        return
    if last and (today - last).days == 1:
        streak = streak + 1 if streak < 7 else 1
    else:
        streak = 1
    user['balance'] += streak
    user['weekly_earned'] = user.get('weekly_earned', 0) + streak
    user['last_daily'] = today.strftime('%Y-%m-%d')
    user['daily_streak'] = streak
    save_user(user)
    bot.send_message(user_id, f"🔥 Ежедневный вход! +{streak} {plural_dubl(streak)}\nТекущий прогресс: {streak}/7. Если пропустишь день — начнёшь сначала.")

@bot.callback_query_handler(func=lambda call: call.data == "get_daily_bonus")
def get_daily_bonus_callback(call):
    user_id = call.from_user.id
    class FakeMessage:
        def __init__(self, from_user):
            self.from_user = from_user
            self.text = "🔥 Ежедневный вход"
    fake_message = FakeMessage(call.from_user)
    daily_entry(fake_message)
    bot.answer_callback_query(call.id)

def plural_dubl(n):
    if n % 10 == 1 and n % 100 != 11:
        return "дубль"
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return "дубля"
    else:
        return "дублей"

def get_current_task_name(user_id):
    if hasattr(bot, 'user_data') and user_id in bot.user_data and bot.user_data[user_id].get('task_id'):
        task_id = bot.user_data[user_id]['task_id']
        t = next((t for t in tasks if t['id'] == task_id), None)
        if t:
            return t['name']
    return None

# --- Команда рейтинга по балансу ---
@bot.message_handler(func=lambda m: m.text == "🏆 Рейтинг недели")
def weekly_rating(message):
    user_id = message.from_user.id
    # Всегда читаем актуальные данные из базы по балансу
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, full_name, balance FROM users ORDER BY balance DESC, user_id ASC LIMIT 100')
        rows = c.fetchall()
    top = rows[:10]
    text = '<b>🏆 Топ-10 по балансу:</b>\n'
    for i, row in enumerate(top, 1):
        text += f"{i}. {row[1]} — {row[2]} {plural_dubl(row[2])}\n"
    # Место пользователя
    place = next((i+1 for i, row in enumerate(rows) if row[0]==user_id), None)
    my_balance = next((row[2] for row in rows if row[0]==user_id), 0)
    if place:
        text += f"\n<b>Твоё место:</b> {place} из {len(rows)} (у тебя {my_balance} {plural_dubl(my_balance)})"
    else:
        text += "\nТы пока не в рейтинге."
    bot.send_message(user_id, text, parse_mode='HTML')

# --- Обработка ответов на обращения в группе ---
@bot.message_handler(func=lambda m: m.chat.id == GROUP_ID and m.reply_to_message)
def handle_support_reply(message):
    # Проверяем, что это ответ на сообщение с обращением
    if not message.reply_to_message:
        return
    
    # Ищем обращение по ID сообщения в группе
    target_message_id = message.reply_to_message.message_id
    support_request = None
    
    for msg in support_messages:
        if msg.get('group_message_id') == target_message_id:
            support_request = msg
            break
    
    if support_request:
        # Отправляем ответ пользователю
        user_id = support_request['user_id']
        try:
            bot.send_message(user_id, f"💬 <b>Ответ поддержки:</b>\n\n{message.text}", parse_mode='HTML')
            # Отмечаем в группе, что ответ отправлен
            bot.reply_to(message, "✅ Ответ отправлен пользователю")
        except Exception as e:
            logger.error(f"Ошибка отправки ответа пользователю {user_id}: {e}")
            bot.reply_to(message, "❌ Ошибка отправки ответа пользователю")
        return
    
    # Проверяем, что это ответ на заявку приза
    # Ищем ID заявки в тексте сообщения
    prize_id_match = re.search(r'Заявка ID: (\d+)', message.reply_to_message.text)
    if prize_id_match:
        prize_id = int(prize_id_match.group(1))
        
        # Получаем информацию о заявке
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM prize_requests WHERE id=?', (prize_id,))
            request = c.fetchone()
        
        if request:
            user_id = request[1]  # user_id
            prize_name = request[2]  # prize_name
            prize_cost = request[3]  # prize_cost
            
            # Отправляем ответ пользователю
            reply_text = f"<b>🎁 Ответ по заявке на приз:</b>\n\nПриз: <b>{prize_name}</b>\n\n{message.text}"
            
            try:
                bot.send_message(user_id, reply_text, parse_mode='HTML')
                bot.reply_to(message, "✅ Ответ отправлен пользователю")
            except Exception as e:
                logger.error(f"Ошибка отправки ответа по призу: {e}")
                bot.reply_to(message, "❌ Ошибка отправки ответа")

# --- Ежедневное напоминание о бонусе ---
def send_daily_reminder():
    res = supabase.table('users').select('user_id').execute()
    user_ids = [row['user_id'] for row in res.data]
    for user_id in user_ids:
        try:
            user = get_user(user_id)
            streak = user.get('daily_streak', 0)
            today = datetime.now().date()
            last = None
            try:
                last = datetime.strptime(user.get('last_daily',''), '%Y-%m-%d').date() if user.get('last_daily') else None
            except Exception:
                last = None
            if last == today:
                text = f"🔥 Ты уже получил дубли за сегодня! Прогресс: {streak}/7."
                markup = None
            else:
                text = f"🔥 Не забудь получить дубли за ежедневный вход!\n\nПрогресс: {streak}/7."
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("Получить дубли", callback_data="get_daily_bonus"))
            bot.send_message(user_id, text, reply_markup=markup)
        except Exception as e:
            logger.error(f"Ошибка рассылки ежедневки {user_id}: {e}")

# --- Пример запуска через APScheduler ---
scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_reminder, 'cron', hour=9, minute=0)  # каждый день в 9:00 по серверу
scheduler.start()

@bot.callback_query_handler(func=lambda call: call.data.startswith('request_prize_'))
def request_prize_callback(call):
    user_id = call.from_user.id
    user = get_user(user_id, call.from_user.username)
    try:
        parts = call.data.split('_')
        prize_cost = int(parts[-1])
        prize_id = int(parts[2])
        # Ищем приз по ID
        prize = next((p for p in prizes if p['id'] == prize_id and p['cost'] == prize_cost), None)
        if not prize:
            logger.error(f"Приз не найден: ID {prize_id}, стоимость {prize_cost}")
            bot.answer_callback_query(call.id, "Приз не найден")
            return
        prize_name = prize['name']
    except Exception as e:
        logger.error(f"Ошибка парсинга данных приза: {call.data} ({e})")
        bot.answer_callback_query(call.id, "Ошибка данных приза")
        return
    if user['balance'] < prize_cost:
        bot.answer_callback_query(call.id, "Недостаточно дублей!")
        return
    # Создаём заявку на приз
    request_id = add_prize_request(user_id, prize_name, prize_cost, user['balance'])
    username = user.get('username')
    username_str = f" (@{username})" if username else ""
    text = f"<b>🎁 Заявка на приз:</b>\n\nПользователь: <a href='tg://user?id={user_id}'>{user['full_name']}</a>{username_str}\nБаланс: {user['balance']} дублей\n\nПриз: <b>{prize_name}</b>\nСтоимость: {prize_cost} дублей\n\nЗаявка ID: {request_id}"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_prize_{request_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_prize_{request_id}")
    )
    try:
        msg = bot.send_message(GROUP_ID, text, parse_mode='HTML', message_thread_id=TOPIC_ID, reply_markup=markup)
        set_prize_request_status(request_id, 'pending', msg.message_id)
        user['balance'] -= prize_cost
        save_user(user)
        bot.answer_callback_query(call.id, "Заявка отправлена!")
        bot.edit_message_text(f"✅ Заявка на приз <b>{prize_name}</b> отправлена!\n\nСписано: {prize_cost} дублей\nОстаток: {user['balance']} дублей\n\nОжидайте подтверждения.", call.message.chat.id, call.message.message_id, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка отправки заявки на приз: {e}")
        bot.answer_callback_query(call.id, "Ошибка отправки заявки")

def md_links_to_html(text):
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text or '')

def remind_daily_bonus(user_id):
    user = get_user(user_id)
    today = datetime.now().date()
    last = None
    try:
        last = datetime.strptime(user.get('last_daily',''), '%Y-%m-%d').date() if user.get('last_daily') else None
    except Exception:
        last = None
    if last != today:
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("Получить дубли", callback_data="get_daily_bonus"))
        bot.send_message(user_id, "🔥 Не забудь получить дубли за ежедневный вход!", reply_markup=markup)

def start_gsheets_exporter():
    def run_export():
        while True:
            try:
                export_to_gsheets_main()
            except Exception as e:
                print(f"[GSHEETS EXPORT ERROR] {e}")
            time.sleep(300)  # 5 минут
    t = threading.Thread(target=run_export, daemon=True)
    t.start()

# Запуск экспортера при старте
start_gsheets_exporter()

@bot.message_handler(commands=['tasks'])
def cmd_tasks(message):
    show_tasks_filter_panel(message)

def show_tasks_filter_panel(message, notice=None):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🕓 Ежедневные", callback_data="filter_daily"),
        telebot.types.InlineKeyboardButton("🗓 Еженедельные", callback_data="filter_weekly")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📅 По дате", callback_data="filter_by_date"),
        telebot.types.InlineKeyboardButton("🔍 Поиск", callback_data="filter_search")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("➕ Добавить задание", callback_data="public_add_task")
    )
    text = "<b>📝 Управление заданиями</b>\n\nВыберите фильтр или добавьте новое задание."
    if notice:
        text = f"<b>{notice}</b>\n\n" + text
    bot.send_message(
        message.chat.id, text, reply_markup=markup, message_thread_id=getattr(message, 'message_thread_id', None), parse_mode='HTML'
    )

# --- Фильтрация и пагинация ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_'))
def filter_tasks_handler(call):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    filter_type = call.data.replace('filter_', '')
    if filter_type == 'daily':
        filtered = [t for t in tasks if t.get('category') == 'daily']
        show_tasks_page(call, filtered, 0, 'daily')
    elif filter_type == 'weekly':
        filtered = [t for t in tasks if t.get('category') == 'weekly']
        show_tasks_page(call, filtered, 0, 'weekly')
    elif filter_type == 'by_date':
        # Список уникальных дат
        dates = sorted(set(t.get('date') for t in tasks if t.get('date')))
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        for d in dates:
            markup.add(telebot.types.InlineKeyboardButton(d, callback_data=f"filter_date_{d}"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data="public_back_to_filter"))
        bot.edit_message_text(
            "<b>Выберите дату:</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML', message_thread_id=call.message.message_thread_id
        )
    elif filter_type == 'search':
        msg = bot.send_message(call.message.chat.id, "Введите часть названия для поиска:", message_thread_id=call.message.message_thread_id)
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, search_tasks_by_name, call.message.chat.id, call.message.message_thread_id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_date_'))
def filter_by_date_handler(call):
    date = call.data.replace('filter_date_', '')
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    filtered = [t for t in tasks if t.get('date') == date]
    show_tasks_page(call, filtered, 0, f'date_{date}')

# --- Пагинация ---
TASKS_PER_PAGE = 5

def show_tasks_page(call, tasks, page, filter_key):
    total = len(tasks)
    start = page * TASKS_PER_PAGE
    end = start + TASKS_PER_PAGE
    page_tasks = tasks[start:end]
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for t in page_tasks:
        btn_text = f"{t['name']} | {('🗓 ' + t.get('date', '-')) if t.get('date') else ''} | {('🕓 Ежедневное' if t['category']=='daily' else '🗓 Еженедельное') if t.get('category') else ''}"
        markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"public_task_{t['id']}"))
    nav = []
    if start > 0:
        nav.append(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{filter_key}_{page-1}"))
    if end < total:
        nav.append(telebot.types.InlineKeyboardButton("Вперёд ➡️", callback_data=f"page_{filter_key}_{page+1}"))
    if nav:
        markup.add(*nav)
    markup.add(telebot.types.InlineKeyboardButton("⬅️ К фильтрам", callback_data="public_back_to_filter"))
    text = f"<b>Задания ({start+1}-{min(end,total)} из {total})</b>"
    bot.edit_message_text(
        text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML', message_thread_id=call.message.message_thread_id
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('page_'))
def paginate_tasks_handler(call):
    parts = call.data.split('_')
    filter_key = '_'.join(parts[1:-1])
    page = int(parts[-1])
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    if filter_key == 'daily':
        filtered = [t for t in tasks if t.get('category') == 'daily']
    elif filter_key == 'weekly':
        filtered = [t for t in tasks if t.get('category') == 'weekly']
    elif filter_key.startswith('date'):
        date = filter_key.split('_', 1)[1]
        filtered = [t for t in tasks if t.get('date') == date]
    else:
        filtered = tasks
    show_tasks_page(call, filtered, page, filter_key)

@bot.callback_query_handler(func=lambda call: call.data == 'public_back_to_filter')
def back_to_filter_panel(call):
    bot.edit_message_text(
        "<b>📝 Управление заданиями</b>\n\nВыберите фильтр или добавьте новое задание.",
        call.message.chat.id, call.message.message_id,
        reply_markup=telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🕓 Ежедневные", callback_data="filter_daily"),
            telebot.types.InlineKeyboardButton("🗓 Еженедельные", callback_data="filter_weekly"),
            telebot.types.InlineKeyboardButton("📅 По дате", callback_data="filter_by_date"),
            telebot.types.InlineKeyboardButton("🔍 Поиск", callback_data="filter_search"),
            telebot.types.InlineKeyboardButton("➕ Добавить задание", callback_data="public_add_task")
        ),
        parse_mode='HTML',
        message_thread_id=call.message.message_thread_id
    )

# --- Поиск по названию ---
def search_tasks_by_name(message, chat_id, thread_id, msg_id):
    query = message.text.strip().lower()
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    filtered = [t for t in tasks if query in t['name'].lower()]
    if not filtered:
        bot.send_message(chat_id, "Ничего не найдено.", message_thread_id=thread_id)
        return
    # Показываем первую страницу поиска
    fake_call = type('FakeCall', (), {
        'message': type('FakeMsg', (), {'chat': type('FakeChat', (), {'id': chat_id})(), 'message_id': msg_id, 'message_thread_id': thread_id})(),
        'data': ''
    })()
    show_tasks_page(fake_call, filtered, 0, f'search_{query}')

@bot.callback_query_handler(func=lambda call: call.data.startswith('public_task_'))
def public_task_menu(call):
    task_id = int(call.data.split('_')[-1])
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        bot.answer_callback_query(call.id, "Задание не найдено")
        return
    status = "🟢 Открыто" if task.get('date', '') <= datetime.now().strftime('%Y-%m-%d') else f"🔴 Откроется {task.get('date', '-')}"
    text = (
        f"<b>Задание:</b> {task['name']}\n"
        f"<b>Описание:</b> {task['desc']}\n"
        f"<b>Категория:</b> {'🕓 Ежедневное' if task['category']=='daily' else '🗓 Еженедельное'}\n"
        f"<b>Награда:</b> {task['reward']}\n"
        f"<b>Дата открытия:</b> {task.get('date', '-')}\n"
        f"<b>Статус:</b> {status}"
    )
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✏️ Название", callback_data=f"edit_task_name_{task_id}"),
        telebot.types.InlineKeyboardButton("📝 Описание", callback_data=f"edit_task_desc_{task_id}"),
    )
    markup.add(
        telebot.types.InlineKeyboardButton("💰 Награда", callback_data=f"edit_task_reward_{task_id}"),
        telebot.types.InlineKeyboardButton("🗓 Дата", callback_data=f"edit_task_date_{task_id}"),
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🔄 Категория", callback_data=f"edit_task_cat_{task_id}"),
        telebot.types.InlineKeyboardButton("❌ Удалить", callback_data=f"public_delete_task_{task_id}"),
    )
    markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data="public_back_to_list"))
    bot.edit_message_text(
        text, call.message.chat.id, call.message.message_id, reply_markup=markup, message_thread_id=call.message.message_thread_id, parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: call.data == 'public_back_to_list')
def public_back_to_list(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_tasks_public_panel(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'public_add_task')
def public_add_task_start(call):
    msg = bot.send_message(call.message.chat.id, "Введите <b>название</b> задания:", parse_mode='HTML', message_thread_id=call.message.message_thread_id)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, public_add_task_name, call.message.chat.id, call.message.message_thread_id)

def public_add_task_name(message, chat_id, thread_id):
    task = {'name': message.text.strip()}
    msg = bot.send_message(chat_id, "Введите <b>описание</b> задания:", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, public_add_task_desc, chat_id, thread_id, task)

def public_add_task_desc(message, chat_id, thread_id, task):
    task['desc'] = message.text.strip()
    msg = bot.send_message(chat_id, "Введите <b>награду</b> за выполнение (число):", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, public_add_task_reward, chat_id, thread_id, task)

def public_add_task_reward(message, chat_id, thread_id, task):
    try:
        task['reward'] = int(message.text.strip())
    except Exception:
        bot.send_message(chat_id, "Некорректная награда. Введите число:", message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, public_add_task_reward, chat_id, thread_id, task)
        return
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("🕓 Ежедневное", callback_data="public_add_task_cat_daily"),
        telebot.types.InlineKeyboardButton("🗓 Еженедельное", callback_data="public_add_task_cat_weekly")
    )
    bot.send_message(chat_id, "Выберите <b>категорию</b> задания:", reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)
    # Сохраняем task в user_data по chat_id
    if not hasattr(bot, 'user_data'): bot.user_data = {}
    bot.user_data[chat_id] = {'add_task': task, 'thread_id': thread_id}

@bot.callback_query_handler(func=lambda call: call.data.startswith('public_add_task_cat_'))
def public_add_task_cat(call):
    cat = call.data.split('_')[-1]
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    task = bot.user_data.get(chat_id, {}).get('add_task', {})
    task['category'] = 'daily' if cat == 'daily' else 'weekly'
    msg = bot.send_message(chat_id, "Введите <b>дату открытия</b> задания в формате ГГГГ-ММ-ДД (или 'сегодня'):", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, public_add_task_date, chat_id, thread_id, task)

def public_add_task_date(message, chat_id, thread_id, task):
    date_str = message.text.strip().lower()
    if date_str == 'сегодня':
        date_str = datetime.now().strftime('%Y-%m-%d')
    try:
        y, m, d = map(int, date_str.split('-'))
        _ = calendar.timegm((y, m, d, 0, 0, 0))
        task['date'] = f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        bot.send_message(chat_id, "Некорректная дата. Введите в формате ГГГГ-ММ-ДД:", message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, public_add_task_date, chat_id, thread_id, task)
        return
    # id и сохранение
    task['id'] = get_next_task_id()
    try:
        with open('tasks.json', 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    except Exception:
        tasks = []
    tasks.append(task)
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_tasks_public_panel(message, notice=f"Задание '{task['name']}' добавлено!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('public_delete_task_'))
def public_delete_task(call):
    task_id = int(call.data.split('_')[-1])
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    tasks = [t for t in tasks if t['id'] != task_id]
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_tasks_public_panel(call.message, notice="Задание удалено!")

# Аналогично можно реализовать public_edit_task (по шагам, как добавление)

def get_next_task_id():
    try:
        with open('tasks.json', 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        return max([t['id'] for t in tasks]) + 1 if tasks else 1
    except Exception:
        return 1

def post_or_replace_tasks_panel(chat_id, thread_id, notice=None):
    # Удаляем старое сообщение-панель, если есть
    try:
        with open("tasks_panel_msg_id.txt") as f:
            old_msg_id = int(f.read())
        bot.delete_message(chat_id, old_msg_id)
    except Exception:
        pass
    # Отправляем новое меню с фильтрами, пагинацией и поиском
    class FakeMessage:
        def __init__(self, chat_id, thread_id):
            self.chat = type('FakeChat', (), {'id': chat_id})()
            self.message_thread_id = thread_id
    fake_msg = FakeMessage(chat_id, thread_id)
    show_tasks_filter_panel(fake_msg, notice)
    # show_tasks_filter_panel сам отправляет сообщение, но не сохраняет message_id
    # Поэтому ниже ловим последнее сообщение и сохраняем его id
    # (или доработай show_tasks_filter_panel, если нужно)
    # ---
    # Альтернативно: можно доработать show_tasks_filter_panel, чтобы возвращать message_id

# Используй post_or_replace_tasks_panel вместо show_tasks_public_panel после любого изменения заданий:
# post_or_replace_tasks_panel(chat_id, thread_id, notice="Задание добавлено!")

# --- Автоматизация панели управления заданиями в теме ---
def auto_post_tasks_panel():
    try:
        show_tasks_moder_panel(TASKS_PANEL_CHAT_ID, TASKS_PANEL_THREAD_ID)
    except Exception as e:
        print(f"Ошибка автопоста панели заданий: {e}")

# Вызовем автопанель при старте бота
import threading
threading.Timer(2, auto_post_tasks_panel).start()

# --- Флаг visible для заданий ---
# При добавлении нового задания: task['visible'] = True
# При скрытии: task['visible'] = False
# При показе: task['visible'] = True

# --- Публичная панель заданий (только в теме 142) ---
def show_tasks_moder_panel(chat_id, thread_id, notice=None):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    tasks = sorted(tasks, key=lambda t: (t.get('date', ''), t['name']))
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for task in tasks:
        if not task.get('visible', True):
            btn_text = f"❌ {task['name']} (скрыто)"
        else:
            btn_text = f"{task['name']}"
        markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"mod_task_{task['id']}"))
    markup.add(telebot.types.InlineKeyboardButton("➕ Добавить задание", callback_data="mod_add_task"))
    text = "<b>Панель модератора: задания</b>\n\nВыберите задание для управления или добавьте новое."
    if notice:
        text = f"<b>{notice}</b>\n\n" + text
    msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)
    # Можно сохранять msg.message_id для удаления старой панели

# --- Карточка задания для модератора ---
def show_task_moder_card(chat_id, thread_id, task_id):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        show_tasks_moder_panel(chat_id, thread_id, notice="Задание не найдено!")
        return
    text = f"<b>Задание:</b> {task['name']}\n<b>Описание:</b> {task['desc']}\n<b>Категория:</b> {'🕓 Ежедневное' if task['category']=='daily' else '🗓 Еженедельное'}\n<b>Награда:</b> {task['reward']}\n<b>Дата:</b> {task.get('date', '-')}\n<b>Статус:</b> {'🟢 Показано' if task.get('visible', True) else '❌ Скрыто'}"
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("✏️ Изменить", callback_data=f"mod_edit_{task_id}"),
        telebot.types.InlineKeyboardButton("❌ Удалить", callback_data=f"mod_delete_{task_id}"),
        telebot.types.InlineKeyboardButton("👁 Скрыть" if task.get('visible', True) else "👁‍🗨 Показать", callback_data=f"mod_toggle_{task_id}")
    )
    markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data="mod_back"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)

# --- Обработчики для модераторов (только в теме 142) ---
@bot.callback_query_handler(func=lambda call: call.message.chat.id == GROUP_ID and getattr(call.message, 'message_thread_id', None) == TASKS_PANEL_THREAD_ID and call.from_user.id in MODERATOR_IDS and call.data.startswith('mod_'))
def moder_tasks_callback(call):
    data = call.data
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    if data == 'mod_add_task':
        msg = bot.send_message(chat_id, "Введите <b>название</b> задания:", parse_mode='HTML', message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, moder_add_task_name, chat_id, thread_id, {})
        return
    if data == 'mod_back':
        show_tasks_moder_panel(chat_id, thread_id)
        return
    if data.startswith('mod_task_'):
        task_id = int(data.split('_')[-1])
        show_task_moder_card(chat_id, thread_id, task_id)
        return
    if data.startswith('mod_delete_'):
        task_id = int(data.split('_')[-1])
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("❌ Подтвердить удаление", callback_data=f"mod_confirmdel_{task_id}"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data=f"mod_task_{task_id}"))
        bot.send_message(chat_id, "Точно удалить задание?", reply_markup=markup, message_thread_id=thread_id)
        return
    if data.startswith('mod_confirmdel_'):
        task_id = int(data.split('_')[-1])
        with open('tasks.json', 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        tasks = [t for t in tasks if t['id'] != task_id]
        with open('tasks.json', 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        show_tasks_moder_panel(chat_id, thread_id, notice="Задание удалено!")
        return
    if data.startswith('mod_toggle_'):
        task_id = int(data.split('_')[-1])
        with open('tasks.json', 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        for t in tasks:
            if t['id'] == task_id:
                t['visible'] = not t.get('visible', True)
        with open('tasks.json', 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        show_task_moder_card(chat_id, thread_id, task_id)
        return
    if data.startswith('mod_edit_'):
        task_id = int(data.split('_')[-1])
        show_task_moder_edit(chat_id, thread_id, task_id)
        return

# --- Добавление задания (пошагово) ---
def moder_add_task_name(message, chat_id, thread_id, task):
    task['name'] = message.text.strip()
    msg = bot.send_message(chat_id, "Введите <b>описание</b> задания:", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, moder_add_task_desc, chat_id, thread_id, task)

def moder_add_task_desc(message, chat_id, thread_id, task):
    task['desc'] = message.text.strip()
    msg = bot.send_message(chat_id, "Введите <b>награду</b> за выполнение (число):", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, moder_add_task_reward, chat_id, thread_id, task)

def moder_add_task_reward(message, chat_id, thread_id, task):
    try:
        task['reward'] = int(message.text.strip())
    except Exception:
        bot.send_message(chat_id, "Некорректная награда. Введите число:", message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, moder_add_task_reward, chat_id, thread_id, task)
        return
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("🕓 Ежедневное", callback_data="mod_cat_daily"),
        telebot.types.InlineKeyboardButton("🗓 Еженедельное", callback_data="mod_cat_weekly")
    )
    bot.send_message(chat_id, "Выберите <b>категорию</b> задания:", reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)
    bot.user_data[chat_id] = {'add_task': task, 'thread_id': thread_id}

@bot.callback_query_handler(func=lambda call: call.data.startswith('mod_cat_'))
def moder_add_task_cat(call):
    cat = call.data.split('_')[-1]
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    task = bot.user_data.get(chat_id, {}).get('add_task', {})
    task['category'] = 'daily' if cat == 'daily' else 'weekly'
    msg = bot.send_message(chat_id, "Введите <b>дату открытия</b> задания в формате ГГГГ-ММ-ДД (или 'сегодня'):", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, moder_add_task_date, chat_id, thread_id, task)

def moder_add_task_date(message, chat_id, thread_id, task):
    date_str = message.text.strip().lower().replace(' ', '')
    if date_str in ('сегодня', 'today', 'now', 'тудэй'):
        date_str = datetime.now().strftime('%Y-%m-%d')
    try:
        y, m, d = map(int, date_str.split('-'))
        _ = calendar.timegm((y, m, d, 0, 0, 0))
        task['date'] = f"{y:04d}-{m:02d}-{d:02d}"
    except Exception as e:
        bot.send_message(chat_id, "Некорректная дата. Введите в формате ГГГГ-ММ-ДД или 'сегодня':", message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, moder_add_task_date, chat_id, thread_id, task)
        return
    task['visible'] = True
    task['id'] = get_next_task_id()
    try:
        with open('tasks.json', 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    except Exception:
        tasks = []
    tasks.append(task)
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_tasks_moder_panel(chat_id, thread_id, notice=f"Задание '{task['name']}' добавлено!")

# --- Редактирование задания (по полям, с возвратом на страницу) ---
def show_task_moder_edit(chat_id, thread_id, task_id, page=0):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        show_tasks_moder_panel(chat_id, thread_id, notice="Задание не найдено!", page=page)
        return
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("✏️ Название", callback_data=f"mod_edit_name_{task_id}_p{page}"),
        telebot.types.InlineKeyboardButton("📝 Описание", callback_data=f"mod_edit_desc_{task_id}_p{page}"),
        telebot.types.InlineKeyboardButton("💰 Награда", callback_data=f"mod_edit_reward_{task_id}_p{page}"),
        telebot.types.InlineKeyboardButton("🗓 Дата", callback_data=f"mod_edit_date_{task_id}_p{page}"),
        telebot.types.InlineKeyboardButton("🔄 Категория", callback_data=f"mod_edit_cat_{task_id}_p{page}")
    )
    markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data=f"mod_task_{task_id}_p{page}"))
    text = f"<b>Редактирование задания:</b> {task['name']}"
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)

# --- Реальное редактирование каждого поля (по шагам) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('mod_edit_name_'))
def moder_edit_name(call):
    parts = call.data.split('_')
    task_id = int(parts[3])
    page = int(parts[4][1:]) if len(parts) > 4 and parts[4].startswith('p') else 0
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    msg = bot.send_message(chat_id, "Введите новое <b>название</b> задания:", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, moder_save_edit_name, chat_id, thread_id, task_id, page)

def moder_save_edit_name(message, chat_id, thread_id, task_id, page):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    for t in tasks:
        if t['id'] == task_id:
            t['name'] = message.text.strip()
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_task_moder_card(chat_id, thread_id, task_id, page=page)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mod_edit_desc_'))
def moder_edit_desc(call):
    parts = call.data.split('_')
    task_id = int(parts[3])
    page = int(parts[4][1:]) if len(parts) > 4 and parts[4].startswith('p') else 0
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    msg = bot.send_message(chat_id, "Введите новое <b>описание</b> задания:", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, moder_save_edit_desc, chat_id, thread_id, task_id, page)

def moder_save_edit_desc(message, chat_id, thread_id, task_id, page):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    for t in tasks:
        if t['id'] == task_id:
            t['desc'] = message.text.strip()
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_task_moder_card(chat_id, thread_id, task_id, page=page)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mod_edit_reward_'))
def moder_edit_reward(call):
    parts = call.data.split('_')
    task_id = int(parts[3])
    page = int(parts[4][1:]) if len(parts) > 4 and parts[4].startswith('p') else 0
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    msg = bot.send_message(chat_id, "Введите новую <b>награду</b> (число):", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, moder_save_edit_reward, chat_id, thread_id, task_id, page)

def moder_save_edit_reward(message, chat_id, thread_id, task_id, page):
    try:
        reward = int(message.text.strip())
    except Exception:
        bot.send_message(chat_id, "Некорректная награда. Введите число:", message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, moder_save_edit_reward, chat_id, thread_id, task_id, page)
        return
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    for t in tasks:
        if t['id'] == task_id:
            t['reward'] = reward
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_task_moder_card(chat_id, thread_id, task_id, page=page)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mod_edit_date_'))
def moder_edit_date(call):
    parts = call.data.split('_')
    task_id = int(parts[3])
    page = int(parts[4][1:]) if len(parts) > 4 and parts[4].startswith('p') else 0
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    msg = bot.send_message(chat_id, "Введите новую <b>дату</b> (ГГГГ-ММ-ДД или 'сегодня'):", parse_mode='HTML', message_thread_id=thread_id)
    bot.register_next_step_handler_by_chat_id(chat_id, moder_save_edit_date, chat_id, thread_id, task_id, page)

def moder_save_edit_date(message, chat_id, thread_id, task_id, page):
    date_str = message.text.strip().lower().replace(' ', '')
    if date_str in ('сегодня', 'today', 'now', 'тудэй'):
        date_str = datetime.now().strftime('%Y-%m-%d')
    try:
        y, m, d = map(int, date_str.split('-'))
        _ = calendar.timegm((y, m, d, 0, 0, 0))
        date_val = f"{y:04d}-{m:02d}-{d:02d}"
    except Exception as e:
        bot.send_message(chat_id, "Некорректная дата. Введите в формате ГГГГ-ММ-ДД или 'сегодня':", message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, moder_save_edit_date, chat_id, thread_id, task_id, page)
        return
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    for t in tasks:
        if t['id'] == task_id:
            t['date'] = date_val
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_task_moder_card(chat_id, thread_id, task_id, page=page)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mod_edit_cat_'))
def moder_edit_cat(call):
    parts = call.data.split('_')
    task_id = int(parts[3])
    page = int(parts[4][1:]) if len(parts) > 4 and parts[4].startswith('p') else 0
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("🕓 Ежедневное", callback_data=f"mod_setcat_daily_{task_id}_p{page}"),
        telebot.types.InlineKeyboardButton("🗓 Еженедельное", callback_data=f"mod_setcat_weekly_{task_id}_p{page}")
    )
    bot.send_message(chat_id, "Выберите новую <b>категорию</b>:", reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mod_setcat_'))
def moder_set_cat(call):
    parts = call.data.split('_')
    cat = parts[2]
    task_id = int(parts[3])
    page = int(parts[4][1:]) if len(parts) > 4 and parts[4].startswith('p') else 0
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    for t in tasks:
        if t['id'] == task_id:
            t['category'] = 'daily' if cat == 'daily' else 'weekly'
    with open('tasks.json', 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    show_task_moder_card(chat_id, thread_id, task_id, page=page)

# --- Пагинация для панели модератора ---
TASKS_PER_PAGE = 5

def show_tasks_moder_panel(chat_id, thread_id, notice=None, page=0):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    tasks = sorted(tasks, key=lambda t: (t.get('date', ''), t['name']))
    total = len(tasks)
    start = page * TASKS_PER_PAGE
    end = start + TASKS_PER_PAGE
    page_tasks = tasks[start:end]
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for task in page_tasks:
        btn_text = f"❌ {task['name']} (скрыто)" if not task.get('visible', True) else f"{task['name']}"
        markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"mod_task_{task['id']}_p{page}"))
    nav = []
    if start > 0:
        nav.append(telebot.types.InlineKeyboardButton("⬅️", callback_data=f"mod_page_{page-1}"))
    if end < total:
        nav.append(telebot.types.InlineKeyboardButton("➡️", callback_data=f"mod_page_{page+1}"))
    if nav:
        markup.add(*nav)
    markup.add(telebot.types.InlineKeyboardButton("➕ Добавить задание", callback_data=f"mod_add_task_p{page}"))
    text = f"<b>Панель модератора: задания</b>\n\nПоказано {start+1}-{min(end,total)} из {total}."
    if notice:
        text = f"<b>{notice}</b>\n\n" + text
    msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)

# --- Карточка задания с возвратом на нужную страницу ---
def show_task_moder_card(chat_id, thread_id, task_id, page=0):
    with open('tasks.json', 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        show_tasks_moder_panel(chat_id, thread_id, notice="Задание не найдено!", page=page)
        return
    text = f"<b>Задание:</b> {task['name']}\n<b>Описание:</b> {task['desc']}\n<b>Категория:</b> {'🕓 Ежедневное' if task['category']=='daily' else '🗓 Еженедельное'}\n<b>Награда:</b> {task['reward']}\n<b>Дата:</b> {task.get('date', '-')}\n<b>Статус:</b> {'🟢 Показано' if task.get('visible', True) else '❌ Скрыто'}"
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("✏️ Изменить", callback_data=f"mod_edit_{task_id}_p{page}"),
        telebot.types.InlineKeyboardButton("❌ Удалить", callback_data=f"mod_delete_{task_id}_p{page}"),
        telebot.types.InlineKeyboardButton("👁 Скрыть" if task.get('visible', True) else "👁‍🗨 Показать", callback_data=f"mod_toggle_{task_id}_p{page}")
    )
    markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data=f"mod_back_p{page}"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML', message_thread_id=thread_id)

# --- Обработчик callback для модераторов с поддержкой страниц ---
@bot.callback_query_handler(func=lambda call: call.message.chat.id == GROUP_ID and getattr(call.message, 'message_thread_id', None) == TASKS_PANEL_THREAD_ID and call.from_user.id in MODERATOR_IDS and call.data.startswith('mod_'))
def moder_tasks_callback(call):
    data = call.data
    chat_id = call.message.chat.id
    thread_id = call.message.message_thread_id
    # Пагинация
    if data.startswith('mod_page_'):
        page = int(data.split('_')[-1])
        show_tasks_moder_panel(chat_id, thread_id, page=page)
        return
    # Добавление
    if data.startswith('mod_add_task'):
        page = int(data.split('_p')[-1]) if '_p' in data else 0
        msg = bot.send_message(chat_id, "Введите <b>название</b> задания:", parse_mode='HTML', message_thread_id=thread_id)
        bot.register_next_step_handler_by_chat_id(chat_id, moder_add_task_name, chat_id, thread_id, {}, page)
        return
    # Назад
    if data.startswith('mod_back_p'):
        page = int(data.split('_p')[-1])
        show_tasks_moder_panel(chat_id, thread_id, page=page)
        return
    # Карточка задания
    if data.startswith('mod_task_'):
        parts = data.split('_')
        task_id = int(parts[2])
        page = int(parts[3][1:]) if len(parts) > 3 and parts[3].startswith('p') else 0
        show_task_moder_card(chat_id, thread_id, task_id, page=page)
        return
    # Удаление
    if data.startswith('mod_delete_'):
        parts = data.split('_')
        task_id = int(parts[2])
        page = int(parts[3][1:]) if len(parts) > 3 and parts[3].startswith('p') else 0
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("❌ Подтвердить удаление", callback_data=f"mod_confirmdel_{task_id}_p{page}"))
        markup.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data=f"mod_task_{task_id}_p{page}"))
        bot.send_message(chat_id, "Точно удалить задание?", reply_markup=markup, message_thread_id=thread_id)
        return
    if data.startswith('mod_confirmdel_'):
        parts = data.split('_')
        task_id = int(parts[2])
        page = int(parts[3][1:]) if len(parts) > 3 and parts[3].startswith('p') else 0
        with open('tasks.json', 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        tasks = [t for t in tasks if t['id'] != task_id]
        with open('tasks.json', 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        show_tasks_moder_panel(chat_id, thread_id, notice="Задание удалено!", page=page)
        return
    # Скрыть/Показать
    if data.startswith('mod_toggle_'):
        parts = data.split('_')
        task_id = int(parts[2])
        page = int(parts[3][1:]) if len(parts) > 3 and parts[3].startswith('p') else 0
        with open('tasks.json', 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        for t in tasks:
            if t['id'] == task_id:
                t['visible'] = not t.get('visible', True)
        with open('tasks.json', 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        show_task_moder_card(chat_id, thread_id, task_id, page=page)
        return
    # Изменить
    if data.startswith('mod_edit_'):
        parts = data.split('_')
        task_id = int(parts[2])
        page = int(parts[3][1:]) if len(parts) > 3 and parts[3].startswith('p') else 0
        show_task_moder_edit(chat_id, thread_id, task_id, page=page)
        return











if __name__ == "__main__":
    logger.info('Бот запущен!')
    print('Бот запущен!')
    
    # Сбрасываем webhook перед запуском
    try:
        bot.delete_webhook()
        print('Webhook сброшен')
    except Exception as e:
        print(f'Ошибка при сбросе webhook: {e}')
    
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            error_msg = str(e)
            logger.error(f'Ошибка при запуске бота: {error_msg}')
            print(f'Ошибка при запуске бота: {error_msg}')
            
            # Обработка ошибки 409 (конфликт экземпляров)
            if '409' in error_msg or 'Conflict' in error_msg:
                print('Обнаружен конфликт экземпляров бота. Пытаемся исправить...')
                try:
                    # Сбрасываем webhook и получаем обновления
                    bot.delete_webhook()
                    updates = bot.get_updates()
                    if updates:
                        # Удаляем все обновления чтобы избежать повторной обработки
                        bot.get_updates(offset=updates[-1].update_id + 1)
                    print('Конфликт исправлен. Перезапускаем бота...')
                    time.sleep(5)
                    continue
                except Exception as fix_error:
                    print(f'Не удалось исправить конфликт: {fix_error}. Ожидаем 30 секунд...')
                    time.sleep(30)
                    continue
            
            # Для других ошибок - ждем и перезапускаем
            print('Ожидаем 10 секунд перед перезапуском...')
            time.sleep(10) 