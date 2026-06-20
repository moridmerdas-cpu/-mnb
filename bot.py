"""
ربات فورواد دوطرفه گروه ↔️ کانال (تلگرام)
==========================================

- زبان: پایتون 3.14
- کتابخانه: python-telegram-bot >= 22 (با پشتیبانی Webhook)
- اجرا روی Render به صورت Web Service (نه Worker)
- ذخیره‌سازی تنظیمات: SQLite (فایل settings.db)
- رابط کاربری: کاملاً فارسی

نکتهٔ مهم در مورد پارامتر «style»:
------------------------------------
تلگرام به‌صورت بومی هیچ استایل/رنگ بصری برای دکمه‌های اینلاین یا دکمه‌های
کیبورد پشتیبانی نمی‌کند و کتابخانهٔ python-telegram-bot هم چنین پارامتری در
کلاس‌های InlineKeyboardButton / KeyboardButton ندارد (و اگر مستقیماً پاس داده
شود، خطای TypeError می‌دهد چون این کلاس‌ها slot-based و محدود هستند).

برای اینکه طبق درخواست شما پارامتر «style» در کد باقی بماند، تمام دکمه‌ها از
طریق دو تابع کمکی inline_btn() و keyboard_btn() ساخته می‌شوند که پارامتر
style را در امضای خود دارند، اما این مقدار را فقط به‌صورت منطقی نگه می‌دارند
(مثلاً برای یکدستی کد) و هرگز آن را به سازندهٔ کلاس‌های اصلی تلگرام پاس
نمی‌دهند. ظاهر واقعی دکمه‌ها در کلاینت تلگرام تغییری نمی‌کند.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# تایپ‌ها و ثابت‌ها (سینتکس پایتون 3.14)
# ---------------------------------------------------------------------------

type ConversationState = int
type ChatId = int

WAITING_FOR_SOURCE: ConversationState = 1
WAITING_FOR_TARGET: ConversationState = 2

DB_PATH = Path(__file__).parent / "settings.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("forward-bot")


# ---------------------------------------------------------------------------
# پیکربندی ربات از روی متغیرهای محیطی
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class BotConfig:
    token: str
    admin_ids: frozenset[int]
    webhook_base_url: str
    port: int

    @staticmethod
    def from_env() -> "BotConfig":
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("متغیر محیطی BOT_TOKEN تنظیم نشده است.")

        admins_raw = os.environ.get("ADMINS", "").strip()
        admin_ids = frozenset(
            int(part) for part in admins_raw.split(",") if part.strip().lstrip("-").isdigit()
        )
        if not admin_ids:
            raise RuntimeError("متغیر محیطی ADMINS تنظیم نشده یا نامعتبر است.")

        webhook_base_url = os.environ.get("WEBHOOK_URL", "").strip().rstrip("/")
        if not webhook_base_url:
            raise RuntimeError("متغیر محیطی WEBHOOK_URL تنظیم نشده است.")

        # Render پورت واقعی را از طریق متغیر PORT تزریق می‌کند.
        # اگر این متغیر موجود نبود، از مقدار پیش‌فرض 8443 استفاده می‌شود.
        port = int(os.environ.get("PORT", "8443"))

        return BotConfig(
            token=token,
            admin_ids=admin_ids,
            webhook_base_url=webhook_base_url,
            port=port,
        )


# ---------------------------------------------------------------------------
# لایه دیتابیس (SQLite)
# ---------------------------------------------------------------------------

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.commit()
    logger.info("دیتابیس settings.db با موفقیت آماده شد.")


def get_setting(key: str, default: str | None = None) -> str | None:
    with db_connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def get_bool_setting(key: str, default: bool = False) -> bool:
    value = get_setting(key)
    if value is None:
        return default
    return value == "1"


def set_bool_setting(key: str, value: bool) -> None:
    set_setting(key, "1" if value else "0")


def get_int_setting(key: str) -> int | None:
    value = get_setting(key)
    return int(value) if value is not None else None


# ---------------------------------------------------------------------------
# توابع کمکی ساخت دکمه (با پارامتر منطقی style - بدون تاثیر بصری در تلگرام)
# ---------------------------------------------------------------------------

def inline_btn(text: str, callback_data: str, style: str = "secondary") -> InlineKeyboardButton:
    """دکمه اینلاین. پارامتر style فقط برای یکدستی کد نگه داشته شده و به
    تلگرام ارسال نمی‌شود (تلگرام چنین قابلیتی ندارد)."""
    _ = style  # به‌صورت عمدی استفاده نمی‌شود؛ فقط برای حفظ امضای تابع
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def keyboard_btn(text: str, style: str = "secondary") -> KeyboardButton:
    """دکمه کیبورد معمولی. پارامتر style فقط منطقی است."""
    _ = style
    return KeyboardButton(text=text)


# ---------------------------------------------------------------------------
# متن‌های فارسی رابط کاربری
# ---------------------------------------------------------------------------

class Texts:
    START = (
        "👋 سلام!\n"
        "به ربات فورواد دوطرفه گروه ↔️ کانال خوش آمدید.\n\n"
        "برای دسترسی به پنل مدیریت دستور /panel را ارسال کنید."
    )
    NOT_ADMIN = "⛔️ شما اجازه استفاده از این بخش را ندارید."
    PANEL_TITLE = "🛠 <b>پنل مدیریت ربات فورواد</b>\n\nیکی از گزینه‌های زیر را انتخاب کنید:"
    PANEL_CLOSED = "🔙 پنل بسته شد. برای باز کردن دوباره /panel را بزنید."

    ASK_SOURCE = (
        "📥 لطفاً یک پیام از <b>گروه منبع</b> را فوروارد کنید\n"
        "یا شناسه عددی چت را ارسال کنید (مثل <code>-1001234567890</code>).\n\n"
        "برای انصراف /cancel را بزنید."
    )
    ASK_TARGET = (
        "📤 لطفاً یک پیام از <b>کانال مقصد</b> را فوروارد کنید\n"
        "یا شناسه عددی چت را ارسال کنید (مثل <code>-1001234567890</code>).\n\n"
        "⚠️ توجه: ربات باید در کانال مقصد، عضو ادمین باشد.\n"
        "برای انصراف /cancel را بزنید."
    )

    INVALID_SOURCE = "❌ نتوانستم چت منبع را شناسایی کنم. دوباره تلاش کنید یا /cancel را بزنید."
    INVALID_TARGET = "❌ نتوانستم چت مقصد را شناسایی کنم. دوباره تلاش کنید یا /cancel را بزنید."

    SOURCE_SET = "✅ گروه منبع با موفقیت تنظیم شد:\n<b>{title}</b>"
    TARGET_SET = "✅ کانال مقصد با موفقیت تنظیم شد:\n<b>{title}</b>"

    BOT_NOT_IN_TARGET = (
        "❌ ربات نتوانست اطلاعات عضویت خود را در این چت دریافت کند.\n"
        "لطفاً ابتدا ربات را به کانال/گروه مقصد اضافه کنید."
    )
    BOT_NOT_ADMIN_IN_TARGET = (
        "❌ ربات در چت مقصد ادمین نیست.\n"
        "لطفاً ابتدا ربات را به‌عنوان ادمین در کانال مقصد تنظیم کنید و دوباره تلاش کنید."
    )

    CANCELLED = "🚫 عملیات لغو شد."

    STATUS_TEMPLATE = (
        "📊 <b>وضعیت فعلی ربات</b>\n\n"
        "📥 گروه منبع: {source}\n"
        "📤 کانال مقصد: {target}\n\n"
        "▶️ فورواد گروه → کانال: {g2c}\n"
        "▶️ فورواد کانال → گروه: {c2g}"
    )
    NOT_SET = "تنظیم نشده ❌"
    ENABLED = "فعال ✅"
    DISABLED = "غیرفعال ⛔️"

    SOURCE_NOT_SET_WARN = "⚠️ ابتدا باید گروه منبع را تنظیم کنید."
    TARGET_NOT_SET_WARN = "⚠️ ابتدا باید کانال مقصد را تنظیم کنید."

    FORWARD_ERROR = "❌ خطا در فوروارد پیام. جزئیات در لاگ ثبت شد."


# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------

def main_reply_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [keyboard_btn("📊 وضعیت", style="primary")],
        [
            keyboard_btn("📥 تنظیم منبع", style="secondary"),
            keyboard_btn("📤 تنظیم مقصد", style="secondary"),
        ],
        [
            keyboard_btn("▶️ شروع فورواد گروه → چنل", style="success"),
            keyboard_btn("⏹ توقف فورواد گروه → چنل", style="danger"),
        ],
        [
            keyboard_btn("▶️ شروع فورواد چنل → گروه", style="success"),
            keyboard_btn("⏹ توقف فورواد چنل → گروه", style="danger"),
        ],
        [keyboard_btn("🔙 بازگشت", style="secondary")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def main_inline_keyboard() -> InlineKeyboardMarkup:
    g2c_enabled = get_bool_setting("forward_group_to_channel")
    c2g_enabled = get_bool_setting("forward_channel_to_group")

    g2c_label = "⏹ توقف فورواد گروه → چنل" if g2c_enabled else "▶️ شروع فورواد گروه → چنل"
    c2g_label = "⏹ توقف فورواد چنل → گروه" if c2g_enabled else "▶️ شروع فورواد چنل → گروه"

    rows = [
        [inline_btn(g2c_label, "toggle_g2c", style="success" if not g2c_enabled else "danger")],
        [inline_btn(c2g_label, "toggle_c2g", style="success" if not c2g_enabled else "danger")],
        [
            inline_btn("📥 تنظیم منبع", "set_source", style="primary"),
            inline_btn("📤 تنظیم مقصد", "set_target", style="primary"),
        ],
        [inline_btn("📊 وضعیت", "status", style="secondary")],
        [inline_btn("🔙 بازگشت", "back", style="secondary")],
    ]
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# توابع کمکی منطقی
# ---------------------------------------------------------------------------

def is_admin(user_id: int, config: BotConfig) -> bool:
    return user_id in config.admin_ids


def build_status_text() -> str:
    source_id = get_int_setting("source_chat_id")
    target_id = get_int_setting("target_chat_id")
    source_title = get_setting("source_title")
    target_title = get_setting("target_title")

    source_display = f"{source_title} (<code>{source_id}</code>)" if source_id else Texts.NOT_SET
    target_display = f"{target_title} (<code>{target_id}</code>)" if target_id else Texts.NOT_SET

    g2c = Texts.ENABLED if get_bool_setting("forward_group_to_channel") else Texts.DISABLED
    c2g = Texts.ENABLED if get_bool_setting("forward_channel_to_group") else Texts.DISABLED

    return Texts.STATUS_TEMPLATE.format(
        source=source_display, target=target_display, g2c=g2c, c2g=c2g
    )


async def resolve_chat_from_message(
    message, context: ContextTypes.DEFAULT_TYPE
) -> tuple[int | None, str | None]:
    """تلاش می‌کند چت مبدا یک پیام فوروارد شده، یا یک شناسه عددی تایپ‌شده را
    شناسایی کند و (chat_id, title) را برمی‌گرداند."""

    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if chat is not None:
            return chat.id, (chat.title or chat.username or str(chat.id))

    if message.text and message.text.strip().lstrip("-").isdigit():
        chat_id = int(message.text.strip())
        try:
            chat = await context.bot.get_chat(chat_id)
            return chat.id, (chat.title or chat.username or str(chat.id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("خطا در دریافت اطلاعات چت %s: %s", chat_id, exc)
            return None, None

    return None, None


# ---------------------------------------------------------------------------
# دستورات پایه
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(Texts.START)


async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: BotConfig = context.bot_data["config"]
    user = update.effective_user
    if user is None or not is_admin(user.id, config):
        await update.message.reply_text(Texts.NOT_ADMIN)
        return

    await update.message.reply_text(
        Texts.PANEL_TITLE,
        reply_markup=main_inline_keyboard(),
        parse_mode="HTML",
    )
    await update.message.reply_text(
        "⌨️ می‌توانید از کیبورد زیر هم استفاده کنید:",
        reply_markup=main_reply_keyboard(),
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    await update.message.reply_text(Texts.CANCELLED, reply_markup=main_reply_keyboard())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# مکالمه تنظیم منبع / مقصد
# ---------------------------------------------------------------------------

async def set_source_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    config: BotConfig = context.bot_data["config"]
    query = update.callback_query
    if query is not None:
        await query.answer()
        if not is_admin(query.from_user.id, config):
            await query.edit_message_text(Texts.NOT_ADMIN)
            return ConversationHandler.END
        await query.message.reply_text(Texts.ASK_SOURCE, parse_mode="HTML")
    else:
        user = update.effective_user
        if user is None or not is_admin(user.id, config):
            await update.message.reply_text(Texts.NOT_ADMIN)
            return ConversationHandler.END
        await update.message.reply_text(Texts.ASK_SOURCE, parse_mode="HTML")
    return WAITING_FOR_SOURCE


async def set_target_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    config: BotConfig = context.bot_data["config"]
    query = update.callback_query
    if query is not None:
        await query.answer()
        if not is_admin(query.from_user.id, config):
            await query.edit_message_text(Texts.NOT_ADMIN)
            return ConversationHandler.END
        await query.message.reply_text(Texts.ASK_TARGET, parse_mode="HTML")
    else:
        user = update.effective_user
        if user is None or not is_admin(user.id, config):
            await update.message.reply_text(Texts.NOT_ADMIN)
            return ConversationHandler.END
        await update.message.reply_text(Texts.ASK_TARGET, parse_mode="HTML")
    return WAITING_FOR_TARGET


async def receive_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    message = update.message
    chat_id, title = await resolve_chat_from_message(message, context)

    if chat_id is None:
        await message.reply_text(Texts.INVALID_SOURCE, parse_mode="HTML")
        return WAITING_FOR_SOURCE

    set_setting("source_chat_id", str(chat_id))
    set_setting("source_title", title or str(chat_id))
    logger.info("گروه منبع تنظیم شد: %s (%s)", title, chat_id)

    await message.reply_text(
        Texts.SOURCE_SET.format(title=title or chat_id),
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )
    return ConversationHandler.END


async def receive_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ConversationState:
    message = update.message
    chat_id, title = await resolve_chat_from_message(message, context)

    if chat_id is None:
        await message.reply_text(Texts.INVALID_TARGET, parse_mode="HTML")
        return WAITING_FOR_TARGET

    try:
        member = await context.bot.get_chat_member(chat_id, context.bot.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("خطا در بررسی عضویت ربات در چت مقصد %s: %s", chat_id, exc)
        await message.reply_text(Texts.BOT_NOT_IN_TARGET, parse_mode="HTML")
        return WAITING_FOR_TARGET

    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        await message.reply_text(Texts.BOT_NOT_ADMIN_IN_TARGET, parse_mode="HTML")
        return WAITING_FOR_TARGET

    set_setting("target_chat_id", str(chat_id))
    set_setting("target_title", title or str(chat_id))
    logger.info("کانال مقصد تنظیم شد: %s (%s)", title, chat_id)

    await message.reply_text(
        Texts.TARGET_SET.format(title=title or chat_id),
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# روتر دکمه‌های اینلاین پنل (با match-case پایتون 3.14)
# ---------------------------------------------------------------------------

async def panel_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: BotConfig = context.bot_data["config"]
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id, config):
        await query.edit_message_text(Texts.NOT_ADMIN)
        return

    data = query.data or ""

    match data:
        case "toggle_g2c":
            new_value = not get_bool_setting("forward_group_to_channel")
            if new_value and get_int_setting("source_chat_id") is None:
                await query.answer(Texts.SOURCE_NOT_SET_WARN, show_alert=True)
                return
            if new_value and get_int_setting("target_chat_id") is None:
                await query.answer(Texts.TARGET_NOT_SET_WARN, show_alert=True)
                return
            set_bool_setting("forward_group_to_channel", new_value)
            await query.edit_message_text(
                Texts.PANEL_TITLE, reply_markup=main_inline_keyboard(), parse_mode="HTML"
            )

        case "toggle_c2g":
            new_value = not get_bool_setting("forward_channel_to_group")
            if new_value and get_int_setting("source_chat_id") is None:
                await query.answer(Texts.SOURCE_NOT_SET_WARN, show_alert=True)
                return
            if new_value and get_int_setting("target_chat_id") is None:
                await query.answer(Texts.TARGET_NOT_SET_WARN, show_alert=True)
                return
            set_bool_setting("forward_channel_to_group", new_value)
            await query.edit_message_text(
                Texts.PANEL_TITLE, reply_markup=main_inline_keyboard(), parse_mode="HTML"
            )

        case "status":
            await query.edit_message_text(
                build_status_text(), reply_markup=main_inline_keyboard(), parse_mode="HTML"
            )

        case "back" | "close":
            await query.edit_message_text(Texts.PANEL_CLOSED)

        case "set_source" | "set_target":
            # این دو callback توسط ConversationHandler مدیریت می‌شوند.
            pass

        case _:
            logger.warning("callback ناشناخته دریافت شد: %s", data)


# ---------------------------------------------------------------------------
# هندلرهای کیبورد متنی (Reply Keyboard)
# ---------------------------------------------------------------------------

async def status_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: BotConfig = context.bot_data["config"]
    user = update.effective_user
    if user is None or not is_admin(user.id, config):
        return
    await update.message.reply_text(build_status_text(), parse_mode="HTML")


async def toggle_g2c_on_text(update: Update, context: ContextTypes.DEFAULT_TYPE, enable: bool) -> None:
    config: BotConfig = context.bot_data["config"]
    user = update.effective_user
    if user is None or not is_admin(user.id, config):
        return
    if enable and (get_int_setting("source_chat_id") is None or get_int_setting("target_chat_id") is None):
        await update.message.reply_text(Texts.SOURCE_NOT_SET_WARN)
        return
    set_bool_setting("forward_group_to_channel", enable)
    await update.message.reply_text(build_status_text(), parse_mode="HTML")


async def toggle_c2g_on_text(update: Update, context: ContextTypes.DEFAULT_TYPE, enable: bool) -> None:
    config: BotConfig = context.bot_data["config"]
    user = update.effective_user
    if user is None or not is_admin(user.id, config):
        return
    if enable and (get_int_setting("source_chat_id") is None or get_int_setting("target_chat_id") is None):
        await update.message.reply_text(Texts.TARGET_NOT_SET_WARN)
        return
    set_bool_setting("forward_channel_to_group", enable)
    await update.message.reply_text(build_status_text(), parse_mode="HTML")


async def start_g2c_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await toggle_g2c_on_text(update, context, True)


async def stop_g2c_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await toggle_g2c_on_text(update, context, False)


async def start_c2g_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await toggle_c2g_on_text(update, context, True)


async def stop_c2g_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await toggle_c2g_on_text(update, context, False)


async def back_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(Texts.PANEL_CLOSED)


# ---------------------------------------------------------------------------
# فورواد پیام‌های واقعی بین گروه و کانال
# ---------------------------------------------------------------------------

async def forward_from_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or message.chat is None:
        return

    source_id = get_int_setting("source_chat_id")
    target_id = get_int_setting("target_chat_id")

    if source_id is None or target_id is None:
        return
    if message.chat.id != source_id:
        return
    if not get_bool_setting("forward_group_to_channel"):
        return

    try:
        await context.bot.forward_message(
            chat_id=target_id,
            from_chat_id=source_id,
            message_id=message.message_id,
        )
        logger.info("پیام %s از گروه %s به کانال %s فوروارد شد.", message.message_id, source_id, target_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("خطا در فوروارد گروه → کانال: %s", exc)


async def forward_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or message.chat is None:
        return

    source_id = get_int_setting("source_chat_id")
    target_id = get_int_setting("target_chat_id")

    if source_id is None or target_id is None:
        return
    if message.chat.id != target_id:
        return
    if not get_bool_setting("forward_channel_to_group"):
        return

    try:
        await context.bot.forward_message(
            chat_id=source_id,
            from_chat_id=target_id,
            message_id=message.message_id,
        )
        logger.info("پیام %s از کانال %s به گروه %s فوروارد شد.", message.message_id, target_id, source_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("خطا در فوروارد کانال → گروه: %s", exc)


# ---------------------------------------------------------------------------
# مدیریت خطا
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("خطای پیش‌بینی نشده: %s", context.error, exc_info=context.error)


# ---------------------------------------------------------------------------
# نقطه ورود برنامه
# ---------------------------------------------------------------------------

def main() -> None:
    config = BotConfig.from_env()
    init_db()

    application = Application.builder().token(config.token).build()
    application.bot_data["config"] = config

    # دستورات پایه
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("panel", panel_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # مکالمه تنظیم منبع / مقصد
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(set_source_entry, pattern=r"^set_source$"),
            CallbackQueryHandler(set_target_entry, pattern=r"^set_target$"),
            MessageHandler(filters.Regex(r"^📥 تنظیم منبع$"), set_source_entry),
            MessageHandler(filters.Regex(r"^📤 تنظیم مقصد$"), set_target_entry),
        ],
        states={
            WAITING_FOR_SOURCE: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_source)],
            WAITING_FOR_TARGET: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_target)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        name="set_chat_conversation",
    )
    application.add_handler(conv_handler)

    # روتر دکمه‌های اینلاین (toggle_*، status، back)
    application.add_handler(CallbackQueryHandler(panel_callback_router))

    # هندلرهای کیبورد متنی - فقط در چت خصوصی با ادمین معنا دارند
    application.add_handler(
        MessageHandler(filters.Regex(r"^📊 وضعیت$") & filters.ChatType.PRIVATE, status_text_handler)
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^▶️ شروع فورواد گروه → چنل$") & filters.ChatType.PRIVATE, start_g2c_text
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^⏹ توقف فورواد گروه → چنل$") & filters.ChatType.PRIVATE, stop_g2c_text
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^▶️ شروع فورواد چنل → گروه$") & filters.ChatType.PRIVATE, start_c2g_text
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^⏹ توقف فورواد چنل → گروه$") & filters.ChatType.PRIVATE, stop_c2g_text
        )
    )
    application.add_handler(
        MessageHandler(filters.Regex(r"^🔙 بازگشت$") & filters.ChatType.PRIVATE, back_text_handler)
    )

    # فورواد واقعی بین گروه و کانال (باید آخرین هندلرها باشند)
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, forward_from_group))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, forward_from_channel))

    application.add_error_handler(error_handler)

    webhook_path = config.token
    full_webhook_url = f"{config.webhook_base_url}/{webhook_path}"

    logger.info("شروع ربات در حالت Webhook روی پورت %s ...", config.port)
    application.run_webhook(
        listen="0.0.0.0",
        port=config.port,
        url_path=webhook_path,
        webhook_url=full_webhook_url,
    )


if __name__ == "__main__":
    main()
