import sqlite3
from datetime import datetime
import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials

DB_PATH = 'users.db'
GSHEET_NAME = 'Город будущего'
RUS_SHEETS = ['Пользователи', 'Поддержка', 'Призы']

# --- Получение всех пользователей и их данных ---
def get_all_users():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users')
        users = c.fetchall()
        columns = [desc[0] for desc in c.description]
    return users, columns

# --- Получение всех выполненных заданий ---
def get_all_user_tasks():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM user_tasks')
        tasks = c.fetchall()
        columns = [desc[0] for desc in c.description]
    return tasks, columns

# --- Получение всех обращений в поддержку ---
def get_all_support():
    # TODO: если обращения хранятся в отдельной таблице, добавить тут
    # Пример: SELECT * FROM support_requests
    # Пока просто заглушка
    return [], []

# --- Получение всех заявок на призы ---
def get_all_prize_requests():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM prize_requests')
        prizes = c.fetchall()
        columns = [desc[0] for desc in c.description]
    return prizes, columns

# --- Формирование данных для Google Sheets ---
def prepare_users_sheet(users, columns):
    # Users: user_id, full_name, age, city, balance, ref_code, invited_by, username, дата регистрации, последний вход, weekly_earned
    header = ['user_id', 'full_name', 'age', 'city', 'balance', 'ref_code', 'invited_by', 'username', 'date_registered', 'last_daily', 'weekly_earned']
    col_idx = {col: i for i, col in enumerate(columns)}
    data = [header]
    for u in users:
        row = [
            u[col_idx.get('user_id')],
            u[col_idx.get('full_name')],
            u[col_idx.get('age')],
            u[col_idx.get('city')],
            u[col_idx.get('balance')],
            u[col_idx.get('ref_code')],
            u[col_idx.get('invited_by')],
            u[col_idx.get('username')],
            '',  # дата регистрации — если есть поле, подставить
            u[col_idx.get('last_daily')],
            u[col_idx.get('weekly_earned')],
        ]
        data.append(row)
    return data

def prepare_support_sheet(support, columns):
    # Support: user_id, full_name, username, сообщение, ответ, время обращения, время ответа
    header = ['user_id', 'full_name', 'username', 'message', 'reply', 'created_at', 'replied_at']
    data = [header]
    # TODO: заполнить, если есть обращения
    return data

def prepare_prizes_sheet(prizes, columns):
    # Prizes: user_id, full_name, username, prize_name, prize_cost, status, created_at, group_message_id
    header = ['user_id', 'full_name', 'username', 'prize_name', 'prize_cost', 'status', 'created_at', 'group_message_id']
    col_idx = {col: i for i, col in enumerate(columns)}
    data = [header]
    for p in prizes:
        # user_id, prize_name, prize_cost, status, created_at, group_message_id
        row = [
            p[col_idx.get('user_id')],
            '',  # full_name — можно подтянуть из users
            '',  # username — можно подтянуть из users
            p[col_idx.get('prize_name')],
            p[col_idx.get('prize_cost')],
            p[col_idx.get('status')],
            p[col_idx.get('created_at')],
            p[col_idx.get('group_message_id')],
        ]
        data.append(row)
    return data

def update_sheet(worksheet, data):
    worksheet.clear()
    worksheet.update('A1', data)

def main():
    users, user_cols = get_all_users()
    tasks, task_cols = get_all_user_tasks()
    prizes, prize_cols = get_all_prize_requests()
    support, support_cols = get_all_support()

    users_sheet = prepare_users_sheet(users, user_cols)
    support_sheet = prepare_support_sheet(support, support_cols)
    prizes_sheet = prepare_prizes_sheet(prizes, prize_cols)

    creds = Credentials.from_service_account_file('credentials.json', scopes=[
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ])
    gc = gspread.authorize(creds)
    sh = gc.open(GSHEET_NAME)

    for title, data in zip(RUS_SHEETS, [users_sheet, support_sheet, prizes_sheet]):
        try:
            ws = sh.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows="100", cols="20")
        update_sheet(ws, data)
    print('Экспорт завершён!')

if __name__ == '__main__':
    main() 