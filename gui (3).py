import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import psycopg2
from psycopg2 import IntegrityError
import bcrypt
import random
from datetime import datetime

# --- КОНФИГУРАЦИЯ БД ---
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "user1",
    "password": "12345678"
}

# --- ЦВЕТА ТЁМНОЙ ТЕМЫ ---
BG_COLOR = "#1e1e1e"
FG_COLOR = "#e0e0e0"
BTN_BG = "#2d2d2d"
BTN_FG = "#ffffff"
ENTRY_BG = "#2d2d2d"
ENTRY_FG = "#e0e0e0"
ACCENT_COLOR = "#007acc"


def get_connection():
    try:
        # TCP keepalive: если клиент умер (kill, сбой питания), сервер БД
        # быстро заметит обрыв и закроет соединение -> сессия будет закрыта
        # через cleanup_stale_sessions().
        return psycopg2.connect(**DB_CONFIG, application_name="gs_app",
                                keepalives=1, keepalives_idle=30,
                                keepalives_interval=10, keepalives_count=3)
    except psycopg2.Error as e:
        messagebox.showerror("Ошибка БД", f"Не удалось подключиться:\n{e}")
        return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Game System")
        self.root.geometry("900x600")
        self.root.configure(bg=BG_COLOR)

        # Настройка ttk стилей
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=BG_COLOR, foreground=FG_COLOR, fieldbackground=ENTRY_BG)
        style.configure('TButton', background=BTN_BG, foreground=BTN_FG)
        style.configure('TLabel', background=BG_COLOR, foreground=FG_COLOR)
        style.configure('TEntry', fieldbackground=ENTRY_BG, foreground=ENTRY_FG)
        style.configure('Treeview', background=ENTRY_BG, foreground=FG_COLOR, fieldbackground=ENTRY_BG)
        style.configure('Treeview.Heading', background=BTN_BG, foreground=FG_COLOR)
        style.map('TButton', background=[('active', ACCENT_COLOR)])
        style.map('Treeview', background=[('selected', ACCENT_COLOR)], foreground=[('selected', '#ffffff')])

        self.conn = get_connection()
        if not self.conn:
            root.destroy()
            return

        self.current_user = None

        # Закрытие окна крестиком раньше оставляло Sessions.ended_at = NULL
        # навсегда — теперь это закрывает сессию и соединение так же,
        # как и "Выйти из аккаунта" / "Выход из программы".
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.cleanup_stale_sessions()
        self.show_auth_frame()

    def on_close(self):
        """Единая точка выхода: крестик окна, кнопки 'Выход'."""
        if self.conn and self.current_user:
            self.end_current_session()

        if self.conn:
            try:
                self.conn.close()
            except psycopg2.Error:
                pass

        self.root.destroy()

    def end_current_session(self):
        cur = self.conn.cursor()
        try:
            cur.execute(
                "UPDATE Sessions SET ended_at = NOW() WHERE session_id = %s AND ended_at IS NULL",
                (self.current_user["session_id"],)
            )
            cur.execute("SELECT set_config('application_name', 'gs_app', false)")
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback()
            print(f"Ошибка завершения сессии: {e}")
        finally:
            cur.close()

    def cleanup_stale_sessions(self):
        """Закрывает сессии, у которых клиент уже не подключён к БД.

        При входе соединение помечается application_name = 'gs_session_<id>'.
        Если приложение убили/оно упало, соединение пропадает из
        pg_stat_activity, а Sessions.ended_at остаётся NULL — такие сессии
        закрываются здесь (при старте, входе и просмотре сессий).
        """
        cur = self.conn.cursor()
        try:
            cur.execute("""
                UPDATE Sessions s SET ended_at = NOW()
                WHERE s.ended_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_stat_activity a
                      WHERE a.application_name = 'gs_session_' || s.session_id::text
                  )
            """)
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback()
            print(f"Ошибка очистки сессий: {e}")
        finally:
            cur.close()

    # --- СТАТУС СЕРВЕРА ТЕКУЩЕЙ СЕССИИ ---
    def is_server_online(self):
        """Для админа: онлайн ли сервер его сессии. Для остальных всегда True."""
        if not self.current_user or self.current_user["role"] != "admin":
            return True
        cur = self.conn.cursor()
        try:
            cur.execute("""
                SELECT srv.status FROM Sessions s
                JOIN Servers srv ON srv.server_id = s.server_id
                WHERE s.session_id = %s
            """, (self.current_user["session_id"],))
            row = cur.fetchone()
            return bool(row) and row[0] == "online"
        except psycopg2.Error:
            self.conn.rollback()
            return False
        finally:
            cur.close()

    def require_server(self):
        if self.is_server_online():
            return True
        messagebox.showerror("Сервер отключен!", "Сервер отключен! Эта функция недоступна.")
        self.show_main_menu()
        return False

    def clear_frame(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def create_button(self, parent, text, command, width=20):
        btn = tk.Button(parent, text=text, command=command, width=width,
                        bg=BTN_BG, fg=BTN_FG, activebackground=ACCENT_COLOR, activeforeground='#ffffff',
                        relief=tk.FLAT, padx=10, pady=5)
        return btn

    def create_label(self, parent, text, font=("Arial", 12), **kwargs):
        lbl = tk.Label(parent, text=text, font=font, bg=BG_COLOR, fg=FG_COLOR, **kwargs)
        return lbl

    def create_entry(self, parent, width=30, show=""):
        entry = tk.Entry(parent, width=width, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground=FG_COLOR, show=show)
        return entry

    # --- ЭКСПОРТ В EXCEL ---
    def export_to_excel(self, data, filename, headers):
        if not data:
            messagebox.showwarning("Предупреждение", "Нет данных для экспорта.")
            return

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            wb = Workbook()
            ws = wb.active
            ws.title = "Data"

            # Стили
            header_font = Font(bold=True, color="FFFFFFFF", size=11)
            header_fill = PatternFill(start_color="FF007ACC", end_color="FF007ACC", fill_type="solid")
            header_alignment = Alignment(horizontal="center", vertical="center")
            thin_border = Border(
                left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin')
            )

            # Заголовки
            for col_num, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_num, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border

            # Данные
            for row_num, row_data in enumerate(data, 2):
                for col_num, value in enumerate(row_data, 1):
                    cell = ws.cell(row=row_num, column=col_num, value=value)
                    cell.border = thin_border
                    if isinstance(value, datetime):
                        cell.number_format = 'YYYY-MM-DD HH:MM:SS'

            # Автоширина
            for col_cells in ws.columns:
                max_length = 0
                col_letter = col_cells[0].column_letter
                for cell in col_cells:
                    try:
                        length = len(str(cell.value or ""))
                        if length > max_length:
                            max_length = length
                    except:
                        pass
                adjusted_width = min(max_length + 4, 50)
                ws.column_dimensions[col_letter].width = adjusted_width

            filepath = f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            wb.save(filepath)
            messagebox.showinfo("Успех", f"Файл сохранён:\n{filepath}")

        except ImportError:
            messagebox.showerror("Ошибка", "Библиотека openpyxl не установлена.\npip install openpyxl")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{e}")

    # --- АВТОРИЗАЦИЯ И РЕГИСТРАЦИЯ ---
    def show_auth_frame(self):
        self.clear_frame()
        self.current_user = None

        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True)

        self.create_label(frame, "=== ГЛАВНОЕ МЕНЮ ===", font=("Arial", 16, "bold")).pack(pady=10)
        self.create_button(frame, "Войти", self.show_login).pack(pady=5)
        self.create_button(frame, "Регистрация", self.show_register).pack(pady=5)
        self.create_button(frame, "Выход", self.on_close).pack(pady=5)

    def show_login(self):
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True)

        self.create_label(frame, "Вход", font=("Arial", 14, "bold")).pack(pady=10)

        self.create_label(frame, "Никнейм:").pack()
        username_entry = self.create_entry(frame)
        username_entry.pack(pady=5)

        self.create_label(frame, "Пароль:").pack()
        password_entry = self.create_entry(frame, show="*")
        password_entry.pack(pady=5)

        def do_login():
            username = username_entry.get().strip()
            password = password_entry.get()

            if not username or not password:
                messagebox.showwarning("Предупреждение", "Заполните все поля.")
                return

            self.cleanup_stale_sessions()
            cur = self.conn.cursor()
            try:
                cur.execute("""
                    SELECT u.user_id, u.username, u.password, r.role_name, u.region_id
                    FROM Users u
                    JOIN Roles r ON u.role_id = r.role_id
                    WHERE u.username = %s
                """, (username,))
                row = cur.fetchone()

                if not row or not check_password(password, row[2]):
                    messagebox.showerror("Ошибка", "Неверный никнейм или пароль.")
                    return

                user_id, uname, _, role_name, region_id = row

                # Проверка бана
                cur.execute("""
                    SELECT reason, ban_expires FROM Bans
                    WHERE banned_user_id = %s
                      AND (ban_expires IS NULL OR ban_expires > NOW())
                    ORDER BY banned_at DESC LIMIT 1
                """, (user_id,))
                ban = cur.fetchone()
                if ban:
                    expires = f"до {ban[1].strftime('%Y-%m-%d %H:%M')}" if ban[1] else "НАВСЕГДА"
                    messagebox.showerror("ЗАБАНЕН", f"Вы забанены {expires}\nПричина: {ban[0]}")
                    return

                # Один сервер на регион: находим сервер этого юзера и проверяем статус
                cur.execute(
                    "SELECT server_id, status FROM Servers WHERE region_id = %s",
                    (region_id,)
                )
                server = cur.fetchone()
                is_admin_login = role_name == "admin"
                if not server and is_admin_login:
                    # У админа может не быть сервера в регионе — берём любой,
                    # чтобы он мог зайти и управлять серверами.
                    cur.execute("SELECT server_id, status FROM Servers ORDER BY server_id LIMIT 1")
                    server = cur.fetchone()
                if not server:
                    messagebox.showerror("Ошибка", "Для вашего региона не настроен сервер.")
                    return

                server_id, server_status = server
                # Админ может войти и при отключённом сервере (получит урезанное меню)
                if server_status != 'online' and not is_admin_login:
                    status_text = "ОТКЛЮЧЁН" if server_status == 'offline' else "НА ТЕХОБСЛУЖИВАНИИ"
                    messagebox.showerror("Сервер недоступен", f"Сервер вашего региона сейчас {status_text}.")
                    return

                # Создание сессии (с привязкой к серверу)
                cur.execute(
                    "INSERT INTO Sessions (user_id, server_id) VALUES (%s, %s) RETURNING session_id",
                    (user_id, server_id)
                )
                session_id = cur.fetchone()[0]
                # Метка соединения — по ней находим "мёртвые" сессии
                cur.execute("SELECT set_config('application_name', %s, false)",
                            (f"gs_session_{session_id}",))
                self.conn.commit()

                self.current_user = {
                    "user_id": user_id,
                    "username": uname,
                    "role": role_name,
                    "session_id": session_id
                }
                messagebox.showinfo("Успех", f"Добро пожаловать, {uname}!")
                self.show_main_menu()

            except psycopg2.Error as e:
                self.conn.rollback()
                messagebox.showerror("Ошибка", f"Ошибка входа:\n{e}")
            finally:
                cur.close()

        self.create_button(frame, "Войти", do_login).pack(pady=10)
        self.create_button(frame, "Назад", self.show_auth_frame).pack(pady=5)

    def show_register(self):
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True)

        self.create_label(frame, "Регистрация", font=("Arial", 14, "bold")).pack(pady=10)

        self.create_label(frame, "Никнейм:").pack()
        username_entry = self.create_entry(frame)
        username_entry.pack(pady=5)

        self.create_label(frame, "Пароль (мин. 6 символов):").pack()
        password_entry = self.create_entry(frame, show="*")
        password_entry.pack(pady=5)

        # Юзер теперь сам выбирает регион, а не получает первый попавшийся
        self.create_label(frame, "Регион:").pack()
        region_var = tk.StringVar()
        region_combo = ttk.Combobox(frame, textvariable=region_var, state="readonly", width=27)
        region_combo.pack(pady=5)

        region_map = {}  # отображаемое имя -> region_id
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT region_id, region_name FROM Regions ORDER BY region_name")
            for rid, rname in cur.fetchall():
                region_map[rname] = rid
            region_combo["values"] = list(region_map.keys())
            # Регион НЕ выбирается автоматически — юзер обязан выбрать сам,
            # иначе комбобокс всегда был бы предзаполнен первым регионом
            # и проверка "регион не выбран" ниже никогда бы не срабатывала.
        except psycopg2.Error as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить регионы:\n{e}")
        finally:
            cur.close()

        def do_register():
            username = username_entry.get().strip()
            password = password_entry.get()
            region_name = region_var.get()

            if not username:
                messagebox.showwarning("Предупреждение", "Никнейм не может быть пустым.")
                return
            if len(password) < 6:
                messagebox.showwarning("Предупреждение", "Пароль должен быть минимум 6 символов.")
                return
            if not region_name or region_name not in region_map:
                messagebox.showwarning("Предупреждение", "Выберите регион.")
                return

            cur = self.conn.cursor()
            try:
                cur.execute("SELECT role_id FROM Roles WHERE role_name = 'user'")
                role_row = cur.fetchone()
                if not role_row:
                    messagebox.showerror("Ошибка", "Роль 'user' не найдена в БД.")
                    return

                region_id = region_map[region_name]

                cur.execute(
                    "INSERT INTO Users (username, password, role_id, region_id) VALUES (%s, %s, %s, %s)",
                    (username, hash_password(password), role_row[0], region_id)
                )
                self.conn.commit()
                messagebox.showinfo("Успех", f"Пользователь '{username}' зарегистрирован.")
                self.show_auth_frame()

            except IntegrityError:
                self.conn.rollback()
                messagebox.showerror("Ошибка", f"Никнейм '{username}' уже занят.")
            except psycopg2.Error as e:
                self.conn.rollback()
                messagebox.showerror("Ошибка", f"Ошибка регистрации:\n{e}")
            finally:
                cur.close()

        self.create_button(frame, "Зарегистрироваться", do_register).pack(pady=10)
        self.create_button(frame, "Назад", self.show_auth_frame).pack(pady=5)

    # --- ГЛАВНОЕ МЕНЮ ---
    def show_main_menu(self):
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True)

        is_admin = self.current_user["role"] == "admin"
        is_mod = self.current_user["role"] == "mod"
        server_online = self.is_server_online()

        self.create_label(frame, f"МЕНЮ ({self.current_user['username']} | {self.current_user['role']})",
                          font=("Arial", 14, "bold")).pack(pady=10)

        if not server_online:
            # Сервер отключён: у админа работают только вкладки без игровой логики
            self.create_label(frame, "Сервер отключен!", font=("Arial", 13, "bold"),
                              fg="#e53935").pack(pady=(0, 10))
            self.create_button(frame, "Сервера", self.admin_toggle_server, width=30).pack(pady=5)
            self.create_button(frame, "Статистика игрока", self.show_player_stats, width=30).pack(pady=5)
            self.create_button(frame, "Результаты матчей", self.show_match_results, width=30).pack(pady=5)
            self.create_button(frame, "Просмотр сессий", self.show_sessions, width=30).pack(pady=5)
            self.create_button(frame, "Выйти из аккаунта", self.logout, width=30).pack(pady=10)
            return

        self.create_button(frame, "Просмотр сессий", self.show_sessions, width=30).pack(pady=5)
        self.create_button(frame, "Результаты матчей", self.show_match_results, width=30).pack(pady=5)
        self.create_button(frame, "Статистика игрока", self.show_player_stats, width=30).pack(pady=5)

        self.create_button(frame, "Играть в Кликер", self.play_clicker, width=30).pack(pady=5)
        self.create_button(frame, "Играть в Угадай число", self.play_guessnumber, width=30).pack(pady=5)
        self.create_button(frame, "Играть в Крестики-нолики", self.play_tictactoe, width=30).pack(pady=5)

        # Баны доступны и админу, и моду (с разными правами внутри панели)
        if is_admin or is_mod:
            self.create_button(frame, "Забанить пользователя", self.admin_ban, width=30).pack(pady=5)
            self.create_button(frame, "Список банов / Разбан", self.show_bans_panel, width=30).pack(pady=5)

        if is_admin:
            self.create_button(frame, "Выдать роль мода", self.admin_promote, width=30).pack(pady=5)
            self.create_button(frame, "Сервера", self.admin_toggle_server, width=30).pack(pady=5)
            self.create_button(frame, "Затереть статистику игрока", self.admin_wipe_stats, width=30).pack(pady=5)

        self.create_button(frame, "Выйти из аккаунта", self.logout, width=30).pack(pady=10)
        self.create_button(frame, "Выход из программы", self.on_close, width=30).pack(pady=5)

    def logout(self):
        self.end_current_session()
        self.show_auth_frame()

    # --- ПРОСМОТР СЕССИЙ ---
    def show_sessions(self):
        self.cleanup_stale_sessions()
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # 1. Сначала определяем структуру данных
        columns = ("ID", "Ник", "Игра", "Начало", "Конец")

        filter_frame = tk.Frame(frame, bg=BG_COLOR)
        filter_frame.pack(fill=tk.X, pady=5)

        self.create_label(filter_frame, "Фильтр по игре:").pack(side=tk.LEFT)
        game_var = tk.StringVar(value="Все")
        game_combo = ttk.Combobox(filter_frame, textvariable=game_var,
                                  values=["Все", "clicker", "tictactoe", "guessnumber"], width=15)
        game_combo.pack(side=tk.LEFT, padx=5)

        self.create_label(filter_frame, "Поиск по нику:").pack(side=tk.LEFT, padx=(10, 0))
        search_entry = self.create_entry(filter_frame, width=20)
        search_entry.pack(side=tk.LEFT, padx=5)

        # Создаем Treeview ДО кнопок, чтобы лямбды его видели
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=20)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)
        tree.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Теперь определяем load_data, когда tree уже существует
        def load_data():
            for item in tree.get_children():
                tree.delete(item)

            game_filter = game_var.get().lower()
            search = search_entry.get().strip()

            conditions = []
            params = []

            if game_filter != "все":
                conditions.append("g.game_name = %s")
                params.append(game_filter)

            if search:
                conditions.append("u.username ILIKE %s")
                params.append(f"%{search}%")

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"""
                SELECT s.session_id, u.username, g.game_name, s.started_at, s.ended_at
                FROM Sessions s
                JOIN Users u ON s.user_id = u.user_id
                LEFT JOIN Matches m ON m.session_id = s.session_id
                LEFT JOIN Games g ON m.game_id = g.game_id
                {where_clause}
                ORDER BY s.started_at DESC
                LIMIT 100;
            """

            cur = self.conn.cursor()
            try:
                cur.execute(query, params)
                rows = cur.fetchall()
                for r in rows:
                    ended = r[4].strftime('%Y-%m-%d %H:%M:%S') if r[4] else "Активна"
                    started = r[3].strftime('%Y-%m-%d %H:%M:%S')
                    game = r[2] or "-"
                    tree.insert("", tk.END, values=(r[0], r[1], game, started, ended))
            except psycopg2.Error as e:
                messagebox.showerror("Ошибка", f"{e}")
            finally:
                cur.close()

        # 3. И только ТЕПЕРЬ создаем кнопки, ссылаясь на уже существующие tree и load_data
        self.create_button(filter_frame, "Экспорт в Excel",
                           lambda: self.export_to_excel(
                               [tree.item(item)['values'] for item in tree.get_children()],
                               "sessions",
                               columns
                           )).pack(side=tk.LEFT, padx=5)

        self.create_button(filter_frame, "Применить фильтр", load_data).pack(side=tk.LEFT, padx=5)

        load_data()  # Загружаем данные сразу

        self.create_button(frame, "Назад", self.show_main_menu).pack(pady=10)

    # --- РЕЗУЛЬТАТЫ МАТЧЕЙ ---
    def show_match_results(self):
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # 1. Структура
        columns = ("MatchID", "Ник", "Игра", "Результат", "Клики", "Попытки", "Дата")

        filter_frame = tk.Frame(frame, bg=BG_COLOR)
        filter_frame.pack(fill=tk.X, pady=5)

        self.create_label(filter_frame, "Фильтр по игре:").pack(side=tk.LEFT)
        game_var = tk.StringVar(value="Все")
        game_combo = ttk.Combobox(filter_frame, textvariable=game_var,
                                  values=["Все", "clicker", "tictactoe", "guessnumber"], width=15)
        game_combo.pack(side=tk.LEFT, padx=5)

        self.create_label(filter_frame, "Поиск по нику:").pack(side=tk.LEFT, padx=(10, 0))
        search_entry = self.create_entry(filter_frame, width=20)
        search_entry.pack(side=tk.LEFT, padx=5)

        # 2. Treeview создаем ДО кнопок
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=20)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=120)
        tree.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 3. Функция загрузки
        def load_data():
            for item in tree.get_children():
                tree.delete(item)

            game_filter = game_var.get().lower()
            search = search_entry.get().strip()

            conditions = []
            params = []

            if game_filter != "все":
                conditions.append("g.game_name = %s")
                params.append(game_filter)

            if search:
                conditions.append("u.username ILIKE %s")
                params.append(f"%{search}%")

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            # LEFT JOIN от Matches, а не INNER JOIN от MatchStats: если админ
            # затирает статистику игрока (DELETE FROM MatchStats), сам факт
            # матча (Matches) остаётся в БД. При INNER JOIN такие матчи
            # пропадали бы из этого списка полностью; при LEFT JOIN они
            # остаются видны, просто с пустыми result/clicks/attempts.
            # username/ник берём через Sessions -> Users, т.к. в Matches
            # нет прямой ссылки на юзера.
            query = f"""
                SELECT m.match_id, u.username, g.game_name, ms.result,
                       ms.click_count, ms.guess_attempts, m.started_at
                FROM Matches m
                JOIN Sessions s ON m.session_id = s.session_id
                JOIN Users u ON s.user_id = u.user_id
                JOIN Games g ON m.game_id = g.game_id
                LEFT JOIN MatchStats ms ON ms.match_id = m.match_id AND ms.user_id = u.user_id
                {where_clause}
                ORDER BY m.started_at DESC
                LIMIT 100;
            """

            cur = self.conn.cursor()
            try:
                cur.execute(query, params)
                rows = cur.fetchall()
                for r in rows:
                    clicks = str(r[4]) if r[4] is not None else "-"
                    guesses = str(r[5]) if r[5] is not None else "-"
                    result = r[3] if r[3] is not None else "-"
                    date = r[6].strftime('%Y-%m-%d %H:%M')
                    tree.insert("", tk.END, values=(r[0], r[1], r[2], result, clicks, guesses, date))
            except psycopg2.Error as e:
                messagebox.showerror("Ошибка", f"{e}")
            finally:
                cur.close()

        # 4. Кнопки (теперь tree и load_data существуют)
        self.create_button(filter_frame, "Экспорт в Excel",
                           lambda: self.export_to_excel(
                               [tree.item(item)['values'] for item in tree.get_children()],
                               "match_stats",
                               columns
                           )).pack(side=tk.LEFT, padx=5)

        self.create_button(filter_frame, "Применить фильтр", load_data).pack(side=tk.LEFT, padx=5)

        load_data()

        self.create_button(frame, "Назад", self.show_main_menu).pack(pady=10)

    # --- СТАТИСТИКА ИГРОКА ---
    def show_player_stats(self):
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True, fill=tk.BOTH)

        self.create_label(frame, "Статистика игрока", font=("Arial", 16, "bold")).pack(pady=10)

        search_frame = tk.Frame(frame, bg=BG_COLOR)
        search_frame.pack(pady=10)

        self.create_label(search_frame, "Никнейм:").pack(side=tk.LEFT)
        username_entry = self.create_entry(search_frame, width=25)
        username_entry.pack(side=tk.LEFT, padx=5)

        result_frame = tk.Frame(frame, bg=BG_COLOR, padx=10, pady=10)
        result_frame.pack(pady=10, fill=tk.BOTH, expand=True)

        # last_stats хранит последние загруженные данные для экспорта в Excel,
        # чтобы кнопка экспорта могла сработать без повторного запроса к БД
        last_stats = {}

        def load_stats():
            for widget in result_frame.winfo_children():
                widget.destroy()
            last_stats.clear()

            username = username_entry.get().strip()
            if not username:
                messagebox.showwarning("Предупреждение", "Введите никнейм.")
                return

            cur = self.conn.cursor()
            try:
                cur.execute("SELECT user_id, username FROM Users WHERE username = %s", (username,))
                user_row = cur.fetchone()
                if not user_row:
                    messagebox.showerror("Ошибка", f"Игрок '{username}' не найден.")
                    return

                user_id, uname = user_row

                # Один запрос со всеми агрегатами сразу (FILTER на PostgreSQL 9.4+)
                cur.execute("""
                    SELECT
                        MAX(ms.click_count) FILTER (WHERE g.game_name = 'clicker') AS pb_clicks,
                        MIN(ms.guess_attempts) FILTER (WHERE g.game_name = 'guessnumber' AND ms.result = 'win') AS pb_guesses,
                        COUNT(*) FILTER (WHERE g.game_name = 'tictactoe' AND ms.result = 'win')  AS ttt_wins,
                        COUNT(*) FILTER (WHERE g.game_name = 'tictactoe' AND ms.result = 'loss') AS ttt_losses,
                        COUNT(*) FILTER (WHERE g.game_name = 'tictactoe' AND ms.result = 'draw') AS ttt_draws
                    FROM MatchStats ms
                    JOIN Games g ON ms.game_id = g.game_id
                    WHERE ms.user_id = %s
                """, (user_id,))
                pb_clicks, pb_guesses, wins, losses, draws = cur.fetchone()

                total_ttt = wins + losses + draws
                winrate = (wins / total_ttt * 100) if total_ttt > 0 else 0.0

                self.create_label(result_frame, f"=== {uname} ===", font=("Arial", 14, "bold")).pack(pady=(0, 10))

                pb_clicks_text = str(pb_clicks) if pb_clicks is not None else "нет данных"
                pb_guesses_text = str(pb_guesses) if pb_guesses is not None else "нет данных"

                self.create_label(result_frame, f"PB Кликер: {pb_clicks_text} кликов",
                                  font=("Arial", 13)).pack(anchor="w", pady=3)
                self.create_label(result_frame, f"PB Угадай число: {pb_guesses_text} попыток",
                                  font=("Arial", 13)).pack(anchor="w", pady=3)
                self.create_label(
                    result_frame,
                    f"Крестики-нолики — W:{wins} L:{losses} D:{draws}  |  Winrate: {winrate:.1f}%",
                    font=("Arial", 13)
                ).pack(anchor="w", pady=3)

                if total_ttt == 0 and pb_clicks is None and pb_guesses is None:
                    self.create_label(result_frame, "У игрока пока нет статистики по играм.",
                                      font=("Arial", 12)).pack(pady=10)

                # Сохраняем для экспорта — одна строка на игрока
                last_stats["username"] = uname
                last_stats["row"] = (
                    uname,
                    pb_clicks_text,
                    pb_guesses_text,
                    wins, losses, draws,
                    f"{winrate:.1f}%"
                )

            except psycopg2.Error as e:
                messagebox.showerror("Ошибка", f"{e}")
            finally:
                cur.close()

        def export_stats():
            if not last_stats:
                messagebox.showwarning("Предупреждение", "Сначала покажите статистику игрока.")
                return

            headers = ("Никнейм", "PB Кликер", "PB Угадай число", "TTT Win", "TTT Loss", "TTT Draw", "TTT Winrate")
            self.export_to_excel([last_stats["row"]], f"player_stats_{last_stats['username']}", headers)

        self.create_button(search_frame, "Показать", load_stats).pack(side=tk.LEFT, padx=5)
        self.create_button(search_frame, "Экспорт в Excel", export_stats).pack(side=tk.LEFT, padx=5)

        self.create_button(frame, "Назад", self.show_main_menu).pack(pady=10)

    # --- ЛОГИКА ИГР (ОБЩИЕ МЕТОДЫ) ---
    def create_match(self, game_name):
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT game_id FROM Games WHERE game_name = %s", (game_name,))
            row = cur.fetchone()
            if not row:
                messagebox.showerror("Ошибка", f"Игра '{game_name}' не найдена в БД.")
                return None

            cur.execute(
                "INSERT INTO Matches (session_id, game_id) VALUES (%s, %s) RETURNING match_id",
                (self.current_user["session_id"], row[0])
            )
            match_id = cur.fetchone()[0]
            self.conn.commit()
            return match_id
        except psycopg2.Error as e:
            self.conn.rollback()
            messagebox.showerror("Ошибка", f"Не удалось создать матч:\n{e}")
            return None
        finally:
            cur.close()

    def save_match_result(self, match_id, user_id, click_count=None, guess_attempts=None, result=None):
        cur = self.conn.cursor()
        try:
            # game_id берём из самого матча — так вызовы save_match_result
            # в играх не меняются, а game_id в MatchStats гарантированно
            # совпадает с игрой матча, т.к. другого источника для него нет.
            cur.execute("SELECT game_id FROM Matches WHERE match_id = %s", (match_id,))
            row = cur.fetchone()
            if not row:
                messagebox.showerror("Ошибка", "Матч не найден.")
                return
            game_id = row[0]

            cur.execute(
                """INSERT INTO MatchStats (match_id, user_id, game_id, click_count, guess_attempts, result)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (match_id, user_id, game_id, click_count, guess_attempts, result)
            )
            cur.execute(
                "UPDATE Matches SET ended_at = NOW() WHERE match_id = %s",
                (match_id,)
            )
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить результат:\n{e}")
        finally:
            cur.close()

    # --- ИГРА: КЛИКЕР ---
    def play_clicker(self):
        if not self.require_server():
            return
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True)

        match_id = self.create_match('clicker')
        if not match_id:
            self.show_main_menu()
            return

        clicks = 0
        time_left = 10
        running = False
        started = False  # таймер ещё не запускался
        after_id = None

        label = self.create_label(frame, "Жмите КЛИК, чтобы начать!", font=("Arial", 20))
        label.pack(pady=20)

        clicks_label = self.create_label(frame, f"Кликов: {clicks}", font=("Arial", 16))
        clicks_label.pack(pady=10)

        time_label = self.create_label(frame, f"Время: {time_left}с", font=("Arial", 16))
        time_label.pack(pady=10)

        def countdown():
            nonlocal time_left, running, after_id
            if time_left > 0 and running:
                time_left -= 1
                time_label.config(text=f"Время: {time_left}с")
                after_id = self.root.after(1000, countdown)
            elif running:
                running = False
                self.save_match_result(match_id, self.current_user["user_id"], click_count=clicks)
                label.config(text=f"Готово! Кликов: {clicks}")
                click_btn.config(state=tk.DISABLED)
                messagebox.showinfo("Результат", f"Вы сделали {clicks} кликов!")
                # Возврат в меню после закрытия сообщения
                self.root.after(100, self.show_main_menu)

        def on_click():
            nonlocal clicks, running, started
            # Первое нажатие на КЛИК одновременно стартует таймер —
            # отдельной кнопки "Старт" больше нет.
            if not started:
                started = True
                running = True
                label.config(text="Кликайте!")
                countdown()

            if running:
                clicks += 1
                clicks_label.config(text=f"Кликов: {clicks}")

        click_btn = tk.Button(frame, text="КЛИК!", width=20, height=3, command=on_click,
                              bg=BTN_BG, fg=BTN_FG, activebackground=ACCENT_COLOR, relief=tk.FLAT)
        click_btn.pack(pady=10)

        def cancel():
            nonlocal running
            running = False
            if after_id is not None:
                self.root.after_cancel(after_id)
            self.show_main_menu()

        self.create_button(frame, "Отмена", cancel).pack(pady=10)

    # --- ИГРА: УГАДАЙ ЧИСЛО ---
    def play_guessnumber(self):
        if not self.require_server():
            return
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True)

        match_id = self.create_match('guessnumber')
        if not match_id:
            self.show_main_menu()
            return

        secret = random.randint(1, 100)
        attempts = 0
        max_attempts = 10

        label = self.create_label(frame, f"Я загадал число от 1 до 100.\nУ тебя {max_attempts} попыток.",
                                  font=("Arial", 14))
        label.pack(pady=20)

        entry = self.create_entry(frame, width=10)
        entry.config(font=("Arial", 16))
        entry.pack(pady=10)

        result_label = self.create_label(frame, "", font=("Arial", 14))
        result_label.pack(pady=10)

        def check_guess():
            nonlocal attempts
            try:
                guess = int(entry.get())
            except ValueError:
                messagebox.showwarning("Ошибка", "Введите число.")
                return

            attempts += 1
            if guess == secret:
                self.save_match_result(match_id, self.current_user["user_id"], guess_attempts=attempts, result='win')
                result_label.config(text=f"Угадал за {attempts} попыток!")
                entry.config(state=tk.DISABLED)
                btn.config(state=tk.DISABLED)
                messagebox.showinfo("Победа", f"Число было {secret}. Попыток: {attempts}")
                self.root.after(100, self.show_main_menu)
            elif attempts >= max_attempts:
                self.save_match_result(match_id, self.current_user["user_id"], guess_attempts=attempts, result='loss')
                result_label.config(text=f"Проиграл. Число было {secret}.")
                entry.config(state=tk.DISABLED)
                btn.config(state=tk.DISABLED)
                messagebox.showinfo("Проигрыш", f"Число было {secret}.")
                self.root.after(100, self.show_main_menu)
            elif guess < secret:
                result_label.config(text=f"Больше. Попытка {attempts}/{max_attempts}")
            else:
                result_label.config(text=f"Меньше. Попытка {attempts}/{max_attempts}")

            entry.delete(0, tk.END)

        btn = tk.Button(frame, text="Проверить", width=20, command=check_guess,
                        bg=BTN_BG, fg=BTN_FG, activebackground=ACCENT_COLOR, relief=tk.FLAT)
        btn.pack(pady=10)

        self.create_button(frame, "Отмена", self.show_main_menu).pack(pady=10)

    # --- ИГРА: КРЕСТИКИ-НОЛИКИ ---
    def play_tictactoe(self):
        if not self.require_server():
            return
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(expand=True)

        match_id = self.create_match('tictactoe')
        if not match_id:
            self.show_main_menu()
            return

        board = [' '] * 9
        buttons = []

        def check_win(b, mark):
            wins = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
            return any(b[a] == b[b_] == b[c] == mark for a, b_, c in wins)

        def on_click(idx):
            if board[idx] != ' ' or buttons[idx]['state'] == tk.DISABLED:
                return

            board[idx] = 'X'
            buttons[idx].config(text='X', state=tk.DISABLED)

            if check_win(board, 'X'):
                self.save_match_result(match_id, self.current_user["user_id"], result='win')
                messagebox.showinfo("Победа", "Вы победили!")
                disable_all()
                self.root.after(100, self.show_main_menu)
                return

            if ' ' not in board:
                self.save_match_result(match_id, self.current_user["user_id"], result='draw')
                messagebox.showinfo("Ничья", "Ничья!")
                disable_all()
                self.root.after(100, self.show_main_menu)
                return

            empty = [i for i, x in enumerate(board) if x == ' ']
            bot_move = random.choice(empty)
            board[bot_move] = 'O'
            buttons[bot_move].config(text='O', state=tk.DISABLED)

            if check_win(board, 'O'):
                self.save_match_result(match_id, self.current_user["user_id"], result='loss')
                messagebox.showinfo("Проигрыш", "Компьютер победил.")
                disable_all()
                self.root.after(100, self.show_main_menu)
                return

            if ' ' not in board:
                self.save_match_result(match_id, self.current_user["user_id"], result='draw')
                messagebox.showinfo("Ничья", "Ничья!")
                disable_all()
                self.root.after(100, self.show_main_menu)
                return

        def disable_all():
            for b in buttons:
                b.config(state=tk.DISABLED)

        grid_frame = tk.Frame(frame, bg=BG_COLOR)
        grid_frame.pack(pady=20)

        for i in range(9):
            btn = tk.Button(grid_frame, text=' ', width=10, height=3, font=("Arial", 20),
                            command=lambda idx=i: on_click(idx),
                            bg=BTN_BG, fg=BTN_FG, activebackground=ACCENT_COLOR, relief=tk.FLAT)
            btn.grid(row=i // 3, column=i % 3, padx=5, pady=5)
            buttons.append(btn)

        self.create_button(frame, "Отмена", self.show_main_menu).pack(pady=10)

    # --- АДМИН/МОД ПАНЕЛЬ: БАНЫ ---
    def admin_ban(self):
        if not self.require_server():
            return
        is_admin = self.current_user["role"] == "admin"

        target = simpledialog.askstring("Бан", "Никнейм пользователя для бана:")
        if not target:
            return

        cur = self.conn.cursor()
        try:
            cur.execute("""
                SELECT u.user_id, r.role_name FROM Users u
                JOIN Roles r ON u.role_id = r.role_id
                WHERE u.username = %s
            """, (target,))
            target_row = cur.fetchone()
            if not target_row:
                messagebox.showerror("Ошибка", f"Пользователь '{target}' не найден.")
                return

            target_id, target_role = target_row
            if target_id == self.current_user["user_id"]:
                messagebox.showwarning("Предупреждение", "Нельзя забанить самого себя.")
                return

            # Мод может банить только обычных юзеров (роль ниже своей),
            # не других модов и не админов. Админ может банить кого угодно.
            if not is_admin and target_role != "user":
                messagebox.showwarning(
                    "Предупреждение",
                    "Модератор может банить только пользователей с ролью 'user'."
                )
                return

            reason = simpledialog.askstring("Бан", "Причина бана:")
            if not reason:
                messagebox.showwarning("Предупреждение", "Причина обязательна.")
                return

            # Срок бана: админ может поставить любой срок (0 = навсегда),
            # мод ограничен максимум 7 днями.
            if is_admin:
                days = simpledialog.askinteger(
                    "Срок бана",
                    "На сколько дней забанить? (0 = навсегда)",
                    minvalue=0
                )
            else:
                days = simpledialog.askinteger(
                    "Срок бана",
                    "На сколько дней забанить? (максимум 7)",
                    minvalue=1, maxvalue=7
                )
            if days is None:
                return

            if is_admin and days == 0:
                cur.execute(
                    "INSERT INTO Bans (banned_user_id, banned_by_user_id, reason, ban_expires) "
                    "VALUES (%s, %s, %s, NULL)",
                    (target_id, self.current_user["user_id"], reason)
                )
                expires_text = "НАВСЕГДА"
            else:
                cur.execute(
                    "INSERT INTO Bans (banned_user_id, banned_by_user_id, reason, ban_expires) "
                    "VALUES (%s, %s, %s, NOW() + (%s || ' days')::interval)",
                    (target_id, self.current_user["user_id"], reason, days)
                )
                expires_text = f"на {days} дн."

            # Бан затирает статистику забаненного — тем же способом, что
            # и ручное затирание админом (DELETE FROM MatchStats). История
            # матчей/сессий (Matches/Sessions) не трогается.
            cur.execute("DELETE FROM MatchStats WHERE user_id = %s", (target_id,))

            self.conn.commit()
            messagebox.showinfo("Успех", f"Пользователь '{target}' забанен ({expires_text}). Статистика затёрта.")
        except IntegrityError as e:
            self.conn.rollback()
            messagebox.showerror("Ошибка", f"{e}")
        except psycopg2.Error as e:
            self.conn.rollback()
            messagebox.showerror("Ошибка", f"{e}")
        finally:
            cur.close()

    def show_bans_panel(self):
        if not self.require_server():
            return
        self.clear_frame()
        frame = tk.Frame(self.root, bg=BG_COLOR, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        is_admin = self.current_user["role"] == "admin"

        self.create_label(frame, "Активные баны", font=("Arial", 16, "bold")).pack(pady=10)

        columns = ("BanID", "Забанен", "Кем забанен", "Причина", "Истекает")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)
        tree.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def load_bans():
            for item in tree.get_children():
                tree.delete(item)

            cur = self.conn.cursor()
            try:
                # Админ видит все активные баны, мод — только те, что выдал сам
                if is_admin:
                    cur.execute("""
                        SELECT b.ban_id, u1.username, u2.username, b.reason, b.ban_expires
                        FROM Bans b
                        JOIN Users u1 ON b.banned_user_id = u1.user_id
                        LEFT JOIN Users u2 ON b.banned_by_user_id = u2.user_id
                        WHERE b.ban_expires IS NULL OR b.ban_expires > NOW()
                        ORDER BY b.banned_at DESC
                    """)
                else:
                    cur.execute("""
                        SELECT b.ban_id, u1.username, u2.username, b.reason, b.ban_expires
                        FROM Bans b
                        JOIN Users u1 ON b.banned_user_id = u1.user_id
                        LEFT JOIN Users u2 ON b.banned_by_user_id = u2.user_id
                        WHERE (b.ban_expires IS NULL OR b.ban_expires > NOW())
                          AND b.banned_by_user_id = %s
                        ORDER BY b.banned_at DESC
                    """, (self.current_user["user_id"],))
                rows = cur.fetchall()
                for ban_id, banned, banned_by, reason, expires in rows:
                    expires_text = expires.strftime('%Y-%m-%d %H:%M') if expires else "НАВСЕГДА"
                    tree.insert("", tk.END, values=(ban_id, banned, banned_by or "-", reason, expires_text))
            except psycopg2.Error as e:
                messagebox.showerror("Ошибка", f"{e}")
            finally:
                cur.close()

        def do_unban():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Предупреждение", "Выберите бан в списке.")
                return

            ban_id = tree.item(selected[0])['values'][0]

            cur = self.conn.cursor()
            try:
                # Мод может разбанить только то, что сам забанил
                if is_admin:
                    cur.execute(
                        "UPDATE Bans SET ban_expires = NOW() WHERE ban_id = %s",
                        (ban_id,)
                    )
                else:
                    cur.execute(
                        "UPDATE Bans SET ban_expires = NOW() WHERE ban_id = %s AND banned_by_user_id = %s",
                        (ban_id, self.current_user["user_id"])
                    )
                    if cur.rowcount == 0:
                        self.conn.rollback()
                        messagebox.showwarning(
                            "Предупреждение",
                            "Вы можете разбанивать только тех, кого забанили сами."
                        )
                        return

                self.conn.commit()
                messagebox.showinfo("Успех", "Пользователь разбанен.")
                load_bans()
            except psycopg2.Error as e:
                self.conn.rollback()
                messagebox.showerror("Ошибка", f"{e}")
            finally:
                cur.close()

        btn_frame = tk.Frame(frame, bg=BG_COLOR)
        btn_frame.pack(pady=10)
        self.create_button(btn_frame, "Разбанить выбранного", do_unban, width=22).pack(side=tk.LEFT, padx=5)
        self.create_button(btn_frame, "Обновить", load_bans, width=15).pack(side=tk.LEFT, padx=5)

        load_bans()

        self.create_button(frame, "Назад", self.show_main_menu).pack(pady=10)

    def admin_promote(self):
        if not self.require_server():
            return
        target = simpledialog.askstring("Повышение", "Никнейм пользователя для выдачи мода:")
        if not target:
            return

        cur = self.conn.cursor()
        try:
            cur.execute("SELECT user_id FROM Users WHERE username = %s", (target,))
            target_row = cur.fetchone()
            if not target_row:
                messagebox.showerror("Ошибка", f"Пользователь '{target}' не найден.")
                return

            cur.execute("SELECT role_id FROM Roles WHERE role_name = 'mod'")
            mod_role = cur.fetchone()
            if not mod_role:
                messagebox.showerror("Ошибка", "Роль 'mod' не найдена в БД.")
                return

            cur.execute(
                "UPDATE Users SET role_id = %s WHERE user_id = %s",
                (mod_role[0], target_row[0])
            )
            self.conn.commit()
            if cur.rowcount == 0:
                messagebox.showwarning("Предупреждение", f"Пользователь '{target}' не обновлён.")
            else:
                messagebox.showinfo("Успех", f"Пользователю '{target}' выдана роль 'mod'.")
        except psycopg2.Error as e:
            self.conn.rollback()
            messagebox.showerror("Ошибка", f"{e}")
        finally:
            cur.close()

    def admin_toggle_server(self):
        cur = self.conn.cursor()
        try:
            cur.execute("""
                SELECT srv.server_id, r.region_name, srv.status
                FROM Servers srv
                JOIN Regions r ON srv.region_id = r.region_id
                ORDER BY r.region_name
            """)
            servers = cur.fetchall()
            if not servers:
                messagebox.showinfo("Информация", "В БД нет серверов.")
                return
        except psycopg2.Error as e:
            messagebox.showerror("Ошибка", f"{e}")
            cur.close()
            return
        finally:
            cur.close()

        win = tk.Toplevel(self.root)
        win.title("Сервера")
        win.configure(bg=BG_COLOR)
        win.geometry("420x400")

        self.create_label(win, "Серверы по регионам", font=("Arial", 13, "bold")).pack(pady=10)

        list_frame = tk.Frame(win, bg=BG_COLOR)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10)

        status_colors = {"online": "#4caf50", "offline": "#e53935", "maintenance": "#ffb300"}

        def refresh_list():
            for widget in list_frame.winfo_children():
                widget.destroy()

            cur2 = self.conn.cursor()
            try:
                cur2.execute("""
                    SELECT srv.server_id, r.region_name, srv.status
                    FROM Servers srv
                    JOIN Regions r ON srv.region_id = r.region_id
                    ORDER BY r.region_name
                """)
                rows = cur2.fetchall()
            except psycopg2.Error as e:
                messagebox.showerror("Ошибка", f"{e}")
                return
            finally:
                cur2.close()

            for server_id, region_name, status in rows:
                row = tk.Frame(list_frame, bg=BG_COLOR)
                row.pack(fill=tk.X, pady=4)

                self.create_label(row, region_name, font=("Arial", 12), width=15, anchor="w").pack(side=tk.LEFT)
                self.create_label(row, status.upper(), font=("Arial", 11, "bold"),
                                  fg=status_colors.get(status, FG_COLOR)).pack(side=tk.LEFT, padx=10)

                def make_cycle(sid=server_id, cur_status=status):
                    def cycle():
                        order = ["online", "offline", "maintenance"]
                        next_status = order[(order.index(cur_status) + 1) % len(order)]
                        cur3 = self.conn.cursor()
                        try:
                            cur3.execute(
                                "UPDATE Servers SET status = %s WHERE server_id = %s",
                                (next_status, sid)
                            )
                            self.conn.commit()
                            refresh_list()
                        except psycopg2.Error as e:
                            self.conn.rollback()
                            messagebox.showerror("Ошибка", f"{e}")
                        finally:
                            cur3.close()
                    return cycle

                self.create_button(row, "Сменить статус", make_cycle(), width=16).pack(side=tk.RIGHT)

        refresh_list()

        def close_servers():
            win.destroy()
            # Статус сервера админа мог измениться — перерисовываем меню
            if self.current_user:
                self.show_main_menu()

        win.protocol("WM_DELETE_WINDOW", close_servers)
        self.create_button(win, "Закрыть", close_servers).pack(pady=10)

    def admin_wipe_stats(self):
        if not self.require_server():
            return
        target = simpledialog.askstring("Затереть статистику", "Никнейм игрока:")
        if not target:
            return

        cur = self.conn.cursor()
        try:
            cur.execute("""
                SELECT u.user_id, r.role_name FROM Users u
                JOIN Roles r ON u.role_id = r.role_id
                WHERE u.username = %s
            """, (target,))
            row = cur.fetchone()
            if not row:
                messagebox.showerror("Ошибка", f"Игрок '{target}' не найден.")
                return

            target_id, target_role = row

            # Затирать стату админа нельзя — только mod и user
            if target_role == "admin":
                messagebox.showwarning("Предупреждение", "Нельзя затереть статистику администратора.")
                return

            confirm = messagebox.askyesno(
                "Подтверждение",
                f"Затереть всю статистику игрока '{target}'?\n"
                f"История матчей и сессий останется, но результаты (PB, W/L/D) будут удалены безвозвратно."
            )
            if not confirm:
                return

            # Matches и Sessions не трогаем: FK MatchStats -> Matches
            # однонаправленный (ON DELETE CASCADE только от Matches к
            # MatchStats), поэтому удаление строк MatchStats никак не
            # затрагивает Matches/Sessions — они остаются как есть.
            cur.execute("DELETE FROM MatchStats WHERE user_id = %s", (target_id,))
            deleted = cur.rowcount
            self.conn.commit()
            messagebox.showinfo("Успех", f"Статистика игрока '{target}' затёрта ({deleted} записей удалено).")

        except psycopg2.Error as e:
            self.conn.rollback()
            messagebox.showerror("Ошибка", f"{e}")
        finally:
            cur.close()


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
