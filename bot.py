import telebot
import os
import random

API_TOKEN = os.getenv('TELEGRAM_TOKEN') or '7601370339:AAH_tTzX6GUwkExnxIAUJ5144DZCzUCAGQE'
bot = telebot.TeleBot(API_TOKEN)

print('Бот запущен!')

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
admin_id = None  # сюда можно вписать свой user_id для поддержки
support_messages = []

# --- Вспомогательные функции ---
def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            'balance': 0,
            'full_name': '',
            'age': '',
            'city': '',
            'tasks_done': set(),
            'ref_code': str(user_id),
            'invited_by': None,
            'ref_friends': set(),
            'ref_progress': {},  # user_id: tasks_done_count
        }
    return users[user_id]

def show_menu(user_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Расскажи про игру подробнее")
    markup.add("Правила игры и обмена дублей на подарки")
    markup.add("Список заданий")
    markup.add("Реферальная программа")
    markup.add("Мой баланс дублей")
    markup.add("Обменять дубли на призы")
    markup.add("Служба поддержки")
    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

# --- Регистрация ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user['full_name']:
        bot.send_message(user_id, "Ты уже зарегистрирован!")
        show_menu(user_id)
        return
    user['balance'] += 10
    bot.send_message(user_id, "👋 Привет! Я Тренер — твой проводник в игре!\n\nДобро пожаловать в увлекательное путешествие, в котором, выполняя задания, ты сможешь заработать Дубли, которые сможешь обменять на реальные призы!\n\nТебе начислено 10 дублей за старт.\n\nКак тебя зовут? (ФИ)")
    bot.register_next_step_handler(message, reg_full_name)

def reg_full_name(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    user['full_name'] = message.text
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
    bot.send_message(user_id, "Из какого ты города? (по прописке)")
    bot.register_next_step_handler(message, reg_city)

def reg_city(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    user['city'] = message.text
    user['balance'] += 25
    bot.send_message(user_id, "Поздравляем, игрок зарегистрирован! Поехали.\n\nТебе начислено 25 дублей.")
    show_menu(user_id)

# --- Меню ---
@bot.message_handler(func=lambda m: m.text == "Мой баланс дублей")
def show_balance(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    bot.send_message(user_id, f"В твоем рюкзаке лежит {user['balance']} дублей")

@bot.message_handler(func=lambda m: m.text == "Расскажи про игру подробнее")
def about_game(message):
    text = (
        "Суть игры в выполнении заданий в течении 3 месяцев, за которые ты получаешь дубли. Дубли можно обменять на реальные призы.\n"
        "Задания есть 2 типов:\n- ежедневные\n- еженедельные\n"
        "За каждое выполненное задание ты получаешь дубли. Так же ты получишь дубли, если приведешь в игру друзей.\n"
        "Так же ты будешь получать дубли за ежедневный вход в игру.\n"
        "Остались вопросы? Напиши нам в службу поддержки"
    )
    bot.send_message(message.from_user.id, text)

@bot.message_handler(func=lambda m: m.text == "Правила игры и обмена дублей на подарки")
def rules(message):
    text = (
        "Первое правило игры – рассказывать всем об этой игре.\n"
        "Второе правило – смотри первое правило.\n"
        "На самом деле, как таковых правил практически нет. НО, игра не терпит оскорблений, мата и любой пошлости, как визуальной так и словесной.\n"
        "Правило обмена дублей на призы:\n"
        "- обменять можно в любое время, когда ты накопишь достаточно количество дублей (минимум 400)\n"
        "- Обменять дубли можно на призы из перечня (смотри во вкладке «обменять дубли на призы»)\n"
        "- Так же обменять дубли можно на призы с маркетплейсов (Озон или ВБ), прислав ссылку на товар. Количество дублей в вашем рюкзаке должно быть не меньше стоимости товара на маркетплейсе."
    )
    bot.send_message(message.from_user.id, text)

# --- Задания ---
@bot.message_handler(func=lambda m: m.text == "Список заданий")
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
    bot.send_message(user_id, "Выбери задание для выполнения:", reply_markup=markup)

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
    bot.edit_message_text("Задание выполнено! +{0} дублей".format(reward), user_id, call.message.message_id)
    # Реферальный прогресс
    if user['invited_by']:
        inviter = get_user(int(user['invited_by']))
        inviter['ref_progress'][user_id] = inviter['ref_progress'].get(user_id, 0) + 1
        # Если друг выполнил 3 задания — начислить 100 дублей
        if inviter['ref_progress'][user_id] == 3:
            inviter['balance'] += 100
            inviter['ref_friends'].add(user_id)
            bot.send_message(inviter['ref_code'], f"Твой друг {user['full_name']} выполнил 3 задания! Тебе начислено 100 дублей.")

# --- Рефералы ---
@bot.message_handler(func=lambda m: m.text == "Реферальная программа")
def referral(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    ref_link = f"/start {user['ref_code']}"
    text = (
        "Приведи друга и получи 100 дублей\n"
        f"Ссылка для друга – {ref_link}\n"
        "ВАЖНО!\nТебе будут начислены дубли после того, как твой друг выполнит 3 задания."
    )
    bot.send_message(user_id, text)

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
@bot.message_handler(func=lambda m: m.text == "Обменять дубли на призы")
def exchange_prizes(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    text = f"В твоем рюкзаке лежит {user['balance']} дублей\n"
    for prize in prizes:
        if prize['cost'] > 0:
            text += f"{prize['name']} – {prize['cost']} дублей\n"
        else:
            text += f"{prize['name']}\n"
    text += "\nЧтобы обменять дубли на приз, напиши: ПРИЗ <название>\n"
    text += "Чтобы обменять дубли на товар с маркетплейса, напиши: МАРКЕТ <ссылка> <стоимость>"
    bot.send_message(user_id, text)

@bot.message_handler(regexp=r'^ПРИЗ (.+)')
def buy_prize(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    prize_name = message.text[5:].strip()
    prize = next((p for p in prizes if prize_name.lower() in p['name'].lower()), None)
    if not prize:
        bot.send_message(user_id, "Такого приза нет.")
        return
    if user['balance'] < prize['cost']:
        bot.send_message(user_id, "Недостаточно дублей!")
        return
    user['balance'] -= prize['cost']
    bot.send_message(user_id, f"Поздравляем! Ты обменял {prize['cost']} дублей на приз: {prize['name']}")

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
        bot.send_message(user_id, "Недостаточно дублей!")
        return
    user['balance'] -= cost
    bot.send_message(user_id, f"Поздравляем! Ты обменял {cost} дублей на товар с маркетплейса: {link}")

# --- Поддержка ---
@bot.message_handler(func=lambda m: m.text == "Служба поддержки")
def support(message):
    bot.send_message(message.from_user.id, "Напиши свой вопрос, и мы обязательно ответим! Просто отправь сообщение.")
    bot.register_next_step_handler(message, save_support)

def save_support(message):
    user_id = message.from_user.id
    support_messages.append({'user_id': user_id, 'text': message.text})
    if admin_id:
        bot.send_message(admin_id, f"Вопрос от пользователя {user_id}: {message.text}")
    bot.send_message(user_id, "Спасибо! Ваш вопрос отправлен в поддержку.")

bot.polling(none_stop=True) 