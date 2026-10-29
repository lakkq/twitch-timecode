import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests
import datetime
import os
import json
import threading
import queue
import sys

from pynput import keyboard

import gspread
from google.oauth2.service_account import Credentials


def _resolve_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _resolve_base_dir()
CONFIG_FILE = os.path.join(BASE_DIR, "twitch_config.json")
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")


class TwitchTimecodeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Twitch Timecode Saver (Windows)")
        self.root.geometry("600x640")
        self.root.resizable(False, False)

        # Слушатель pynput
        self.listener = None
        self.listener_active = False
        self._target_combo = ""  # строка вида "ctrl+alt+t"

        # Режим записи хоткея
        self._record_listener = None
        self._record_mods = set()
        self._main_was_active = False

        # Google Sheets
        self.sheets_client = None

        self._build_ui()
        self._load_config()

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # --- Twitch ---
        frame = ttk.Frame(self.root, relief="groove", padding=8)
        frame.pack(fill="x", **pad)
        ttk.Label(frame, text="Данные авторизации Twitch",
                  font=("", 11, "bold")).grid(row=0, column=0, columnspan=2,
                                              sticky="w", pady=(0, 6))
        ttk.Label(frame, text="Client ID:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.entry_client_id = ttk.Entry(frame, width=50)
        self.entry_client_id.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Client Secret:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.entry_client_secret = ttk.Entry(frame, width=50, show="*")
        self.entry_client_secret.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Имя канала:").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        self.entry_channel = ttk.Entry(frame, width=50)
        self.entry_channel.grid(row=3, column=1, padx=5, pady=5)

        # --- Google Sheets ---
        frame_gs = ttk.Frame(self.root, relief="groove", padding=8)
        frame_gs.pack(fill="x", **pad)
        ttk.Label(frame_gs, text="Google Sheets",
                  font=("", 11, "bold")).grid(row=0, column=0, columnspan=2,
                                              sticky="w", pady=(0, 6))
        ttk.Label(frame_gs, text="ID таблицы:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.entry_spreadsheet_id = ttk.Entry(frame_gs, width=50)
        self.entry_spreadsheet_id.grid(row=1, column=1, padx=5, pady=5)
        ttk.Label(frame_gs, text="(ID из URL таблицы, между /d/ и /edit)",
                  foreground="gray").grid(row=2, column=0, columnspan=2,
                                          sticky="w", padx=5)

        # --- Настройки ---
        frame2 = ttk.Frame(self.root, relief="groove", padding=8)
        frame2.pack(fill="x", **pad)
        ttk.Label(frame2, text="Настройки",
                  font=("", 11, "bold")).grid(row=0, column=0, columnspan=3,
                                              sticky="w", pady=(0, 6))

        ttk.Label(frame2, text="Горячая клавиша:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.entry_hotkey = ttk.Entry(frame2, width=20, state="readonly")
        self.entry_hotkey.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        self.entry_hotkey.insert(0, "ctrl+alt+t")
        ttk.Label(frame2, text="(кликните и нажмите комбинацию)",
                  foreground="gray").grid(row=1, column=2, sticky="w", padx=5)

        self.entry_hotkey.bind("<FocusIn>", self._on_hotkey_focus_in)
        self.entry_hotkey.bind("<FocusOut>", self._on_hotkey_focus_out)
        self.entry_hotkey.bind("<Button-1>", lambda e: self.entry_hotkey.focus_set())

        ttk.Label(frame2, text="Локальный файл:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.entry_output = ttk.Entry(frame2, width=30)
        self.entry_output.grid(row=2, column=1, sticky="w", padx=5, pady=5)
        self.entry_output.insert(0, "timestamps.txt")
        ttk.Button(frame2, text="...", width=3,
                   command=self._choose_file).grid(row=2, column=2, padx=5)

        # --- Кнопки ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", **pad)
        self.btn_start = ttk.Button(btn_frame, text="Сохранить и запустить",
                                    command=self._start_listener)
        self.btn_start.pack(side="left", padx=5)
        self.btn_stop = ttk.Button(btn_frame, text="Остановить",
                                   command=self._stop_listener, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Проверить Twitch",
                   command=self._test_auth).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Проверить Sheets",
                   command=self._test_sheets).pack(side="right", padx=5)

        # --- Лог ---
        frame3 = ttk.Frame(self.root, relief="groove", padding=8)
        frame3.pack(fill="both", expand=True, **pad)
        ttk.Label(frame3, text="Журнал",
                  font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))
        self.text_log = tk.Text(frame3, height=8, state="disabled", wrap="word")
        self.text_log.pack(fill="both", expand=True)

    # ---------- Утилиты ----------
    def _log(self, message):
        self.text_log.configure(state="normal")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.text_log.insert("end", f"[{ts}] {message}\n")
        self.text_log.see("end")
        self.text_log.configure(state="disabled")

    def _choose_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text files", "*.txt"),
                                                       ("All files", "*.*")])
        if path:
            self.entry_output.delete(0, "end")
            self.entry_output.insert(0, path)

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entry_client_id.insert(0, data.get("client_id", ""))
                self.entry_client_secret.insert(0, data.get("client_secret", ""))
                self.entry_channel.insert(0, data.get("channel", ""))
                self.entry_spreadsheet_id.insert(0, data.get("spreadsheet_id", ""))
                self._set_hotkey(data.get("hotkey", "ctrl+alt+t"))
                self.entry_output.delete(0, "end")
                self.entry_output.insert(0, data.get("output", "timestamps.txt"))
                self._log("Загружены сохранённые настройки.")
            except Exception as e:
                self._log(f"Не удалось загрузить настройки: {e}")

    def _save_config(self):
        data = {
            "client_id": self.entry_client_id.get().strip(),
            "client_secret": self.entry_client_secret.get().strip(),
            "channel": self.entry_channel.get().strip(),
            "spreadsheet_id": self.entry_spreadsheet_id.get().strip(),
            "hotkey": self.entry_hotkey.get().strip(),
            "output": self.entry_output.get().strip(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._log("Настройки сохранены.")
        except Exception as e:
            self._log(f"Ошибка сохранения настроек: {e}")

    def _set_hotkey(self, combo):
        self.entry_hotkey.configure(state="normal")
        self.entry_hotkey.delete(0, "end")
        self.entry_hotkey.insert(0, combo)
        self.entry_hotkey.configure(state="readonly")

    def _validate_inputs(self):
        if not self.entry_client_id.get().strip():
            messagebox.showerror("Ошибка", "Введите Client ID")
            return False
        if not self.entry_client_secret.get().strip():
            messagebox.showerror("Ошибка", "Введите Client Secret")
            return False
        if not self.entry_channel.get().strip():
            messagebox.showerror("Ошибка", "Введите имя канала")
            return False
        if not self.entry_hotkey.get().strip():
            messagebox.showerror("Ошибка", "Укажите горячую клавишу")
            return False
        return True

    # ---------- Twitch API ----------
    def _get_app_access_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": self.entry_client_id.get().strip(),
            "client_secret": self.entry_client_secret.get().strip(),
            "grant_type": "client_credentials",
        }
        resp = requests.post(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _get_stream_start_time(self, token):
        headers = {
            "Client-ID": self.entry_client_id.get().strip(),
            "Authorization": f"Bearer {token}",
        }
        channel = self.entry_channel.get().strip().lower()
        url = f"https://api.twitch.tv/helix/streams?user_login={channel}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return None
        started_at_str = data[0]["started_at"]
        return datetime.datetime.strptime(started_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )

    def _test_auth(self):
        if not self._validate_inputs():
            return

        def task():
            try:
                token = self._get_app_access_token()
                self._log("Twitch: авторизация успешна.")
                start = self._get_stream_start_time(token)
                if start:
                    self._log(f"Канал в сети. Начало (UTC): "
                              f"{start.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    self._log("Twitch: авторизация верна, но канал офлайн.")
            except requests.HTTPError as e:
                self._log(f"Twitch HTTP: {e.response.status_code} — проверьте Client ID/Secret.")
            except Exception as e:
                self._log(f"Twitch: {e}")

        threading.Thread(target=task, daemon=True).start()

    # ---------- Google Sheets ----------
    def _init_sheets_client(self):
        if self.sheets_client is not None:
            return True
        if not os.path.exists(CREDENTIALS_FILE):
            self._log(f"Не найден {CREDENTIALS_FILE} рядом со скриптом.")
            return False
        try:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(
                CREDENTIALS_FILE, scopes=scope)
            self.sheets_client = gspread.authorize(creds)
            self._log("Google Sheets: клиент инициализирован.")
            return True
        except Exception as e:
            self._log(f"Google Sheets: ошибка авторизации — {e}")
            return False

    def _test_sheets(self):
        sid = self.entry_spreadsheet_id.get().strip()
        if not sid:
            messagebox.showerror("Ошибка", "Введите ID Google Таблицы")
            return

        def task():
            if not self._init_sheets_client():
                return
            try:
                sh = self.sheets_client.open_by_key(sid)
                self._log(f"Google Sheets: подключение успешно — «{sh.title}»")
                titles = [ws.title for ws in sh.worksheets()]
                self._log(f"Листы: {', '.join(titles) if titles else 'пусто'}")
            except Exception as e:
                self._log(f"Google Sheets: {e}")

        threading.Thread(target=task, daemon=True).start()

    def _write_to_sheets(self, channel, now_str, timecode):
        sid = self.entry_spreadsheet_id.get().strip()
        if not sid:
            return
        if not self._init_sheets_client():
            return
        try:
            sh = self.sheets_client.open_by_key(sid)
            try:
                worksheet = sh.worksheet(channel)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=channel, rows=1000, cols=5)
                worksheet.append_row(["Дата и время", "Таймкод", "Канал"])
                self._log(f"Google Sheets: создан лист «{channel}».")
            worksheet.append_row([now_str, timecode, channel])
            self._log(f"Google Sheets: записано {timecode} → лист «{channel}».")
        except Exception as e:
            self._log(f"Google Sheets: ошибка записи — {e}")

    # ---------- Парсинг и запуск слушателя (pynput) ----------
    def _parse_hotkey(self, hotkey_str):
        """Преобразует 'ctrl+alt+t' в формат pynput '<ctrl>+<alt>+t'."""
        parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
        formatted = []
        for p in parts:
            if p in ("ctrl", "alt", "shift", "cmd", "win"):
                formatted.append("<cmd>" if p == "win" else f"<{p}>")
            else:
                formatted.append(p)
        return "+".join(formatted)

    def _start_listener(self):
        if not self._validate_inputs():
            return
        self._save_config()

        hotkey_str = self.entry_hotkey.get().strip()
        try:
            pynput_combo = self._parse_hotkey(hotkey_str)
            self._target_combo = hotkey_str

            # Создаём GlobalHotKeys из pynput
            self.listener = keyboard.GlobalHotKeys({
                pynput_combo: self._on_hotkey
            })
            self.listener.start()

            self.listener_active = True
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self._log(f"Слушатель запущен. Горячая клавиша: {hotkey_str}")
        except Exception as e:
            self._log(f"Не удалось зарегистрировать горячую клавишу: {e}")

    def _stop_listener(self):
        if self.listener is not None:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
        self.listener_active = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._log("Слушатель остановлен.")

    # ---------- Запись хоткея (pynput) ----------
    def _on_hotkey_focus_in(self, event=None):
        if self._record_listener is not None:
            return

        self._main_was_active = self.listener_active
        if self._main_was_active:
            self._stop_listener()

        self._record_mods = set()
        self._set_hotkey("Нажмите комбинацию...")

        def on_press(key):
            # Модификаторы
            if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                self._record_mods.add("ctrl")
                return
            if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                self._record_mods.add("alt")
                return
            if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
                self._record_mods.add("shift")
                return
            if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
                self._record_mods.add("win")
                return

            # Обычная клавиша
            if hasattr(key, "char") and key.char:
                ch = key.char.lower()
                if ch.isprintable() and len(ch) == 1:
                    mods = sorted(self._record_mods)
                    combo = "+".join(mods + [ch])
                    self.root.after(0, lambda: self._finalize_record(combo))

        self._record_listener = keyboard.Listener(on_press=on_press)
        self._record_listener.start()
        self._log("Режим записи: нажмите комбинацию.")

    def _finalize_record(self, combo):
        self._set_hotkey(combo)
        self._stop_record_listener()
        self._log(f"Записан хоткей: {combo}")
        if self._main_was_active:
            self._main_was_active = False
            self.root.after(300, self._start_listener)
        self.root.focus_set()

    def _on_hotkey_focus_out(self, event=None):
        if self._record_listener is not None:
            self._stop_record_listener()
            if self._main_was_active:
                self._main_was_active = False
                self.root.after(300, self._start_listener)

    def _stop_record_listener(self):
        if self._record_listener is not None:
            try:
                self._record_listener.stop()
            except Exception:
                pass
            self._record_listener = None

    # ---------- Обработка хоткея ----------
    def _on_hotkey(self):
        threading.Thread(target=self._capture_timecode, daemon=True).start()

    def _capture_timecode(self):
        self._log("Нажата горячая клавиша. Получаю данные...")
        try:
            token = self._get_app_access_token()
            start_time = self._get_stream_start_time(token)
            if not start_time:
                self._log("Канал офлайн — таймкод не сохранён.")
                return

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            elapsed = now_utc - start_time
            if elapsed.total_seconds() < 0:
                elapsed = datetime.timedelta(seconds=0)

            total_seconds = int(elapsed.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            timecode = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            channel = self.entry_channel.get().strip()
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Локальный файл
            line = f"[{now_str}] Канал: {channel} | Таймкод: {timecode}"
            output_path = self.entry_output.get().strip() or "timestamps.txt"
            if not os.path.isabs(output_path):
                output_path = os.path.join(BASE_DIR, output_path)
            try:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                self._log(f"Файл: сохранено → {output_path}")
            except Exception as e:
                self._log(f"Файл: ошибка записи — {e}")

            # Google Sheets
            if self.entry_spreadsheet_id.get().strip():
                self._write_to_sheets(channel, now_str, timecode)
            else:
                self._log("Google Sheets: ID не указан — пропускаю.")

        except requests.HTTPError as e:
            self._log(f"Twitch HTTP: {e.response.status_code} — проверьте токены.")
        except Exception as e:
            self._log(f"Ошибка: {e}")

    # ---------- Закрытие ----------
    def on_close(self):
        self._stop_record_listener()
        self._stop_listener()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = TwitchTimecodeApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()