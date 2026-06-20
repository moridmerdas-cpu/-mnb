import logging
import sqlite3
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ─── Config ───────────────────────────────────────────────────────────────────

ADMINS = [8296865861]  # ← Replace with your actual admin Telegram user IDs
BOT_TOKEN = "8637969459:AAHNqip3CO8Wv9iXXvXIJ1uFalvpB5cfsig"  # ← Replace with your bot token from @BotFather
DB_PATH = "settings.db"

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Conversation States ──────────────────────────────────────────────────────

WAITING_SOURCE = 1
WAITING_TARGET = 2

# ─── Database ─────────────────────────────────────────────────────────────────

db_lock = threading.Lock()


def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source INTEGER,
                target INTEGER,
                active INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        # Insert a default row if none exists
        row = conn.execute("SELECT COUNT(*) FROM settings").fetchone()
        if row[0] == 0:
            conn.execute("INSERT INTO settings (source, target, active) VALUES (NULL, NULL, 0)")
            conn.commit()
        conn.close()


def get_settings() -> dict:
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT source, target, active FROM settings ORDER BY id LIMIT 1").fetchone()
        conn.close()
    if row:
        return {"source": row[0], "target": row[1], "active": row[2]}
    return {"source": None, "target": None, "active": 0}


def set_source(chat_id: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE settings SET source = ? WHERE id = 1", (chat_id,))
        conn.commit()
        conn.close()


def set_target(chat_id: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE settings SET target = ? WHERE id = 1", (chat_id,))
        conn.commit()
        conn.close()


def set_active(state: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE settings SET active = ? WHERE id = 1", (state,))
        conn.commit()
        conn.close()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📥 تنظیم گروه", callback_data="set_source")],
        [InlineKeyboardButton("📤 تنظیم چنل", callback_data="set_target")],
        [
            InlineKeyboardButton("▶️ شروع فورواد", callback_data="start_forward"),
            InlineKeyboardButton("⏹ توقف فورواد", callback_data="stop_forward"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def status_text(settings: dict) -> str:
    source = f"`{settings['source']}`" if settings["source"] else "تنظیم نشده"
    target = f"`{settings['target']}`" if settings["target"] else "تنظیم نشده"
    active = "✅ فعال" if settings["active"] else "⏹ غیرفعال"
    return (
        f"🎛 *پنل مدیریت ربات*\n\n"
        f"📥 گروه منبع: {source}\n"
        f"📤 چنل مقصد: {target}\n"
        f"🔄 وضعیت فورواد: {active}"
    )


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# ─── Command Handlers ─────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ دسترسی نداری")
        return ConversationHandler.END

    settings = get_settings()
    await update.message.reply_text(
        status_text(settings),
        reply_markup=admin_panel_keyboard(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─── Callback Handlers ────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not is_admin(user.id):
        await query.edit_message_text("❌ دسترسی نداری")
        return ConversationHandler.END

    data = query.data

    if data == "set_source":
        await query.edit_message_text(
            "📥 یوزرنیم گروه را ارسال کن (مثال: @mygroup)\n\n"
            "برای انصراف /cancel بزن"
        )
        return WAITING_SOURCE

    elif data == "set_target":
        await query.edit_message_text(
            "📤 یوزرنیم چنل را ارسال کن (مثال: @mychannel)\n\n"
            "برای انصراف /cancel بزن"
        )
        return WAITING_TARGET

    elif data == "start_forward":
        settings = get_settings()
        if not settings["source"]:
            await query.edit_message_text(
                "❌ ابتدا گروه منبع را تنظیم کن",
                reply_markup=admin_panel_keyboard(),
            )
            return ConversationHandler.END
        if not settings["target"]:
            await query.edit_message_text(
                "❌ ابتدا چنل مقصد را تنظیم کن",
                reply_markup=admin_panel_keyboard(),
            )
            return ConversationHandler.END
        set_active(1)
        settings = get_settings()
        await query.edit_message_text(
            "✅ فورواد فعال شد\n\n" + status_text(settings),
            reply_markup=admin_panel_keyboard(),
            parse_mode="Markdown",
        )
        logger.info("Forwarding activated by admin %s", user.id)
        return ConversationHandler.END

    elif data == "stop_forward":
        set_active(0)
        settings = get_settings()
        await query.edit_message_text(
            "⏹ فورواد متوقف شد\n\n" + status_text(settings),
            reply_markup=admin_panel_keyboard(),
            parse_mode="Markdown",
        )
        logger.info("Forwarding deactivated by admin %s", user.id)
        return ConversationHandler.END

    return ConversationHandler.END


# ─── Source Input Handler ─────────────────────────────────────────────────────

async def receive_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    text = update.message.text.strip()
    if not text.startswith("@"):
        await update.message.reply_text(
            "❌ یوزرنیم باید با @ شروع بشه. دوباره امتحان کن یا /cancel بزن"
        )
        return WAITING_SOURCE

    bot: Bot = context.bot
    try:
        chat = await bot.get_chat(text)
        if chat.type not in ("group", "supergroup"):
            await update.message.reply_text(
                "❌ این یوزرنیم گروه نیست. یوزرنیم یک گروه وارد کن"
            )
            return WAITING_SOURCE

        set_source(chat.id)
        settings = get_settings()
        await update.message.reply_text(
            f"✅ گروه «{chat.title}» با موفقیت وصل شد\n\n" + status_text(settings),
            reply_markup=admin_panel_keyboard(),
            parse_mode="Markdown",
        )
        logger.info("Source group set to %s (%s) by admin %s", chat.title, chat.id, user.id)
        return ConversationHandler.END

    except Exception as e:
        logger.error("Error getting source chat %s: %s", text, e)
        await update.message.reply_text(
            "❌ گروه پیدا نشد. مطمئن شو ربات عضو گروه هست و یوزرنیم درسته.\n"
            "دوباره امتحان کن یا /cancel بزن"
        )
        return WAITING_SOURCE


# ─── Target Input Handler ─────────────────────────────────────────────────────

async def receive_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    text = update.message.text.strip()
    if not text.startswith("@"):
        await update.message.reply_text(
            "❌ یوزرنیم باید با @ شروع بشه. دوباره امتحان کن یا /cancel بزن"
        )
        return WAITING_TARGET

    bot: Bot = context.bot
    try:
        chat = await bot.get_chat(text)
        if chat.type != "channel":
            await update.message.reply_text(
                "❌ این یوزرنیم چنل نیست. یوزرنیم یک چنل وارد کن"
            )
            return WAITING_TARGET

        # Check if bot is admin in the channel
        try:
            bot_member = await bot.get_chat_member(chat.id, bot.id)
            if bot_member.status not in ("administrator", "creator"):
                await update.message.reply_text(
                    "❌ ربات باید ادمین چنل باشه تا بتونه پیام بفرسته.\n"
                    "ربات رو ادمین کن و دوباره امتحان کن"
                )
                return WAITING_TARGET
        except Exception:
            await update.message.reply_text(
                "❌ ربات باید ادمین چنل باشه. ربات رو اضافه و ادمین کن"
            )
            return WAITING_TARGET

        set_target(chat.id)
        settings = get_settings()
        await update.message.reply_text(
            f"✅ چنل «{chat.title}» با موفقیت وصل شد\n\n" + status_text(settings),
            reply_markup=admin_panel_keyboard(),
            parse_mode="Markdown",
        )
        logger.info("Target channel set to %s (%s) by admin %s", chat.title, chat.id, user.id)
        return ConversationHandler.END

    except Exception as e:
        logger.error("Error getting target chat %s: %s", text, e)
        await update.message.reply_text(
            "❌ چنل پیدا نشد. مطمئن شو ربات ادمین چنل هست و یوزرنیم درسته.\n"
            "دوباره امتحان کن یا /cancel بزن"
        )
        return WAITING_TARGET


# ─── Cancel Handler ───────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END
    settings = get_settings()
    await update.message.reply_text(
        "❌ عملیات لغو شد\n\n" + status_text(settings),
        reply_markup=admin_panel_keyboard(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─── Message Forwarder ────────────────────────────────────────────────────────

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = get_settings()

    if not settings["active"]:
        return
    if not settings["source"] or not settings["target"]:
        return

    message = update.message or update.channel_post
    if not message:
        return

    chat_id = message.chat_id
    if chat_id != settings["source"]:
        return

    target = settings["target"]
    bot: Bot = context.bot

    try:
        await bot.forward_message(
            chat_id=target,
            from_chat_id=chat_id,
            message_id=message.message_id,
        )
        logger.info(
            "Forwarded message %s from chat %s to %s",
            message.message_id,
            chat_id,
            target,
        )
    except Exception as e:
        logger.error("Failed to forward message %s: %s", message.message_id, e)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_callback),
        ],
        states={
            WAITING_SOURCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_source),
                CommandHandler("cancel", cancel),
            ],
            WAITING_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
        per_chat=True,
    )

    app.add_handler(conv_handler)

    # Forward messages from any group/channel
    app.add_handler(
        MessageHandler(
            (filters.ChatType.GROUPS | filters.ChatType.CHANNEL)
            & (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL
               | filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE | filters.Sticker.ALL),
            forward_message,
        ),
        group=1,
    )

    logger.info("Bot started with polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
