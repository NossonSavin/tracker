import tkinter as tk
from tkinter import ttk, messagebox
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import threading
import time
import yfinance as yf

from PIL import Image, ImageDraw, ImageTk
import pandas as pd

VISIBLE_UPDATE_INTERVAL_MS = 5 * 1000  # 5 seconds
HOLDINGS_FILE = Path(__file__).with_name("holdings.json")
SETTINGS_FILE = Path(__file__).with_name("settings.json")

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]

class StockTickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Portfolio: $0.00")
        self.root.geometry("655x600")
        self.root.minsize(655, 00)
        self.root.configure(bg="#eef2f6")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.settings = self.load_settings()
        saved_geometry = self.settings.get("window_geometry")
        if isinstance(saved_geometry, str):
            try:
                self.root.geometry(saved_geometry)
            except tk.TclError:
                pass

        icon_path = Path(__file__).with_name("icon.png")
        self.icon_path = icon_path
        self.badge_icon_image = None
        self.app_icon_image = None
        if icon_path.exists():
            try:
                icon_image = Image.open(icon_path)
                self.app_icon_image = ImageTk.PhotoImage(icon_image)
                self.badge_icon_image = ImageTk.PhotoImage(icon_image.resize((18, 18), Image.LANCZOS))
                self.root.iconphoto(False, self.app_icon_image)
            except Exception:
                try:
                    self.app_icon_image = tk.PhotoImage(file=str(icon_path))
                    self.badge_icon_image = tk.PhotoImage(file=str(icon_path))
                    self.root.iconphoto(False, self.app_icon_image)
                except tk.TclError:
                    self.badge_icon_image = None
                    self.app_icon_image = None

        self.holdings = self.load_holdings()
        self.show_change = tk.BooleanVar(value=self.settings.get("show_change", False))
        self.last_total_value = 0.0
        self.refresh_after_id = None
        self.settings_save_after_id = None
        self.refresh_in_progress = False
        self.value_badge = None
        self.value_badge_label = None
        self.badge_drag_start = None
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("Main.TFrame", background="#eef2f6")
        self.style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"), foreground="#1f4e79", background="#eef2f6")
        self.style.configure("Form.TLabel", font=("Segoe UI", 10), foreground="#33475b", background="#eef2f6")
        self.style.configure("Form.TEntry", font=("Segoe UI", 10), padding=6, fieldbackground="#ffffff", background="#ffffff")
        self.style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=8)
        self.style.map("Action.TButton", background=[("active", "#357ae8"), ("!disabled", "#4b8bf8")], foreground=[("!disabled", "#ffffff")])
        self.style.configure("Custom.Treeview", font=("Segoe UI", 10), rowheight=26, fieldbackground="#ffffff", background="#ffffff", bordercolor="#d7dbe0", borderwidth=1)
        self.style.configure("Custom.Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#e8eff7", foreground="#1f4e79")
        self.style.map("Custom.Treeview", background=[("selected", "#4b8bf8")], foreground=[("selected", "#ffffff")])
        self.create_widgets()
        self.root.bind("<Configure>", self.on_window_configure)
        self.create_value_badge()
        if self.holdings:
            total_value = sum(item["value"] for item in self.holdings)
            self.update_display(self.holdings, total_value)
        self.schedule_refresh(immediate=True)
        self.monitor_badge_visibility()

    def create_widgets(self):
        frame = ttk.Frame(self.root, padding=16, style="Main.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        header = ttk.Label(frame, text="Portfolio Tracker", style="Header.TLabel")
        header.grid(row=row, column=0, columnspan=7, sticky=tk.W, pady=(0, 16))

        row += 1
        input_frame = ttk.Frame(frame, style="Main.TFrame")
        input_frame.grid(row=row, column=0, columnspan=7, sticky=tk.W, pady=4)

        ttk.Label(input_frame, text=" Stock symbol:", style="Form.TLabel").grid(row=0, column=0, sticky=tk.W)
        self.symbol_entry = ttk.Entry(input_frame, width=12, style="Form.TEntry")
        self.symbol_entry.grid(row=0, column=1, sticky=tk.W, padx=(4, 12))

        ttk.Label(input_frame, text=" Shares:", style="Form.TLabel").grid(row=0, column=2, sticky=tk.W)
        self.shares_entry = ttk.Entry(input_frame, width=9, style="Form.TEntry")
        self.shares_entry.grid(row=0, column=3, sticky=tk.W, padx=(4, 12))

        ttk.Label(input_frame, text=" Invested:", style="Form.TLabel").grid(row=0, column=4, sticky=tk.W)
        self.invested_entry = ttk.Entry(input_frame, width=11, style="Form.TEntry")
        self.invested_entry.grid(row=0, column=5, sticky=tk.W, padx=(4, 12))

        add_button = ttk.Button(input_frame, text="Add / Update", command=self.on_add_holding, style="Action.TButton")
        add_button.grid(row=0, column=6, sticky=tk.W)

        row += 1
        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=7, sticky="ew", pady=16)

        row += 1
        columns = ("move", "symbol", "shares", "price", "invested", "value", "diff")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=10, style="Custom.Treeview")
        self.tree.heading("move", text="")
        self.tree.heading("symbol", text="Symbol")
        self.tree.heading("shares", text="Shares")
        self.tree.heading("price", text="Price")
        self.tree.heading("invested", text="Invested")
        self.tree.heading("value", text="Value")
        self.tree.heading("diff", text="Diff")
        self.tree.column("move", width=30, anchor=tk.CENTER)
        self.tree.column("symbol", width=90, anchor=tk.CENTER)
        self.tree.column("shares", width=70, anchor=tk.CENTER)
        self.tree.column("price", width=100, anchor=tk.CENTER)
        self.tree.column("invested", width=110, anchor=tk.CENTER)
        self.tree.column("value", width=110, anchor=tk.CENTER)
        self.tree.column("diff", width=110, anchor=tk.CENTER)
        self.tree.grid(row=row, column=0, columnspan=7, sticky="nsew")
        self.tree.tag_configure("oddrow", background="#ffffff", foreground="#000000")
        self.tree.tag_configure("evenrow", background="#f4f7fb", foreground="#000000")
        self.tree.tag_configure("positive", foreground="#008000")
        self.tree.tag_configure("negative", foreground="#B00020")
        self.tree.bind("<<TreeviewSelect>>", self.on_holdings_select)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)

        row += 1
        self.root.grid_rowconfigure(row, weight=1)
        frame.grid_rowconfigure(row, weight=1)

        row += 1
        self.total_box = tk.Frame(frame, bg="#ffffff", bd=1, relief="solid", padx=12, pady=12)
        self.total_box.grid(row=row, column=0, columnspan=7, sticky=tk.W, pady=(16, 0))
        top_total = tk.Frame(self.total_box, bg="#ffffff")
        top_total.pack(side=tk.TOP, fill=tk.X)
        self.show_price_radio = tk.Radiobutton(top_total, text="", variable=self.show_change, value=False, command=self.refresh_total_display, bg="#ffffff", activebackground="#ffffff", selectcolor="#ffffff", bd=0, highlightthickness=0)
        self.show_price_radio.pack(side=tk.LEFT, padx=(0, 2))
        self.total_label = tk.Label(top_total, text="Total portfolio value:", font=("Segoe UI", 14, "bold"), fg="#1f4e79", bg="#ffffff", cursor="hand2")
        self.total_label.pack(side=tk.LEFT)
        self.total_value_label = tk.Label(top_total, text="$0.00", font=("Segoe UI", 14, "bold"), fg="#008000", bg="#ffffff", cursor="hand2")
        self.total_value_label.pack(side=tk.LEFT, padx=(10, 0))
        self.total_label.bind("<Button-1>", lambda e: self.select_total_view(False))
        self.total_value_label.bind("<Button-1>", lambda e: self.select_total_view(False))

        bottom_total = tk.Frame(self.total_box, bg="#ffffff")
        bottom_total.pack(side=tk.TOP, fill=tk.X, pady=(10, 0))
        self.total_diff_radio = tk.Radiobutton(bottom_total, text="", variable=self.show_change, value=True, command=self.refresh_total_display, bg="#ffffff", activebackground="#ffffff", selectcolor="#ffffff", bd=0, highlightthickness=0)
        self.total_diff_radio.pack(side=tk.LEFT, padx=(0, 2))
        self.total_diff_text = tk.Label(bottom_total, text="Total change:", font=("Segoe UI", 14, "bold"), fg="#1f4e79", bg="#ffffff", cursor="hand2")
        self.total_diff_text.pack(side=tk.LEFT)
        self.total_diff_value = tk.Label(bottom_total, text="$0.00", font=("Segoe UI", 14, "bold"), fg="#008000", bg="#ffffff", cursor="hand2")
        self.total_diff_value.pack(side=tk.LEFT, padx=(10, 0))
        self.total_diff_text.bind("<Button-1>", lambda e: self.select_total_view(True))
        self.total_diff_value.bind("<Button-1>", lambda e: self.select_total_view(True))

        row += 1
        self.status_label = tk.Label(frame, text="Last updated: N/A", font=("Segoe UI", 10), foreground="#546c7a", bg="#eef2f6", bd=0, highlightthickness=0)
        self.status_label.grid(row=row, column=0, columnspan=6, pady=(8, 0), sticky=tk.W)

        quit_button = ttk.Button(frame, text="Quit", command=self.quit_app)
        quit_button.grid(row=row, column=6, pady=(8, 0), sticky=tk.E)

    def select_total_view(self, show_change):
        self.show_change.set(show_change)
        self.refresh_total_display()

    def on_holdings_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        values = self.tree.item(item_id, "values")
        if not values or len(values) < 7:
            return

        symbol, shares, _, invested, _, diff = values[1], values[2], values[3], values[4], values[5], values[6]
        self.symbol_entry.delete(0, tk.END)
        self.symbol_entry.insert(0, symbol)
        self.shares_entry.delete(0, tk.END)
        self.shares_entry.insert(0, shares)
        self.invested_entry.delete(0, tk.END)
        self.invested_entry.insert(0, invested.replace("$", ""))

    def move_selected_up(self):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if not values:
            return
        symbol = values[1]
        index = next((i for i, item in enumerate(self.holdings) if item["symbol"] == symbol), None)
        if index is None or index == 0:
            return
        self.holdings[index - 1], self.holdings[index] = self.holdings[index], self.holdings[index - 1]
        self.save_holdings()
        self.display_cached_holdings()
        self.tree.selection_set(self.tree.get_children()[index - 1])

    def move_selected_down(self):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if not values:
            return
        symbol = values[1]
        index = next((i for i, item in enumerate(self.holdings) if item["symbol"] == symbol), None)
        if index is None or index == len(self.holdings) - 1:
            return
        self.holdings[index + 1], self.holdings[index] = self.holdings[index], self.holdings[index + 1]
        self.save_holdings()
        self.display_cached_holdings()
        self.tree.selection_set(self.tree.get_children()[index + 1])

    def on_tree_click(self, event):
        row_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not row_id or not column:
            return

        values = self.tree.item(row_id, "values")
        if not values or len(values) < 7:
            return

        if column != "#1":
            return

        symbol = values[1]
        index = next((i for i, item in enumerate(self.holdings) if item["symbol"] == symbol), None)
        if index is None:
            return

        bbox = self.tree.bbox(row_id, column)
        if not bbox:
            return
        cell_x = event.x - bbox[0]

        if cell_x < bbox[2] / 2:
            if index == 0:
                return
            self.holdings[index - 1], self.holdings[index] = self.holdings[index], self.holdings[index - 1]
            self.save_holdings()
            self.display_cached_holdings()
            self.tree.selection_set(self.tree.get_children()[index - 1])
        else:
            if index == len(self.holdings) - 1:
                return
            self.holdings[index + 1], self.holdings[index] = self.holdings[index], self.holdings[index + 1]
            self.save_holdings()
            self.display_cached_holdings()
            self.tree.selection_set(self.tree.get_children()[index + 1])

    def create_value_badge(self):
        self.value_badge = tk.Toplevel(self.root)
        self.value_badge.overrideredirect(True)
        self.value_badge.attributes("-topmost", True)
        try:
            self.value_badge.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        transparent_bg = "#FFFFFF"
        self.value_badge.configure(bg=transparent_bg)
        try:
            self.value_badge.attributes("-transparentcolor", transparent_bg)
        except tk.TclError:
            pass

        self.value_badge_label = tk.Label(
            self.value_badge,
            text="0.00",
            image=self.badge_icon_image,
            compound="left",
            bg=transparent_bg,
            fg="#000000",
            padx=12,
            pady=6,
            font=("Segoe UI", 11, "bold"),
            bd=0,
            highlightthickness=0,
        )
        self.value_badge_label.image = self.badge_icon_image
        self.value_badge_label.pack()
        for widget in (self.value_badge, self.value_badge_label):
            widget.bind("<ButtonPress-1>", self.start_badge_drag)
            widget.bind("<B1-Motion>", self.drag_value_badge)
            widget.bind("<ButtonRelease-1>", self.end_badge_drag)
            widget.bind("<Button-3>", self.show_badge_menu)

        self.badge_menu = tk.Menu(self.value_badge, tearoff=0)
        self.badge_menu.add_command(label="Show app", command=self.show_window)
        self.badge_menu.add_command(label="Refresh now", command=self.refresh_now)
        self.badge_menu.add_separator()
        self.badge_menu.add_command(label="Dock to taskbar", command=self.dock_badge_to_taskbar)
        self.badge_menu.add_command(label="Quit", command=self.quit_app)
        self.root.after(0, self.position_value_badge)

    def position_value_badge(self):
        if self.value_badge is None:
            return

        self.value_badge.update_idletasks()
        width = self.value_badge.winfo_width()
        height = self.value_badge.winfo_height()
        screen_width = self.value_badge.winfo_screenwidth()
        screen_height = self.value_badge.winfo_screenheight()
        saved_position = self.settings.get("badge_position")

        if saved_position:
            x = saved_position.get("x", 0)
            y = saved_position.get("y", 0)
        elif (taskbar_rect := self.get_taskbar_rect()):
            left, top, right, bottom = taskbar_rect
            taskbar_width = right - left
            taskbar_height = bottom - top

            if taskbar_width >= taskbar_height:
                x = right - width - 180
                y = top + max(0, (taskbar_height - height) // 2)
            else:
                x = left + max(0, (taskbar_width - width) // 2)
                y = bottom - height - 180
        else:
            x = screen_width - width - 180
            y = screen_height - height - 8

        x = max(0, min(x, screen_width - width))
        y = max(0, min(y, screen_height - height))
        self.value_badge.geometry(f"+{x}+{y}")

    def start_badge_drag(self, event):
        self.badge_drag_start = (event.x_root, event.y_root, self.value_badge.winfo_x(), self.value_badge.winfo_y())

    def drag_value_badge(self, event):
        if self.badge_drag_start is None:
            return

        start_x, start_y, window_x, window_y = self.badge_drag_start
        x = window_x + event.x_root - start_x
        y = window_y + event.y_root - start_y
        self.value_badge.geometry(f"+{x}+{y}")

    def end_badge_drag(self, event):
        if self.badge_drag_start is None:
            return

        start_x, start_y, _, _ = self.badge_drag_start
        moved = abs(event.x_root - start_x) > 3 or abs(event.y_root - start_y) > 3
        self.badge_drag_start = None
        self.save_badge_position()
        if not moved:
            self.show_window()

    def show_badge_menu(self, event):
        self.badge_menu.tk_popup(event.x_root, event.y_root)

    def dock_badge_to_taskbar(self):
        self.settings.pop("badge_position", None)
        self.save_settings()
        self.position_value_badge()

    def save_badge_position(self):
        if self.value_badge is None:
            return

        self.settings["badge_position"] = {
            "x": self.value_badge.winfo_x(),
            "y": self.value_badge.winfo_y(),
        }
        self.save_settings()

    def get_taskbar_rect(self):
        hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if not hwnd:
            return None

        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return rect.left, rect.top, rect.right, rect.bottom

    def monitor_badge_visibility(self):
        if self.value_badge is not None:
            if self.is_foreground_app_fullscreen():
                self.value_badge.withdraw()
            else:
                self.value_badge.deiconify()
                self.value_badge.attributes("-topmost", True)
        self.root.after(200, self.monitor_badge_visibility)

    def is_foreground_app_fullscreen(self):
        foreground = ctypes.windll.user32.GetForegroundWindow()
        if not foreground:
            return False

        if self.is_shell_window(foreground):
            return False

        if self.get_process_name(foreground).lower() == "explorer.exe":
            return False

        badge_hwnd = self.get_window_handle(self.value_badge)
        root_hwnd = self.get_window_handle(self.root)
        if foreground in (badge_hwnd, root_hwnd):
            return False

        window_rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(foreground, ctypes.byref(window_rect)):
            return False

        monitor = ctypes.windll.user32.MonitorFromWindow(foreground, 2)
        if not monitor:
            return False

        monitor_info = MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return False

        monitor_rect = monitor_info.rcMonitor
        margin = 2
        return (
            window_rect.left <= monitor_rect.left + margin
            and window_rect.top <= monitor_rect.top + margin
            and window_rect.right >= monitor_rect.right - margin
            and window_rect.bottom >= monitor_rect.bottom - margin
        )

    def is_shell_window(self, hwnd):
        class_name = self.get_window_class(hwnd)
        shell_classes = {
            "Shell_TrayWnd",
            "Shell_SecondaryTrayWnd",
            "TaskListThumbnailWnd",
            "TaskSwitcherWnd",
            "MultitaskingViewFrame",
            "Progman",
            "WorkerW",
        }
        return class_name in shell_classes or "TaskList" in class_name

    def get_window_class(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        if not ctypes.windll.user32.GetClassNameW(hwnd, buffer, len(buffer)):
            return ""
        return buffer.value

    def get_process_name(self, hwnd):
        process_id = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return ""

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            process_id.value,
        )
        if not handle:
            return ""

        try:
            buffer = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(buffer))
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return Path(buffer.value).name
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def get_window_handle(self, window):
        if window is None:
            return None
        try:
            return window.winfo_id()
        except tk.TclError:
            return None

    def show_window(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.refresh_now()
        self.root.after(0, self.root.lift)
        self.root.attributes("-topmost", True)
        self.root.after(100, lambda: self.root.attributes("-topmost", False))

    def hide_window(self):
        self.root.withdraw()
        if self.value_badge is not None:
            self.value_badge.attributes("-topmost", True)

    def on_add_holding(self):
        symbol = self.symbol_entry.get().strip().upper()
        try:
            shares = float(self.shares_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number of shares.")
            return

        invested_text = self.invested_entry.get().strip()
        invested = None
        if invested_text:
            invested = self.to_price(invested_text)
            if invested is None:
                messagebox.showerror("Error", "Please enter a valid invested amount.")
                return

        if not symbol or shares <= 0:
            messagebox.showerror("Error", "Please enter a valid symbol and positive shares.")
            return

        existing = next((item for item in self.holdings if item["symbol"] == symbol), None)
        if existing:
            existing["shares"] = shares
            if invested is not None:
                existing["invested"] = invested
            existing["value"] = existing.get("price", 0.0) * shares
        else:
            self.holdings.append(
                {
                    "symbol": symbol,
                    "shares": shares,
                    "price": 0.0,
                    "invested": invested or 0.0,
                    "value": 0.0,
                }
            )

        self.symbol_entry.delete(0, tk.END)
        self.shares_entry.delete(0, tk.END)
        self.invested_entry.delete(0, tk.END)
        self.save_holdings()
        self.display_cached_holdings()
        self.refresh_now()

    def display_cached_holdings(self):
        total_value = sum(item.get("value", 0.0) for item in self.holdings)
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.holdings):
            diff = item.get("value", 0.0) - item.get("invested", 0.0)
            row_tag = "evenrow" if index % 2 else "oddrow"
            diff_tag = "negative" if diff < 0 else "positive"
            if index == 0:
                move_value = "  ⬇"
            elif index == len(self.holdings) - 1:
                move_value = "⬆  "
            else:
                move_value = "⬆ ⬇"
            self.tree.insert(
                "",
                tk.END,
                values=(
                    move_value,
                    item["symbol"],
                    item["shares"],
                    f"${item['price']:.2f}",
                    f"${item.get('invested', 0.0):.2f}",
                    f"${item['value']:.2f}",
                    f"${diff:,.2f}",
                ),
                tags=(row_tag, diff_tag),
            )

        self.last_total_value = total_value
        self.update_total_title(total_value)
        self.update_total_diff(total_value)

    def load_holdings(self):
        if not HOLDINGS_FILE.exists():
            return []

        try:
            saved_holdings = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Could not load saved holdings: {exc}")
            return []

        holdings = []
        for item in saved_holdings:
            symbol = str(item.get("symbol", "")).strip().upper()
            shares = self.to_price(item.get("shares"))
            if not symbol or shares is None:
                continue
            price = self.to_price(item.get("price")) or 0.0
            invested = self.to_price(item.get("invested")) or 0.0
            value = price * shares
            holdings.append(
                {
                    "symbol": symbol,
                    "shares": shares,
                    "price": price,
                    "invested": invested,
                    "value": value,
                }
            )
        return holdings

    def save_holdings(self):
        data = [
            {
                "symbol": item["symbol"],
                "shares": item["shares"],
                "price": item.get("price", 0.0),
                "invested": item.get("invested", 0.0),
            }
            for item in self.holdings
        ]

        try:
            HOLDINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"Could not save holdings: {exc}")

    def load_settings(self):
        if not SETTINGS_FILE.exists():
            return {}

        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Could not load settings: {exc}")
            return {}

        return settings if isinstance(settings, dict) else {}

    def save_settings(self):
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"Could not save settings: {exc}")
        finally:
            self.settings_save_after_id = None

    def schedule_settings_save(self):
        if self.settings_save_after_id is not None:
            try:
                self.root.after_cancel(self.settings_save_after_id)
            except tk.TclError:
                pass
        self.settings_save_after_id = self.root.after(200, self.save_settings)

    def on_window_configure(self, event):
        if event.widget is not self.root:
            return
        geometry = self.root.geometry()
        if self.settings.get("window_geometry") != geometry:
            self.settings["window_geometry"] = geometry
            self.schedule_settings_save()

    def refresh_portfolio_values(self):
        if not self.holdings:
            self.update_total_title(0.0)
            self.tree.delete(*self.tree.get_children())
            return

        if self.refresh_in_progress:
            return

        self.refresh_in_progress = True
        holdings_snapshot = [item.copy() for item in self.holdings]
        thread = threading.Thread(target=self.fetch_prices, args=(holdings_snapshot,), daemon=True)
        thread.start()

    def fetch_prices(self, holdings):
        total_value = 0.0
        updated = []
        failed_symbols = []
        for item in holdings:
            price = self.get_stock_price(item["symbol"])
            if price is None:
                price = item.get("price", 0.0)
                failed_symbols.append(item["symbol"])
            value = price * item["shares"]
            updated.append({"symbol": item["symbol"], "shares": item["shares"], "price": price, "value": value})
            total_value += value

        self.root.after(0, lambda: self.update_display(updated, total_value, failed_symbols))

    def get_stock_price(self, symbol):
        ticker = yf.Ticker(symbol)

        try:
            price = self.get_quote_price(ticker)
            if price is not None:
                return price
        except Exception as exc:
            print(f"Could not fetch quote price for {symbol}: {exc}")

        try:
            price = self.get_fast_info_price(ticker)
            if price is not None:
                return price
        except Exception as exc:
            print(f"Could not fetch live price for {symbol}: {exc}")

        try:
            data = yf.download(
                tickers=symbol,
                period="1d",
                interval="1m",
                progress=False,
                threads=False,
                auto_adjust=False,
            )
            price = self.get_close_price(data, symbol)
            if price is not None:
                return price
        except Exception as exc:
            print(f"Could not download intraday price for {symbol}: {exc}")

        try:
            history = ticker.history(period="5d", interval="1d", auto_adjust=False)
            price = self.get_close_price(history, symbol)
            if price is not None:
                return price
        except Exception as exc:
            print(f"Could not fetch price history for {symbol}: {exc}")

        try:
            data = yf.download(
                tickers=symbol,
                period="5d",
                interval="1d",
                progress=False,
                threads=False,
                auto_adjust=False,
            )
            return self.get_close_price(data, symbol)
        except Exception as exc:
            print(f"Could not download price for {symbol}: {exc}")
            return None

    def get_quote_price(self, ticker):
        quote = ticker.info
        market_state = quote.get("marketState")

        if market_state in ("PRE", "PREPRE"):
            price = self.to_price(quote.get("preMarketPrice"))
            if price is not None:
                return price
        if market_state in ("POST", "POSTPOST"):
            price = self.to_price(quote.get("postMarketPrice"))
            if price is not None:
                return price

        for key in ("currentPrice", "regularMarketPrice", "ask", "bid", "regularMarketPreviousClose"):
            price = self.to_price(quote.get(key))
            if price is not None:
                return price

        return None

    def get_fast_info_price(self, ticker):
        fast_info = getattr(ticker, "fast_info", None)
        if not fast_info:
            return None

        for key in ("last_price", "regular_market_price", "previous_close"):
            value = None
            try:
                value = fast_info[key]
            except (KeyError, TypeError):
                value = getattr(fast_info, key, None)

            price = self.to_price(value)
            if price is not None:
                return price
        return None

    def get_close_price(self, data, symbol):
        if data is None or data.empty or "Close" not in data:
            return None

        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            if symbol in close:
                close = close[symbol]
            elif len(close.columns) == 1:
                close = close.iloc[:, 0]
            else:
                return None

        close = close.dropna()
        if close.empty:
            return None
        return self.to_price(close.iloc[-1])

    def to_price(self, value):
        if value is None:
            return None
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None

    def update_display(self, updated_holdings, total_value=None, failed_symbols=None):
        self.refresh_in_progress = False
        updated_by_symbol = {item["symbol"]: item for item in updated_holdings}
        merged_holdings = []

        for item in self.holdings:
            updated = updated_by_symbol.get(item["symbol"])
            invested = item.get("invested", 0.0)
            if updated is None:
                price = item.get("price", 0.0)
                shares = item["shares"]
            else:
                price = updated.get("price", item.get("price", 0.0))
                shares = item["shares"]
            merged_holdings.append(
                {
                    "symbol": item["symbol"],
                    "shares": shares,
                    "price": price,
                    "invested": invested,
                    "value": price * shares,
                }
            )

        for symbol, updated in updated_by_symbol.items():
            if any(item["symbol"] == symbol for item in merged_holdings):
                continue
            merged_holdings.append(updated)

        self.holdings = merged_holdings
        total_value = sum(item["value"] for item in self.holdings)
        self.last_total_value = total_value
        self.save_holdings()
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.holdings):
            diff = item.get("value", 0.0) - item.get("invested", 0.0)
            row_tag = "evenrow" if index % 2 else "oddrow"
            diff_tag = "negative" if diff < 0 else "positive"
            if index == 0:
                move_value = "  ⬇"
            elif index == len(self.holdings) - 1:
                move_value = "⬆  "
            else:
                move_value = "⬆ ⬇"
            self.tree.insert(
                "",
                tk.END,
                values=(
                    move_value,
                    item["symbol"],
                    item["shares"],
                    f"${item['price']:.2f}",
                    f"${item.get('invested', 0.0):.2f}",
                    f"${item['value']:.2f}",
                    f"${diff:,.2f}",
                ),
                tags=(row_tag, diff_tag),
            )

        self.update_total_title(total_value)
        self.update_total_diff(total_value)
        if failed_symbols:
            failed = ", ".join(failed_symbols)
            self.status_label.config(text=f"Last updated: {time.strftime('%H:%M:%S')}. No new price for: {failed}")
        else:
            self.status_label.config(text=f"Last updated: {time.strftime('%H:%M:%S')}")

    def schedule_refresh(self, immediate=False):
        if self.refresh_after_id is not None:
            try:
                self.root.after_cancel(self.refresh_after_id)
            except tk.TclError:
                pass
            self.refresh_after_id = None

        if immediate:
            self.refresh_portfolio_values()
        interval = VISIBLE_UPDATE_INTERVAL_MS
        self.refresh_after_id = self.root.after(interval, self.refresh_now)

    def refresh_now(self):
        self.schedule_refresh(immediate=True)

    def update_total_title(self, total_value):
        invested_total = sum(item.get("invested", 0.0) for item in self.holdings)
        diff = total_value - invested_total
        self.last_total_value = total_value

        total_text = f"${total_value:,.2f}"
        self.total_label.config(text="Total portfolio value:")
        self.total_value_label.config(text=total_text, foreground="#008000")
        self.root.title(f"Portfolio: {total_text}")

        if self.show_change.get():
            badge_text = f"${diff:,.2f}"
            badge_color = "#B00020" if diff < 0 else "#008000"
        else:
            badge_text = total_text
            badge_color = "#008000"

        if self.value_badge_label is not None:
            self.value_badge_label.config(text=badge_text, fg=badge_color)
            self.position_value_badge()

    def refresh_total_display(self):
        self.settings["show_change"] = self.show_change.get()
        self.save_settings()
        self.update_total_title(self.last_total_value)

    def update_total_diff(self, total_value):
        invested_total = sum(item.get("invested", 0.0) for item in self.holdings)
        diff = total_value - invested_total
        diff_text = f"${diff:,.2f}"
        self.total_diff_text.config(text="Total change:")
        self.total_diff_value.config(text=diff_text, fg="#B00020" if diff < 0 else "#008000")

    def is_window_visible(self):
        return self.root.state() != "withdrawn"

    def quit_app(self):
        if self.refresh_after_id is not None:
            try:
                self.root.after_cancel(self.refresh_after_id)
            except tk.TclError:
                pass
            self.refresh_after_id = None

        if self.value_badge is not None:
            self.value_badge.destroy()
            self.value_badge = None

        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = StockTickerApp(root)
    root.mainloop()
