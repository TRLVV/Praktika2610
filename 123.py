import psycopg2
from psycopg2 import IntegrityError
import bcrypt
import random
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "user1",
    "password": "12345678"
}


def get_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except psycopg2.Error as e:
        print(f"[ERROR] Не удалось подключиться к БД: {e}")
        return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def register(conn):
    username = input("Придумайте никнейм: ").strip()
    if not username:
        print("[!] Никнейм не может быть пустым.")
        return

    password = input("Придумайте пароль: ")
    if len(password) < 6:
        print("[!] Пароль должен быть минимум 6 символов.")
        return

    cur = conn.cursor()
    try:
        cur.execute("SELECT role_id FROM Roles WHERE role_name = 'user'")
        role_row = cur.fetchone()
        if not role_row:
            print("[ERROR] Роль 'user' не найдена в таблице Roles. Создайте её.")
            return

        cur.execute(
            "INSERT INTO Users (username, password, rolename) VALUES (%s, %s, %s)",
            (username, hash_password(password), role_row[0])
        )
        conn.commit()
        print(f"[OK] Пользователь '{username}' успешно зарегистрирован.")
    except IntegrityError:
        conn.rollback()
        print(f"[!] Никнейм '{username}' уже занят.")
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[ERROR] Ошибка регистрации: {e}")
    finally:
        cur.close()


def login(conn):
    username = input("Никнейм: ").strip()
    password = input("Пароль: ")

    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT u.user_id, u.username, u.password, r.role_name
            FROM Users u
            JOIN Roles r ON u.rolename = r.role_id
            WHERE u.username = %s
        """, (username,))
        row = cur.fetchone()

        if not row or not check_password(password, row[2]):
            print("[!] Неверный никнейм или пароль.")
            return None

        user_id, uname, _, role_name = row

        cur.execute("""
            SELECT reason, ban_expires FROM Bans
            WHERE banned_user_id = %s
              AND (ban_expires IS NULL OR ban_expires > NOW())
            ORDER BY banned_at DESC LIMIT 1
        """, (user_id,))
        ban = cur.fetchone()
        if ban:
            expires = f"до {ban[1].strftime('%Y-%m-%d %H:%M')}" if ban[1] else "НАВСЕГДА"
            print(f"\n🚫 ВЫ ЗАБАНЕННЫ {expires}")
            print(f"   Причина: {ban[0]}")
            return None

        cur.execute(
            "INSERT INTO Sessions (user_session) VALUES (%s) RETURNING session_id",
            (user_id,)
        )
        session_id = cur.fetchone()[0]
        conn.commit()

        print(f"\n[OK] Добро пожаловать, {uname}! Роль: {role_name}")
        return {
            "user_id": user_id,
            "username": uname,
            "role": role_name,
            "session_id": session_id
        }

    except psycopg2.Error as e:
        conn.rollback()
        print(f"[ERROR] Ошибка входа: {e}")
        return None
    finally:
        cur.close()


def logout(conn, user):
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE Sessions SET ended_at = NOW() WHERE session_id = %s AND ended_at IS NULL",
            (user["session_id"],)
        )
        conn.commit()
        print("[OK] Сессия завершена.")
    except psycopg2.Error as e:
        print(f"[ERROR] Ошибка выхода: {e}")
    finally:
        cur.close()


def admin_ban(conn, admin_user):
    target = input("Никнейм пользователя для бана: ").strip()
    reason = input("Причина бана: ").strip()
    if not reason:
        print("[!] Причина обязательна.")
        return

    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM Users WHERE username = %s", (target,))
        target_row = cur.fetchone()
        if not target_row:
            print(f"[!] Пользователь '{target}' не найден.")
            return

        target_id = target_row[0]
        if target_id == admin_user["user_id"]:
            print("[!] Нельзя забанить самого себя.")
            return

        cur.execute(
            "INSERT INTO Bans (banned_user_id, banned_by_user_id, reason) VALUES (%s, %s, %s)",
            (target_id, admin_user["user_id"], reason)
        )
        conn.commit()
        print(f"[OK] Пользователь '{target}' забанен навсегда.")
    except IntegrityError as e:
        conn.rollback()
        print(f"[!] Ошибка: {e}")
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[ERROR] {e}")
    finally:
        cur.close()


def admin_promote(conn):
    target = input("Никнейм пользователя для выдачи мода: ").strip()

    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM Users WHERE username = %s", (target,))
        target_row = cur.fetchone()
        if not target_row:
            print(f"[!] Пользователь '{target}' не найден.")
            return

        cur.execute("SELECT role_id FROM Roles WHERE role_name = 'mod'")
        mod_role = cur.fetchone()
        if not mod_role:
            print("[ERROR] Роль 'mod' не найдена в таблице Roles.")
            return

        cur.execute(
            "UPDATE Users SET rolename = %s WHERE user_id = %s",
            (mod_role[0], target_row[0])
        )
        conn.commit()
        if cur.rowcount == 0:
            print(f"[!] Пользователь '{target}' не обновлён.")
        else:
            print(f"[OK] Пользователю '{target}' выдана роль 'mod'.")
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[ERROR] {e}")
    finally:
        cur.close()


def view_sessions(conn):
    game_filter = input("Фильтр по игре (clicker/tictactoe/guessnumber или Enter): ").strip().lower()
    search = input("Поиск по нику (или Enter): ").strip()

    conditions = []
    params = []

    if game_filter:
        valid_games = ('clicker', 'tictactoe', 'guessnumber')
        if game_filter not in valid_games:
            print(f"[!] Некорректная игра. Допустимые: {', '.join(valid_games)}")
            return
        conditions.append("g.game_name = %s")
        params.append(game_filter)

    if search:
        conditions.append("u.username ILIKE %s")
        params.append(f"%{search}%")

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
        SELECT s.session_id, u.username, g.game_name, s.started_at, s.ended_at
        FROM Sessions s
        JOIN Users u ON s.user_session = u.user_id
        LEFT JOIN Matches m ON m.started_at >= s.started_at
            AND (m.ended_at IS NULL OR m.ended_at <= s.ended_at)
        LEFT JOIN Games g ON m.games = g.game_id
        {where_clause}
        ORDER BY s.started_at DESC
        LIMIT 100;
    """

    cur = conn.cursor()
    try:
        cur.execute(query, params)
        rows = cur.fetchall()
        if not rows:
            print("Сессии не найдены.")
        else:
            print(f"\n{'ID':<6} {'Ник':<15} {'Игра':<15} {'Начало':<22} {'Конец'}")
            print("-" * 80)
            for r in rows:
                ended = r[4].strftime('%Y-%m-%d %H:%M:%S') if r[4] else "Активна"
                started = r[3].strftime('%Y-%m-%d %H:%M:%S')
                game = r[2] or "-"
                print(f"{r[0]:<6} {r[1]:<15} {game:<15} {started:<22} {ended}")
    except psycopg2.Error as e:
        print(f"[ERROR] {e}")
    finally:
        cur.close()


def view_match_results(conn):
    game_filter = input("Фильтр по игре (clicker/tictactoe/guessnumber или Enter): ").strip().lower()
    search = input("Поиск по нику (или Enter): ").strip()

    conditions = []
    params = []

    if game_filter:
        valid_games = ('clicker', 'tictactoe', 'guessnumber')
        if game_filter not in valid_games:
            print(f"[!] Некорректная игра. Допустимые: {', '.join(valid_games)}")
            return
        conditions.append("g.game_name = %s")
        params.append(game_filter)

    if search:
        conditions.append("u.username ILIKE %s")
        params.append(f"%{search}%")

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
        SELECT ms.match_id, u.username, g.game_name, ms.result,
               ms.click_count, ms.guess_attempts, m.started_at
        FROM MatchStats ms
        JOIN Users u ON ms.user_id = u.user_id
        JOIN Matches m ON ms.match_id = m.match_id
        JOIN Games g ON m.games = g.game_id
        {where_clause}
        ORDER BY m.started_at DESC
        LIMIT 100;
    """

    cur = conn.cursor()
    try:
        cur.execute(query, params)
        rows = cur.fetchall()
        if not rows:
            print("Результаты матчей не найдены.")
        else:
            print(f"\n{'MatchID':<9} {'Ник':<15} {'Игра':<15} {'Результат':<10} {'Клики':<8} {'Попытки':<8} {'Дата'}")
            print("-" * 90)
            for r in rows:
                clicks = r[4] if r[4] is not None else "-"
                guesses = r[5] if r[5] is not None else "-"
                date = r[6].strftime('%Y-%m-%d %H:%M')
                print(f"{r[0]:<9} {r[1]:<15} {r[2]:<15} {r[3]:<10} {str(clicks):<8} {str(guesses):<8} {date}")
    except psycopg2.Error as e:
        print(f"[ERROR] {e}")
    finally:
        cur.close()


def create_match(conn, game_name):
    cur = conn.cursor()
    try:
        cur.execute("SELECT game_id FROM Games WHERE game_name = %s", (game_name,))
        row = cur.fetchone()
        if not row:
            print(f"[ERROR] Игра '{game_name}' не найдена в таблице Games.")
            return None

        cur.execute(
            "INSERT INTO Matches (games) VALUES (%s) RETURNING match_id",
            (row[0],)
        )
        match_id = cur.fetchone()[0]
        conn.commit()
        return match_id
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[ERROR] Не удалось создать матч: {e}")
        return None
    finally:
        cur.close()


def save_match_result(conn, match_id, user_id, click_count=None, guess_attempts=None, result=None):
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO MatchStats (match_id, user_id, click_count, guess_attempts, result)
               VALUES (%s, %s, %s, %s, %s)""",
            (match_id, user_id, click_count, guess_attempts, result)
        )
        cur.execute(
            "UPDATE Matches SET ended_at = NOW() WHERE match_id = %s",
            (match_id,)
        )
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[ERROR] Не удалось сохранить результат: {e}")
    finally:
        cur.close()


def play_clicker(conn, user):
    print("\n=== КЛИКЕР ===")
    print("У вас 10 секунд. Кликайте Enter как можно быстрее!")
    input("Нажмите Enter для старта...")

    match_id = create_match(conn, 'clicker')
    if not match_id:
        return

    import time
    start = time.time()
    clicks = 0
    while time.time() - start < 10:
        input()
        clicks += 1
        elapsed = int(time.time() - start)
        print(f"Кликов: {clicks} | Осталось: {10 - elapsed}с")

    save_match_result(conn, match_id, user["user_id"], click_count=clicks)
    print(f"[OK] Игра завершена. Кликов: {clicks}")


def play_guessnumber(conn, user):
    print("\n=== УГАДАЙ ЧИСЛО ===")
    secret = random.randint(1, 100)
    attempts = 0
    max_attempts = 10

    match_id = create_match(conn, 'guessnumber')
    if not match_id:
        return

    print(f"Я загадал число от 1 до 100. У тебя {max_attempts} попыток.")

    while attempts < max_attempts:
        try:
            guess = int(input(f"Попытка {attempts + 1}/{max_attempts}: "))
        except ValueError:
            print("[!] Введите число.")
            continue

        attempts += 1
        if guess == secret:
            save_match_result(conn, match_id, user["user_id"], guess_attempts=attempts, result='win')
            print(f"[OK] Угадал за {attempts} попыток!")
            return
        elif guess < secret:
            print("Больше.")
        else:
            print("Меньше.")

    save_match_result(conn, match_id, user["user_id"], guess_attempts=attempts, result='loss')
    print(f"[!] Не угадал. Число было {secret}.")


def play_tictactoe(conn, user):
    print("\n=== КРЕСТИКИ-НОЛИКИ ===")
    board = [' '] * 9

    def print_board():
        for i in range(0, 9, 3):
            print(f" {board[i]} | {board[i+1]} | {board[i+2]} ")
            if i < 6:
                print("---+---+---")

    def check_win(b, mark):
        wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        return any(b[a]==b[b_]==b[c]==mark for a,b_,c in wins)

    match_id = create_match(conn, 'tictactoe')
    if not match_id:
        return

    print("Вы играете за X. Компьютер за O.")
    print_board()

    while True:
        try:
            pos = int(input("Ваш ход (1-9): ")) - 1
            if pos < 0 or pos > 8 or board[pos] != ' ':
                print("[!] Некорректный ход.")
                continue
        except ValueError:
            print("[!] Введите число от 1 до 9.")
            continue

        board[pos] = 'X'
        if check_win(board, 'X'):
            print_board()
            save_match_result(conn, match_id, user["user_id"], result='win')
            print("[OK] Вы победили!")
            return
        if ' ' not in board:
            print_board()
            save_match_result(conn, match_id, user["user_id"], result='draw')
            print("[OK] Ничья.")
            return

        empty = [i for i, x in enumerate(board) if x == ' ']
        bot_move = random.choice(empty)
        board[bot_move] = 'O'

        if check_win(board, 'O'):
            print_board()
            save_match_result(conn, match_id, user["user_id"], result='loss')
            print("[!] Компьютер победил.")
            return
        if ' ' not in board:
            print_board()
            save_match_result(conn, match_id, user["user_id"], result='draw')
            print("[OK] Ничья.")
            return

        print_board()


def main():
    conn = get_connection()
    if not conn:
        return

    current_user = None

    while True:
        if current_user is None:
            print("\n=== ГЛАВНОЕ МЕНЮ ===")
            print("1. Войти")
            print("2. Регистрация")
            print("0. Выход из программы")
            choice = input("> ").strip()

            if choice == "1":
                current_user = login(conn)
            elif choice == "2":
                register(conn)
            elif choice == "0":
                break
            else:
                print("[!] Неизвестная команда.")
        else:
            is_admin = current_user["role"] == "admin"
            print(f"\n=== МЕНЮ ({current_user['username']} | {current_user['role']}) ===")
            print("1. Просмотр сессий")
            print("2. Результаты матчей")
            print("3. Играть в Кликер")
            print("4. Играть в Угадай число")
            print("5. Играть в Крестики-нолики")
            if is_admin:
                print("6. Забанить пользователя (навсегда)")
                print("7. Выдать роль мода")
            print("9. Выйти из аккаунта")
            print("0. Выход из программы")
            choice = input("> ").strip()

            if choice == "1":
                view_sessions(conn)
            elif choice == "2":
                view_match_results(conn)
            elif choice == "3":
                play_clicker(conn, current_user)
            elif choice == "4":
                play_guessnumber(conn, current_user)
            elif choice == "5":
                play_tictactoe(conn, current_user)
            elif choice == "6" and is_admin:
                admin_ban(conn, current_user)
            elif choice == "7" and is_admin:
                admin_promote(conn)
            elif choice == "9":
                logout(conn, current_user)
                current_user = None
            elif choice == "0":
                logout(conn, current_user)
                break
            else:
                print("[!] Неизвестная команда или нет прав.")

    conn.close()
    print("Соединение закрыто.")


if __name__ == "__main__":
    main()