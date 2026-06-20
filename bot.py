"""
╔══════════════════════════════════════════════╗
║        ربات فورواردر تلگرام  🤖              ║
║  python-telegram-bot 22+  |  Python 3.11+    ║
╚══════════════════════════════════════════════╝

تنظیمات اجباری:
  BOT_TOKEN  ← توکن از @BotFather
  ADMINS     ← آیدی عددی ادمین‌ها
"""

# ════════════════════════════════════════════════
#  1.  کتابخانه‌ها
# ════════════════════════════════════════════════

import logging
import sqlite3
import threading

from telegram import (
    Update,
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ════════════════════════════════════════════════
#  2.  تنظیمات اصلی  ← اینجا رو عوض کن
# ════════════════════════════════════════════════

BOT_TOKEN = "8637969459:AAHNqip3CO8Wv9iXXvXIJ1uFalvpB5cfsig"   # توکن از @BotFather
ADMINS    = [8296865861]              # آیدی عددی ادمین (می‌تونی چند تا بذاری)
DB_PATH   = "settings.db"

# ════════════════════════════════════════════════
#  3.  لاگ
# ════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════
#  4.  دیتابیس (thread-safe)
# ════════════════════════════════════════════════

_lock = threading.Lock()


def init_db() -> None:
    with _lock, sqlite3.connect(DB_PATH) as cx:
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                source  INTEGER,
                target  INTEGER,
                active  INTEGER DEFAULT 0
            )
            """
        )
        if cx.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
            cx.execute("INSERT INTO settings (source, target, active) VALUES (NULL, NULL, 0)")
        cx.commit()


def db_get() -> dict:
    with _lock, sqlite3.connect(DB_PATH) as cx:
        r = cx.execute("SELECT source, target, active FROM settings LIMIT 1").fetchone()
    return {"source": r[0], "target": r[1], "active": r[2]} if r else {"source": None, "target": None, "active": 0}


def db_set(field: str, value) -> None:
    if field not in {"source", "target", "active"}:
        raise ValueError(f"Unknown field: {field}")
    with _lock, sqlite3.connect(DB_PATH) as cx:
        cx.execute(f"UPDATE settings SET {field} = ? WHERE id = 1", (value,))
        cx.commit()


# ════════════════════════════════════════════════
#  5.  حالت‌های مکالمه
# ════════════════════════════════════════════════

WAIT_SOURCE, WAIT_TARGET = range(2)

# ════════════════════════════════════════════════
#  6.  کیبورد و متن پنل
# ════════════════════════════════════════════════

def panel_inline_kb() -> InlineKeyboardMarkup:
    """دکمه‌های شیشه‌ای رنگی داخل پیام"""
    return InlineKeyboardMarkup([
        [
            # سبز ← شروع فورواد
            InlineKeyboardButton("▶️ شروع فورواد",  style="success", callback_data="start"),
            # قرمز ← توقف فورواد
            InlineKeyboardButton("⏹ توقف فورواد",   style="danger",  callback_data="stop"),
        ],
        [
            # آبی ← تنظیم گروه
            InlineKeyboardButton("📥 تنظیم گروه",   style="primary", callback_data="set_src"),
            # آبی ← تنظیم چنل
            InlineKeyboardButton("📤 تنظیم چنل",    style="primary", callback_data="set_tgt"),
        ],
        [
            InlineKeyboardButton("🔄 بروزرسانی",    callback_data="refresh"),
        ],
    ])


def panel_reply_kb() -> ReplyKeyboardMarkup:
    """دکمه‌های رنگی پایین صفحه"""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("▶️ شروع فورواد",  style="success"),   # سبز
                KeyboardButton("⏹ توقف فورواد",   style="danger"),    # قرمز
            ],
            [
                KeyboardButton("📥 تنظیم گروه",   style="primary"),   # آبی
                KeyboardButton("📤 تنظیم چنل",    style="primary"),   # آبی
            ],
        ],
        resize_keyboard=True,
    )


def panel_text(s: dict) -> str:
    src    = f"`{s['source']}`"  if s["source"] else "─ تنظیم نشده"
    tgt    = f"`{s['target']}`"  if s["target"] else "─ تنظیم نشده"
    status = "✅ فعال"           if s["active"] else "🔴 غیرفعال"
    return (
        "╔══════════════════════╗\n"
        "║   🎛  پنل مدیریت     ║\n"
        "╚══════════════════════╝\n\n"
        f"📥 *گروه منبع:*  {src}\n"
        f"📤 *چنل مقصد:*   {tgt}\n"
        f"📡 *فورواد:*      {status}"
    )


# ════════════════════════════════════════════════
#  7.  دستور /start
# ════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("❌ شما دسترسی ندارید")
        return ConversationHandler.END

    s = db_get()

    # دکمه‌های پایین صفحه (رنگی)
    await update.message.reply_text(
        "🎛 *پنل مدیریت ربات*\nاز دکمه‌های پایین یا دکمه‌های زیر پیام استفاده کن:",
        reply_markup=panel_reply_kb(),
        parse_mode="Markdown",
    )

    # دکمه‌های شیشه‌ای رنگی داخل پیام
    await update.message.reply_text(
        panel_text(s),
        reply_markup=panel_inline_kb(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════
#  8.  هندلر دکمه‌های شیشه‌ای (Inline)
# ════════════════════════════════════════════════

async def on_inline_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if uid not in ADMINS:
        await q.edit_message_text("❌ شما دسترسی ندارید")
        return ConversationHandler.END

    data = q.data

    if data == "refresh":
        s = db_get()
        await q.edit_message_text(panel_text(s), reply_markup=panel_inline_kb(), parse_mode="Markdown")
        return ConversationHandler.END

    if data == "start":
        s = db_get()
        if not s["source"]:
            await q.answer("⚠️ ابتدا گروه منبع را تنظیم کنید", show_alert=True)
            return ConversationHandler.END
        if not s["target"]:
            await q.answer("⚠️ ابتدا چنل مقصد را تنظیم کنید", show_alert=True)
            return ConversationHandler.END
        db_set("active", 1)
        s = db_get()
        await q.edit_message_text(
            "✅ *فورواد فعال شد!*\n\n" + panel_text(s),
            reply_markup=panel_inline_kb(),
            parse_mode="Markdown",
        )
        log.info("▶ Forwarding STARTED by admin %s", uid)
        return ConversationHandler.END

    if data == "stop":
        db_set("active", 0)
        s = db_get()
        await q.edit_message_text(
            "⏹ *فورواد متوقف شد*\n\n" + panel_text(s),
            reply_markup=panel_inline_kb(),
            parse_mode="Markdown",
        )
        log.info("■ Forwarding STOPPED by admin %s", uid)
        return ConversationHandler.END

    if data == "set_src":
        await q.edit_message_text(
            "📥 *تنظیم گروه منبع*\n\n"
            "یوزرنیم گروه را ارسال کن:\n"
            "مثال: `@mygroup`\n\n"
            "برای انصراف /cancel بزن",
            parse_mode="Markdown",
        )
        return WAIT_SOURCE

    if data == "set_tgt":
        await q.edit_message_text(
            "📤 *تنظیم چنل مقصد*\n\n"
            "یوزرنیم چنل را ارسال کن:\n"
            "مثال: `@mychannel`\n\n"
            "⚠️ ربات باید ادمین چنل باشد\n\n"
            "برای انصراف /cancel بزن",
            parse_mode="Markdown",
        )
        return WAIT_TARGET

    return ConversationHandler.END


# ════════════════════════════════════════════════
#  9.  هندلر دکمه‌های پایین صفحه (Reply Keyboard)
# ════════════════════════════════════════════════

async def on_reply_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text

    if uid not in ADMINS:
        return ConversationHandler.END

    if "شروع فورواد" in text:
        s = db_get()
        if not s["source"]:
            await update.message.reply_text("⚠️ ابتدا گروه منبع را تنظیم کن")
            return ConversationHandler.END
        if not s["target"]:
            await update.message.reply_text("⚠️ ابتدا چنل مقصد را تنظیم کن")
            return ConversationHandler.END
        db_set("active", 1)
        s = db_get()
        await update.message.reply_text(
            "✅ *فورواد فعال شد!*\n\n" + panel_text(s),
            reply_markup=panel_inline_kb(),
            parse_mode="Markdown",
        )
        log.info("▶ Forwarding STARTED by admin %s", uid)

    elif "توقف فورواد" in text:
        db_set("active", 0)
        s = db_get()
        await update.message.reply_text(
            "⏹ *فورواد متوقف شد*\n\n" + panel_text(s),
            reply_markup=panel_inline_kb(),
            parse_mode="Markdown",
        )
        log.info("■ Forwarding STOPPED by admin %s", uid)

    elif "تنظیم گروه" in text:
        await update.message.reply_text(
            "📥 *تنظیم گروه منبع*\n\n"
            "یوزرنیم گروه را ارسال کن:\n"
            "مثال: `@mygroup`\n\n"
            "برای انصراف /cancel بزن",
            parse_mode="Markdown",
        )
        return WAIT_SOURCE

    elif "تنظیم چنل" in text:
        await update.message.reply_text(
            "📤 *تنظیم چنل مقصد*\n\n"
            "یوزرنیم چنل را ارسال کن:\n"
            "مثال: `@mychannel`\n\n"
            "⚠️ ربات باید ادمین چنل باشد\n\n"
            "برای انصراف /cancel بزن",
            parse_mode="Markdown",
        )
        return WAIT_TARGET

    return ConversationHandler.END


# ════════════════════════════════════════════════
#  10. دریافت یوزرنیم گروه
# ════════════════════════════════════════════════

async def recv_source(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    # اگر یکی از دکمه‌های منو زده شد، دوباره روت کن
    if any(kw in text for kw in ["شروع فورواد", "توقف فورواد", "تنظیم گروه", "تنظیم چنل"]):
        return await on_reply_button(update, ctx)

    if not text.startswith("@"):
        await update.message.reply_text(
            "❌ یوزرنیم باید با @ شروع شود\n"
            "مثال: `@mygroup`\n\n"
            "دوباره ارسال کن یا /cancel بزن",
            parse_mode="Markdown",
        )
        return WAIT_SOURCE

    try:
        chat = await ctx.bot.get_chat(text)
    except Exception as e:
        log.warning("get_chat failed for %s: %s", text, e)
        await update.message.reply_text(
            "❌ گروه پیدا نشد!\n\n"
            "• مطمئن شو ربات عضو گروه است\n"
            "• یوزرنیم را چک کن\n\n"
            "دوباره امتحان کن یا /cancel بزن"
        )
        return WAIT_SOURCE

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "❌ این یک گروه نیست!\n"
            "یوزرنیم یک گروه یا سوپرگروه وارد کن"
        )
        return WAIT_SOURCE

    db_set("source", chat.id)
    s = db_get()
    log.info("📥 Source set to %s (%s) by %s", chat.title, chat.id, uid)
    await update.message.reply_text(
        f"✅ گروه «*{chat.title}*» با موفقیت وصل شد 🎉\n\n" + panel_text(s),
        reply_markup=panel_inline_kb(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════
#  11. دریافت یوزرنیم چنل
# ════════════════════════════════════════════════

async def recv_target(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    # اگر یکی از دکمه‌های منو زده شد، دوباره روت کن
    if any(kw in text for kw in ["شروع فورواد", "توقف فورواد", "تنظیم گروه", "تنظیم چنل"]):
        return await on_reply_button(update, ctx)

    if not text.startswith("@"):
        await update.message.reply_text(
            "❌ یوزرنیم باید با @ شروع شود\n"
            "مثال: `@mychannel`\n\n"
            "دوباره ارسال کن یا /cancel بزن",
            parse_mode="Markdown",
        )
        return WAIT_TARGET

    try:
        chat = await ctx.bot.get_chat(text)
    except Exception as e:
        log.warning("get_chat failed for %s: %s", text, e)
        await update.message.reply_text(
            "❌ چنل پیدا نشد!\n\n"
            "• مطمئن شو ربات ادمین چنل است\n"
            "• یوزرنیم را چک کن\n\n"
            "دوباره امتحان کن یا /cancel بزن"
        )
        return WAIT_TARGET

    if chat.type != "channel":
        await update.message.reply_text(
            "❌ این یک چنل نیست!\n"
            "یوزرنیم یک چنل وارد کن"
        )
        return WAIT_TARGET

    # بررسی ادمین بودن ربات در چنل
    try:
        me = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
        if me.status not in ("administrator", "creator"):
            raise PermissionError("not admin")
    except Exception:
        await update.message.reply_text(
            "❌ ربات ادمین چنل نیست!\n\n"
            "۱. ربات را به چنل اضافه کن\n"
            "۲. به ربات دسترسی ادمین بده\n"
            "۳. دوباره یوزرنیم را ارسال کن"
        )
        return WAIT_TARGET

    db_set("target", chat.id)
    s = db_get()
    log.info("📤 Target set to %s (%s) by %s", chat.title, chat.id, uid)
    await update.message.reply_text(
        f"✅ چنل «*{chat.title}*» با موفقیت وصل شد 🎉\n\n" + panel_text(s),
        reply_markup=panel_inline_kb(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════
#  12. لغو عملیات
# ════════════════════════════════════════════════

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        return ConversationHandler.END
    s = db_get()
    await update.message.reply_text(
        "🚫 عملیات لغو شد\n\n" + panel_text(s),
        reply_markup=panel_inline_kb(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════
#  13. فورواد پیام‌ها (گروه → چنل)
# ════════════════════════════════════════════════

async def do_forward(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = db_get()
    if not s["active"] or not s["source"] or not s["target"]:
        return

    msg = update.message or update.channel_post
    if not msg or msg.chat_id != s["source"]:
        return

    try:
        await ctx.bot.forward_message(
            chat_id=s["target"],
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        log.info("📨 Forwarded msg#%s  [%s → %s]", msg.message_id, s["source"], s["target"])
    except Exception as e:
        log.error("❌ Forward failed msg#%s: %s", msg.message_id, e)


# ════════════════════════════════════════════════
#  14. اجرای ربات
# ════════════════════════════════════════════════

def main() -> None:
    init_db()
    log.info("🚀 Bot starting...")

    app = Application.builder().token(BOT_TOKEN).build()

    # فیلتر پیام‌های قابل فورواد
    fwd_filter = (
        (filters.ChatType.GROUPS | filters.ChatType.CHANNEL)
        & (
            filters.TEXT
            | filters.PHOTO
            | filters.VIDEO
            | filters.Document.ALL
            | filters.AUDIO
            | filters.VOICE
            | filters.VIDEO_NOTE
            | filters.Sticker.ALL
            | filters.ANIMATION
        )
    )

    # پنل ادمین (مکالمه اصلی)
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_inline_button),
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                on_reply_button,
            ),
        ],
        states={
            WAIT_SOURCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_source),
                CommandHandler("cancel", cmd_cancel),
            ],
            WAIT_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_target),
                CommandHandler("cancel", cmd_cancel),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start",  cmd_start),
        ],
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv,                                              group=0)
    app.add_handler(MessageHandler(fwd_filter, do_forward),           group=1)

    log.info("✅ Bot is running (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
