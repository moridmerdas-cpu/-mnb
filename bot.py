import os
import json
import requests
from flask import Flask, request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import sqlite3
import asyncio
import threading

# ======== تنظیمات ========
TOKEN = "8637969459:AAHNqip3CO8Wv9iXXvXIJ1uFalvpB5cfsig"
WEBHOOK_URL = "https://mnb-i2hm.onrender.com"
ADMINS = [8296865861]  # آیدی عددی خودت رو جایگزین کن

# ======== دیتابیس ========
db = sqlite3.connect("db.sqlite", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source INTEGER,
    target INTEGER,
    active INTEGER DEFAULT 0
)
""")
db.commit()

def is_admin(user_id):
    return user_id in ADMINS

def get_settings():
    cur.execute("SELECT source, target, active FROM settings WHERE id=1")
    row = cur.fetchone()
    if row:
        return row
    cur.execute("INSERT INTO settings (id, source, target, active) VALUES (1, NULL, NULL, 0)")
    db.commit()
    return (None, None, 0)

def save_settings(source=None, target=None, active=None):
    s, t, a = get_settings()
    cur.execute("""
    INSERT OR REPLACE INTO settings (id, source, target, active)
    VALUES (1, ?, ?, ?)
    """, (
        source if source is not None else s,
        target if target is not None else t,
        active if active is not None else a
    ))
    db.commit()

# ======== اپلیکیشن تلگرام ========
app = Application.builder().token(TOKEN).build()

# ======== هندلرها ========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"Start command from user: {user_id}")
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ دسترسی نداری")
        return

    keyboard = [
        [
            InlineKeyboardButton("📥 تنظیم گروه", callback_data="set_group"),
            InlineKeyboardButton("📤 تنظیم چنل", callback_data="set_channel")
        ],
        [
            InlineKeyboardButton("▶️ شروع فورواد", callback_data="start_fw"),
            InlineKeyboardButton("⏹ توقف فورواد", callback_data="stop_fw")
        ]
    ]
    await update.message.reply_text(
        "🎛 پنل مدیریت ربات\n\n"
        "برای تنظیمات از دکمه‌ها استفاده کن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ دسترسی نداری")
        return

    if query.data == "set_group":
        context.user_data["mode"] = "set_group"
        await query.edit_message_text(
            "📥 یوزرنیم گروه را ارسال کن (مثال: @mygroup)\n\n"
            "⚠️ ربات باید در گروه عضو باشد و دسترسی ارسال پیام داشته باشد."
        )
    elif query.data == "set_channel":
        context.user_data["mode"] = "set_channel"
        await query.edit_message_text(
            "📤 یوزرنیم چنل را ارسال کن (مثال: @mychannel)\n\n"
            "⚠️ ربات باید در چنل ادمین باشد."
        )
    elif query.data == "start_fw":
        save_settings(active=1)
        await query.edit_message_text("✅ فورواد فعال شد")
    elif query.data == "stop_fw":
        save_settings(active=0)
        await query.edit_message_text("⏹ فورواد متوقف شد")

async def capture_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id) or update.message.chat.type != "private":
        return

    mode = context.user_data.get("mode")
    if not mode:
        return

    text = update.message.text.strip()
    if not text.startswith("@"):
        await update.message.reply_text("❌ یوزرنیم باید با @ شروع شود")
        return

    try:
        chat = await context.bot.get_chat(text)
    except Exception as e:
        await update.message.reply_text(f"❌ پیدا نشد یا ربات دسترسی ندارد\n\nخطا: {str(e)}")
        return

    if mode == "set_group":
        if chat.type not in ["group", "supergroup"]:
            await update.message.reply_text("❌ این یوزرنیم گروه نیست")
            return
        save_settings(source=chat.id)
        context.user_data["mode"] = None
        await update.message.reply_text(
            f"✅ گروه «{chat.title}» با موفقیت وصل شد\n"
            f"آیدی: {chat.id}"
        )
    elif mode == "set_channel":
        if chat.type != "channel":
            await update.message.reply_text("❌ این یوزرنیم چنل نیست")
            return
        save_settings(target=chat.id)
        context.user_data["mode"] = None
        await update.message.reply_text(
            f"✅ چنل «{chat.title}» با موفقیت وصل شد\n"
            f"آیدی: {chat.id}"
        )

async def forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    source, target, active = get_settings()
    if not active or not update.message or update.message.chat_id != source:
        return
    try:
        await update.message.forward(chat_id=target)
        print(f"Forwarded message from {source} to {target}")
    except Exception as e:
        print(f"Forward error: {e}")

# اضافه کردن هندلرها
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buttons))
app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, capture_username))
app.add_handler(MessageHandler(filters.ALL & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP), forward))

# ======== حل مشکل Async در Flask ========
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def process_update_sync(update_data):
    """پردازش آپدیت به صورت همزمان"""
    try:
        update = Update.de_json(update_data, app.bot)
        # اجرای async در محیط sync
        future = asyncio.run_coroutine_threadsafe(
            app.process_update(update),
            loop
        )
        future.result(timeout=10)  # انتظار حداکثر 10 ثانیه
        return True
    except Exception as e:
        print(f"Error processing update: {e}")
        return False

# ======== Flask Server ========
flask_app = Flask(__name__)

@flask_app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """دریافت آپدیت از تلگرام"""
    try:
        data = json.loads(request.data)
        
        # پردازش آپدیت
        success = process_update_sync(data)
        
        if success:
            return Response("ok", status=200)
        else:
            return Response("error", status=500)
            
    except Exception as e:
        print(f"Error in webhook: {e}")
        return Response(f"error: {e}", status=500)

@flask_app.route("/", methods=["GET"])
def index():
    return "✅ Bot is running!"

@flask_app.route("/setwebhook", methods=["GET"])
def set_webhook():
    """تنظیم وب‌هوک"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
        params = {"url": f"{WEBHOOK_URL}/{TOKEN}"}
        response = requests.get(url, params=params)
        return f"Webhook response: {response.json()}"
    except Exception as e:
        return f"Error: {e}"

@flask_app.route("/getwebhook", methods=["GET"])
def get_webhook():
    """بررسی وضعیت وب‌هوک"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
        response = requests.get(url)
        return response.json()
    except Exception as e:
        return f"Error: {e}"

@flask_app.route("/status", methods=["GET"])
def status():
    """وضعیت ربات"""
    source, target, active = get_settings()
    return {
        "status": "running",
        "source": source,
        "target": target,
        "active": bool(active),
        "admins": ADMINS
    }

# ======== اجرا ========
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    
    print("=" * 50)
    print("🤖 Bot Starting...")
    print("=" * 50)
    
    # شروع event loop در یک thread جداگانه
    def start_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()
    
    thread = threading.Thread(target=start_loop, daemon=True)
    thread.start()
    
    # تنظیم وب‌هوک
    print("📡 Setting webhook...")
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
        params = {"url": f"{WEBHOOK_URL}/{TOKEN}"}
        response = requests.get(url, params=params)
        print(f"✅ Webhook response: {response.json()}")
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")
    
    # اطلاعات وب‌هوک
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
        response = requests.get(url)
        print(f"📊 Webhook info: {response.json()}")
    except Exception as e:
        print(f"❌ Error getting webhook info: {e}")
    
    print("=" * 50)
    print(f"🚀 Starting Flask server on port {PORT}...")
    print(f"🌐 Webhook URL: {WEBHOOK_URL}/{TOKEN}")
    print("=" * 50)
    
    # اجرای Flask
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
