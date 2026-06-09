"""
╔══════════════════════════════════════════════════════════╗
║     ربات پیشرفته مدیریت گروه تلگرام                    ║
║     نوشته شده با python-telegram-bot v20                ║
╚══════════════════════════════════════════════════════════╝

ویژگی‌ها:
 - مدیریت اعضا (کیک، بن، آنبن، مخفی)
 - سیستم هشدار (warn) با آستانه قابل تنظیم
 - فیلتر کلمات ناپسند
 - ضد اسپم هوشمند
 - خوش‌آمدگویی و خداحافظی سفارشی
 - سیستم نقش (مود، ادمین، VIP)
 - آمار گروه
 - زمان‌بندی پیام (broadcast)
 - لاک گروه (فقط ادمین‌ها بنویسند)
 - سیستم کپچا برای اعضای جدید
 - گزارش تخلف
 - پشتیبان‌گیری از تنظیمات
"""

import logging
import json
import os
import re
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps

from telegram import (
    Update, ChatPermissions, InlineKeyboardButton,
    InlineKeyboardMarkup, ChatMemberAdministrator, ChatMemberOwner
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ChatMemberHandler,
    filters, ContextTypes
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError

# ─── تنظیمات اولیه ───────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# توکن ربات را از متغیر محیطی یا مستقیم وارد کنید
BOT_TOKEN = 8451721611:AAG-184s3sZqs-3OcKjEozYv4XJWJ9hP8pE

# ─── ذخیره‌سازی داده (در پروداکشن از دیتابیس استفاده کنید) ──
DATA_FILE = "data.json"

def load_data() -> dict:
    """بارگذاری داده از فایل JSON"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("خطا در خواندن فایل داده، شروع با داده خالی")
    return {}

def save_data(data: dict):
    """ذخیره داده در فایل JSON"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"خطا در ذخیره داده: {e}")

# داده کلی برنامه
DB = load_data()

def get_group(chat_id: int) -> dict:
    """دریافت داده یک گروه (ایجاد اگر وجود نداشت)"""
    key = str(chat_id)
    if key not in DB:
        DB[key] = {
            "warns": {},          # {user_id: count}
            "warn_limit": 3,      # حد هشدار قبل از بن
            "muted": {},          # {user_id: until_timestamp}
            "banned": [],         # [user_id]
            "vip": [],            # [user_id]
            "mods": [],           # [user_id]
            "bad_words": [],      # کلمات ممنوع
            "welcome_msg": "👋 {name} عزیز به {group} خوش آمدی!",
            "goodbye_msg": "🚪 {name} از گروه خارج شد.",
            "locked": False,      # آیا گروه قفل است؟
            "anti_spam": True,    # ضد اسپم
            "captcha": False,     # کپچای اعضای جدید
            "captcha_pending": {},# {user_id: answer}
            "spam_count": {},     # {user_id: [timestamps]}
            "report_count": {},   # {user_id: count}
            "stats": {
                "messages": 0,
                "joins": 0,
                "leaves": 0,
                "banned_total": 0
            },
            "notes": {},          # یادداشت‌های ذخیره‌شده
            "filters": {},        # فیلترهای خودکار {trigger: response}
            "rules": "",          # قوانین گروه
            "created_at": datetime.now().isoformat()
        }
        save_data(DB)
    return DB[key]

# ─── دکوراتورها ──────────────────────────────────────────

def admin_only(func):
    """فقط ادمین‌ها می‌توانند این دستور را اجرا کنند"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user:
            return
        chat = update.effective_chat
        user = update.effective_user
        if chat.type == "private":
            return await func(update, context)
        try:
            member = await chat.get_member(user.id)
            if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
                return await func(update, context)
            # بررسی mod های داخلی
            g = get_group(chat.id)
            if user.id in g.get("mods", []):
                return await func(update, context)
            await update.message.reply_text("⛔️ فقط ادمین‌ها مجاز به استفاده از این دستور هستند.")
        except TelegramError:
            pass
    return wrapper

def group_only(func):
    """فقط در گروه قابل استفاده"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
            return await func(update, context)
        if update.message:
            await update.message.reply_text("⚠️ این دستور فقط در گروه کار می‌کند.")
    return wrapper

# ─── دستورات اصلی ────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start"""
    keyboard = [
        [
            InlineKeyboardButton("📋 راهنما", callback_data="help"),
            InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings")
        ],
        [
            InlineKeyboardButton("📊 آمار", callback_data="stats"),
            InlineKeyboardButton("📞 پشتیبانی", url="https://t.me/your_support")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "🤖 *ربات پیشرفته مدیریت گروه*\n\n"
        "سلام! من یک ربات قدرتمند برای مدیریت گروه‌های تلگرام هستم.\n\n"
        "✅ مدیریت اعضا\n"
        "✅ سیستم هشدار هوشمند\n"
        "✅ ضد اسپم\n"
        "✅ فیلتر کلمات\n"
        "✅ کپچا برای اعضای جدید\n"
        "✅ آمار دقیق\n\n"
        "برای شروع، من را به گروه اضافه کنید و ادمین کنید! 👇"
    )
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /help"""
    text = (
        "📋 *راهنمای دستورات*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "👮 *مدیریت اعضا*\n"
        "`/ban` — بن کردن کاربر\n"
        "`/unban` — رفع بن\n"
        "`/kick` — اخراج از گروه\n"
        "`/mute [دقیقه]` — بی‌صدا کردن\n"
        "`/unmute` — رفع سکوت\n"
        "`/warn` — هشدار به کاربر\n"
        "`/unwarn` — حذف هشدار\n"
        "`/warns` — نمایش هشدارها\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚙️ *تنظیمات گروه*\n"
        "`/setlimit [عدد]` — تنظیم حد هشدار\n"
        "`/lock` — قفل گروه\n"
        "`/unlock` — باز کردن قفل\n"
        "`/setwelcome` — پیام خوش‌آمدگویی\n"
        "`/setgoodbye` — پیام خداحافظی\n"
        "`/setrules` — تنظیم قوانین\n"
        "`/rules` — نمایش قوانین\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🚫 *فیلتر و اسپم*\n"
        "`/addbadword [کلمه]` — افزودن کلمه ممنوع\n"
        "`/delbadword [کلمه]` — حذف کلمه ممنوع\n"
        "`/badwords` — لیست کلمات ممنوع\n"
        "`/antispam on/off` — روشن/خاموش ضد اسپم\n"
        "`/captcha on/off` — روشن/خاموش کپچا\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📝 *یادداشت و فیلتر*\n"
        "`/save [نام] [متن]` — ذخیره یادداشت\n"
        "`/get [نام]` یا `#نام` — دریافت یادداشت\n"
        "`/notes` — لیست یادداشت‌ها\n"
        "`/filter [کلمه] [پاسخ]` — فیلتر خودکار\n"
        "`/filters` — لیست فیلترها\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📊 *اطلاعات*\n"
        "`/stats` — آمار گروه\n"
        "`/info` — اطلاعات کاربر\n"
        "`/id` — شناسه کاربر/گروه\n"
        "`/report` — گزارش تخلف\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ─── مدیریت اعضا ─────────────────────────────────────────

def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """یافتن کاربر هدف از ریپلای یا آرگومان"""
    msg = update.message
    if msg.reply_to_message:
        return msg.reply_to_message.from_user
    if context.args:
        try:
            return int(context.args[0])  # آیدی عددی
        except ValueError:
            pass
    return None

@admin_only
@group_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بن کردن کاربر /ban"""
    chat = update.effective_chat
    msg = update.message
    g = get_group(chat.id)
    target = get_target_user(update, context)
    if not target:
        await msg.reply_text("⚠️ روی پیام کاربر ریپلای کنید یا آیدی بدهید.")
        return
    user_id = target.id if hasattr(target, 'id') else target
    reason = " ".join(context.args[1:]) if context.args and len(context.args) > 1 else "بدون دلیل"
    try:
        await chat.ban_member(user_id)
        if str(user_id) not in g["banned"]:
            g["banned"].append(str(user_id))
        g["stats"]["banned_total"] += 1
        save_data(DB)
        name = target.full_name if hasattr(target, 'full_name') else str(user_id)
        keyboard = [[InlineKeyboardButton("🔓 رفع بن", callback_data=f"unban_{user_id}")]]
        await msg.reply_text(
            f"🚫 *کاربر بن شد*\n\n"
            f"👤 کاربر: [{name}](tg://user?id={user_id})\n"
            f"📝 دلیل: {reason}\n"
            f"👮 توسط: {update.effective_user.full_name}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except TelegramError as e:
        await msg.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رفع بن /unban"""
    chat = update.effective_chat
    g = get_group(chat.id)
    target = get_target_user(update, context)
    if not target:
        await update.message.reply_text("⚠️ آیدی کاربر را وارد کنید.")
        return
    user_id = target.id if hasattr(target, 'id') else target
    try:
        await chat.unban_member(user_id)
        if str(user_id) in g["banned"]:
            g["banned"].remove(str(user_id))
        save_data(DB)
        await update.message.reply_text(f"✅ بن کاربر `{user_id}` برداشته شد.", parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        await update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اخراج موقت /kick"""
    chat = update.effective_chat
    target = get_target_user(update, context)
    if not target:
        await update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    user_id = target.id if hasattr(target, 'id') else target
    reason = " ".join(context.args[1:]) if context.args and len(context.args) > 1 else "بدون دلیل"
    try:
        await chat.ban_member(user_id)
        await chat.unban_member(user_id)
        name = target.full_name if hasattr(target, 'full_name') else str(user_id)
        await update.message.reply_text(
            f"👢 *کاربر اخراج شد*\n\n"
            f"👤 {name}\n📝 دلیل: {reason}",
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بی‌صدا کردن /mute [دقیقه]"""
    chat = update.effective_chat
    g = get_group(chat.id)
    target = get_target_user(update, context)
    if not target:
        await update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    user_id = target.id if hasattr(target, 'id') else target
    # مدت زمان
    duration = 60  # پیش‌فرض ۶۰ دقیقه
    if context.args:
        try:
            duration = int(context.args[-1])
        except ValueError:
            pass
    until = datetime.now() + timedelta(minutes=duration)
    try:
        await chat.restrict_member(
            user_id,
            ChatPermissions(can_send_messages=False),
            until_date=until
        )
        g["muted"][str(user_id)] = until.timestamp()
        save_data(DB)
        name = target.full_name if hasattr(target, 'full_name') else str(user_id)
        keyboard = [[InlineKeyboardButton("🔊 رفع سکوت", callback_data=f"unmute_{user_id}")]]
        await update.message.reply_text(
            f"🔇 *کاربر بی‌صدا شد*\n\n"
            f"👤 {name}\n⏱ مدت: {duration} دقیقه",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رفع سکوت /unmute"""
    chat = update.effective_chat
    g = get_group(chat.id)
    target = get_target_user(update, context)
    if not target:
        await update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    user_id = target.id if hasattr(target, 'id') else target
    try:
        await chat.restrict_member(user_id, ChatPermissions(
            can_send_messages=True, can_send_media_messages=True,
            can_send_other_messages=True, can_add_web_page_previews=True
        ))
        g["muted"].pop(str(user_id), None)
        save_data(DB)
        await update.message.reply_text(f"🔊 سکوت کاربر `{user_id}` برداشته شد.", parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        await update.message.reply_text(f"❌ خطا: {e}")

# ─── سیستم هشدار ─────────────────────────────────────────

@admin_only
@group_only
async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هشدار به کاربر /warn"""
    chat = update.effective_chat
    g = get_group(chat.id)
    target = get_target_user(update, context)
    if not target:
        await update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    user_id = str(target.id if hasattr(target, 'id') else target)
    reason = " ".join(context.args[1:]) if context.args and len(context.args) > 1 else "بدون دلیل"
    g["warns"][user_id] = g["warns"].get(user_id, 0) + 1
    count = g["warns"][user_id]
    limit = g["warn_limit"]
    save_data(DB)
    name = target.full_name if hasattr(target, 'full_name') else user_id
    if count >= limit:
        # بن خودکار
        try:
            await chat.ban_member(int(user_id))
            g["stats"]["banned_total"] += 1
            g["warns"].pop(user_id, None)
            save_data(DB)
            await update.message.reply_text(
                f"🚨 *کاربر به دلیل {limit} هشدار بن شد!*\n\n"
                f"👤 [{name}](tg://user?id={user_id})\n📝 آخرین دلیل: {reason}",
                parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError:
            pass
    else:
        bars = "🟥" * count + "⬜️" * (limit - count)
        await update.message.reply_text(
            f"⚠️ *هشدار داده شد*\n\n"
            f"👤 [{name}](tg://user?id={user_id})\n"
            f"📝 دلیل: {reason}\n"
            f"📊 هشدارها: {bars} ({count}/{limit})",
            parse_mode=ParseMode.MARKDOWN
        )

@admin_only
@group_only
async def unwarn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف هشدار /unwarn"""
    chat = update.effective_chat
    g = get_group(chat.id)
    target = get_target_user(update, context)
    if not target:
        await update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    user_id = str(target.id if hasattr(target, 'id') else target)
    if user_id in g["warns"] and g["warns"][user_id] > 0:
        g["warns"][user_id] -= 1
        if g["warns"][user_id] == 0:
            del g["warns"][user_id]
        save_data(DB)
        await update.message.reply_text(f"✅ یک هشدار از کاربر `{user_id}` کم شد.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("این کاربر هشداری ندارد.")

@group_only
async def show_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش هشدارهای یک کاربر /warns"""
    chat = update.effective_chat
    g = get_group(chat.id)
    target = get_target_user(update, context)
    if not target:
        await update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    user_id = str(target.id if hasattr(target, 'id') else target)
    count = g["warns"].get(user_id, 0)
    limit = g["warn_limit"]
    name = target.full_name if hasattr(target, 'full_name') else user_id
    bars = "🟥" * count + "⬜️" * max(0, limit - count)
    await update.message.reply_text(
        f"📊 *هشدارهای {name}*\n\n{bars}\n{count} از {limit} هشدار",
        parse_mode=ParseMode.MARKDOWN
    )

# ─── قفل گروه ────────────────────────────────────────────

@admin_only
@group_only
async def lock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قفل گروه — فقط ادمین‌ها پیام بدهند /lock"""
    chat = update.effective_chat
    g = get_group(chat.id)
    try:
        await chat.set_permissions(ChatPermissions(can_send_messages=False))
        g["locked"] = True
        save_data(DB)
        await update.message.reply_text("🔒 گروه قفل شد. فقط ادمین‌ها می‌توانند پیام بدهند.")
    except TelegramError as e:
        await update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
async def unlock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """باز کردن قفل گروه /unlock"""
    chat = update.effective_chat
    g = get_group(chat.id)
    try:
        await chat.set_permissions(ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        ))
        g["locked"] = False
        save_data(DB)
        await update.message.reply_text("🔓 قفل گروه برداشته شد.")
    except TelegramError as e:
        await update.message.reply_text(f"❌ خطا: {e}")

# ─── تنظیمات خوش‌آمدگویی ────────────────────────────────

@admin_only
@group_only
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setwelcome [پیام] — تنظیم پیام خوش‌آمدگویی
    متغیرها: {name}=نام، {group}=نام گروه، {id}=آیدی
    """
    if not context.args:
        await update.message.reply_text(
            "📝 *نحوه استفاده:*\n`/setwelcome متن پیام`\n\n"
            "متغیرها:\n`{name}` — نام کاربر\n`{group}` — نام گروه\n`{id}` — آیدی کاربر",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    g = get_group(update.effective_chat.id)
    g["welcome_msg"] = " ".join(context.args)
    save_data(DB)
    await update.message.reply_text(
        f"✅ پیام خوش‌آمدگویی تنظیم شد:\n\n{g['welcome_msg']}"
    )

@admin_only
@group_only
async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setgoodbye [پیام] — تنظیم پیام خداحافظی"""
    if not context.args:
        await update.message.reply_text("⚠️ متن پیام را وارد کنید.")
        return
    g = get_group(update.effective_chat.id)
    g["goodbye_msg"] = " ".join(context.args)
    save_data(DB)
    await update.message.reply_text(f"✅ پیام خداحافظی تنظیم شد:\n\n{g['goodbye_msg']}")

# ─── ورود و خروج اعضا ────────────────────────────────────

async def member_joined(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هنگام ورود عضو جدید"""
    chat = update.effective_chat
    g = get_group(chat.id)
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        g["stats"]["joins"] += 1
        save_data(DB)
        # کپچا فعال است؟
        if g.get("captcha"):
            await handle_captcha_join(update, context, member, g)
            return
        # پیام خوش‌آمدگویی
        welcome = g["welcome_msg"].format(
            name=member.full_name,
            group=chat.title or "گروه",
            id=member.id
        )
        keyboard = [[InlineKeyboardButton("📋 قوانین گروه", callback_data=f"rules_{chat.id}")]]
        await update.message.reply_text(
            welcome,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_captcha_join(update, context, member, g):
    """مدیریت کپچا برای اعضای جدید"""
    import random
    chat = update.effective_chat
    # محاسبه ساده
    a, b = random.randint(1, 10), random.randint(1, 10)
    answer = a + b
    g["captcha_pending"][str(member.id)] = answer
    save_data(DB)
    # ابتدا کاربر رو محدود کن
    try:
        await chat.restrict_member(member.id, ChatPermissions(can_send_messages=False))
    except TelegramError:
        pass
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=f"captcha_{member.id}_{i}") for i in range(answer-2, answer+3) if i > 0]
    ]
    msg = await update.message.reply_text(
        f"👋 {member.full_name} عزیز!\n\n"
        f"🔐 برای ورود به گروه، لطفاً این سوال را پاسخ دهید:\n\n"
        f"*{a} + {b} = ?*\n\n"
        f"⏱ ۶۰ ثانیه وقت دارید.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    # حذف خودکار بعد از ۶۰ ثانیه
    async def auto_kick():
        await asyncio.sleep(60)
        if str(member.id) in g.get("captcha_pending", {}):
            try:
                await chat.ban_member(member.id)
                await chat.unban_member(member.id)
                del g["captcha_pending"][str(member.id)]
                save_data(DB)
                await msg.edit_text(f"⏰ {member.full_name} به موقع پاسخ نداد و اخراج شد.")
            except TelegramError:
                pass
    asyncio.create_task(auto_kick())

async def member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هنگام خروج عضو"""
    chat = update.effective_chat
    g = get_group(chat.id)
    member = update.message.left_chat_member
    if member and not member.is_bot:
        g["stats"]["leaves"] += 1
        save_data(DB)
        goodbye = g["goodbye_msg"].format(
            name=member.full_name,
            group=chat.title or "گروه",
            id=member.id
        )
        await update.message.reply_text(goodbye)

# ─── ضد اسپم ─────────────────────────────────────────────

SPAM_THRESHOLD = 5   # پیام
SPAM_WINDOW    = 5   # ثانیه

async def check_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی اسپم — True اگر اسپم بود"""
    chat = update.effective_chat
    user = update.effective_user
    if not user:
        return False
    g = get_group(chat.id)
    if not g.get("anti_spam", True):
        return False
    # بررسی ادمین
    try:
        member = await chat.get_member(user.id)
        if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
            return False
    except TelegramError:
        return False
    uid = str(user.id)
    now = datetime.now().timestamp()
    if uid not in g["spam_count"]:
        g["spam_count"][uid] = []
    # پنجره زمانی
    g["spam_count"][uid] = [t for t in g["spam_count"][uid] if now - t < SPAM_WINDOW]
    g["spam_count"][uid].append(now)
    save_data(DB)
    if len(g["spam_count"][uid]) >= SPAM_THRESHOLD:
        # مکالمه مشکوک
        try:
            await update.message.delete()
            await chat.restrict_member(
                user.id,
                ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(minutes=5)
            )
            await context.bot.send_message(
                chat.id,
                f"🛡 *ضد اسپم*: [{user.full_name}](tg://user?id={user.id}) به دلیل اسپم ۵ دقیقه بی‌صدا شد.",
                parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError:
            pass
        return True
    return False

# ─── فیلتر کلمات ─────────────────────────────────────────

async def check_bad_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی کلمات ممنوع"""
    chat = update.effective_chat
    msg = update.message
    if not msg or not msg.text:
        return False
    g = get_group(chat.id)
    bad_words = g.get("bad_words", [])
    if not bad_words:
        return False
    text_lower = msg.text.lower()
    for word in bad_words:
        if word.lower() in text_lower:
            try:
                await msg.delete()
                warn_msg = await context.bot.send_message(
                    chat.id,
                    f"⚠️ [{msg.from_user.full_name}](tg://user?id={msg.from_user.id})، استفاده از این کلمه ممنوع است!",
                    parse_mode=ParseMode.MARKDOWN
                )
                await asyncio.sleep(5)
                await warn_msg.delete()
            except TelegramError:
                pass
            return True
    return False

async def check_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی فیلترهای خودکار"""
    chat = update.effective_chat
    msg = update.message
    if not msg or not msg.text:
        return
    g = get_group(chat.id)
    text_lower = msg.text.lower()
    for trigger, response in g.get("filters", {}).items():
        if trigger.lower() in text_lower:
            await msg.reply_text(response)
            return

# ─── هندلر اصلی پیام ─────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر اصلی تمام پیام‌ها"""
    if not update.message or not update.effective_chat:
        return
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        return
    g = get_group(chat.id)
    g["stats"]["messages"] += 1
    # بررسی کلمات ممنوع
    if await check_bad_words(update, context):
        return
    # بررسی اسپم
    if await check_spam(update, context):
        return
    # بررسی فیلترها
    await check_filters(update, context)
    # بررسی #یادداشت
    if update.message.text and update.message.text.startswith('#'):
        note_name = update.message.text[1:].split()[0]
        notes = g.get("notes", {})
        if note_name in notes:
            await update.message.reply_text(notes[note_name])

# ─── دستورات تنظیمات ─────────────────────────────────────

@admin_only
@group_only
async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setlimit [عدد] — تنظیم حد هشدار"""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ `/setlimit [عدد]` مثلاً `/setlimit 5`", parse_mode=ParseMode.MARKDOWN)
        return
    g = get_group(update.effective_chat.id)
    g["warn_limit"] = max(1, int(context.args[0]))
    save_data(DB)
    await update.message.reply_text(f"✅ حد هشدار روی {g['warn_limit']} تنظیم شد.")

@admin_only
@group_only
async def add_bad_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addbadword [کلمه]"""
    if not context.args:
        await update.message.reply_text("⚠️ کلمه را وارد کنید.")
        return
    g = get_group(update.effective_chat.id)
    word = " ".join(context.args).lower()
    if word not in g["bad_words"]:
        g["bad_words"].append(word)
        save_data(DB)
    await update.message.reply_text(f"✅ کلمه `{word}` به لیست اضافه شد.", parse_mode=ParseMode.MARKDOWN)

@admin_only
@group_only
async def del_bad_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delbadword [کلمه]"""
    if not context.args:
        await update.message.reply_text("⚠️ کلمه را وارد کنید.")
        return
    g = get_group(update.effective_chat.id)
    word = " ".join(context.args).lower()
    if word in g["bad_words"]:
        g["bad_words"].remove(word)
        save_data(DB)
        await update.message.reply_text(f"✅ کلمه `{word}` حذف شد.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("این کلمه در لیست نیست.")

@group_only
async def list_bad_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/badwords"""
    g = get_group(update.effective_chat.id)
    words = g.get("bad_words", [])
    if not words:
        await update.message.reply_text("📭 هیچ کلمه ممنوعی تنظیم نشده.")
        return
    text = "🚫 *کلمات ممنوع:*\n\n" + "\n".join(f"• `{w}`" for w in words)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
@group_only
async def toggle_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/antispam on/off"""
    g = get_group(update.effective_chat.id)
    if context.args and context.args[0].lower() in ["on", "off"]:
        g["anti_spam"] = context.args[0].lower() == "on"
    else:
        g["anti_spam"] = not g.get("anti_spam", True)
    save_data(DB)
    status = "✅ روشن" if g["anti_spam"] else "❌ خاموش"
    await update.message.reply_text(f"🛡 ضد اسپم: {status}")

@admin_only
@group_only
async def toggle_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/captcha on/off"""
    g = get_group(update.effective_chat.id)
    if context.args and context.args[0].lower() in ["on", "off"]:
        g["captcha"] = context.args[0].lower() == "on"
    else:
        g["captcha"] = not g.get("captcha", False)
    save_data(DB)
    status = "✅ روشن" if g["captcha"] else "❌ خاموش"
    await update.message.reply_text(f"🔐 کپچا: {status}")

# ─── یادداشت ─────────────────────────────────────────────

@admin_only
@group_only
async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/save [نام] [متن]"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ `/save نام متن`", parse_mode=ParseMode.MARKDOWN)
        return
    g = get_group(update.effective_chat.id)
    name = context.args[0]
    content = " ".join(context.args[1:])
    g["notes"][name] = content
    save_data(DB)
    await update.message.reply_text(f"✅ یادداشت `{name}` ذخیره شد.", parse_mode=ParseMode.MARKDOWN)

@group_only
async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/get [نام]"""
    if not context.args:
        await update.message.reply_text("⚠️ نام یادداشت را وارد کنید.")
        return
    g = get_group(update.effective_chat.id)
    name = context.args[0]
    if name in g.get("notes", {}):
        await update.message.reply_text(g["notes"][name])
    else:
        await update.message.reply_text(f"یادداشت `{name}` یافت نشد.", parse_mode=ParseMode.MARKDOWN)

@group_only
async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/notes"""
    g = get_group(update.effective_chat.id)
    notes = g.get("notes", {})
    if not notes:
        await update.message.reply_text("📭 هیچ یادداشتی ذخیره نشده.")
        return
    text = "📝 *یادداشت‌ها:*\n\n" + "\n".join(f"• `#{k}`" for k in notes.keys())
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ─── فیلتر خودکار ────────────────────────────────────────

@admin_only
@group_only
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/filter [کلمه] [پاسخ]"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ `/filter کلمه پاسخ`", parse_mode=ParseMode.MARKDOWN)
        return
    g = get_group(update.effective_chat.id)
    trigger = context.args[0].lower()
    response = " ".join(context.args[1:])
    g["filters"][trigger] = response
    save_data(DB)
    await update.message.reply_text(f"✅ فیلتر `{trigger}` اضافه شد.", parse_mode=ParseMode.MARKDOWN)

@group_only
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/filters"""
    g = get_group(update.effective_chat.id)
    fl = g.get("filters", {})
    if not fl:
        await update.message.reply_text("📭 هیچ فیلتری تنظیم نشده.")
        return
    text = "🔧 *فیلترها:*\n\n" + "\n".join(f"• `{k}` ← {v}" for k, v in fl.items())
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ─── قوانین ──────────────────────────────────────────────

@admin_only
@group_only
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setrules [متن]"""
    if not context.args:
        await update.message.reply_text("⚠️ متن قوانین را وارد کنید.")
        return
    g = get_group(update.effective_chat.id)
    g["rules"] = " ".join(context.args)
    save_data(DB)
    await update.message.reply_text("✅ قوانین گروه تنظیم شد.")

@group_only
async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rules"""
    g = get_group(update.effective_chat.id)
    rules = g.get("rules", "")
    if not rules:
        await update.message.reply_text("📭 هنوز قوانینی تنظیم نشده.")
        return
    await update.message.reply_text(f"📜 *قوانین گروه:*\n\n{rules}", parse_mode=ParseMode.MARKDOWN)

# ─── آمار ────────────────────────────────────────────────

@group_only
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats"""
    chat = update.effective_chat
    g = get_group(chat.id)
    st = g.get("stats", {})
    try:
        count = await chat.get_member_count()
    except TelegramError:
        count = "?"
    warns_total = sum(g.get("warns", {}).values())
    await update.message.reply_text(
        f"📊 *آمار گروه {chat.title}*\n\n"
        f"👥 اعضا: {count}\n"
        f"💬 پیام‌ها: {st.get('messages', 0)}\n"
        f"➕ ورودی: {st.get('joins', 0)}\n"
        f"➖ خروجی: {st.get('leaves', 0)}\n"
        f"🚫 بن‌شده: {st.get('banned_total', 0)}\n"
        f"⚠️ هشدارهای فعال: {warns_total}\n"
        f"🔒 وضعیت: {'قفل' if g.get('locked') else 'باز'}\n"
        f"🛡 ضد اسپم: {'روشن' if g.get('anti_spam', True) else 'خاموش'}\n"
        f"🔐 کپچا: {'روشن' if g.get('captcha') else 'خاموش'}",
        parse_mode=ParseMode.MARKDOWN
    )

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/info — اطلاعات کاربر"""
    target = get_target_user(update, context)
    if target and hasattr(target, 'id'):
        user = target
    else:
        user = update.effective_user
    text = (
        f"👤 *اطلاعات کاربر*\n\n"
        f"🆔 آیدی: `{user.id}`\n"
        f"👤 نام: {user.full_name}\n"
        f"🔗 یوزرنیم: @{user.username or 'ندارد'}\n"
        f"🤖 ربات: {'بله' if user.is_bot else 'خیر'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/id"""
    chat = update.effective_chat
    user = update.effective_user
    text = f"👤 آیدی شما: `{user.id}`\n💬 آیدی گروه: `{chat.id}`"
    if update.message.reply_to_message:
        ru = update.message.reply_to_message.from_user
        text += f"\n👤 آیدی کاربر ریپلای: `{ru.id}`"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@group_only
async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/report — گزارش تخلف به ادمین‌ها"""
    chat = update.effective_chat
    user = update.effective_user
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ روی پیام متخلف ریپلای کنید.")
        return
    reported = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "بدون دلیل"
    # اطلاع‌رسانی به ادمین‌ها
    try:
        admins = await chat.get_administrators()
        for admin in admins:
            if not admin.user.is_bot:
                try:
                    await context.bot.send_message(
                        admin.user.id,
                        f"🚨 *گزارش تخلف*\n\n"
                        f"📍 گروه: {chat.title}\n"
                        f"👤 گزارش‌دهنده: {user.full_name}\n"
                        f"⚠️ متخلف: {reported.full_name} (`{reported.id}`)\n"
                        f"📝 دلیل: {reason}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except TelegramError:
                    pass
    except TelegramError:
        pass
    await update.message.reply_text("✅ گزارش شما به ادمین‌ها ارسال شد.")
    try:
        await update.message.delete()
    except TelegramError:
        pass

# ─── Callback queries ────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر دکمه‌های inline"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "help":
        await query.message.reply_text("برای راهنما /help را بزنید.")

    elif data == "stats":
        if update.effective_chat.type in ["group", "supergroup"]:
            g = get_group(update.effective_chat.id)
            st = g.get("stats", {})
            await query.edit_message_text(
                f"📊 پیام‌ها: {st.get('messages',0)}\n"
                f"👥 ورودی: {st.get('joins',0)}\n"
                f"🚫 بن: {st.get('banned_total',0)}"
            )

    elif data.startswith("unban_"):
        user_id = int(data.split("_")[1])
        try:
            await update.effective_chat.unban_member(user_id)
            await query.edit_message_text(f"✅ بن کاربر `{user_id}` برداشته شد.", parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            await query.edit_message_text(f"❌ {e}")

    elif data.startswith("unmute_"):
        user_id = int(data.split("_")[1])
        try:
            await update.effective_chat.restrict_member(
                user_id,
                ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                can_send_other_messages=True, can_add_web_page_previews=True)
            )
            await query.edit_message_text(f"✅ سکوت کاربر `{user_id}` برداشته شد.", parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            await query.edit_message_text(f"❌ {e}")

    elif data.startswith("captcha_"):
        parts = data.split("_")
        user_id = int(parts[1])
        chosen = int(parts[2])
        chat = update.effective_chat
        g = get_group(chat.id)
        # فقط خود کاربر می‌تواند جواب دهد
        if query.from_user.id != user_id:
            await query.answer("این سوال برای شما نیست!", show_alert=True)
            return
        correct = g.get("captcha_pending", {}).get(str(user_id))
        if correct and chosen == correct:
            del g["captcha_pending"][str(user_id)]
            save_data(DB)
            try:
                await chat.restrict_member(user_id, ChatPermissions(
                    can_send_messages=True, can_send_media_messages=True,
                    can_send_other_messages=True, can_add_web_page_previews=True
                ))
            except TelegramError:
                pass
            await query.edit_message_text(f"✅ خوش آمدید! کپچا تایید شد.")
        else:
            await query.answer("❌ پاسخ اشتباه! دوباره تلاش کنید.", show_alert=True)

    elif data.startswith("rules_"):
        chat_id = int(data.split("_")[1])
        g = get_group(chat_id)
        rules = g.get("rules", "قوانینی تنظیم نشده.")
        await query.answer(rules[:200], show_alert=True)

# ─── راه‌اندازی ربات ────────────────────────────────────

def main():
    """اجرای ربات"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ لطفاً توکن ربات را در BOT_TOKEN تنظیم کنید!")
        print("💡 توکن را از @BotFather دریافت کنید.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # دستورات پایه
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("info", user_info))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("rules", show_rules))
    app.add_handler(CommandHandler("report", report_user))

    # مدیریت اعضا
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))

    # سیستم هشدار
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("unwarn", unwarn_user))
    app.add_handler(CommandHandler("warns", show_warns))
    app.add_handler(CommandHandler("setlimit", set_warn_limit))

    # قفل گروه
    app.add_handler(CommandHandler("lock", lock_group))
    app.add_handler(CommandHandler("unlock", unlock_group))

    # تنظیمات
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("setgoodbye", set_goodbye))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("antispam", toggle_antispam))
    app.add_handler(CommandHandler("captcha", toggle_captcha))

    # کلمات ممنوع
    app.add_handler(CommandHandler("addbadword", add_bad_word))
    app.add_handler(CommandHandler("delbadword", del_bad_word))
    app.add_handler(CommandHandler("badwords", list_bad_words))

    # یادداشت و فیلتر
    app.add_handler(CommandHandler("save", save_note))
    app.add_handler(CommandHandler("get", get_note))
    app.add_handler(CommandHandler("notes", list_notes))
    app.add_handler(CommandHandler("filter", add_filter))
    app.add_handler(CommandHandler("filters", list_filters))

    # ورود و خروج
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, member_joined))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left))

    # پیام‌های عمومی
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # دکمه‌های inline
    app.add_handler(CallbackQueryHandler(button_callback))

    print("✅ ربات در حال اجراست...")
    print("🔄 برای توقف Ctrl+C بزنید")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
