import os
import sys
import time
import threading
import requests
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw
import pystray

# ===================== HÀM HỖ TRỢ =====================

ICON_PATH = "C:/Users/ThanhLQ/Downloads/n.ico"   # đổi thành file .ico của bạn

def create_image():
    try:
        return Image.open(ICON_PATH)
    except Exception as e:
        print(f"⚠️ Không tìm thấy icon, fallback mặc định: {e}")
        # fallback icon tròn xanh
        image = Image.new("RGB", (64, 64), "white")
        dc = ImageDraw.Draw(image)
        dc.ellipse((8, 8, 56, 56), fill="green")
        return image

def add_to_startup():
    try:
        import win32com.client
    except ImportError:
        print("⚠️ Cần cài pywin32 để dùng startup")
        return

    startup_path = os.path.join(
        os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )
    shortcut_path = os.path.join(startup_path, "StockBot.lnk")
    target = sys.executable
    script = os.path.abspath(__file__)

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = target
    shortcut.Arguments = f'"{script}"'
    shortcut.WorkingDirectory = os.path.dirname(script)
    shortcut.IconLocation = target
    shortcut.save()

def fetch_vps_data(symbol, max_retries=5, retry_delay=2):
    url = f"https://bgapidatafeed.vps.com.vn/getliststockdata/{symbol}"
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                return {}
        except requests.RequestException:
            time.sleep(retry_delay * attempt)
    return {}

def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print("❌ Lỗi gửi Telegram:", e)

def get_status_emoji(lastPrice, change, ref_price, ceiling, floor_price):
    if lastPrice == ceiling:
        return "😈"  # trần
    elif lastPrice == ref_price:
        return "😳"  # tham chiếu
    elif lastPrice == floor_price:
        return "🥶"  # sàn
    elif change > 0:
        return "🤢"  # tăng
    elif change < 0:
        return "😡"  # giảm
    else:
        return "⚪"  # không đổi

# ===================== BOT LOGIC =====================

last_sent_data = {}
sent_full_morning = False
sent_full_afternoon = False

def start_bot(bot_token, chat_id, symbols_file, check_interval, run_startup):
    global last_sent_data, sent_full_morning, sent_full_afternoon

    if run_startup:
        add_to_startup()

    while True:
        now = time.localtime()
        hour, minute = now.tm_hour, now.tm_min

        telegram_lines = []
        ceiling_symbols = []
        floor_symbols = []

        try:
            with open(symbols_file, "r") as f:
                symbols_to_track = [line.strip().upper() for line in f.readlines() if line.strip()]
        except Exception as e:
            print(f"❌ Lỗi đọc file mã: {e}")
            time.sleep(check_interval)
            continue

        full_mode = False
        allow_send = False

        # 👉 chỉ bắn trong khung giờ 9h - 15h
        if 9 <= hour <= 15:
            allow_send = True

        # 👉 9h sáng: bắn full 1 lần
        if hour == 9 and not sent_full_morning:
            full_mode = True
            sent_full_morning = True
            allow_send = True

        # 👉 15h chiều: bắn full 1 lần
        if hour == 15 and not sent_full_afternoon:
            full_mode = True
            sent_full_afternoon = True
            allow_send = True

        for symbol in symbols_to_track:
            data = fetch_vps_data(symbol)
            if not data:
                continue

            lastPrice = float(data.get('lastPrice', 0))
            ref_price = float(data.get('r', 0))
            ceiling = float(data.get('c', 0))
            floor_price = float(data.get('f', 0))
            change = lastPrice - ref_price
            emoji = get_status_emoji(lastPrice, change, ref_price, ceiling, floor_price)

            prev_sent = last_sent_data.get(symbol)

            if full_mode or prev_sent is None or (allow_send and prev_sent != lastPrice):
                telegram_lines.append(
                    f"{emoji} {symbol}: {lastPrice} ({change:+.2f}), T:{ceiling}, TC:{ref_price}, S:{floor_price}"
                )
                last_sent_data[symbol] = lastPrice

            if lastPrice == ceiling:
                ceiling_symbols.append(symbol)
            if lastPrice == floor_price:
                floor_symbols.append(symbol)

        # 👉 Gom thành 1 tin duy nhất
        if telegram_lines and allow_send:
            if ceiling_symbols:
                telegram_lines.append("💜 MÃ TRẦN: " + ", ".join(ceiling_symbols))
            if floor_symbols:
                telegram_lines.append("🩵 MÃ SÀN: " + ", ".join(floor_symbols))
            send_telegram_message(bot_token, chat_id, "\n".join(telegram_lines))

        # 👉 reset lại cờ cho ngày hôm sau
        if hour == 0:
            sent_full_morning = False
            sent_full_afternoon = False
            last_sent_data = {}

        time.sleep(check_interval)

# ===================== TRAY ICON =====================

def run_tray_icon():
    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    def on_show(icon, item):
        if not root.winfo_viewable():  # chỉ mở nếu đang ẩn
            root.deiconify()
        root.lift()
        root.focus_force()

    icon = pystray.Icon(
        "stockbot",
        create_image(),
        "StockBot đang chạy",
        menu=pystray.Menu(
            pystray.MenuItem("Hiện cửa sổ", on_show),
            pystray.MenuItem("Thoát", on_quit)
        )
    )
    icon.run()

# ===================== GUI =====================

def browse_file():
    file_path = filedialog.askopenfilename(
        title="Chọn file .txt danh sách mã cần theo dõi",
        filetypes=[("Text files", "*.txt")]
    )
    if file_path and file_path.endswith(".txt"):
        entry_file.delete(0, tk.END)
        entry_file.insert(0, file_path)
    elif file_path:
        messagebox.showerror("Sai định dạng", "Vui lòng chọn đúng file .txt!")

def run():
    bot_token = entry_token.get().strip()
    chat_id = entry_chatid.get().strip()
    symbols_file = entry_file.get().strip()
    fetch_interval = int(entry_interval.get().strip())
    run_startup = var_startup.get()

    if not bot_token or not chat_id or not symbols_file:
        messagebox.showerror("Thiếu dữ liệu", "Vui lòng điền đầy đủ Token, Chat ID và File danh sách mã.")
        return

    t = threading.Thread(target=start_bot, args=(bot_token, chat_id, symbols_file, fetch_interval, run_startup), daemon=True)
    t.start()

    messagebox.showinfo("Bot", "✅ Bot đã khởi động, sẽ gửi tin vào Telegram.\nBạn có thể thấy icon ở khay hệ thống.")
    root.withdraw()  # ẩn cửa sổ sau khi bắt đầu

# ===================== MAIN =====================

root = tk.Tk()
root.title("StockBot Config (Author: ThanhLQ)")
root.geometry("400x250")

# 👉 Thay icon Tkinter bằng feather.ico
try:
    root.iconbitmap(ICON_PATH)
except Exception as e:
    print("⚠️ Không thể set icon cho cửa sổ Tkinter:", e)

tk.Label(root, text="Bot Token:").pack()
entry_token = tk.Entry(root, width=40)
entry_token.pack()

tk.Label(root, text="Chat ID:").pack()
entry_chatid = tk.Entry(root, width=40)
entry_chatid.pack()

tk.Label(root, text="File mã (.txt):").pack()
frame_file = tk.Frame(root)
frame_file.pack()
entry_file = tk.Entry(frame_file, width=30)
entry_file.pack(side=tk.LEFT)
btn_browse = tk.Button(frame_file, text="Browse", command=browse_file)
btn_browse.pack(side=tk.LEFT)

tk.Label(root, text="Interval (giây):").pack()
entry_interval = tk.Entry(root, width=10)
entry_interval.insert(0, "60")
entry_interval.pack()

var_startup = tk.BooleanVar()
chk_startup = tk.Checkbutton(root, text="Khởi động cùng Windows", variable=var_startup)
chk_startup.pack()

btn_start = tk.Button(root, text="Bắt đầu", command=run)
btn_start.pack(pady=10)

# chạy tray icon song song
t_tray = threading.Thread(target=run_tray_icon, daemon=True)
t_tray.start()

root.protocol("WM_DELETE_WINDOW", lambda: root.withdraw())  # ẩn khi nhấn X
root.mainloop()
