"""
╔══════════════════════════════════════════════════╗
║         ربات فورواردر دوطرفه  🤖                ║
║  python-telegram-bot 22+  |  Python 3.14+        ║
║  Web Service Mode (Render)                       ║
╚══════════════════════════════════════════════════╝
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Self, override

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ════════════════════════════════════════════════
#  تنظیمات با متغیرهای محیطی (Python 3.14+)
# ════════════════════════════════════════════════

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    msg = "❌ BOT_TOKEN environment variable is not set!"
    raise ValueError(msg)

ADMINS: list[int] = []
admins_str: str = os.getenv("ADMINS", "")
if admins_str:
    ADMINS = [int(x.strip()) for x in admins_str.split(",") if x.strip()]
if not ADMINS:
    msg = "❌ ADMINS environment variable is not set!"
    raise ValueError(msg)

DB_PATH: str = os.getenv("DB_PATH", "settings.db")
PORT: int = int(os.getenv("PORT", "8443"))
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")

log = logging.getLogger(__name__)

# ════════════════════════════════════════════════
#  حالت‌های مکالمه (با Type Aliases جدید پایتون 3.14)
# ════════════════════════════════════════════════

type ConversationState = int

ST_MENU: ConversationState = 0
ST_PANEL: ConversationState = 1
ST_SRC: ConversationState = 2
ST_TGT: ConversationState = 3

# ════════════════════════════════════════════════
#  مدل داده با slots و frozen (پایتون 3.14)
# ════════════════════════════════════════════════

@dataclass(slots=True, frozen=True)
class Config:
    mode: str
    source: int | None
    target: int | None
    active: bool

    @property
    def ready(self) -> bool:
        """آیا تنظیمات کامل است؟"""
        return self.source is not None and self.target is not None

    @property
    def mode_label(self) -> str:
        """برچسب حالت فورواد"""
        return "گروه  →  چنل 📤" if self.mode == "gtc" else "چنل  →  گروه 📥"

# ════════════════════════════════════════════════
#  دیتابیس (thread-safe با Context Manager)
# ════════════════════════════════════════════════

_lock = threading.Lock()

def init_db() -> None:
    """ایجاد جدول دیتابیس اگر وجود نداشته باشد"""
    with _lock:
        with sqlite3.connect(DB_PATH) as cx:
            cx.execute(
                """
                CREATE TABLE IF NOT EXISTS configs (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode    TEXT    NOT NULL UNIQUE,
                    source  INTEGER,
                    target  INTEGER,
                    active  INTEGER DEFAULT 0
                )
                """
            )
            for m in ("gtc", "ctg"):
                cx.execute(
                    "INSERT OR IGNORE INTO configs (mode, source, target, active) VALUES (?, NULL, NULL, 0)",
                    (m,),
                )
            cx.commit()

def db_get(mode: str) -> Config:
    """دریافت تنظیمات از دیتابیس"""
    with _lock:
        with sqlite3.connect(DB_PATH) as cx:
            row = cx.execute(
                "SELECT source, target, active FROM configs WHERE mode=?",
                (mode,)
            ).fetchone()
    if row:
        return Config(mode=mode, source=row[0], target=row[1], active=bool(row[2]))
    return Config(mode=mode, source=None, target=None, active=False)

def db_set(mode: str, field: str, value: int | None) -> None:
    """به‌روزرسانی تنظیمات در دیتابیس"""
    # بررسی فیلد معتبر با match-case پایتون 3.14
    match field:
        case "source" | "target" | "active":
            pass
        case _:
            msg = f"Unknown field: {field!r}"
            raise ValueError(msg)
    
    with _lock:
        with sqlite3.connect(DB_PATH) as cx:
            cx.execute(
                f"UPDATE configs SET {field}=? WHERE mode=?",
                (value, mode)
            )
            cx.commit()

# ════════════════════════════════════════════════
#  ابزار: نرمال‌سازی یوزرنیم
# ════════════════════════════════════════════════

def normalize(text: str) -> str:
    """نرمال‌سازی یوزرنیم از فرمت‌های مختلف"""
    if not text or not text.strip():
        return ""
    
    t: str = text.strip()
    prefixes: tuple[str, ...] = (
        "https://telegram.me/",
        "https://t.me/",
        "http://t.me/",
        "telegram.me/",
        "t.me/",
    )
    
    for prefix in prefixes:
        if t.lower().startswith(prefix):
            t = t[len(prefix):]
            break
    
    t = t.lstrip("@").split("/")[0].split("?")[0]
    return f"@{t}" if t else ""

# ════════════════════════════════════════════════
#  کیبورد و متن (با style برای PTB)
# ════════════════════════════════════════════════

def mode_select_kb() -> InlineKeyboardMarkup:
    """صفحه انتخاب حالت فورواد"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📤 فورواد گروه  →  چنل",
                style="success",
                callback_data="mode_gtc"
            )
        ],
        [
            InlineKeyboardButton(
                "📥 فورواد چنل  →  گروه",
                style="primary",
                callback_data="mode_ctg"
            )
        ],
    ])

def panel_kb(mode: str) -> InlineKeyboardMarkup:
    """پنل مدیریت هر حالت"""
    p: str = f"{mode}:"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "▶️ شروع فورواد",
                style="success",
                callback_data=f"{p}start"
            ),
            InlineKeyboardButton(
                "⏹ توقف فورواد",
                style="danger",
                callback_data=f"{p}stop"
            ),
        ],
        [
            InlineKeyboardButton(
                "📥 تنظیم منبع",
                style="primary",
                callback_data=f"{p}set_src"
            ),
            InlineKeyboardButton(
                "📤 تنظیم مقصد",
                style="primary",
                callback_data=f"{p}set_tgt"
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 وضعیت",
                style="secondary",
                callback_data=f"{p}status"
            ),
            InlineKeyboardButton(
                "🔙 بازگشت",
                style="secondary",
                callback_data="back"
            ),
        ],
    ])

def reply_kb() -> ReplyKeyboardMarkup:
    """دکمه‌های پایین صفحه"""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("▶️ شروع فورواد", style="success"),
                KeyboardButton("⏹ توقف فورواد", style="danger"),
            ],
            [
                KeyboardButton("📥 تنظیم منبع", style="primary"),
                KeyboardButton("📤 تنظیم مقصد", style="primary"),
            ],
            [
                KeyboardButton("📊 وضعیت", style="secondary"),
                KeyboardButton("🔙 بازگشت", style="secondary"),
            ],
        ],
        resize_keyboard=True,
    )

def panel_text(cfg: Config) -> str:
    """متن نمایش وضعیت"""
    src: str = f"`{cfg.source}`" if cfg.source else "─ تنظیم نشده"
    tgt: str = f"`{cfg.target}`" if cfg.target else "─ تنظیم نشده"
    status: str = "✅ فعال" if cfg.active else "🔴 غیرفعال"
    
    src_lbl: str
    tgt_lbl: str
    if cfg.mode == "gtc":
        src_lbl, tgt_lbl = "📥 گروه منبع", "📤 چنل مقصد"
    else:
        src_lbl, tgt_lbl = "📥 چنل منبع", "📤 گروه مقصد"
    
    return (
        f"╔══════════════════════╗\n"
        f"║  🎛  {cfg.mode_label:<18}║\n"
        f"╚══════════════════════╝\n\n"
        f"{src_lbl}:  {src}\n"
        f"{tgt_lbl}:   {tgt}\n"
        f"📡 *فورواد:*      {status}"
    )

# ════════════════════════════════════════════════
#  هندلرهای ربات
# ════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    """دستور /start"""
    if not update.effective_user or update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ شما دسترسی ندارید")
        return ConversationHandler.END

    ctx.user_data.clear()
    await update.message.reply_text(
        "🤖 *ربات فورواردر دوطرفه*\n\nجهت فورواد را انتخاب کن:",
        reply_markup=mode_select_kb(),
        parse_mode="Markdown",
    )
    return ST_MENU

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    """هندلر دکمه‌های Inline"""
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if uid not in ADMINS:
        await q.edit_message_text("❌ شما دسترسی ندارید")
        return ConversationHandler.END

    data: str = q.data

    # انتخاب حالت با match-case پایتون 3.14
    match data:
        case "mode_gtc" | "mode_ctg":
            mode: str = data.split("_")[1]
            ctx.user_data["mode"] = mode
            cfg: Config = db_get(mode)
            await q.edit_message_text(
                panel_text(cfg),
                reply_markup=panel_kb(mode),
                parse_mode="Markdown",
            )
            await q.message.reply_text(
                "از دکمه‌های پایین هم می‌تونی استفاده کنی:",
                reply_markup=reply_kb(),
            )
            return ST_PANEL

        case "back":
            ctx.user_data.pop("mode", None)
            await q.message.edit_reply_markup(reply_markup=None)
            await q.edit_message_text(
                "🤖 *ربات فورواردر دوطرفه*\n\nجهت فورواد را انتخاب کن:",
                reply_markup=mode_select_kb(),
                parse_mode="Markdown",
            )
            return ST_MENU

    # دکمه‌های پنل با فرمت mode:action
    if ":" not in data:
        return ST_PANEL

    mode, action = data.split(":", 1)
    ctx.user_data["mode"] = mode
    cfg = db_get(mode)

    match action:
        case "status":
            await q.edit_message_text(
                f"📊 *وضعیت فعلی*\n\n{panel_text(cfg)}",
                reply_markup=panel_kb(mode),
                parse_mode="Markdown",
            )

        case "start":
            match (cfg.source, cfg.target):
                case (None, _):
                    await q.answer("⚠️ ابتدا منبع را تنظیم کنید", show_alert=True)
                    return ST_PANEL
                case (_, None):
                    await q.answer("⚠️ ابتدا مقصد را تنظیم کنید", show_alert=True)
                    return ST_PANEL
            db_set(mode, "active", 1)
            cfg = db_get(mode)
            await q.edit_message_text(
                f"✅ *فورواد فعال شد!*\n\n{panel_text(cfg)}",
                reply_markup=panel_kb(mode),
                parse_mode="Markdown",
            )
            log.info("▶ [%s] Forwarding STARTED by admin %s", mode, uid)

        case "stop":
            db_set(mode, "active", 0)
            cfg = db_get(mode)
            await q.edit_message_text(
                f"⏹ *فورواد متوقف شد*\n\n{panel_text(cfg)}",
                reply_markup=panel_kb(mode),
                parse_mode="Markdown",
            )
            log.info("■ [%s] Forwarding STOPPED by admin %s", mode, uid)

        case "set_src":
            src_type: str = "گروه یا سوپرگروه" if mode == "gtc" else "چنل"
            await q.edit_message_text(
                f"📥 *تنظیم منبع ({src_type})*\n\n"
                f"یوزرنیم {src_type} را ارسال کن\n\n"
                "فرمت‌های قابل قبول:\n"
                "`@username`\n"
                "`t.me/username`\n"
                "`https://t.me/username`\n\n"
                "برای انصراف /cancel بزن",
                parse_mode="Markdown",
            )
            return ST_SRC

        case "set_tgt":
            tgt_type: str = "چنل" if mode == "gtc" else "گروه یا سوپرگروه"
            admin_msg: str = "⚠️ ربات باید ادمین چنل باشد\n\n" if mode == "gtc" else "⚠️ ربات باید عضو گروه باشد\n\n"
            await q.edit_message_text(
                f"📤 *تنظیم مقصد ({tgt_type})*\n\n"
                f"یوزرنیم {tgt_type} را ارسال کن\n\n"
                "فرمت‌های قابل قبول:\n"
                "`@username`\n"
                "`t.me/username`\n"
                "`https://t.me/username`\n\n"
                f"{admin_msg}"
                "برای انصراف /cancel بزن",
                parse_mode="Markdown",
            )
            return ST_TGT

    return ST_PANEL

async def on_reply_kb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    """هندلر دکمه‌های Reply Keyboard"""
    uid = update.effective_user.id
    text = update.message.text
    mode = ctx.user_data.get("mode")

    if uid not in ADMINS or not mode:
        return ST_PANEL

    cfg = db_get(mode)

    # استفاده از match-case پایتون 3.14 با شرط‌های مختلف
    match text:
        case text if "شروع فورواد" in text:
            match (cfg.source, cfg.target):
                case (None, _):
                    await update.message.reply_text("⚠️ ابتدا منبع را تنظیم کن")
                    return ST_PANEL
                case (_, None):
                    await update.message.reply_text("⚠️ ابتدا مقصد را تنظیم کن")
                    return ST_PANEL
            db_set(mode, "active", 1)
            cfg = db_get(mode)
            await update.message.reply_text(
                f"✅ *فورواد فعال شد!*\n\n{panel_text(cfg)}",
                reply_markup=panel_kb(mode),
                parse_mode="Markdown",
            )
            log.info("▶ [%s] STARTED", mode)

        case text if "توقف فورواد" in text:
            db_set(mode, "active", 0)
            cfg = db_get(mode)
            await update.message.reply_text(
                f"⏹ *فورواد متوقف شد*\n\n{panel_text(cfg)}",
                reply_markup=panel_kb(mode),
                parse_mode="Markdown",
            )
            log.info("■ [%s] STOPPED", mode)

        case text if "تنظیم منبع" in text:
            src_type = "گروه یا سوپرگروه" if mode == "gtc" else "چنل"
            await update.message.reply_text(
                f"📥 یوزرنیم {src_type} را ارسال کن\n(مثال: @username یا t.me/username)\n\n/cancel برای انصراف"
            )
            return ST_SRC

        case text if "تنظیم مقصد" in text:
            tgt_type = "چنل" if mode == "gtc" else "گروه یا سوپرگروه"
            await update.message.reply_text(
                f"📤 یوزرنیم {tgt_type} را ارسال کن\n(مثال: @username یا t.me/username)\n\n/cancel برای انصراف"
            )
            return ST_TGT

        case text if "وضعیت" in text:
            await update.message.reply_text(
                f"📊 *وضعیت فعلی*\n\n{panel_text(cfg)}",
                reply_markup=panel_kb(mode),
                parse_mode="Markdown",
            )

        case text if "بازگشت" in text:
            ctx.user_data.pop("mode", None)
            await update.message.reply_text(
                "🤖 *ربات فورواردر دوطرفه*\n\nجهت فورواد را انتخاب کن:",
                reply_markup=mode_select_kb(),
                parse_mode="Markdown",
            )
            return ST_MENU

    return ST_PANEL

async def recv_src(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    """دریافت و اعتبارسنجی منبع"""
    mode = ctx.user_data.get("mode")
    if not mode:
        return ConversationHandler.END

    # بررسی دکمه‌های منو
    if any(kw in update.message.text for kw in ["شروع", "توقف", "تنظیم", "وضعیت", "بازگشت"]):
        return await on_reply_kb(update, ctx)

    username = normalize(update.message.text)
    if not username or username == "@":
        await update.message.reply_text(
            "❌ یوزرنیم نامعتبر است\n\n"
            "مثال: `@mygroup` یا `t.me/mygroup`\n\n"
            "دوباره ارسال کن یا /cancel بزن",
            parse_mode="Markdown",
        )
        return ST_SRC

    try:
        chat = await ctx.bot.get_chat(username)
    except Exception as e:
        log.warning("get_chat failed for %r: %s", username, e)
        await update.message.reply_text(
            "❌ چت پیدا نشد!\n\n"
            "• یوزرنیم را چک کن\n"
            "• مطمئن شو ربات عضو آن است\n\n"
            "دوباره ارسال کن یا /cancel بزن"
        )
        return ST_SRC

    # اعتبارسنجی نوع منبع با match-case
    match mode:
        case "gtc":  # منبع باید گروه باشد
            match chat.type:
                case "group" | "supergroup":
                    pass
                case _:
                    await update.message.reply_text("❌ این گروه نیست! یوزرنیم یک گروه یا سوپرگروه وارد کن")
                    return ST_SRC
        case "ctg":  # منبع باید چنل باشد
            if chat.type != "channel":
                await update.message.reply_text("❌ این چنل نیست! یوزرنیم یک چنل وارد کن")
                return ST_SRC

    db_set(mode, "source", chat.id)
    cfg = db_get(mode)
    log.info("[%s] Source → %s (%s)", mode, chat.title, chat.id)
    await update.message.reply_text(
        f"✅ منبع «*{chat.title}*» با موفقیت وصل شد 🎉\n\n{panel_text(cfg)}",
        reply_markup=panel_kb(mode),
        parse_mode="Markdown",
    )
    return ST_PANEL

async def recv_tgt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    """دریافت و اعتبارسنجی مقصد"""
    mode = ctx.user_data.get("mode")
    if not mode:
        return ConversationHandler.END

    # بررسی دکمه‌های منو
    if any(kw in update.message.text for kw in ["شروع", "توقف", "تنظیم", "وضعیت", "بازگشت"]):
        return await on_reply_kb(update, ctx)

    username = normalize(update.message.text)
    if not username or username == "@":
        await update.message.reply_text(
            "❌ یوزرنیم نامعتبر است\n\n"
            "مثال: `@mychannel` یا `t.me/mychannel`\n\n"
            "دوباره ارسال کن یا /cancel بزن",
            parse_mode="Markdown",
        )
        return ST_TGT

    try:
        chat = await ctx.bot.get_chat(username)
    except Exception as e:
        log.warning("get_chat failed for %r: %s", username, e)
        await update.message.reply_text(
            "❌ چت پیدا نشد!\n\n"
            "• یوزرنیم را چک کن\n"
            "• مطمئن شو ربات عضو/ادمین آن است\n\n"
            "دوباره ارسال کن یا /cancel بزن"
        )
        return ST_TGT

    # اعتبارسنجی نوع مقصد
    match mode:
        case "gtc":  # مقصد باید چنل باشد
            if chat.type != "channel":
                await update.message.reply_text("❌ این چنل نیست! یوزرنیم یک چنل وارد کن")
                return ST_TGT
            # بررسی ادمین بودن ربات در چنل
            try:
                me = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
                match me.status:
                    case "administrator" | "creator":
                        pass
                    case _:
                        raise PermissionError
            except Exception:
                await update.message.reply_text(
                    "❌ ربات ادمین چنل نیست!\n\n"
                    "۱. ربات را به چنل اضافه کن\n"
                    "۲. دسترسی ادمین بده\n"
                    "۳. دوباره یوزرنیم را ارسال کن"
                )
                return ST_TGT

        case "ctg":  # مقصد باید گروه باشد
            match chat.type:
                case "group" | "supergroup":
                    pass
                case _:
                    await update.message.reply_text("❌ این گروه نیست! یوزرنیم یک گروه یا سوپرگروه وارد کن")
                    return ST_TGT

    db_set(mode, "target", chat.id)
    cfg = db_get(mode)
    log.info("[%s] Target → %s (%s)", mode, chat.title, chat.id)
    await update.message.reply_text(
        f"✅ مقصد «*{chat.title}*» با موفقیت وصل شد 🎉\n\n{panel_text(cfg)}",
        reply_markup=panel_kb(mode),
        parse_mode="Markdown",
    )
    return ST_PANEL

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    """لغو عملیات"""
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return ConversationHandler.END
    
    mode = ctx.user_data.get("mode")
    if mode:
        cfg = db_get(mode)
        await update.message.reply_text(
            f"🚫 عملیات لغو شد\n\n{panel_text(cfg)}",
            reply_markup=panel_kb(mode),
            parse_mode="Markdown",
        )
        return ST_PANEL
    
    await update.message.reply_text(
        "🚫 عملیات لغو شد\n\nجهت فورواد را انتخاب کن:",
        reply_markup=mode_select_kb(),
        parse_mode="Markdown",
    )
    return ST_MENU

async def do_forward(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """فوروارد پیام‌ها از منبع به مقصد"""
    # تشخیص نوع پیام
    if update.channel_post:
        msg = update.channel_post
    elif update.message:
        msg = update.message
    else:
        return
    
    if msg is None:
        return
    
    chat_id = msg.chat_id

    # بررسی هر دو حالت
    for mode in ("gtc", "ctg"):
        cfg = db_get(mode)
        
        if not cfg.active:
            continue
            
        if not cfg.ready:
            continue
            
        if chat_id != cfg.source:
            continue
            
        # فوروارد کردن
        try:
            await ctx.bot.forward_message(
                chat_id=cfg.target,
                from_chat_id=chat_id,
                message_id=msg.message_id,
            )
            log.info("📨 [%s] msg#%s  %s → %s", mode, msg.message_id, cfg.source, cfg.target)
            return
        except Exception as e:
            log.error("❌ [%s] Forward failed msg#%s: %s", mode, msg.message_id, e)

# ════════════════════════════════════════════════
#  اجرا با Webhook
# ════════════════════════════════════════════════

def main() -> None:
    """تابع اصلی اجرای ربات"""
    # تنظیم لاگ
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        level=logging.INFO,
    )
    
    init_db()
    log.info("🚀 Bot starting (Python 3.14 | PTB 22+)...")
    log.info(f"📋 BOT_TOKEN: {'✅' if BOT_TOKEN else '❌'}")
    log.info(f"📋 ADMINS: {ADMINS}")
    log.info(f"📋 PORT: {PORT}")
    log.info(f"📋 WEBHOOK_URL: {WEBHOOK_URL}")
    log.info(f"📋 DB_PATH: {DB_PATH}")

    app = Application.builder().token(BOT_TOKEN).build()

    # فیلتر ساده برای همه پیام‌ها
    fwd_filter = filters.ALL & ~filters.COMMAND

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_button),
        ],
        states={
            ST_MENU: [
                CallbackQueryHandler(on_button),
            ],
            ST_PANEL: [
                CallbackQueryHandler(on_button),
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    on_reply_kb,
                ),
            ],
            ST_SRC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_src),
                CommandHandler("cancel", cmd_cancel),
                CallbackQueryHandler(on_button),
            ],
            ST_TGT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_tgt),
                CommandHandler("cancel", cmd_cancel),
                CallbackQueryHandler(on_button),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
        ],
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv, group=0)
    app.add_handler(MessageHandler(fwd_filter, do_forward), group=1)

    # استفاده از Webhook برای Render
    if WEBHOOK_URL:
        log.info("🌐 Setting up webhook...")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True,
        )
    else:
        log.warning("⚠️ WEBHOOK_URL not set! Falling back to polling...")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )

if __name__ == "__main__":
    main()
