"""
ربات پیشرفته مدیریت گروه تلگرام
نسخه سازگار با python-telegram-bot 13.15
"""

import logging
import json
import os
from datetime import datetime, timedelta
from functools import wraps

from telegram import (
    Update, ChatPermissions,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler,
    CallbackQueryHandler, Filters, CallbackContext
)

# ── لاگ ──────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── توکن ─────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("❌ توکن تنظیم نشده! BOT_TOKEN را در Environment Variables بذار.")

# ── دیتابیس ساده ─────────────────────────────────────────
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

DB = load_data()

def get_group(chat_id):
    key = str(chat_id)
    if key not in DB:
        DB[key] = {
            "warns": {},
            "warn_limit": 3,
            "muted": {},
            "bad_words": [],
            "welcome_msg": "👋 {name} عزیز به {group} خوش آمدی!",
            "goodbye_msg": "🚪 {name} از گروه خارج شد.",
            "locked": False,
            "anti_spam": True,
            "rules": "",
            "notes": {},
            "filters": {},
            "stats": {"messages": 0, "joins": 0, "leaves": 0, "banned": 0},
            "spam_tracker": {}
        }
        save_data(DB)
    return DB[key]

# ── دکوراتورها ───────────────────────────────────────────
def admin_only(func):
    @wraps(func)
    def wrapper(update: Update, context: CallbackContext):
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return
        if chat.type == "private":
            return func(update, context)
        member = chat.get_member(user.id)
        if member.status in ["administrator", "creator"]:
            return func(update, context)
        update.message.reply_text("⛔️ فقط ادمین‌ها مجاز هستند.")
    return wrapper

def group_only(func):
    @wraps(func)
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_chat.type in ["group", "supergroup"]:
            return func(update, context)
        update.message.reply_text("⚠️ این دستور فقط در گروه کار می‌کند.")
    return wrapper

def get_target(update, context):
    """یافتن کاربر هدف"""
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        try:
            return int(context.args[0])
        except:
            pass
    return None

# ── دستورات پایه ─────────────────────────────────────────
def start(update: Update, context: CallbackContext):
    keyboard = [[
        InlineKeyboardButton("📋 راهنما", callback_data="help"),
        InlineKeyboardButton("📊 آمار", callback_data="stats")
    ]]
    update.message.reply_text(
        "🤖 *ربات مدیریت گروه*\n\n"
        "برای راهنمای کامل /help را بزنید.\n\n"
        "✅ مدیریت اعضا\n"
        "✅ سیستم هشدار\n"
        "✅ ضد اسپم\n"
        "✅ فیلتر کلمات\n"
        "✅ یادداشت و فیلتر خودکار",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📋 *راهنمای دستورات*\n\n"
        "👮 *مدیریت اعضا:*\n"
        "/ban — بن کردن\n"
        "/unban — رفع بن\n"
        "/kick — اخراج\n"
        "/mute [دقیقه] — بی‌صدا\n"
        "/unmute — رفع سکوت\n\n"
        "⚠️ *هشدار:*\n"
        "/warn — هشدار\n"
        "/unwarn — حذف هشدار\n"
        "/warns — نمایش هشدارها\n"
        "/setlimit [عدد] — حد هشدار\n\n"
        "⚙️ *تنظیمات:*\n"
        "/lock — قفل گروه\n"
        "/unlock — باز کردن\n"
        "/setwelcome [متن] — خوش‌آمدگویی\n"
        "/setgoodbye [متن] — خداحافظی\n"
        "/setrules [متن] — قوانین\n"
        "/rules — نمایش قوانین\n\n"
        "🚫 *فیلتر:*\n"
        "/addbadword [کلمه]\n"
        "/delbadword [کلمه]\n"
        "/badwords — لیست\n"
        "/antispam on/off\n\n"
        "📝 *یادداشت:*\n"
        "/save [نام] [متن]\n"
        "/get [نام] یا #نام\n"
        "/notes — لیست\n\n"
        "📊 *اطلاعات:*\n"
        "/stats — آمار گروه\n"
        "/id — نمایش آیدی\n"
        "/report — گزارش تخلف",
        parse_mode="Markdown"
    )

# ── مدیریت اعضا ──────────────────────────────────────────
@admin_only
@group_only
def ban_user(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    uid = target.id if hasattr(target, 'id') else target
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "بدون دلیل"
    try:
        update.effective_chat.kick_member(uid)
        g = get_group(update.effective_chat.id)
        g["stats"]["banned"] += 1
        save_data(DB)
        name = target.full_name if hasattr(target, 'full_name') else str(uid)
        keyboard = [[InlineKeyboardButton("🔓 رفع بن", callback_data=f"unban_{uid}")]]
        update.message.reply_text(
            f"🚫 *بن شد*\n👤 {name}\n📝 دلیل: {reason}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
def unban_user(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ آیدی بدهید.")
        return
    uid = target.id if hasattr(target, 'id') else target
    try:
        update.effective_chat.unban_member(uid)
        update.message.reply_text(f"✅ بن کاربر `{uid}` برداشته شد.", parse_mode="Markdown")
    except Exception as e:
        update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
def kick_user(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    uid = target.id if hasattr(target, 'id') else target
    try:
        update.effective_chat.kick_member(uid)
        update.effective_chat.unban_member(uid)
        name = target.full_name if hasattr(target, 'full_name') else str(uid)
        update.message.reply_text(f"👢 {name} اخراج شد.")
    except Exception as e:
        update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
def mute_user(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    uid = target.id if hasattr(target, 'id') else target
    duration = 60
    if context.args:
        try:
            duration = int(context.args[-1])
        except:
            pass
    until = datetime.now() + timedelta(minutes=duration)
    try:
        update.effective_chat.restrict_member(
            uid,
            ChatPermissions(can_send_messages=False),
            until_date=until
        )
        name = target.full_name if hasattr(target, 'full_name') else str(uid)
        keyboard = [[InlineKeyboardButton("🔊 رفع سکوت", callback_data=f"unmute_{uid}")]]
        update.message.reply_text(
            f"🔇 *بی‌صدا شد*\n👤 {name}\n⏱ {duration} دقیقه",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        update.message.reply_text(f"❌ خطا: {e}")

@admin_only
@group_only
def unmute_user(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    uid = target.id if hasattr(target, 'id') else target
    try:
        update.effective_chat.restrict_member(
            uid,
            ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        update.message.reply_text(f"🔊 سکوت کاربر `{uid}` برداشته شد.", parse_mode="Markdown")
    except Exception as e:
        update.message.reply_text(f"❌ خطا: {e}")

# ── سیستم هشدار ──────────────────────────────────────────
@admin_only
@group_only
def warn_user(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    uid = str(target.id if hasattr(target, 'id') else target)
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "بدون دلیل"
    g = get_group(update.effective_chat.id)
    g["warns"][uid] = g["warns"].get(uid, 0) + 1
    count = g["warns"][uid]
    limit = g["warn_limit"]
    save_data(DB)
    name = target.full_name if hasattr(target, 'full_name') else uid
    if count >= limit:
        try:
            update.effective_chat.kick_member(int(uid))
            g["warns"].pop(uid, None)
            save_data(DB)
            update.message.reply_text(
                f"🚨 *{name} بعد از {limit} هشدار بن شد!*\nدلیل: {reason}",
                parse_mode="Markdown"
            )
        except Exception as e:
            update.message.reply_text(f"❌ {e}")
    else:
        bars = "🟥" * count + "⬜️" * (limit - count)
        update.message.reply_text(
            f"⚠️ *هشدار*\n👤 {name}\n📝 {reason}\n{bars} ({count}/{limit})",
            parse_mode="Markdown"
        )

@admin_only
@group_only
def unwarn_user(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    uid = str(target.id if hasattr(target, 'id') else target)
    g = get_group(update.effective_chat.id)
    if uid in g["warns"] and g["warns"][uid] > 0:
        g["warns"][uid] -= 1
        if g["warns"][uid] == 0:
            del g["warns"][uid]
        save_data(DB)
        update.message.reply_text("✅ یک هشدار کم شد.")
    else:
        update.message.reply_text("این کاربر هشداری ندارد.")

@group_only
def show_warns(update: Update, context: CallbackContext):
    target = get_target(update, context)
    if not target:
        update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
        return
    uid = str(target.id if hasattr(target, 'id') else target)
    g = get_group(update.effective_chat.id)
    count = g["warns"].get(uid, 0)
    limit = g["warn_limit"]
    name = target.full_name if hasattr(target, 'full_name') else uid
    bars = "🟥" * count + "⬜️" * max(0, limit - count)
    update.message.reply_text(
        f"📊 *هشدارهای {name}*\n{bars}\n{count} از {limit}",
        parse_mode="Markdown"
    )

# ── قفل گروه ─────────────────────────────────────────────
@admin_only
@group_only
def lock_group(update: Update, context: CallbackContext):
    try:
        update.effective_chat.set_permissions(ChatPermissions(can_send_messages=False))
        g = get_group(update.effective_chat.id)
        g["locked"] = True
        save_data(DB)
        update.message.reply_text("🔒 گروه قفل شد.")
    except Exception as e:
        update.message.reply_text(f"❌ {e}")

@admin_only
@group_only
def unlock_group(update: Update, context: CallbackContext):
    try:
        update.effective_chat.set_permissions(ChatPermissions(
            can_send_messages=True, can_send_media_messages=True,
            can_send_other_messages=True, can_add_web_page_previews=True
        ))
        g = get_group(update.effective_chat.id)
        g["locked"] = False
        save_data(DB)
        update.message.reply_text("🔓 قفل گروه برداشته شد.")
    except Exception as e:
        update.message.reply_text(f"❌ {e}")

# ── خوش‌آمدگویی ──────────────────────────────────────────
@admin_only
@group_only
def set_welcome(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("مثال: /setwelcome سلام {name} خوش اومدی!")
        return
    g = get_group(update.effective_chat.id)
    g["welcome_msg"] = " ".join(context.args)
    save_data(DB)
    update.message.reply_text(f"✅ پیام خوش‌آمدگویی:\n{g['welcome_msg']}")

@admin_only
@group_only
def set_goodbye(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("مثال: /setgoodbye {name} خداحافظ!")
        return
    g = get_group(update.effective_chat.id)
    g["goodbye_msg"] = " ".join(context.args)
    save_data(DB)
    update.message.reply_text(f"✅ پیام خداحافظی:\n{g['goodbye_msg']}")

def member_joined(update: Update, context: CallbackContext):
    chat = update.effective_chat
    g = get_group(chat.id)
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        g["stats"]["joins"] += 1
        save_data(DB)
        msg = g["welcome_msg"].format(
            name=member.full_name,
            group=chat.title or "گروه",
            id=member.id
        )
        update.message.reply_text(msg)

def member_left(update: Update, context: CallbackContext):
    chat = update.effective_chat
    g = get_group(chat.id)
    member = update.message.left_chat_member
    if member and not member.is_bot:
        g["stats"]["leaves"] += 1
        save_data(DB)
        msg = g["goodbye_msg"].format(
            name=member.full_name,
            group=chat.title or "گروه",
            id=member.id
        )
        update.message.reply_text(msg)

# ── کلمات ممنوع ──────────────────────────────────────────
@admin_only
@group_only
def add_bad_word(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("⚠️ کلمه را وارد کنید.")
        return
    g = get_group(update.effective_chat.id)
    word = " ".join(context.args).lower()
    if word not in g["bad_words"]:
        g["bad_words"].append(word)
        save_data(DB)
    update.message.reply_text(f"✅ `{word}` اضافه شد.", parse_mode="Markdown")

@admin_only
@group_only
def del_bad_word(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("⚠️ کلمه را وارد کنید.")
        return
    g = get_group(update.effective_chat.id)
    word = " ".join(context.args).lower()
    if word in g["bad_words"]:
        g["bad_words"].remove(word)
        save_data(DB)
        update.message.reply_text(f"✅ `{word}` حذف شد.", parse_mode="Markdown")
    else:
        update.message.reply_text("این کلمه در لیست نیست.")

@group_only
def list_bad_words(update: Update, context: CallbackContext):
    g = get_group(update.effective_chat.id)
    words = g.get("bad_words", [])
    if not words:
        update.message.reply_text("📭 هیچ کلمه ممنوعی ندارید.")
        return
    update.message.reply_text(
        "🚫 *کلمات ممنوع:*\n\n" + "\n".join(f"• `{w}`" for w in words),
        parse_mode="Markdown"
    )

@admin_only
@group_only
def toggle_antispam(update: Update, context: CallbackContext):
    g = get_group(update.effective_chat.id)
    if context.args and context.args[0].lower() in ["on", "off"]:
        g["anti_spam"] = context.args[0].lower() == "on"
    else:
        g["anti_spam"] = not g.get("anti_spam", True)
    save_data(DB)
    status = "✅ روشن" if g["anti_spam"] else "❌ خاموش"
    update.message.reply_text(f"🛡 ضد اسپم: {status}")

# ── یادداشت ──────────────────────────────────────────────
@admin_only
@group_only
def save_note(update: Update, context: CallbackContext):
    if not context.args or len(context.args) < 2:
        update.message.reply_text("مثال: /save سوال جواب سوال اینجاست")
        return
    g = get_group(update.effective_chat.id)
    name = context.args[0]
    content = " ".join(context.args[1:])
    g["notes"][name] = content
    save_data(DB)
    update.message.reply_text(f"✅ یادداشت `{name}` ذخیره شد.", parse_mode="Markdown")

@group_only
def get_note(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("مثال: /get نام")
        return
    g = get_group(update.effective_chat.id)
    name = context.args[0]
    if name in g.get("notes", {}):
        update.message.reply_text(g["notes"][name])
    else:
        update.message.reply_text(f"یادداشت `{name}` پیدا نشد.", parse_mode="Markdown")

@group_only
def list_notes(update: Update, context: CallbackContext):
    g = get_group(update.effective_chat.id)
    notes = g.get("notes", {})
    if not notes:
        update.message.reply_text("📭 هیچ یادداشتی ندارید.")
        return
    update.message.reply_text(
        "📝 *یادداشت‌ها:*\n\n" + "\n".join(f"• `#{k}`" for k in notes.keys()),
        parse_mode="Markdown"
    )

# ── قوانین ───────────────────────────────────────────────
@admin_only
@group_only
def set_rules(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("مثال: /setrules قانون ۱: احترام")
        return
    g = get_group(update.effective_chat.id)
    g["rules"] = " ".join(context.args)
    save_data(DB)
    update.message.reply_text("✅ قوانین تنظیم شد.")

@group_only
def show_rules(update: Update, context: CallbackContext):
    g = get_group(update.effective_chat.id)
    rules = g.get("rules", "")
    if not rules:
        update.message.reply_text("📭 قوانینی تنظیم نشده.")
        return
    update.message.reply_text(f"📜 *قوانین:*\n\n{rules}", parse_mode="Markdown")

# ── آمار و اطلاعات ────────────────────────────────────────
@group_only
def show_stats(update: Update, context: CallbackContext):
    chat = update.effective_chat
    g = get_group(chat.id)
    st = g.get("stats", {})
    try:
        count = chat.get_members_count()
    except:
        count = "?"
    update.message.reply_text(
        f"📊 *آمار {chat.title}*\n\n"
        f"👥 اعضا: {count}\n"
        f"💬 پیام‌ها: {st.get('messages', 0)}\n"
        f"➕ ورودی: {st.get('joins', 0)}\n"
        f"➖ خروجی: {st.get('leaves', 0)}\n"
        f"🚫 بن شده: {st.get('banned', 0)}\n"
        f"⚠️ هشدار فعال: {sum(g.get('warns', {}).values())}\n"
        f"🔒 وضعیت: {'قفل' if g.get('locked') else 'باز'}\n"
        f"🛡 ضد اسپم: {'روشن' if g.get('anti_spam', True) else 'خاموش'}",
        parse_mode="Markdown"
    )

def get_id(update: Update, context: CallbackContext):
    user = update.effective_user
    chat = update.effective_chat
    text = f"👤 آیدی شما: `{user.id}`\n💬 آیدی گروه: `{chat.id}`"
    if update.message.reply_to_message:
        ru = update.message.reply_to_message.from_user
        text += f"\n👤 آیدی کاربر ریپلای: `{ru.id}`"
    update.message.reply_text(text, parse_mode="Markdown")

@group_only
def report_user(update: Update, context: CallbackContext):
    if not update.message.reply_to_message:
        update.message.reply_text("⚠️ روی پیام متخلف ریپلای کنید.")
        return
    reported = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "بدون دلیل"
    try:
        admins = update.effective_chat.get_administrators()
        for admin in admins:
            if not admin.user.is_bot:
                try:
                    context.bot.send_message(
                        admin.user.id,
                        f"🚨 *گزارش تخلف*\n"
                        f"📍 گروه: {update.effective_chat.title}\n"
                        f"👤 گزارش‌دهنده: {update.effective_user.full_name}\n"
                        f"⚠️ متخلف: {reported.full_name}\n"
                        f"📝 دلیل: {reason}",
                        parse_mode="Markdown"
                    )
                except:
                    pass
    except:
        pass
    update.message.reply_text("✅ گزارش به ادمین‌ها ارسال شد.")

@admin_only
@group_only
def set_warn_limit(update: Update, context: CallbackContext):
    if not context.args or not context.args[0].isdigit():
        update.message.reply_text("مثال: /setlimit 5")
        return
    g = get_group(update.effective_chat.id)
    g["warn_limit"] = max(1, int(context.args[0]))
    save_data(DB)
    update.message.reply_text(f"✅ حد هشدار: {g['warn_limit']}")

# ── هندلر پیام اصلی ──────────────────────────────────────
SPAM_WINDOW = 5
SPAM_MAX = 5

def handle_message(update: Update, context: CallbackContext):
    if not update.message or not update.effective_chat:
        return
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        return
    g = get_group(chat.id)
    g["stats"]["messages"] = g["stats"].get("messages", 0) + 1

    user = update.effective_user
    if not user:
        return

    # بررسی ادمین
    try:
        member = chat.get_member(user.id)
        is_admin = member.status in ["administrator", "creator"]
    except:
        is_admin = False

    # فیلتر کلمات
    if update.message.text:
        text_lower = update.message.text.lower()
        for word in g.get("bad_words", []):
            if word in text_lower:
                try:
                    update.message.delete()
                    msg = update.message.reply_text(
                        f"⚠️ {user.full_name}، این کلمه ممنوع است!"
                    )
                    import threading
                    def del_msg():
                        import time; time.sleep(5)
                        try: msg.delete()
                        except: pass
                    threading.Thread(target=del_msg, daemon=True).start()
                except:
                    pass
                return

    # ضد اسپم
    if g.get("anti_spam", True) and not is_admin:
        uid = str(user.id)
        now = datetime.now().timestamp()
        tracker = g.get("spam_tracker", {})
        if uid not in tracker:
            tracker[uid] = []
        tracker[uid] = [t for t in tracker[uid] if now - t < SPAM_WINDOW]
        tracker[uid].append(now)
        g["spam_tracker"] = tracker
        if len(tracker[uid]) >= SPAM_MAX:
            try:
                update.message.delete()
                until = datetime.now() + timedelta(minutes=5)
                chat.restrict_member(
                    user.id,
                    ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                context.bot.send_message(
                    chat.id,
                    f"🛡 {user.full_name} به دلیل اسپم ۵ دقیقه بی‌صدا شد."
                )
                tracker[uid] = []
            except:
                pass

    # فیلترهای خودکار
    if update.message.text:
        text_lower = update.message.text.lower()
        for trigger, response in g.get("filters", {}).items():
            if trigger.lower() in text_lower:
                update.message.reply_text(response)
                break
        # یادداشت با #
        if update.message.text.startswith('#'):
            note_name = update.message.text[1:].split()[0]
            if note_name in g.get("notes", {}):
                update.message.reply_text(g["notes"][note_name])

    save_data(DB)

# ── Callback ─────────────────────────────────────────────
def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data

    if data == "help":
        query.message.reply_text("برای راهنما /help بزنید.")
    elif data == "stats":
        query.message.reply_text("برای آمار /stats بزنید.")
    elif data.startswith("unban_"):
        uid = int(data.split("_")[1])
        try:
            query.message.chat.unban_member(uid)
            query.edit_message_text(f"✅ بن `{uid}` برداشته شد.", parse_mode="Markdown")
        except Exception as e:
            query.edit_message_text(f"❌ {e}")
    elif data.startswith("unmute_"):
        uid = int(data.split("_")[1])
        try:
            query.message.chat.restrict_member(
                uid,
                ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            query.edit_message_text(f"✅ سکوت `{uid}` برداشته شد.", parse_mode="Markdown")
        except Exception as e:
            query.edit_message_text(f"❌ {e}")

# ── راه‌اندازی ────────────────────────────────────────────
def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("id", get_id))
    dp.add_handler(CommandHandler("stats", show_stats))
    dp.add_handler(CommandHandler("rules", show_rules))
    dp.add_handler(CommandHandler("report", report_user))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("unban", unban_user))
    dp.add_handler(CommandHandler("kick", kick_user))
    dp.add_handler(CommandHandler("mute", mute_user))
    dp.add_handler(CommandHandler("unmute", unmute_user))
    dp.add_handler(CommandHandler("warn", warn_user))
    dp.add_handler(CommandHandler("unwarn", unwarn_user))
    dp.add_handler(CommandHandler("warns", show_warns))
    dp.add_handler(CommandHandler("setlimit", set_warn_limit))
    dp.add_handler(CommandHandler("lock", lock_group))
    dp.add_handler(CommandHandler("unlock", unlock_group))
    dp.add_handler(CommandHandler("setwelcome", set_welcome))
    dp.add_handler(CommandHandler("setgoodbye", set_goodbye))
    dp.add_handler(CommandHandler("setrules", set_rules))
    dp.add_handler(CommandHandler("addbadword", add_bad_word))
    dp.add_handler(CommandHandler("delbadword", del_bad_word))
    dp.add_handler(CommandHandler("badwords", list_bad_words))
    dp.add_handler(CommandHandler("antispam", toggle_antispam))
    dp.add_handler(CommandHandler("save", save_note))
    dp.add_handler(CommandHandler("get", get_note))
    dp.add_handler(CommandHandler("notes", list_notes))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, member_joined))
    dp.add_handler(MessageHandler(Filters.status_update.left_chat_member, member_left))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CallbackQueryHandler(button_callback))

    logger.info("✅ ربات شروع شد!")
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()
