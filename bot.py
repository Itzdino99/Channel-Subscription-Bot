import os
import time
import uuid
import telebot

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread


# =========================================================
# KEEP-ALIVE SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running and healthy!"


def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# =========================================================
# CONFIGURATION
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
UPI_ID = os.getenv("UPI_ID", "")
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "").replace("@", "")

if not BOT_TOKEN or not MONGO_URI or not ADMIN_ID:
    raise ValueError("BOT_TOKEN, MONGO_URI and ADMIN_ID are required!")

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client["sub_management"]

# OLD COLLECTIONS - KEPT
channels_col = db["channels"]
users_col = db["users"]

# NEW / OTHER COLLECTIONS
bot_users_col = db["bot_users"]
settings_col = db["settings"]
force_channels_col = db["force_channels"]
coupons_col = db["coupons"]
coupon_uses_col = db["coupon_uses"]
feedback_col = db["feedback"]
premium_plans_col = db["premium_plans"]
premium_channels_col = db["premium_channels"]
milestones_col = db["milestones"]
milestone_claims_col = db["milestone_claims"]
purchase_history_col = db["purchase_history"]
coin_history_col = db["coin_history"]
daily_claims_col = db["daily_claims"]
audit_log_col = db["audit_logs"]
notification_col = db["notifications"]
feature_log_col = db["feature_logs"]
admin_action_col = db["admin_actions"]
announcement_col = db["announcements"]

pending_payments = {}
# Temporary in-memory selections used by the bulk Premium redeem flow.
bulk_redeem_selections = {}


# =========================================================
# BUTTON CONSTANTS
# =========================================================

# USER BUTTONS
USER_PROFILE = "🌐 My Profile"
USER_REFER = "🔗 Refer & Earn"
USER_REDEEM = "🎁 Redeem Premium"
USER_COUPON = "🎟️ Claim Coupon"
USER_REFERRALS = "👥 My Referrals"
USER_MILESTONES = "🎯 Milestones"
USER_LEADERBOARD = "🏆 Leaderboard"
USER_HOW = "📖 How It Works"
USER_FEEDBACK = "💬 Feedback"
USER_CONTACT = "📞 Contact Admin"

# ADMIN BUTTONS
ADMIN_CHANNELS = "📢 Channels"
ADMIN_PREMIUM = "🎁 Premium"
ADMIN_MILESTONES = "🎯 Milestones"
ADMIN_VERIFICATION = "📣 Verification"
ADMIN_USERS = "👥 Users"
ADMIN_COUPONS = "🎟️ Coupons"
ADMIN_SETTINGS = "⚙️ Settings"
ADMIN_MODE = "🔄 User Mode"
ADMIN_PANEL_BUTTON = "👑 Admin Panel"
ADMIN_DASHBOARD = "📊 Dashboard"
ADMIN_PURCHASES = "💰 Purchase History"
ADMIN_PREMIUM_BUYERS = "👑 Premium Buyers"
ADMIN_USER_SEARCH = "🔎 Search User"
ADMIN_COIN_ADD = "🪙 Add Coins"
ADMIN_SINGLE_BROADCAST = "📨 Single User Broadcast"
ADMIN_PREMIUM_MANAGE = "🛠️ Manage Premium User"
ADMIN_MAINTENANCE = "🚧 Maintenance Mode"
ADMIN_FEATURES = "🎛️ Feature Control"
ADMIN_ANALYTICS = "📈 Advanced Analytics"
ADMIN_BULK_RULES = "📦 Bulk Discount Rules"
ADMIN_AUDIT = "🧾 Audit Log"
ADMIN_BACKUP_INFO = "💾 System Health"
ADMIN_ANNOUNCEMENTS = "📣 Announcement Center"

USER_WALLET = "💳 Wallet"
USER_HISTORY = "🧾 My History"
USER_DAILY = "🎁 Daily Bonus"
USER_NOTIFICATIONS = "🔔 Notifications"
USER_STATUS = "📊 My Status"
USER_HELP = "🆘 Help & Rules"


# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "_id": "bot_settings",

    "coin_name": "KP",
    "coin_emoji": "🌽",
    "referral_reward": 10,
    "timezone": "Asia/Kathmandu",
    "maintenance_mode": False,
    "expiry_notice_hours": [24, 1],
    # Advanced feature switches. Every major optional system can be
    # enabled/disabled from the Admin Feature Control panel.
    "feature_flags": {
        "referrals": True,
        "milestones": True,
        "coupons": True,
        "leaderboard": True,
        "feedback": True,
        "daily_bonus": True,
        "wallet": True,
        "purchase_history": True,
        "notifications": True,
        "bulk_redeem": True,
        "single_redeem": True,
        "force_join": True,
        "maintenance": True,
        "premium_expiry_notice": True,
        "broadcast": True,
    },

    # Bulk pricing is based on the normal Premium plan cost.
    # Admin only sets discount rules; there is no second bulk price.
    "bulk_discount_rules": [
        {"min_channels": 2, "discount_type": "percent", "discount_value": 0},
        {"min_channels": 4, "discount_type": "percent", "discount_value": 0},
        {"min_channels": 5, "discount_type": "percent", "discount_value": 0},
    ],
    "bulk_max_channels": 50,

    # User engagement controls.
    "daily_bonus": 5,
    "daily_streak_bonus": 2,
    "daily_bonus_max": 25,
    "welcome_bonus": 0,
    "referral_multiplier": 1.0,

    # Notifications and receipts.
    "purchase_receipt": True,
    "purchase_notification_admin": True,
    "coin_notification": True,

    # Operational controls.
    "audit_log_enabled": True,
    "health_log_enabled": True,
    "auto_cleanup_days": 0,

    # Legacy fixed bulk price (kept for backward compatibility).
    "bulk_redeem_price": None,

    # Separate Bulk Redeem prices for each Premium duration/plan.
    # Example: {"plan_id": 500}
    "bulk_redeem_prices": {},

    # Legacy support
    "reward_channel_id": None,
    "reward_channel_name": "Premium Channel",

    # Logging channels
    "start_log_channel_id": None,
    "start_log_channel_name": None,

    "milestone_log_channel_id": None,
    "milestone_log_channel_name": None,

    # Editable texts
    "welcome_text": (
        "✨ *Welcome!*\n\n"
        "Choose an option below."
    ),

    "force_join_text": (
        "🎉 *Welcome!*\n\n"
        "You joined using a referral link.\n\n"
        "To continue, please join all the required channels/groups "
        "below and then press *Verify & Continue*."
    ),

    "verification_success_text": (
        "✅ *Verification Successful!*\n\n"
        "Welcome! You can now use all bot features."
    ),

    "how_it_works_text": (
        "📖 *How It Works*\n\n"
        "1️⃣ Share your referral link.\n"
        "2️⃣ Your friend starts the bot using your link.\n"
        "3️⃣ They join the required channels.\n"
        "4️⃣ They press Verify & Continue.\n"
        "5️⃣ You receive coins for successful referrals.\n"
        "6️⃣ Complete milestones for bonus rewards.\n"
        "7️⃣ Redeem coins for Premium!"
    ),

    "feedback_text": (
        "💬 *Send Feedback*\n\n"
        "Please send your feedback, suggestion or problem. "
        "It will be delivered to the admin."
    ),

    # User buttons
    "btn_profile": USER_PROFILE,
    "btn_refer": USER_REFER,
    "btn_redeem": USER_REDEEM,
    "btn_coupon": USER_COUPON,
    "btn_referrals": USER_REFERRALS,
    "btn_milestones": USER_MILESTONES,
    "btn_leaderboard": USER_LEADERBOARD,
    "btn_how": USER_HOW,
    "btn_feedback": USER_FEEDBACK,
    "btn_contact": USER_CONTACT
}


def get_settings():
    settings = settings_col.find_one({"_id": "bot_settings"})

    if not settings:
        settings_col.insert_one(DEFAULT_SETTINGS.copy())
        settings = DEFAULT_SETTINGS.copy()

    missing = {}

    for key, value in DEFAULT_SETTINGS.items():
        if key not in settings:
            missing[key] = value

    if missing:
        settings_col.update_one(
            {"_id": "bot_settings"},
            {"$set": missing}
        )
        settings.update(missing)

    return settings


def update_setting(key, value):
    settings_col.update_one(
        {"_id": "bot_settings"},
        {"$set": {key: value}},
        upsert=True
    )


def get_bot_timezone():
    timezone_name = get_settings().get("timezone", "Asia/Kathmandu")

    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("Asia/Kathmandu")


def bot_time_now():
    """Current time in the timezone selected from the admin panel."""
    return datetime.now(get_bot_timezone())


def format_bot_time(value):
    """Format stored UTC/naive datetimes using the selected bot timezone."""
    if not value:
        return "Unknown"

    try:
        if value.tzinfo is None:
            # Existing MongoDB records are stored as naive UTC values.
            value = value.replace(tzinfo=ZoneInfo("UTC"))
        return value.astimezone(get_bot_timezone()).strftime("%d %b %Y, %H:%M")
    except Exception:
        try:
            return value.strftime("%d %b %Y, %H:%M")
        except Exception:
            return "Unknown"


# =========================================================
# DATABASE SETUP / LEGACY MIGRATION
# =========================================================

def setup_database():

    try:
        milestone_claims_col.create_index(
            [("user_id", 1), ("milestone_id", 1)],
            unique=True
        )
    except Exception:
        pass

    try:
        bot_users_col.create_index("user_id", unique=True)
    except Exception:
        pass

    # Migrate old Premium channel if present
    settings = get_settings()

    if (
        settings.get("reward_channel_id")
        and premium_channels_col.count_documents({}) == 0
    ):
        premium_channels_col.update_one(
            {"channel_id": settings["reward_channel_id"]},
            {
                "$set": {
                    "channel_id": settings["reward_channel_id"],
                    "name": settings.get(
                        "reward_channel_name",
                        "Premium Channel"
                    ),
                    "added_at": datetime.now()
                }
            },
            upsert=True
        )

    # Create default flexible plans only if no plans exist
    if premium_plans_col.count_documents({}) == 0:
        premium_plans_col.insert_many([
            {
                "plan_id": "day_1",
                "amount": 1,
                "unit": "day",
                "duration_seconds": 86400,
                "cost": 50,
                "created_at": datetime.now()
            },
            {
                "plan_id": "day_7",
                "amount": 7,
                "unit": "day",
                "duration_seconds": 604800,
                "cost": 250,
                "created_at": datetime.now()
            },
            {
                "plan_id": "day_30",
                "amount": 30,
                "unit": "day",
                "duration_seconds": 2592000,
                "cost": 800,
                "created_at": datetime.now()
            }
        ])


# =========================================================
# USER HELPERS
# =========================================================

def get_user(user_id):
    return bot_users_col.find_one({"user_id": user_id})


def is_banned(user_id):
    user = get_user(user_id)
    return bool(user and user.get("banned", False))


def register_user(user):
    existing = get_user(user.id)

    bot_users_col.update_one(
        {"user_id": user.id},
        {
            "$setOnInsert": {
                "user_id": user.id,
                "joined_at": datetime.now(),
                "coins": 0,
                "referral_count": 0,
                "verified_referral": False,
                "banned": False,
                "mode": "user"
            },
            "$set": {
                "first_name": user.first_name or "",
                "username": user.username or ""
            }
        },
        upsert=True
    )

    return existing is None


def get_coin_balance(user_id):
    user = get_user(user_id)
    return int(user.get("coins", 0)) if user else 0


def add_coins(user_id, amount):
    bot_users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"coins": int(amount)}},
        upsert=True
    )


def user_display_name(user):
    if not user:
        return "Unknown User"

    name = user.get("first_name") or "User"
    username = user.get("username")

    if username:
        return f"{name} (@{username})"

    return name


def is_admin_mode(user_id):
    if user_id != ADMIN_ID:
        return False

    user = get_user(user_id)
    return bool(user and user.get("mode") == "admin")


def format_duration(amount, unit):
    amount = int(amount)

    names = {
        "minute": ("Minute", "Minutes"),
        "hour": ("Hour", "Hours"),
        "day": ("Day", "Days"),
        "month": ("Month", "Months"),
        "year": ("Year", "Years")
    }

    singular, plural = names.get(
        unit,
        ("Unit", "Units")
    )

    return f"{amount} {singular if amount == 1 else plural}"


def duration_seconds(amount, unit):

    amount = int(amount)

    unit_seconds = {
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "month": 2592000,  # 30 days
        "year": 31536000   # 365 days
    }

    return amount * unit_seconds[unit]


# =========================================================
# USER START LOGGING
# =========================================================

def send_start_log(user_id):

    settings = get_settings()
    channel_id = settings.get("start_log_channel_id")

    if not channel_id:
        return

    user = get_user(user_id)

    if not user:
        return

    username = (
        f"@{user.get('username')}"
        if user.get("username")
        else "Not set"
    )

    referrer_text = "No referrer"

    referrer_id = (
        user.get("referrer_id")
        or user.get("pending_referrer")
    )

    if referrer_id:
        referrer = get_user(referrer_id)

        if referrer:
            referrer_text = (
                f"{user_display_name(referrer)}\n"
                f"🆔 `{referrer_id}`"
            )
        else:
            referrer_text = f"User ID: `{referrer_id}`"

    try:
        bot.send_message(
            channel_id,
            f"""👤 *New User Started the Bot*

👤 Name: {user.get('first_name', 'User')}
🌐 Username: {username}
🆔 User ID: `{user_id}`

🔗 *Referrer:*
{referrer_text}

📅 Started: {datetime.now().strftime("%d %b %Y, %H:%M")}""",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Start log error: {e}")


# =========================================================
# USER KEYBOARD
# =========================================================

def user_menu_markup(user_id=None):

    settings = get_settings()

    markup = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    markup.row(
        KeyboardButton(settings["btn_profile"]),
        KeyboardButton(settings["btn_refer"])
    )

    markup.row(
        KeyboardButton(settings["btn_redeem"]),
        KeyboardButton(settings["btn_coupon"])
    )

    markup.row(
        KeyboardButton(settings["btn_referrals"]),
        KeyboardButton(settings["btn_milestones"])
    )

    markup.row(
        KeyboardButton(settings["btn_leaderboard"]),
        KeyboardButton(settings["btn_how"])
    )

    markup.row(
        KeyboardButton(settings["btn_feedback"]),
        KeyboardButton(settings["btn_contact"])
    )

    # This shortcut is only added for the configured admin account.
    if user_id == ADMIN_ID:
        markup.row(KeyboardButton(ADMIN_PANEL_BUTTON))

    return markup


def show_user_menu(chat_id):

    settings = get_settings()

    bot.send_message(
        chat_id,
        settings["welcome_text"],
        reply_markup=user_menu_markup(chat_id),
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN KEYBOARD PANEL
# =========================================================

def admin_menu_markup():

    markup = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=1
    )

    markup.row(KeyboardButton(ADMIN_CHANNELS))
    markup.row(KeyboardButton(ADMIN_PREMIUM))
    markup.row(KeyboardButton(ADMIN_MILESTONES))
    markup.row(KeyboardButton(ADMIN_VERIFICATION))
    markup.row(KeyboardButton(ADMIN_USERS))
    markup.row(KeyboardButton(ADMIN_COUPONS))
    markup.row(KeyboardButton(ADMIN_SETTINGS))
    markup.row(KeyboardButton(ADMIN_DASHBOARD))
    markup.row(KeyboardButton(ADMIN_PURCHASES))
    markup.row(KeyboardButton(ADMIN_PREMIUM_BUYERS))
    markup.row(KeyboardButton(ADMIN_USER_SEARCH))
    markup.row(KeyboardButton(ADMIN_COIN_ADD))
    markup.row(KeyboardButton(ADMIN_SINGLE_BROADCAST))
    markup.row(KeyboardButton(ADMIN_PREMIUM_MANAGE))
    markup.row(KeyboardButton(ADMIN_MAINTENANCE))
    markup.row(KeyboardButton(ADMIN_MODE))

    return markup


def show_admin_panel(chat_id):

    if chat_id != ADMIN_ID:
        return

    settings = get_settings()

    bot.send_message(
        chat_id,
        f"""👑 *ADMIN PANEL*

🌽 Currency: *{settings['coin_name']}*
🎁 Reward Channels: *{premium_channels_col.count_documents({})}*
🎯 Milestones: *{milestones_col.count_documents({})}*

👇 *Use the buttons below.*""",
        reply_markup=admin_menu_markup(),
        parse_mode="Markdown"
    )


def switch_to_admin_mode():

    bot_users_col.update_one(
        {"user_id": ADMIN_ID},
        {"$set": {"mode": "admin"}},
        upsert=True
    )


def switch_to_user_mode():

    bot_users_col.update_one(
        {"user_id": ADMIN_ID},
        {"$set": {"mode": "user"}},
        upsert=True
    )


# =========================================================
# FORCE JOIN SYSTEM
# =========================================================

def get_force_join_markup():

    markup = InlineKeyboardMarkup()
    channels = list(force_channels_col.find())

    for channel in channels:
        join_url = channel.get("join_url")

        if join_url:
            markup.add(
                InlineKeyboardButton(
                    f"📢 Join {channel.get('name', 'Channel')}",
                    url=join_url
                )
            )

    markup.add(
        InlineKeyboardButton(
            "✅ Verify & Continue",
            callback_data="verify_referral"
        )
    )

    return markup


def show_force_join(chat_id):

    channels = list(force_channels_col.find())
    settings = get_settings()

    if not channels:
        bot.send_message(
            chat_id,
            "⚠️ Required verification channels have not been configured yet."
        )
        return

    bot.send_message(
        chat_id,
        settings["force_join_text"],
        reply_markup=get_force_join_markup(),
        parse_mode="Markdown"
    )


def is_user_in_channel(channel_id, user_id):

    try:
        member = bot.get_chat_member(channel_id, user_id)

        return member.status in (
            "creator",
            "administrator",
            "member",
            "restricted"
        )

    except Exception as e:
        print(f"Membership check error: {channel_id} | {e}")
        return False


def check_all_force_channels(user_id):

    channels = list(force_channels_col.find())

    if not channels:
        return False

    for channel in channels:
        if not is_user_in_channel(
            channel["channel_id"],
            user_id
        ):
            return False

    return True


# =========================================================
# START COMMAND
# =========================================================

@bot.message_handler(commands=["start"])
def start_handler(message):

    user_id = message.from_user.id
    is_new_user = register_user(message.from_user)

    if is_banned(user_id):
        bot.send_message(
            message.chat.id,
            "🚫 Your access to this bot has been restricted."
        )
        return

    parts = message.text.split(maxsplit=1)
    start_argument = (
        parts[1].strip()
        if len(parts) > 1
        else None
    )

    # OLD PAID CHANNEL DEEP LINK
    if start_argument:
        try:
            possible_channel_id = int(start_argument)

            if possible_channel_id < 0:

                ch_data = channels_col.find_one(
                    {"channel_id": possible_channel_id}
                )

                if ch_data:

                    markup = InlineKeyboardMarkup()

                    markup.add(
                        InlineKeyboardButton(
                            "🔗 Demo",
                            url="https://t.me/+lSW2hYbgrUNkMzFl"
                        )
                    )

                    for p_time in ch_data.get("plans", {}):

                        minutes = int(p_time)

                        if minutes > 525600:
                            label = "💎 Lifetime"
                        elif minutes >= 1440:
                            label = f"📅 {minutes // 1440} Days"
                        else:
                            label = f"⏱ {minutes} Min"

                        markup.add(
                            InlineKeyboardButton(
                                label,
                                callback_data=(
                                    f"select_{possible_channel_id}_{p_time}"
                                )
                            )
                        )

                    if CONTACT_USERNAME:
                        markup.add(
                            InlineKeyboardButton(
                                "📞 Contact Admin",
                                url=f"https://t.me/{CONTACT_USERNAME}"
                            )
                        )

                    bot.send_message(
                        message.chat.id,
                        f"""✨ *Welcome!*

📢 *Channel:* `{ch_data['name']}`

Select a subscription plan below.""",
                        reply_markup=markup,
                        parse_mode="Markdown"
                    )
                    return

        except ValueError:
            pass
        except Exception as e:
            print(f"Paid start error: {e}")

    # Existing pending referral
    user_data = get_user(user_id)

    if (
        user_data
        and user_data.get("pending_referrer") is not None
        and not user_data.get("verified_referral", False)
    ):
        show_force_join(message.chat.id)
        return

    # New referral
    if start_argument:

        try:
            referrer_id = int(start_argument)
            referrer = get_user(referrer_id)

            if (
                referrer_id != user_id
                and referrer is not None
                and not is_banned(referrer_id)
                and not user_data.get("verified_referral", False)
                and user_data.get("pending_referrer") is None
                and user_data.get("referrer_id") is None
            ):

                bot_users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "pending_referrer": referrer_id,
                            "referred_at": datetime.now()
                        }
                    }
                )

                # Log after referrer is attached
                send_start_log(user_id)

                show_force_join(message.chat.id)
                return

        except ValueError:
            pass

    # Log new normal users
    if is_new_user:
        send_start_log(user_id)

    # ADMIN
    if user_id == ADMIN_ID:

        switch_to_admin_mode()

        bot.send_message(
            message.chat.id,
            "👑 *Admin Mode Activated*",
            parse_mode="Markdown"
        )

        show_admin_panel(message.chat.id)
        return

    show_user_menu(message.chat.id)


# =========================================================
# VERIFY REFERRAL
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "verify_referral"
)
def verify_referral(call):

    user_id = call.from_user.id

    if is_banned(user_id):
        bot.answer_callback_query(
            call.id,
            "Your account is restricted.",
            show_alert=True
        )
        return

    user_data = get_user(user_id)

    if not user_data:
        bot.answer_callback_query(
            call.id,
            "Please start the bot again.",
            show_alert=True
        )
        return

    referrer_id = user_data.get("pending_referrer")

    if referrer_id is None:
        bot.answer_callback_query(
            call.id,
            "No pending referral verification.",
            show_alert=True
        )
        return

    if not check_all_force_channels(user_id):
        bot.answer_callback_query(
            call.id,
            "❌ Join all required channels first.",
            show_alert=True
        )
        return

    settings = get_settings()
    reward = int(settings["referral_reward"])

    result = bot_users_col.update_one(
        {
            "user_id": user_id,
            "verified_referral": False,
            "pending_referrer": referrer_id
        },
        {
            "$set": {
                "verified_referral": True,
                "referrer_id": referrer_id,
                "pending_referrer": None,
                "verified_at": datetime.now()
            }
        }
    )

    if result.modified_count != 1:
        bot.answer_callback_query(
            call.id,
            "Already processed.",
            show_alert=True
        )
        return

    # Add normal referral reward
    bot_users_col.update_one(
        {
            "user_id": referrer_id,
            "banned": {"$ne": True}
        },
        {
            "$inc": {
                "coins": reward,
                "referral_count": 1
            }
        }
    )

    bot.answer_callback_query(
        call.id,
        "Verification successful!"
    )

    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass

    new_user = get_user(user_id)
    person_name = user_display_name(new_user)

    try:
        bot.send_message(
            referrer_id,
            f"""🎉 *New Successful Referral!*

👤 *{person_name}* completed verification.

{settings['coin_emoji']} You received *{reward} {settings['coin_name']}*!""",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # Check milestone after every successful referral
    check_and_reward_milestones(referrer_id)

    bot.send_message(
        user_id,
        settings["verification_success_text"],
        parse_mode="Markdown"
    )

    show_user_menu(user_id)


# =========================================================
# PROFILE
# =========================================================

def is_user_button(message, setting_key):
    try:
        return (
            message.text == get_settings().get(setting_key)
        )
    except Exception:
        return False


@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_profile")
        and m.from_user.id != ADMIN_ID
    )
)
def my_profile(message):

    user_id = message.from_user.id
    register_user(message.from_user)

    user = get_user(user_id)
    settings = get_settings()

    joined = user.get("joined_at")

    joined_text = (
        joined.strftime("%d %b %Y")
        if isinstance(joined, datetime)
        else "Unknown"
    )

    referrer_text = "No one"

    if user.get("referrer_id"):

        referrer = get_user(user["referrer_id"])

        if referrer:
            referrer_text = user_display_name(referrer)
        else:
            referrer_text = "Unknown User"

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Not set"
    )

    bot.send_message(
        message.chat.id,
        f"""👤 *My Profile*

👤 Name: {message.from_user.first_name or 'User'}
🌐 Username: {username}
🆔 ID: `{user_id}`
📅 Joined: {joined_text}

👥 Successful Referrals: *{user.get('referral_count', 0)}*
{settings['coin_emoji']} Balance: *{user.get('coins', 0)} {settings['coin_name']}*

🔗 Referred By: *{referrer_text}*""",
        parse_mode="Markdown"
    )


# =========================================================
# REFER & EARN
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_refer")
        and m.from_user.id != ADMIN_ID
    )
)
def refer_and_earn(message):

    user_id = message.from_user.id
    register_user(message.from_user)

    user = get_user(user_id)
    settings = get_settings()

    try:
        username = bot.get_me().username
        link = f"https://t.me/{username}?start={user_id}"
    except Exception:
        link = "Unable to generate referral link."

    bot.send_message(
        message.chat.id,
        f"""🔗 *Refer & Earn*

🎁 *Reward per successful referral:*
{settings['coin_emoji']} *{settings['referral_reward']} {settings['coin_name']}*

👥 *Successful Referrals:* {user.get('referral_count', 0)}

🔗 *Your Referral Link:*

`{link}`

📌 Your friend must start using this link and complete verification before you receive the reward.""",
        parse_mode="Markdown"
    )


# =========================================================
# MY REFERRALS
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_referrals")
        and m.from_user.id != ADMIN_ID
    )
)
def my_referrals(message):

    referred_users = list(
        bot_users_col.find({
            "referrer_id": message.from_user.id,
            "verified_referral": True
        }).sort(
            "verified_at",
            DESCENDING
        ).limit(30)
    )

    if not referred_users:
        bot.send_message(
            message.chat.id,
            "👥 *My Referrals*\n\nYou don't have any successful referrals yet.",
            parse_mode="Markdown"
        )
        return

    text = "👥 *My Successful Referrals*\n\n"

    for number, user in enumerate(referred_users, 1):
        text += f"{number}. {user_display_name(user)}\n"

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# MILESTONE SYSTEM
# =========================================================

def progress_bar(current, target, length=10):

    if target <= 0:
        return "░" * length

    percentage = min(
        100,
        int((current / target) * 100)
    )

    filled = int((percentage / 100) * length)

    return (
        "█" * filled
        + "░" * (length - filled)
    )


def check_and_reward_milestones(user_id):

    user = get_user(user_id)

    if not user or is_banned(user_id):
        return

    referral_count = int(
        user.get("referral_count", 0)
    )

    milestones = list(
        milestones_col.find({
            "target": {"$lte": referral_count}
        })
    )

    for milestone in milestones:

        milestone_id = str(milestone["_id"])

        try:
            milestone_claims_col.insert_one({
                "user_id": user_id,
                "milestone_id": milestone_id,
                "claimed_at": datetime.now()
            })
        except Exception:
            # Already claimed
            continue

        reward = int(milestone["reward"])
        add_coins(user_id, reward)

        settings = get_settings()

        try:
            bot.send_message(
                user_id,
                f"""🎉 *Milestone Completed!*

🎯 Target: *{milestone['target']} Referrals*
{settings['coin_emoji']} Reward: *{reward} {settings['coin_name']}*

💰 The reward has been automatically added to your balance!""",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        # Milestone logging channel
        log_channel = settings.get(
            "milestone_log_channel_id"
        )

        if log_channel:

            try:
                user_data = get_user(user_id)

                bot.send_message(
                    log_channel,
                    f"""🎯 *Milestone Completed*

👤 User: {user_display_name(user_data)}
🆔 ID: `{user_id}`

🎯 Target: *{milestone['target']} Referrals*
{settings['coin_emoji']} Reward: *{reward} {settings['coin_name']}*""",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Milestone log error: {e}")


@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_milestones")
        and m.from_user.id != ADMIN_ID
    )
)
def show_milestones(message):

    user = get_user(message.from_user.id)

    if not user:
        register_user(message.from_user)
        user = get_user(message.from_user.id)

    current = int(user.get("referral_count", 0))
    settings = get_settings()

    milestones = list(
        milestones_col.find().sort(
            "target",
            1
        )
    )

    if not milestones:
        bot.send_message(
            message.chat.id,
            "🎯 *Milestones*\n\nNo milestones have been added yet.",
            parse_mode="Markdown"
        )
        return

    text = (
        "🎯 *Referral Milestones*\n\n"
        f"👥 Your Referrals: *{current}*\n\n"
    )

    for milestone in milestones:

        target = int(milestone["target"])
        reward = int(milestone["reward"])

        claimed = milestone_claims_col.find_one({
            "user_id": message.from_user.id,
            "milestone_id": str(milestone["_id"])
        })

        if claimed:
            status = "✅ Completed"
        else:
            percentage = min(
                100,
                int((current / target) * 100)
            )

            status = (
                f"{progress_bar(current, target)} "
                f"{percentage}%\n"
                f"📊 {min(current, target)}/{target}"
            )

        text += (
            f"🎯 *{target} Referrals*\n"
            f"{settings['coin_emoji']} Reward: *{reward} "
            f"{settings['coin_name']}*\n"
            f"{status}\n\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# HOW IT WORKS / CONTACT / FEEDBACK
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_how")
        and m.from_user.id != ADMIN_ID
    )
)
def how_it_works(message):

    bot.send_message(
        message.chat.id,
        get_settings()["how_it_works_text"],
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_contact")
        and m.from_user.id != ADMIN_ID
    )
)
def contact_admin(message):

    if not CONTACT_USERNAME:
        bot.send_message(
            message.chat.id,
            "⚠️ Admin contact has not been configured."
        )
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    bot.send_message(
        message.chat.id,
        "📞 *Need help?*\n\nContact the admin below:",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_feedback")
        and m.from_user.id != ADMIN_ID
    )
)
def feedback_start(message):

    msg = bot.send_message(
        message.chat.id,
        get_settings()["feedback_text"],
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        receive_feedback
    )


def receive_feedback(message):

    if not message.text:
        bot.send_message(
            message.chat.id,
            "❌ Please send feedback as text."
        )
        return

    feedback_col.insert_one({
        "user_id": message.from_user.id,
        "name": message.from_user.first_name or "",
        "username": message.from_user.username or "",
        "text": message.text,
        "created_at": datetime.now()
    })

    try:
        bot.send_message(
            ADMIN_ID,
            f"""💬 *New Feedback*

👤 {message.from_user.first_name}
🆔 `{message.from_user.id}`

📝 *Message:*
{message.text}""",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    bot.send_message(
        message.chat.id,
        "✅ Thank you! Your feedback has been sent."
    )


# =========================================================
# FLEXIBLE PREMIUM REDEEM SYSTEM
# =========================================================

def get_premium_channels():
    return list(
        premium_channels_col.find().sort(
            "added_at",
            1
        )
    )


def redeem_channel_menu(user_id, chat_id):
    """Premium entry menu: user chooses Single Channel or Bulk Redeem first."""
    settings = get_settings()
    channels = get_premium_channels()

    if not channels:
        bot.send_message(
            chat_id,
            "⚠️ Premium rewards are not available yet."
        )
        return

    markup = InlineKeyboardMarkup(row_width=1)

    # Always let the user explicitly choose the purchase mode.
    if feature_enabled("single_redeem"):
        markup.add(
            InlineKeyboardButton(
                "🎁 Buy / Redeem Single Channel",
                callback_data="redeemmode:single"
            )
        )

    if feature_enabled("bulk_redeem") and len(channels) >= 2:
        markup.add(
            InlineKeyboardButton(
                "📦 Buy / Redeem Bulk Channels",
                callback_data="bulk:start"
            )
        )

    bot.send_message(
        chat_id,
        f"""🎁 *Premium Purchase*

{settings['coin_emoji']} *Balance:* {get_coin_balance(user_id)} {settings['coin_name']}

Choose how you want to get Premium:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "redeemmode:single"
)
def redeem_single_mode(call):
    """Open the normal single-channel selector."""
    if not feature_enabled("single_redeem"):
        bot.answer_callback_query(
            call.id,
            "Single-channel redeem is currently disabled by Admin.",
            show_alert=True
        )
        return

    channels = get_premium_channels()
    if not channels:
        bot.answer_callback_query(call.id, "No Premium channels available.", show_alert=True)
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for channel in channels:
        markup.add(
            InlineKeyboardButton(
                f"📢 {channel['name']}",
                callback_data=f"rchannel:{channel['channel_id']}"
            )
        )
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="redeemmode:back"))

    bot.edit_message_text(
        "🎁 *Single Channel Premium*\n\nChoose the channel you want to buy/redeem:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data == "redeemmode:back"
)
def redeem_mode_back(call):
    redeem_channel_menu(
        call.from_user.id,
        call.message.chat.id
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_redeem")
        and m.from_user.id != ADMIN_ID
    )
)
def redeem_premium_menu(message):

    redeem_channel_menu(
        message.from_user.id,
        message.chat.id
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("rchannel:")
)
def select_redeem_channel(call):

    channel_id = int(
        call.data.split(":")[1]
    )

    show_redeem_plans(
        call.from_user.id,
        call.message.chat.id,
        channel_id
    )

    bot.answer_callback_query(call.id)


def show_redeem_plans(user_id, chat_id, channel_id):

    settings = get_settings()

    channel = premium_channels_col.find_one(
        {"channel_id": channel_id}
    )

    if not channel:
        bot.send_message(
            chat_id,
            "❌ Premium channel not found."
        )
        return

    plans = list(
        premium_plans_col.find().sort(
            "duration_seconds",
            1
        )
    )

    if not plans:
        bot.send_message(
            chat_id,
            "⚠️ No Premium plans are available."
        )
        return

    markup = InlineKeyboardMarkup()

    for plan in plans:

        duration = format_duration(
            plan["amount"],
            plan["unit"]
        )

        markup.add(
            InlineKeyboardButton(
                f"🎁 {duration} — "
                f"{plan['cost']} {settings['coin_name']}",
                callback_data=(
                    f"redeem:{plan['plan_id']}:"
                    f"{channel_id}"
                )
            )
        )

    bot.send_message(
        chat_id,
        f"""🎁 *Redeem Premium*

📢 *Channel:* {channel['name']}
{settings['coin_emoji']} *Balance:* {get_coin_balance(user_id)} {settings['coin_name']}

Choose your Premium duration:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# BULK PREMIUM REDEEM SYSTEM
# =========================================================

def get_bulk_price_for_plan(plan_id):
    """Return the normal Premium plan price used as the bulk base price."""
    plan = premium_plans_col.find_one({"plan_id": plan_id})
    if plan and plan.get("cost") is not None:
        return int(plan["cost"])

    # Backward compatibility for installations that still use legacy bulk prices.
    settings = get_settings()
    prices = settings.get("bulk_redeem_prices", {}) or {}
    price = prices.get(str(plan_id))
    if price is not None:
        return int(price)
    legacy_price = settings.get("bulk_redeem_price")
    return int(legacy_price) if legacy_price is not None else None


def get_bulk_discount_rule(count):
    settings = get_settings()
    rules = settings.get("bulk_discount_rules", []) or []
    matches = [
        r for r in rules
        if int(r.get("min_channels", 0)) <= int(count)
        and float(r.get("discount_value", 0)) > 0
    ]
    return (
        sorted(matches, key=lambda r: int(r.get("min_channels", 0)), reverse=True)[0]
        if matches else None
    )


def calculate_bulk_total(single_price, count):
    single_price = max(0, int(single_price))
    count = max(0, int(count))
    original = single_price * count
    rule = get_bulk_discount_rule(count)
    discount = 0
    if rule:
        value = float(rule.get("discount_value", 0))
        if rule.get("discount_type") == "fixed":
            discount = int(value)
        else:
            discount = int(original * value / 100)
    discount = max(0, min(original, discount))
    return original, discount, original - discount, rule


@bot.callback_query_handler(
    func=lambda c: c.data == "bulk:start"
)
def bulk_redeem_start(call):

    if not feature_enabled("bulk_redeem"):
        bot.answer_callback_query(
            call.id,
            "Bulk Premium is currently disabled by Admin.",
            show_alert=True
        )
        return

    if is_banned(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            "Your account is restricted.",
            show_alert=True
        )
        return

    settings = get_settings()
    bulk_prices = settings.get("bulk_redeem_prices", {}) or {}
    legacy_price = settings.get("bulk_redeem_price")

    if not bulk_prices and legacy_price is None:
        bot.answer_callback_query(
            call.id,
            "Bulk redemption is not available right now.",
            show_alert=True
        )
        return

    channels = get_premium_channels()
    plans = list(
        premium_plans_col.find().sort(
            "duration_seconds",
            1
        )
    )

    if not channels or not plans:
        bot.answer_callback_query(
            call.id,
            "Premium channels or plans are not available.",
            show_alert=True
        )
        return

    markup = InlineKeyboardMarkup()

    for plan in plans:
        markup.add(
            InlineKeyboardButton(
                f"🎁 {format_duration(plan['amount'], plan['unit'])} — {get_bulk_price_for_plan(plan['plan_id']) if get_bulk_price_for_plan(plan['plan_id']) is not None else 'Not set'} {settings['coin_name'] if get_bulk_price_for_plan(plan['plan_id']) is not None else ''}",
                callback_data=f"bulkplan:{plan['plan_id']}"
            )
        )

    bot.send_message(
        call.message.chat.id,
        f"""📦 *Bulk Premium Redeem*

📢 You can select as many Premium channels as you want.
💡 Each duration has its own admin-set Bulk Redeem price, and that price stays the same regardless of the number of channels.

First, choose the Premium duration and price:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.answer_callback_query(call.id)


def show_bulk_channel_selector(chat_id, user_id, plan_id):
    plan = premium_plans_col.find_one({"plan_id": plan_id})
    channels = get_premium_channels()
    settings = get_settings()
    single_price = get_bulk_price_for_plan(plan_id)

    if not plan or not channels or single_price is None:
        bot.send_message(chat_id, "❌ This bulk redeem option is no longer available.")
        return

    state = bulk_redeem_selections.get(user_id)
    if not state or state.get("plan_id") != plan_id:
        state = {"plan_id": plan_id, "channel_ids": []}
        bulk_redeem_selections[user_id] = state

    selected = set(state.get("channel_ids", []))
    max_channels = int(settings.get("bulk_max_channels", 50))
    channels = channels[:max_channels]

    original, discount, final, rule = calculate_bulk_total(single_price, len(selected))
    markup = InlineKeyboardMarkup()

    for channel in channels:
        channel_id = channel["channel_id"]
        prefix = "✅" if channel_id in selected else "☐"
        markup.add(InlineKeyboardButton(
            f"{prefix} {channel['name']}",
            callback_data=f"bulktoggle:{plan_id}:{channel_id}"
        ))

    if selected:
        price_line = (
            f"💰 Before discount: *{original} {settings['coin_name']}*\n"
            f"🏷️ Discount: *-{discount} {settings['coin_name']}*\n"
            f"✅ Final cost: *{final} {settings['coin_name']}*"
        )
    else:
        price_line = "💰 Select channels to calculate your exact bulk price."

    markup.add(InlineKeyboardButton(
        f"🎉 Confirm ({final} {settings['coin_name']})",
        callback_data=f"bulkconfirm:{plan_id}"
    ))

    bot.send_message(
        chat_id,
        f"""📦 *Bulk Premium Purchase*

🎁 *Duration:* {format_duration(plan['amount'], plan['unit'])}
📌 *Selected:* {len(selected)} channel(s)
📏 *Maximum:* {max_channels} channel(s)

{price_line}

💡 Bulk price starts from the normal single-channel price and only the
admin-configured discount is applied. The more channels you select, the
system recalculates the exact total before you confirm.""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("bulkplan:")
)
def select_bulk_plan(call):

    plan_id = call.data.split(":", 1)[1]
    bulk_redeem_selections[call.from_user.id] = {
        "plan_id": plan_id,
        "channel_ids": []
    }

    show_bulk_channel_selector(
        call.message.chat.id,
        call.from_user.id,
        plan_id
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("bulktoggle:")
)
def toggle_bulk_channel(call):

    try:
        _, plan_id, channel_id = call.data.split(":", 2)
        channel_id = int(channel_id)
        user_id = call.from_user.id

        state = bulk_redeem_selections.get(user_id)
        if not state or state.get("plan_id") != plan_id:
            state = {"plan_id": plan_id, "channel_ids": []}
            bulk_redeem_selections[user_id] = state

        selected = state["channel_ids"]
        max_channels = int(get_settings().get("bulk_max_channels", 50))

        if channel_id in selected:
            selected.remove(channel_id)
        else:
            if len(selected) >= max_channels:
                bot.answer_callback_query(
                    call.id,
                    f"Maximum {max_channels} channels allowed.",
                    show_alert=True
                )
                return
            selected.append(channel_id)

        # Show an updated selector in a fresh message so the existing bot
        # structure remains unchanged and callback state stays simple.
        show_bulk_channel_selector(
            call.message.chat.id,
            user_id,
            plan_id
        )

        bot.answer_callback_query(call.id)

    except Exception as e:
        print(f"Bulk toggle error: {e}")
        bot.answer_callback_query(
            call.id,
            "❌ Unable to update your selection.",
            show_alert=True
        )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("bulkconfirm:")
)
def confirm_bulk_redeem(call):

    try:
        plan_id = call.data.split(":", 1)[1]
        user_id = call.from_user.id

        if is_banned(user_id):
            bot.answer_callback_query(
                call.id,
                "Your account is restricted.",
                show_alert=True
            )
            return

        state = bulk_redeem_selections.get(user_id, {})
        selected_ids = list(dict.fromkeys(state.get("channel_ids", [])))

        if state.get("plan_id") != plan_id or not selected_ids:
            bot.answer_callback_query(
                call.id,
                "❌ Please select at least one Premium channel first.",
                show_alert=True
            )
            return

        plan = premium_plans_col.find_one({"plan_id": plan_id})
        settings = get_settings()
        single_price = get_bulk_price_for_plan(plan_id)

        if not plan or single_price is None:
            bot.answer_callback_query(
                call.id,
                "This bulk option is no longer available.",
                show_alert=True
            )
            return

        single_price = int(single_price)
        original_price, discount_amount, bulk_price, discount_rule = calculate_bulk_total(
            single_price, len(selected_ids)
        )

        channels = list(
            premium_channels_col.find(
                {"channel_id": {"$in": selected_ids}}
            )
        )

        if len(channels) != len(selected_ids):
            bot.answer_callback_query(
                call.id,
                "❌ One or more selected channels are no longer available.",
                show_alert=True
            )
            return

        # Deduct the single fixed bulk price only once, no matter how many
        # channels were selected.
        result = bot_users_col.update_one(
            {
                "user_id": user_id,
                "coins": {"$gte": bulk_price},
                "banned": {"$ne": True}
            },
            {"$inc": {"coins": -bulk_price}}
        )

        if result.modified_count != 1:
            bot.answer_callback_query(
                call.id,
                "❌ You don't have enough coins for the bulk redemption!",
                show_alert=True
            )
            return

        expiry_datetime = datetime.now() + timedelta(
            seconds=int(plan["duration_seconds"])
        )
        created_links = []

        try:
            for channel in channels:
                link = bot.create_chat_invite_link(
                    channel["channel_id"],
                    member_limit=1,
                    expire_date=int(expiry_datetime.timestamp())
                )

                created_links.append((channel, link.invite_link))

                users_col.update_one(
                    {
                        "user_id": user_id,
                        "channel_id": channel["channel_id"]
                    },
                    {
                        "$set": {
                            "expiry": expiry_datetime.timestamp(),
                            "source": "bulk_coin_reward",
                            "plan_id": plan_id,
                            "duration": format_duration(
                                plan["amount"],
                                plan["unit"]
                            )
                        }
                    },
                    upsert=True
                )

        except Exception as e:
            # Refund the one fixed price if any channel cannot be completed.
            add_coins(user_id, bulk_price)

            # Best-effort cleanup of already-created one-time invite links.
            for channel, invite_link in created_links:
                try:
                    bot.revoke_chat_invite_link(
                        channel["channel_id"],
                        invite_link
                    )
                except Exception:
                    pass

            print(f"Bulk redeem error: {e}")
            bot.answer_callback_query(
                call.id,
                "❌ Something went wrong. Your coins were refunded.",
                show_alert=True
            )
            return

        log_purchase(user_id, "bulk_redeem", bulk_price, settings["coin_name"], {"plan_id": plan_id, "channels": len(created_links)})

        bulk_redeem_selections.pop(user_id, None)

        lines = [
            "🎉 *Bulk Premium Redeemed Successfully!*",
            "",
            f"🎁 *Duration:* {format_duration(plan['amount'], plan['unit'])}",
            f"📦 *Channels:* {len(created_links)}",
            f"💰 *Original:* {original_price} {settings['coin_name']}",
            f"🏷️ *Discount:* -{discount_amount} {settings['coin_name']}",
            f"💰 *Paid:* {bulk_price} {settings['coin_name']}",
            f"⏰ *Expires:* {format_bot_time(expiry_datetime)}",
            "",
            "🔗 *Join Your Premium Channels:*"
        ]

        for number, (channel, invite_link) in enumerate(created_links, 1):
            lines.extend([
                "",
                f"{number}. *{channel['name']}*",
                invite_link
            ])

        lines.extend([
            "",
            "⚠️ Each link can only be used once."
        ])

        bot.answer_callback_query(
            call.id,
            "Bulk Premium redeemed successfully!"
        )

        bot.send_message(
            user_id,
            "\n".join(lines),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    except Exception as e:
        print(f"Bulk redeem callback error: {e}")
        bot.answer_callback_query(
            call.id,
            "❌ Unable to complete bulk redemption.",
            show_alert=True
        )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("redeem:")
)
def redeem_premium(call):

    if not feature_enabled("single_redeem"):
        bot.answer_callback_query(
            call.id,
            "Single-channel Premium is currently disabled by Admin.",
            show_alert=True
        )
        return

    try:

        _, plan_id, channel_id = call.data.split(":")

        channel_id = int(channel_id)
        user_id = call.from_user.id

        if is_banned(user_id):
            bot.answer_callback_query(
                call.id,
                "Your account is restricted.",
                show_alert=True
            )
            return

        plan = premium_plans_col.find_one(
            {"plan_id": plan_id}
        )

        channel = premium_channels_col.find_one(
            {"channel_id": channel_id}
        )

        if not plan or not channel:
            bot.answer_callback_query(
                call.id,
                "This Premium option is no longer available.",
                show_alert=True
            )
            return

        cost = int(plan["cost"])

        # Atomic coin deduction
        result = bot_users_col.update_one(
            {
                "user_id": user_id,
                "coins": {"$gte": cost},
                "banned": {"$ne": True}
            },
            {
                "$inc": {"coins": -cost}
            }
        )

        if result.modified_count != 1:
            bot.answer_callback_query(
                call.id,
                "❌ You don't have enough coins!",
                show_alert=True
            )
            return

        expiry_datetime = (
            datetime.now()
            + timedelta(
                seconds=int(plan["duration_seconds"])
            )
        )

        try:
            link = bot.create_chat_invite_link(
                channel_id,
                member_limit=1,
                expire_date=int(
                    expiry_datetime.timestamp()
                )
            )

            # If old membership exists, replace expiry
            users_col.update_one(
                {
                    "user_id": user_id,
                    "channel_id": channel_id
                },
                {
                    "$set": {
                        "expiry": expiry_datetime.timestamp(),
                        "source": "coin_reward",
                        "plan_id": plan_id,
                        "duration": format_duration(
                            plan["amount"],
                            plan["unit"]
                        )
                    }
                },
                upsert=True
            )

            settings = get_settings()

            bot.answer_callback_query(
                call.id,
                "Premium redeemed successfully!"
            )

            bot.send_message(
                user_id,
                f"""🎉 *Premium Redeemed Successfully!*

🎁 *Duration:* {format_duration(plan['amount'], plan['unit'])}
📢 *Channel:* {channel['name']}
⏰ *Expires:* {format_bot_time(expiry_datetime)}

🔗 *Join Premium Channel:*
{link.invite_link}

⚠️ This link can only be used once.""",
                parse_mode="Markdown"
            )

        except Exception as e:

            add_coins(user_id, cost)

            print(f"Redeem error: {e}")

            bot.answer_callback_query(
                call.id,
                "❌ Something went wrong. Your coins were refunded.",
                show_alert=True
            )

    except Exception as e:
        print(f"Redeem callback error: {e}")


# =========================================================
# COUPON SYSTEM
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_coupon")
        and m.from_user.id != ADMIN_ID
    )
)
def claim_coupon_prompt(message):

    msg = bot.send_message(
        message.chat.id,
        "🎟️ Send the coupon code you want to claim."
    )

    bot.register_next_step_handler(
        msg,
        process_coupon
    )


def process_coupon(message):

    if not message.text:
        return

    code = message.text.strip().upper()
    user_id = message.from_user.id
    settings = get_settings()

    if is_banned(user_id):
        return

    coupon = coupons_col.find_one(
        {"code": code}
    )

    if not coupon:
        bot.send_message(
            message.chat.id,
            "❌ Invalid coupon code."
        )
        return

    if (
        coupon.get("expires_at")
        and coupon["expires_at"] < datetime.now()
    ):
        bot.send_message(
            message.chat.id,
            "⌛ This coupon has expired."
        )
        return

    already_used = coupon_uses_col.find_one({
        "coupon_code": code,
        "user_id": user_id
    })

    if already_used:
        bot.send_message(
            message.chat.id,
            "⚠️ You have already used this coupon."
        )
        return

    result = coupons_col.update_one(
        {
            "code": code,
            "used_count": {
                "$lt": coupon.get("max_uses", 1)
            }
        },
        {
            "$inc": {"used_count": 1}
        }
    )

    if result.modified_count != 1:
        bot.send_message(
            message.chat.id,
            "❌ This coupon is no longer available."
        )
        return

    coupon_uses_col.insert_one({
        "coupon_code": code,
        "user_id": user_id,
        "claimed_at": datetime.now()
    })

    coins = int(coupon["coins"])
    add_coins(user_id, coins)

    bot.send_message(
        message.chat.id,
        f"""🎉 *Coupon Claimed Successfully!*

{settings['coin_emoji']} You received *{coins} {settings['coin_name']}*!""",
        parse_mode="Markdown"
    )


# =========================================================
# LEADERBOARD
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and is_user_button(m, "btn_leaderboard")
        and m.from_user.id != ADMIN_ID
    )
)
def leaderboard(message):

    users = list(
        bot_users_col.find({
            "referral_count": {"$gt": 0},
            "banned": {"$ne": True}
        }).sort(
            "referral_count",
            DESCENDING
        ).limit(10)
    )

    if not users:
        bot.send_message(
            message.chat.id,
            "🏆 No successful referrals yet."
        )
        return

    text = "🏆 *Referral Leaderboard*\n\n"

    for position, user in enumerate(users, 1):
        text += (
            f"{position}. "
            f"{user.get('first_name', 'User')} — "
            f"*{user.get('referral_count', 0)} referrals*\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN ACCESS HELPER
# =========================================================

def admin_only(call_or_message):
    return (
        call_or_message.from_user.id == ADMIN_ID
    )


@bot.message_handler(commands=["admin"])
def admin_command(message):

    if message.from_user.id != ADMIN_ID:
        return

    register_user(message.from_user)
    switch_to_admin_mode()
    show_admin_panel(message.chat.id)


@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_PANEL_BUTTON
    )
)
def admin_panel_shortcut(message):
    """Open the admin panel directly from the normal user keyboard."""
    switch_to_admin_mode()
    show_admin_panel(message.chat.id)


# =========================================================
# ADMIN MODE SWITCH
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_MODE
    )
)
def admin_to_user_mode(message):

    switch_to_user_mode()

    bot.send_message(
        ADMIN_ID,
        "🔄 *User Mode Activated*\n\nYou can now see and use the normal user keyboard.",
        reply_markup=user_menu_markup(ADMIN_ID),
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN PANEL BUTTON HANDLERS
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_CHANNELS
    )
)
def admin_channels_menu(message):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Add Paid Channel",
            callback_data="admin:add_paid_channel"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📋 Manage Paid Channels",
            callback_data="admin:list_paid_channels"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "📢 *Channel Management*\n\nChoose an option:",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_PREMIUM
    )
)
def admin_premium_menu(message):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Add Redeem Plan",
            callback_data="premium:add_plan"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📋 Manage Redeem Plans",
            callback_data="premium:manage_plans"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "➕ Add Premium Channel",
            callback_data="premium:add_channel"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📢 Manage Premium Channels",
            callback_data="premium:manage_channels"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📦 Set Bulk Redeem Prices (By Duration)",
            callback_data="premium:set_bulk_price"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "🎁 *Premium Management*\n\n"
        "Manage Premium durations and channels using the buttons below.",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_MILESTONES
    )
)
def admin_milestone_menu(message):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Add Milestone",
            callback_data="milestone:add"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📋 Manage Milestones",
            callback_data="milestone:manage"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📢 Set Milestone Log Channel",
            callback_data="milestone:set_log"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "🎯 *Milestone Management*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_VERIFICATION
    )
)
def admin_verification_menu(message):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Add Required Channel",
            callback_data="verify:add"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🗑️ Remove Required Channel",
            callback_data="verify:manage"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "📣 *Referral Verification Channels*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_USERS
    )
)
def admin_users_menu(message):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📊 Bot Statistics",
            callback_data="users:stats"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📢 Broadcast Message",
            callback_data="users:broadcast"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📋 Recent Users",
            callback_data="users:recent"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📢 Set User Start Log Channel",
            callback_data="users:set_log"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🚫 Ban / Unban User",
            callback_data="users:banmenu"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "👥 *User Management*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_COUPONS
    )
)
def admin_coupons_menu(message):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Create Coupon",
            callback_data="coupon:create"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🟢 Active Coupons",
            callback_data="coupon:active"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "⌛ Expired Coupons",
            callback_data="coupon:expired"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "🎟️ *Coupon Management*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: (
        m.from_user.id == ADMIN_ID
        and m.text == ADMIN_SETTINGS
    )
)
def admin_settings_menu(message):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🪙 Coin & Referral Settings",
            callback_data="settings:coins"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "✏️ Edit Bot Texts",
            callback_data="settings:texts"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔘 Edit User Buttons",
            callback_data="settings:buttons"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🕒 Bot Time Zone",
            callback_data="settings:timezone"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "💬 View Feedback",
            callback_data="settings:feedback"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "⚙️ *Settings*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN CALLBACK - PAID CHANNELS
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "admin:add_paid_channel"
)
def add_paid_channel_callback(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward any message from the channel you want to add.\n\n"
        "Make sure the bot is an administrator there."
    )

    bot.register_next_step_handler(
        msg,
        get_plans
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data == "admin:list_paid_channels"
)
def list_paid_channels_callback(call):

    if not admin_only(call):
        return

    markup = InlineKeyboardMarkup()
    cursor = channels_col.find({"admin_id": ADMIN_ID})

    count = 0

    for ch in cursor:
        markup.add(
            InlineKeyboardButton(
                f"📢 {ch['name']}",
                callback_data=(
                    f"manage_{ch['channel_id']}"
                )
            )
        )
        count += 1

    bot.send_message(
        ADMIN_ID,
        "Your Managed Channels:" if count else "No channels found.",
        reply_markup=markup
    )

    bot.answer_callback_query(call.id)


# OLD /channels COMMAND STILL WORKS
@bot.message_handler(
    commands=["channels"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_channels(message):

    admin_channels_menu(message)


# OLD ADD SYSTEM
def get_plans(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Message was not forwarded. Please try again."
        )
        return

    ch_id = message.forward_from_chat.id
    ch_name = message.forward_from_chat.title

    msg = bot.send_message(
        ADMIN_ID,
        f"""✅ Channel Detected: {ch_name}

Enter plans in this format:

`1440:99,43200:199`

1440 = 1 Day
43200 = 30 Days""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        finalize_channel,
        ch_id,
        ch_name
    )


def finalize_channel(message, ch_id, ch_name):

    try:
        raw_plans = message.text.split(",")
        plans_dict = {}

        for plan in raw_plans:
            duration, price = plan.strip().split(":")
            plans_dict[duration.strip()] = price.strip()

        channels_col.update_one(
            {"channel_id": ch_id},
            {
                "$set": {
                    "name": ch_name,
                    "plans": plans_dict,
                    "admin_id": ADMIN_ID
                }
            },
            upsert=True
        )

        bot_username = bot.get_me().username

        bot.send_message(
            ADMIN_ID,
            f"""✅ Setup Successful!

Invite Link:
`https://t.me/{bot_username}?start={ch_id}`""",
            parse_mode="Markdown"
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format. Please try again."
        )


# =========================================================
# PREMIUM ADMIN - FLEXIBLE PLANS
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "premium:add_plan"
)
def premium_add_plan(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        """➕ *Add Premium Redeem Plan*

First, send the duration amount only.

Examples:
`1`
`12`
`67`
`30`

You will choose Minutes, Hours, Days, Months or Years using buttons next.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        premium_get_amount
    )

    bot.answer_callback_query(call.id)


def premium_get_amount(message):

    try:
        amount = int(message.text.strip())

        if amount <= 0:
            raise ValueError

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Please send a valid positive number."
        )
        return

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            "⏱️ Minutes",
            callback_data=f"punit:minute:{amount}"
        ),
        InlineKeyboardButton(
            "🕐 Hours",
            callback_data=f"punit:hour:{amount}"
        ),
        InlineKeyboardButton(
            "📅 Days",
            callback_data=f"punit:day:{amount}"
        ),
        InlineKeyboardButton(
            "🗓️ Months",
            callback_data=f"punit:month:{amount}"
        ),
        InlineKeyboardButton(
            "📆 Years",
            callback_data=f"punit:year:{amount}"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "Choose the duration unit:",
        reply_markup=markup
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("punit:")
)
def premium_choose_unit(call):

    if not admin_only(call):
        return

    _, unit, amount = call.data.split(":")

    amount = int(amount)

    msg = bot.send_message(
        ADMIN_ID,
        f"""🎁 *{format_duration(amount, unit)}*

Now send the *coin cost* for this Premium plan.

Example: `500`""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        premium_get_cost,
        amount,
        unit
    )

    bot.answer_callback_query(call.id)


def premium_get_cost(message, amount, unit):

    try:
        cost = int(message.text.strip())

        if cost < 0:
            raise ValueError

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Please send a valid coin amount."
        )
        return

    plan_id = uuid.uuid4().hex[:10]

    premium_plans_col.insert_one({
        "plan_id": plan_id,
        "amount": amount,
        "unit": unit,
        "duration_seconds": duration_seconds(
            amount,
            unit
        ),
        "cost": cost,
        "created_at": datetime.now()
    })

    bot.send_message(
        ADMIN_ID,
        f"""✅ *Premium Plan Added!*

🎁 Duration: *{format_duration(amount, unit)}*
🪙 Cost: *{cost} {get_settings()['coin_name']}*""",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "premium:manage_plans"
)
def manage_premium_plans(call):

    if not admin_only(call):
        return

    plans = list(
        premium_plans_col.find().sort(
            "duration_seconds",
            1
        )
    )

    if not plans:
        bot.send_message(
            ADMIN_ID,
            "No Premium plans found."
        )
        return

    markup = InlineKeyboardMarkup()

    for plan in plans:

        markup.add(
            InlineKeyboardButton(
                f"🗑️ Remove {format_duration(plan['amount'], plan['unit'])} "
                f"— {plan['cost']} KP",
                callback_data=(
                    f"pdelete:{plan['plan_id']}"
                )
            )
        )

    bot.send_message(
        ADMIN_ID,
        "🎁 *Premium Redeem Plans*\n\n"
        "Press a plan below to remove it.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("pdelete:")
)
def delete_premium_plan(call):

    if not admin_only(call):
        return

    plan_id = call.data.split(":")[1]

    premium_plans_col.delete_one(
        {"plan_id": plan_id}
    )

    bot.answer_callback_query(
        call.id,
        "Premium plan removed."
    )

    try:
        bot.edit_message_text(
            "✅ Premium plan removed. Open Premium again to manage the updated list.",
            call.message.chat.id,
            call.message.message_id
        )
    except Exception:
        pass


# =========================================================
# BULK REDEEM PRICE SETTINGS (SEPARATE PRICE PER DURATION)
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "premium:set_bulk_price"
)
def set_bulk_redeem_price(call):

    if not admin_only(call):
        return

    plans = list(premium_plans_col.find().sort("duration_seconds", 1))
    if not plans:
        bot.answer_callback_query(call.id, "Create a Premium duration first.", show_alert=True)
        return

    markup = InlineKeyboardMarkup()
    for plan in plans:
        price = get_bulk_price_for_plan(plan["plan_id"])
        price_text = f"{price} {get_settings()['coin_name']}" if price is not None else "Not set"
        markup.add(
            InlineKeyboardButton(
                f"🎁 {format_duration(plan['amount'], plan['unit'])} — {price_text}",
                callback_data=f"bulkprice:{plan['plan_id']}"
            )
        )

    bot.send_message(
        ADMIN_ID,
        "📦 *Bulk Redeem Prices by Duration*\n\n"
        "Select a duration and set its fixed Bulk Redeem price. "
        "Users can select any number of channels, but pay that duration's price only once.",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("bulkprice:")
)
def select_bulk_price_duration(call):

    if not admin_only(call):
        return

    plan_id = call.data.split(":", 1)[1]
    plan = premium_plans_col.find_one({"plan_id": plan_id})
    if not plan:
        bot.answer_callback_query(call.id, "Plan not found.", show_alert=True)
        return

    current_price = get_bulk_price_for_plan(plan_id)
    current_text = (
        f"{current_price} {get_settings()['coin_name']}"
        if current_price is not None else "Not set"
    )

    msg = bot.send_message(
        ADMIN_ID,
        f"🎁 *{format_duration(plan['amount'], plan['unit'])}*\n\n"
        f"Current Bulk Price: *{current_text}*\n\n"
        "Send the fixed coin price for this duration.\n"
        "This price will be charged only once, no matter how many channels the user selects.\n\n"
        "Example: `500`",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, save_bulk_redeem_price, plan_id)
    bot.answer_callback_query(call.id)


def save_bulk_redeem_price(message, plan_id):

    if message.from_user.id != ADMIN_ID:
        return

    try:
        price = int(message.text.strip())
        if price < 0:
            raise ValueError
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Please send a valid coin amount (0 or more).")
        return

    settings = get_settings()
    prices = settings.get("bulk_redeem_prices", {}) or {}
    prices[str(plan_id)] = price
    update_setting("bulk_redeem_prices", prices)

    plan = premium_plans_col.find_one({"plan_id": plan_id})
    duration = format_duration(plan["amount"], plan["unit"]) if plan else "Selected duration"
    bot.send_message(
        ADMIN_ID,
        f"✅ *Bulk Redeem Price Updated!*\n\n"
        f"🎁 Duration: *{duration}*\n"
        f"💰 Fixed Price: *{price} {get_settings()['coin_name']}*\n\n"
        "Users selecting this duration can choose any number of Premium channels and will pay this price only once.",
        parse_mode="Markdown"
    )


# =========================================================
# PREMIUM CHANNEL MANAGEMENT
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "premium:add_channel"
)
def add_premium_channel(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward any message from the Premium channel.\n\n"
        "The bot must be an administrator in that channel."
    )

    bot.register_next_step_handler(
        msg,
        save_premium_channel
    )

    bot.answer_callback_query(call.id)


def save_premium_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from a channel."
        )
        return

    chat = message.forward_from_chat

    premium_channels_col.update_one(
        {"channel_id": chat.id},
        {
            "$set": {
                "channel_id": chat.id,
                "name": chat.title or "Premium Channel",
                "added_at": datetime.now()
            }
        },
        upsert=True
    )

    # Keep legacy setting updated too
    update_setting("reward_channel_id", chat.id)
    update_setting(
        "reward_channel_name",
        chat.title or "Premium Channel"
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Premium reward channel added: *{chat.title}*",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "premium:manage_channels"
)
def manage_premium_channels(call):

    if not admin_only(call):
        return

    channels = get_premium_channels()

    if not channels:
        bot.send_message(
            ADMIN_ID,
            "No Premium reward channels found."
        )
        return

    markup = InlineKeyboardMarkup()

    for channel in channels:
        markup.add(
            InlineKeyboardButton(
                f"🗑️ Remove {channel['name']}",
                callback_data=(
                    f"pcdelete:{channel['channel_id']}"
                )
            )
        )

    bot.send_message(
        ADMIN_ID,
        "📢 *Premium Reward Channels*",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("pcdelete:")
)
def delete_premium_channel(call):

    if not admin_only(call):
        return

    channel_id = int(
        call.data.split(":")[1]
    )

    premium_channels_col.delete_one(
        {"channel_id": channel_id}
    )

    bot.answer_callback_query(
        call.id,
        "Premium channel removed."
    )

    try:
        bot.edit_message_text(
            "✅ Premium channel removed.",
            call.message.chat.id,
            call.message.message_id
        )
    except Exception:
        pass


# =========================================================
# MILESTONE ADMIN
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "milestone:add"
)
def add_milestone(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        """🎯 *Add Referral Milestone*

Send the referral target.

Example:
`10`

This means the user must successfully refer 10 people.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        milestone_get_target
    )

    bot.answer_callback_query(call.id)


def milestone_get_target(message):

    try:
        target = int(message.text.strip())

        if target <= 0:
            raise ValueError

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Send a valid positive referral target."
        )
        return

    msg = bot.send_message(
        ADMIN_ID,
        f"🎯 Target: *{target} referrals*\n\n"
        "Now send the coin reward.",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        milestone_get_reward,
        target
    )


def milestone_get_reward(message, target):

    try:
        reward = int(message.text.strip())

        if reward < 0:
            raise ValueError

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Send a valid reward amount."
        )
        return

    milestones_col.update_one(
        {"target": target},
        {
            "$set": {
                "target": target,
                "reward": reward,
                "updated_at": datetime.now()
            },
            "$setOnInsert": {
                "created_at": datetime.now()
            }
        },
        upsert=True
    )

    bot.send_message(
        ADMIN_ID,
        f"""✅ *Milestone Saved!*

🎯 {target} Referrals
🌽 Reward: {reward} {get_settings()['coin_name']}""",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "milestone:manage"
)
def manage_milestones(call):

    if not admin_only(call):
        return

    milestones = list(
        milestones_col.find().sort(
            "target",
            1
        )
    )

    if not milestones:
        bot.send_message(
            ADMIN_ID,
            "No milestones added yet."
        )
        return

    markup = InlineKeyboardMarkup()

    for milestone in milestones:
        markup.add(
            InlineKeyboardButton(
                f"🗑️ {milestone['target']} Referrals "
                f"— {milestone['reward']} KP",
                callback_data=(
                    f"mdelete:{str(milestone['_id'])}"
                )
            )
        )

    bot.send_message(
        ADMIN_ID,
        "🎯 *Manage Milestones*\n\nPress a milestone to remove it.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("mdelete:")
)
def delete_milestone(call):

    if not admin_only(call):
        return

    from bson import ObjectId

    try:
        milestone_id = ObjectId(
            call.data.split(":")[1]
        )

        milestones_col.delete_one(
            {"_id": milestone_id}
        )

        bot.answer_callback_query(
            call.id,
            "Milestone removed."
        )

    except Exception:
        bot.answer_callback_query(
            call.id,
            "Unable to remove milestone."
        )


@bot.callback_query_handler(
    func=lambda c: c.data == "milestone:set_log"
)
def set_milestone_log(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward a message from the channel where milestone completions should be logged."
    )

    bot.register_next_step_handler(
        msg,
        save_milestone_log_channel
    )

    bot.answer_callback_query(call.id)


def save_milestone_log_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a channel message."
        )
        return

    chat = message.forward_from_chat

    update_setting(
        "milestone_log_channel_id",
        chat.id
    )

    update_setting(
        "milestone_log_channel_name",
        chat.title
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Milestone log channel set to *{chat.title}*.",
        parse_mode="Markdown"
    )


# =========================================================
# VERIFICATION CHANNEL ADMIN
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "verify:add"
)
def force_add_callback(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward a message from the channel/group users must join.\n\n"
        "Make sure the bot is an administrator there."
    )

    bot.register_next_step_handler(
        msg,
        save_force_channel
    )

    bot.answer_callback_query(call.id)


def save_force_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from a channel/group."
        )
        return

    chat = message.forward_from_chat
    channel_id = chat.id
    name = chat.title or "Required Channel"

    if chat.username:
        join_url = f"https://t.me/{chat.username}"
    else:
        try:
            invite = bot.create_chat_invite_link(
                channel_id
            )
            join_url = invite.invite_link
        except Exception:
            bot.send_message(
                ADMIN_ID,
                "❌ Could not create a join link. Make the bot an admin."
            )
            return

    force_channels_col.update_one(
        {"channel_id": channel_id},
        {
            "$set": {
                "channel_id": channel_id,
                "name": name,
                "join_url": join_url,
                "added_at": datetime.now()
            }
        },
        upsert=True
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Required channel added: *{name}*",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "verify:manage"
)
def force_list_callback(call):

    if not admin_only(call):
        return

    channels = list(
        force_channels_col.find()
    )

    if not channels:
        bot.send_message(
            ADMIN_ID,
            "No required channels configured."
        )
        return

    markup = InlineKeyboardMarkup()

    for channel in channels:
        markup.add(
            InlineKeyboardButton(
                f"🗑 Remove {channel['name']}",
                callback_data=(
                    f"force_remove_{channel['channel_id']}"
                )
            )
        )

    bot.send_message(
        ADMIN_ID,
        "📢 *Required Verification Channels*",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("force_remove_")
)
def remove_force_channel(call):

    if not admin_only(call):
        return

    try:
        channel_id = int(
            call.data.replace(
                "force_remove_",
                ""
            )
        )

        force_channels_col.delete_one(
            {"channel_id": channel_id}
        )

        bot.answer_callback_query(
            call.id,
            "Channel removed!"
        )

    except Exception:
        pass


# =========================================================
# USER ADMIN FEATURES
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "users:stats"
)
def admin_stats_callback(call):

    if not admin_only(call):
        return

    send_bot_stats()
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data == "users:recent"
)
def recent_users(call):

    if not admin_only(call):
        return

    try:
        users = list(
            bot_users_col.find().sort(
                [("joined_at", DESCENDING), ("_id", DESCENDING)]
            ).limit(30)
        )

        if not users:
            bot.answer_callback_query(call.id)
            bot.send_message(ADMIN_ID, "No users found.")
            return

        lines = ["👥 Recent Users", ""]

        for number, user in enumerate(users, 1):
            name = user.get("first_name") or "User"
            username = user.get("username")
            user_id = user.get("user_id", "Unknown")
            joined = format_bot_time(user.get("joined_at"))

            display = name
            if username:
                display += f" (@{username})"

            lines.append(f"{number}. {display}")
            lines.append(f"🆔 {user_id}")
            lines.append(f"📅 Joined: {joined}")
            lines.append("")

        # Plain text avoids Telegram Markdown errors caused by user names.
        bot.answer_callback_query(call.id)
        bot.send_message(
            ADMIN_ID,
            "\n".join(lines)
        )

    except Exception as e:
        print(f"Recent users error: {e}")
        bot.answer_callback_query(
            call.id,
            "❌ Unable to load recent users.",
            show_alert=True
        )


@bot.callback_query_handler(
    func=lambda c: c.data == "users:set_log"
)
def set_user_log(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward a message from the channel where new users should be logged."
    )

    bot.register_next_step_handler(
        msg,
        save_user_log_channel
    )

    bot.answer_callback_query(call.id)


def save_user_log_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a channel message."
        )
        return

    chat = message.forward_from_chat

    update_setting(
        "start_log_channel_id",
        chat.id
    )

    update_setting(
        "start_log_channel_name",
        chat.title
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ User start log channel set to *{chat.title}*.",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "users:broadcast"
)
def broadcast_callback(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Send the message you want to broadcast to all users."
    )

    bot.register_next_step_handler(
        msg,
        broadcast_message
    )

    bot.answer_callback_query(call.id)


def broadcast_message(message):

    users = bot_users_col.find(
        {"banned": {"$ne": True}},
        {"user_id": 1}
    )

    success = 0
    failed = 0

    bot.send_message(
        ADMIN_ID,
        "📢 Broadcasting started..."
    )

    for user in users:
        try:
            bot.copy_message(
                user["user_id"],
                message.chat.id,
                message.message_id
            )
            success += 1
            time.sleep(0.05)
        except Exception:
            failed += 1

    bot.send_message(
        ADMIN_ID,
        f"""📢 *Broadcast Complete*

✅ Sent: *{success}*
❌ Failed: *{failed}*""",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "users:banmenu"
)
def ban_menu(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        "Send the User ID in this format:\n\n"
        "`ban USER_ID`\n"
        "or\n"
        "`unban USER_ID`\n"
        "or\n"
        "`info USER_ID`",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        process_user_management
    )

    bot.answer_callback_query(call.id)


def process_user_management(message):

    try:
        parts = message.text.split()
        action = parts[0].lower()
        user_id = int(parts[1])

        if user_id == ADMIN_ID:
            bot.send_message(
                ADMIN_ID,
                "❌ You cannot ban the admin."
            )
            return

        if action == "ban":

            bot_users_col.update_one(
                {"user_id": user_id},
                {"$set": {"banned": True}}
            )

            bot.send_message(
                ADMIN_ID,
                f"🚫 User `{user_id}` banned.",
                parse_mode="Markdown"
            )

        elif action == "unban":

            bot_users_col.update_one(
                {"user_id": user_id},
                {"$set": {"banned": False}}
            )

            bot.send_message(
                ADMIN_ID,
                f"✅ User `{user_id}` unbanned.",
                parse_mode="Markdown"
            )

        elif action == "info":

            user = get_user(user_id)

            if not user:
                bot.send_message(
                    ADMIN_ID,
                    "❌ User not found."
                )
                return

            bot.send_message(
                ADMIN_ID,
                f"""👤 *User Information*

Name: {user.get('first_name', 'Unknown')}
Username: @{user.get('username') or 'Not set'}
ID: `{user_id}`

🪙 Coins: {user.get('coins', 0)}
👥 Referrals: {user.get('referral_count', 0)}
🚫 Banned: {user.get('banned', False)}""",
                parse_mode="Markdown"
            )

        else:
            raise ValueError

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


# =========================================================
# COUPON ADMIN
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "coupon:create"
)
def create_coupon_callback(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        """🎟️ *Create Coupon*

Send details in this format:

`CODE COINS MAX_USERS HOURS`

Example:
`WELCOME100 100 50 24`""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        create_coupon_from_text
    )

    bot.answer_callback_query(call.id)


def create_coupon_from_text(message):

    try:
        parts = message.text.split()

        code = parts[0].upper()
        coins = int(parts[1])
        max_users = int(parts[2])
        hours = int(parts[3])

        coupons_col.update_one(
            {"code": code},
            {
                "$set": {
                    "code": code,
                    "coins": coins,
                    "max_uses": max_users,
                    "used_count": 0,
                    "expires_at": (
                        datetime.now()
                        + timedelta(hours=hours)
                    ),
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Coupon `{code}` created successfully.",
            parse_mode="Markdown"
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


@bot.callback_query_handler(
    func=lambda c: c.data in ("coupon:list", "coupon:active", "coupon:expired")
)
def list_coupons_callback(call):

    if not admin_only(call):
        return

    now = datetime.now()

    if call.data == "coupon:expired":
        query = {"expires_at": {"$lte": now}}
        title = "⌛ *Expired Coupons*"
    else:
        # Legacy coupons without an expiry date are treated as active.
        query = {
            "$or": [
                {"expires_at": {"$gt": now}},
                {"expires_at": {"$exists": False}},
                {"expires_at": None}
            ]
        }
        title = "🟢 *Active Coupons*"

    coupons = list(
        coupons_col.find(query).sort(
            "created_at",
            DESCENDING
        ).limit(20)
    )

    if not coupons:
        bot.answer_callback_query(call.id)
        bot.send_message(
            ADMIN_ID,
            "No active coupons found." if call.data != "coupon:expired" else "No expired coupons found."
        )
        return

    text = title + "\n\n"
    markup = InlineKeyboardMarkup()

    for coupon in coupons:
        code = coupon.get("code", "UNKNOWN")
        used_count = coupon.get("used_count", 0)
        max_uses = coupon.get("max_uses", 0)
        expires_at = coupon.get("expires_at")

        text += (
            f"🎟️ `{code}` — {coupon.get('coins', 0)} coins\n"
            f"Uses: {used_count}/{max_uses}\n"
        )

        if expires_at:
            text += f"Expires: {format_bot_time(expires_at)}\n"

        text += "\n"

        markup.add(
            InlineKeyboardButton(
                f"🗑️ Delete {code}",
                callback_data=f"coupon:delete:{str(coupon['_id'])}"
            )
        )

    bot.answer_callback_query(call.id)
    bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("coupon:delete:")
)
def delete_coupon_callback(call):

    if not admin_only(call):
        return

    try:
        from bson import ObjectId

        coupon_id = ObjectId(call.data.split(":", 2)[2])
        coupon = coupons_col.find_one_and_delete({"_id": coupon_id})

        if not coupon:
            bot.answer_callback_query(
                call.id,
                "Coupon was already removed.",
                show_alert=True
            )
            return

        # Remove claim history as well so the database stays clean.
        coupon_uses_col.delete_many({
            "coupon_code": coupon.get("code")
        })

        bot.answer_callback_query(
            call.id,
            "Coupon deleted successfully."
        )

        try:
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass

        bot.send_message(
            ADMIN_ID,
            f"🗑️ Coupon `{coupon.get('code', 'UNKNOWN')}` deleted.",
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Coupon delete error: {e}")
        bot.answer_callback_query(
            call.id,
            "❌ Unable to delete this coupon.",
            show_alert=True
        )


# =========================================================
# TIMEZONE SETTINGS
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "settings:timezone"
)
def timezone_settings(call):

    if not admin_only(call):
        return

    current_timezone = get_settings().get(
        "timezone",
        "Asia/Kathmandu"
    )

    msg = bot.send_message(
        ADMIN_ID,
        "🕒 *Bot Time Zone*\n\n"
        f"Current: `{current_timezone}`\n\n"
        "Send an IANA timezone name.\n\n"
        "Examples:\n"
        "`Asia/Kathmandu` (Nepal)\n"
        "`Asia/Kolkata` (India)\n"
        "`Asia/Dubai`\n"
        "`Europe/London`\n"
        "`America/New_York`",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        process_timezone_setting
    )

    bot.answer_callback_query(call.id)


def process_timezone_setting(message):

    try:
        timezone_name = message.text.strip()
        ZoneInfo(timezone_name)

        update_setting("timezone", timezone_name)

        bot.send_message(
            ADMIN_ID,
            "✅ Time zone updated successfully.\n\n"
            f"🕒 New time zone: `{timezone_name}`\n"
            f"📅 Current bot time: {bot_time_now().strftime('%d %b %Y, %H:%M')}",
            parse_mode="Markdown"
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid timezone name.\n\n"
            "Example: `Asia/Kathmandu`",
            parse_mode="Markdown"
        )


# =========================================================
# SETTINGS ADMIN
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "settings:coins"
)
def coin_settings(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        """🪙 *Coin & Referral Settings*

Send one of these:

`coin NAME`
`emoji EMOJI`
`referral AMOUNT`

Examples:
`coin KP`
`emoji 🌽`
`referral 10`""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        process_coin_settings
    )

    bot.answer_callback_query(call.id)


def process_coin_settings(message):

    try:
        parts = message.text.split(
            maxsplit=1
        )

        action = parts[0].lower()
        value = parts[1].strip()

        if action == "coin":
            update_setting("coin_name", value)

        elif action == "emoji":
            update_setting("coin_emoji", value)

        elif action == "referral":
            update_setting(
                "referral_reward",
                int(value)
            )

        else:
            raise ValueError

        bot.send_message(
            ADMIN_ID,
            "✅ Setting updated successfully."
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid setting format."
        )


@bot.callback_query_handler(
    func=lambda c: c.data == "settings:texts"
)
def edit_texts_menu(call):

    if not admin_only(call):
        return

    bot.send_message(
        ADMIN_ID,
        """✏️ *Editable Texts*

Send:

`welcome Your text`
`forcejoin Your text`
`verified Your text`
`how Your text`
`feedback Your text`

Example:
`welcome Welcome to my bot!`""",
        parse_mode="Markdown"
    )

    msg = bot.send_message(
        ADMIN_ID,
        "👇 Send the text setting you want to update."
    )

    bot.register_next_step_handler(
        msg,
        process_edit_text
    )

    bot.answer_callback_query(call.id)


def process_edit_text(message):

    mapping = {
        "welcome": "welcome_text",
        "forcejoin": "force_join_text",
        "verified": "verification_success_text",
        "how": "how_it_works_text",
        "feedback": "feedback_text"
    }

    try:
        key, text = message.text.split(
            maxsplit=1
        )

        key = key.lower()

        if key not in mapping:
            raise ValueError

        update_setting(
            mapping[key],
            text
        )

        bot.send_message(
            ADMIN_ID,
            "✅ Text updated successfully."
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid text format."
        )


@bot.callback_query_handler(
    func=lambda c: c.data == "settings:buttons"
)
def edit_buttons_menu(call):

    if not admin_only(call):
        return

    msg = bot.send_message(
        ADMIN_ID,
        """🔘 *Edit User Button*

Send:

`profile New Name`
`refer New Name`
`redeem New Name`
`coupon New Name`
`referrals New Name`
`milestones New Name`
`leaderboard New Name`
`how New Name`
`feedback New Name`
`contact New Name`

Example:
`profile 👤 My Account`""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        process_edit_button
    )

    bot.answer_callback_query(call.id)


def process_edit_button(message):

    mapping = {
        "profile": "btn_profile",
        "refer": "btn_refer",
        "redeem": "btn_redeem",
        "coupon": "btn_coupon",
        "referrals": "btn_referrals",
        "milestones": "btn_milestones",
        "leaderboard": "btn_leaderboard",
        "how": "btn_how",
        "feedback": "btn_feedback",
        "contact": "btn_contact"
    }

    try:
        key, name = message.text.split(
            maxsplit=1
        )

        key = key.lower()

        if key not in mapping:
            raise ValueError

        update_setting(
            mapping[key],
            name
        )

        bot.send_message(
            ADMIN_ID,
            "✅ Button name updated."
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid button format."
        )


@bot.callback_query_handler(
    func=lambda c: c.data == "settings:feedback"
)
def admin_feedbacks_callback(call):

    if not admin_only(call):
        return

    feedbacks = list(
        feedback_col.find().sort(
            "created_at",
            DESCENDING
        ).limit(10)
    )

    if not feedbacks:
        bot.send_message(
            ADMIN_ID,
            "💬 No feedback yet."
        )
        return

    text = "💬 *Recent Feedback*\n\n"

    for item in feedbacks:
        text += (
            f"👤 {item.get('name', 'User')}\n"
            f"📝 {item.get('text', '')[:300]}\n"
            "━━━━━━━━━━━━\n"
        )

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )

    bot.answer_callback_query(call.id)


# =========================================================
# OLD PAID PAYMENT SYSTEM - KEPT
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("select_")
)
def user_pays(call):

    try:
        _, ch_id, mins = call.data.split("_")

        ch_data = channels_col.find_one(
            {"channel_id": int(ch_id)}
        )

        if not ch_data:
            bot.answer_callback_query(
                call.id,
                "Channel not found."
            )
            return

        price = float(
            ch_data["plans"][mins]
        )

        usd_price = price / 100
        inr_price = price / 2
        minutes = int(mins)

        if minutes > 525600:
            plan_name = "💎 Lifetime"
        elif minutes >= 1440:
            plan_name = (
                f"📅 {minutes // 1440} Days"
            )
        else:
            plan_name = (
                f"⏱ {minutes} Min"
            )

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "✅ I Have Paid",
                callback_data=(
                    f"paid_{ch_id}_{mins}"
                )
            )
        )

        if CONTACT_USERNAME:
            markup.add(
                InlineKeyboardButton(
                    "📞 Contact Admin",
                    url=f"https://t.me/{CONTACT_USERNAME}"
                )
            )

        qr_url = (
            "https://i.ibb.co/v4yw96tb/"
            "IMG-20260712-103503.jpg"
        )

        bot.send_photo(
            call.message.chat.id,
            qr_url,
            caption=(
                f"📢 *{ch_data['name']}*\n\n"
                f"💎 *Plan:* {plan_name}\n\n"
                f"💰 *Price*\n"
                f"🇳🇵 NPR: {price:.0f}\n"
                f"🇺🇸 USD: ${usd_price:.2f}\n"
                f"🇮🇳 INR: ₹{inr_price:.2f}\n\n"
                "━━━━━━━━━━━━━━\n"
                "⚠️ *This QR is for Nepali users only.*\n\n"
                f"*Binance ID:*\n`{UPI_ID}`\n\n"
                "📋 After payment, tap *I Have Paid* "
                "and send your screenshot."
            ),
            reply_markup=markup,
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Payment selection error: {e}")


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("paid_")
)
def payment_screenshot_request(call):

    _, ch_id, mins = call.data.split("_")
    user_id = call.from_user.id

    if user_id in pending_payments:
        bot.answer_callback_query(
            call.id,
            "⚠️ You already have a pending payment.",
            show_alert=True
        )
        return

    ch_data = channels_col.find_one(
        {"channel_id": int(ch_id)}
    )

    if not ch_data:
        return

    pending_payments[user_id] = {
        "channel_id": int(ch_id),
        "channel_name": ch_data["name"],
        "plan": mins,
        "price": ch_data["plans"][mins],
        "time": datetime.now()
    }

    bot.answer_callback_query(call.id)

    bot.send_message(
        user_id,
        "📷 *Upload Payment Screenshot*\n\n"
        "Please send your payment screenshot as a *PHOTO*.",
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=["text"]
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "📷 Please upload your payment screenshot as a PHOTO."
    )


@bot.message_handler(content_types=["document"])
def document_handler(message):

    if message.from_user.id in pending_payments:
        bot.reply_to(
            message,
            "❌ Please send the screenshot as a PHOTO, not a document."
        )


@bot.message_handler(content_types=["photo"])
def photo_handler(message):

    user_id = message.from_user.id

    if user_id not in pending_payments:
        return

    try:
        payment = pending_payments[user_id]

        bot.forward_message(
            ADMIN_ID,
            message.chat.id,
            message.message_id
        )

        username = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else "No Username"
        )

        bot.send_message(
            ADMIN_ID,
            f"""🔔 *Payment Verification Required*

👤 Name: {message.from_user.first_name}
🆔 User ID: `{user_id}`
🌐 Username: {username}

📢 Channel: {payment['channel_name']}
💎 Plan: {payment['plan']}
💰 Price: NPR {payment['price']}""",
            parse_mode="Markdown"
        )

        markup = InlineKeyboardMarkup(
            row_width=2
        )

        markup.add(
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=(
                    f"app_{user_id}_"
                    f"{payment['channel_id']}_"
                    f"{payment['plan']}"
                )
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"rej_{user_id}"
            )
        )

        bot.send_message(
            ADMIN_ID,
            "👇 Select an action:",
            reply_markup=markup
        )

        bot.send_message(
            user_id,
            "✅ Screenshot uploaded successfully!\n\n"
            "⏳ Waiting for admin verification."
        )

        del pending_payments[user_id]

    except Exception as e:
        print(f"PHOTO HANDLER ERROR: {e}")


# =========================================================
# PAYMENT APPROVAL
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("app_")
)
def approve_now(call):

    if call.from_user.id != ADMIN_ID:
        return

    try:
        _, u_id, ch_id, mins = call.data.split("_")

        u_id = int(u_id)
        ch_id = int(ch_id)
        mins = int(mins)

        expiry_datetime = (
            datetime.now()
            + timedelta(minutes=mins)
        )

        link = bot.create_chat_invite_link(
            ch_id,
            member_limit=1,
            expire_date=int(
                expiry_datetime.timestamp()
            )
        )

        users_col.update_one(
            {
                "user_id": u_id,
                "channel_id": ch_id
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp(),
                    "source": "paid_subscription"
                }
            },
            upsert=True
        )

        log_purchase(u_id, "paid_subscription", 0, "cash", {"channel_id": ch_id, "minutes": mins})

        if mins > 525600:
            plan_name = "💎 Lifetime"
        elif mins >= 1440:
            plan_name = (
                f"📅 {mins // 1440} Days"
            )
        else:
            plan_name = (
                f"⏱ {mins} Minutes"
            )

        bot.send_message(
            u_id,
            f"""🎉 *Payment Approved!*

💎 *Plan:* {plan_name}

🔗 *Join Link:*
{link.invite_link}

⚠️ This link can only be used once.""",
            parse_mode="Markdown"
        )

        bot.edit_message_text(
            "✅ Payment Approved Successfully.",
            call.message.chat.id,
            call.message.message_id
        )

    except Exception as e:
        bot.send_message(
            ADMIN_ID,
            f"❌ Approval Error:\n{e}"
        )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("rej_")
)
def reject_payment(call):

    if call.from_user.id != ADMIN_ID:
        return

    user_id = int(
        call.data.split("_")[1]
    )

    pending_payments.pop(
        user_id,
        None
    )

    bot.send_message(
        user_id,
        "❌ *Payment Rejected*\n\n"
        "Your payment could not be verified. Contact the admin if needed.",
        parse_mode="Markdown"
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# STATS
# =========================================================

def send_bot_stats():

    total_users = bot_users_col.count_documents({})
    banned_users = bot_users_col.count_documents(
        {"banned": True}
    )

    verified_referrals = bot_users_col.count_documents(
        {"verified_referral": True}
    )

    total_coins = list(
        bot_users_col.aggregate([
            {
                "$group": {
                    "_id": None,
                    "total": {
                        "$sum": "$coins"
                    }
                }
            }
        ])
    )

    coins = (
        total_coins[0]["total"]
        if total_coins
        else 0
    )

    bot.send_message(
        ADMIN_ID,
        f"""📊 *Bot Statistics*

👥 Total Users: *{total_users}*
🔗 Verified Referrals: *{verified_referrals}*
🚫 Banned Users: *{banned_users}*
🪙 Total User Coins: *{coins}*

📢 Paid Channels: *{channels_col.count_documents({})}*
🎁 Premium Channels: *{premium_channels_col.count_documents({})}*
🎯 Milestones: *{milestones_col.count_documents({})}*
🎟️ Coupons: *{coupons_col.count_documents({})}*""",
        parse_mode="Markdown"
    )


# =========================================================
# CLEAR EXPIRED PENDING PAYMENTS
# =========================================================

def clear_pending_payments():

    now = datetime.now()
    expired = []

    for user_id, data in list(
        pending_payments.items()
    ):

        if (
            now - data["time"]
        ).total_seconds() >= 600:

            try:
                bot.send_message(
                    user_id,
                    "⌛ Your payment verification request expired. Please try again."
                )
            except Exception:
                pass

            expired.append(user_id)

    for user_id in expired:
        pending_payments.pop(
            user_id,
            None
        )


# =========================================================
# AUTO REMOVE EXPIRED MEMBERS
# =========================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find(
        {"expiry": {"$lte": now}}
    )

    for user in expired_users:

        try:
            channel_id = user["channel_id"]
            user_id = user["user_id"]

            # Remove member without permanently banning
            bot.ban_chat_member(
                channel_id,
                user_id
            )

            bot.unban_chat_member(
                channel_id,
                user_id
            )

            source = user.get(
                "source",
                "paid_subscription"
            )

            settings = get_settings()

            if source == "coin_reward":

                balance = get_coin_balance(
                    user_id
                )

                plans = list(
                    premium_plans_col.find()
                )

                minimum_cost = min(
                    [
                        int(p["cost"])
                        for p in plans
                    ],
                    default=0
                )

                if (
                    balance >= minimum_cost
                    and minimum_cost > 0
                ):
                    message_text = (
                        "⏰ *Your Premium Has Expired*\n\n"
                        "Your Premium time has ended and you have been removed from the channel.\n\n"
                        f"{settings['coin_emoji']} You have *{balance} "
                        f"{settings['coin_name']}*.\n\n"
                        "🎁 You have enough coins to buy Premium again! "
                        "Open the bot and press *Redeem Premium*."
                    )
                else:
                    message_text = (
                        "⏰ *Your Premium Has Expired*\n\n"
                        "Your Premium time has ended and you have been removed from the channel.\n\n"
                        "🔗 Refer more friends to earn coins and redeem Premium again!"
                    )

                try:
                    bot.send_message(
                        user_id,
                        message_text,
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            else:

                try:
                    bot_username = bot.get_me().username

                    rejoin_url = (
                        f"https://t.me/{bot_username}"
                        f"?start={channel_id}"
                    )

                    markup = InlineKeyboardMarkup()

                    markup.add(
                        InlineKeyboardButton(
                            "🔁 Re-Join / Renew",
                            url=rejoin_url
                        )
                    )

                    bot.send_message(
                        user_id,
                        "⚠️ Your subscription has expired.\n\n"
                        "Click below to renew.",
                        reply_markup=markup
                    )

                except Exception:
                    pass

            users_col.delete_one(
                {"_id": user["_id"]}
            )

        except Exception as e:
            # Keep database record so scheduler can retry
            print(
                f"Kick expired user error: {e}"
            )


# =========================================================
# ADDITIONAL ADMIN FEATURES
# =========================================================

def log_purchase(user_id, source, amount, coin_name, details=None):
    try:
        purchase_history_col.insert_one({
            "user_id": int(user_id),
            "source": source,
            "amount": int(amount),
            "coin_name": coin_name,
            "details": details or {},
            "created_at": datetime.now()
        })
    except Exception as e:
        print(f"Purchase history error: {e}")


def log_coin_change(user_id, amount, reason, admin_id=None):
    try:
        coin_history_col.insert_one({
            "user_id": int(user_id),
            "amount": int(amount),
            "reason": reason,
            "admin_id": admin_id,
            "created_at": datetime.now()
        })
    except Exception as e:
        print(f"Coin history error: {e}")


def admin_dashboard_text():
    settings = get_settings()
    total = bot_users_col.count_documents({})
    active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    expired = users_col.count_documents({"expiry": {"$lte": datetime.now().timestamp()}})
    sales = list(purchase_history_col.aggregate([{"$group":{"_id":None,"total":{"$sum":"$amount"},"count":{"$sum":1}}}]))
    total_sales = sales[0].get("total", 0) if sales else 0
    sale_count = sales[0].get("count", 0) if sales else 0
    coins = list(bot_users_col.aggregate([{"$group":{"_id":None,"total":{"$sum":"$coins"}}}]))
    total_coins = coins[0].get("total", 0) if coins else 0
    return (f"📊 *Admin Dashboard*\n\n"
            f"👥 Users: *{total}*\n"
            f"👑 Active Premium records: *{active}*\n"
            f"⌛ Expired Premium records: *{expired}*\n"
            f"💰 Logged purchases: *{sale_count}*\n"
            f"🪙 Logged purchase coins: *{total_sales}*\n"
            f"🌽 User coin balance total: *{total_coins}*\n"
            f"🚧 Maintenance: *{'ON' if settings.get('maintenance_mode') else 'OFF'}*\n"
            f"🕒 Timezone: `{settings.get('timezone','Asia/Kathmandu')}`")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_DASHBOARD)
def additional_dashboard(message):
    bot.send_message(ADMIN_ID, admin_dashboard_text(), parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_PURCHASES)
def purchase_history_menu(message):
    rows = list(purchase_history_col.find().sort("created_at", DESCENDING).limit(30))
    if not rows:
        bot.send_message(ADMIN_ID, "💰 No purchase history recorded yet.")
        return
    lines=["💰 *Recent Purchase History*",""]
    for r in rows:
        lines.append(f"🆔 `{r.get('user_id')}` | {r.get('amount',0)} {r.get('coin_name','coins')} | {r.get('source','unknown')}")
        lines.append(f"🕒 {format_bot_time(r.get('created_at'))}")
    bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_PREMIUM_BUYERS)
def premium_buyers_menu(message):
    now=datetime.now().timestamp()
    rows=list(users_col.find({"expiry":{"$gt":now}}).sort("expiry",1).limit(100))
    if not rows:
        bot.send_message(ADMIN_ID,"👑 No active Premium buyers found.")
        return
    lines=["👑 *Active Premium Buyers*",""]
    for r in rows:
        u=get_user(r.get("user_id")) or {}
        name=u.get("first_name") or "User"
        username=f" @{u.get('username')}" if u.get('username') else ""
        lines.append(f"• {name}{username} — `{r.get('user_id')}`")
        lines.append(f"  📢 {r.get('channel_name', r.get('channel_id','Unknown'))}")
        lines.append(f"  ⏰ {format_bot_time(datetime.fromtimestamp(r['expiry']))}")
    bot.send_message(ADMIN_ID,"\n".join(lines),parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_USER_SEARCH)
def user_search_prompt(message):
    msg=bot.send_message(ADMIN_ID,"🔎 Send Telegram user ID or @username.")
    bot.register_next_step_handler(msg, process_admin_user_search)


def process_admin_user_search(message):
    value=message.text.strip().lstrip('@')
    user=None
    if value.isdigit(): user=get_user(int(value))
    else: user=bot_users_col.find_one({"username":{"$regex":f"^{value}$","$options":"i"}})
    if not user:
        bot.send_message(ADMIN_ID,"❌ User not found."); return
    uid=user.get("user_id")
    premiums=list(users_col.find({"user_id":uid}))
    text=(f"👤 *User Details*\n\nName: {user.get('first_name','User')}\n"
          f"Username: @{user.get('username','-')}\n🆔 `{uid}`\n"
          f"🌽 Coins: *{user.get('coins',0)}*\n"
          f"🔗 Referrals: *{user.get('referral_count',0)}*\n"
          f"👑 Premium records: *{len(premiums)}*")
    for r in premiums:
        text += f"\n• {r.get('channel_name',r.get('channel_id'))} — {format_bot_time(datetime.fromtimestamp(r['expiry'])) if r.get('expiry') else '-'}"
    bot.send_message(ADMIN_ID,text,parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_COIN_ADD)
def coin_add_prompt(message):
    msg=bot.send_message(ADMIN_ID,"🪙 Send: `USER_ID AMOUNT`\nExample: `123456789 100`",parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_admin_coin_add)


def process_admin_coin_add(message):
    try:
        uid, amount=message.text.split()[:2]
        uid=int(uid); amount=int(amount)
        if not get_user(uid): bot.send_message(ADMIN_ID,"❌ User not found."); return
        if amount == 0: bot.send_message(ADMIN_ID,"❌ Amount cannot be zero."); return
        add_coins(uid,amount)
        log_coin_change(uid,amount,"admin_adjustment",ADMIN_ID)
        bot.send_message(uid,f"🪙 Your coin balance was adjusted by *{amount}*.",parse_mode="Markdown")
        bot.send_message(ADMIN_ID,f"✅ Added {amount} coins to `{uid}`.",parse_mode="Markdown")
    except Exception:
        bot.send_message(ADMIN_ID,"❌ Invalid format.")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_SINGLE_BROADCAST)
def single_broadcast_prompt(message):
    msg=bot.send_message(ADMIN_ID,"📨 Send: `USER_ID message`",parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_single_broadcast)


def process_single_broadcast(message):
    try:
        parts=message.text.split(maxsplit=1)
        uid=int(parts[0]); text=parts[1]
        bot.send_message(uid,text)
        bot.send_message(ADMIN_ID,"✅ Message sent successfully.")
    except Exception as e:
        bot.send_message(ADMIN_ID,f"❌ Unable to send message: {e}")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_PREMIUM_MANAGE)
def premium_manage_prompt(message):
    msg=bot.send_message(ADMIN_ID,"🛠️ Send Premium user ID to manage.")
    bot.register_next_step_handler(msg, premium_manage_user)


def premium_manage_user(message):
    try:
        uid=int(message.text.strip())
        rows=list(users_col.find({"user_id":uid}))
        if not rows:
            bot.send_message(ADMIN_ID,"❌ No Premium record found."); return
        markup=InlineKeyboardMarkup()
        for r in rows:
            markup.add(InlineKeyboardButton(f"⏰ Extend {r.get('channel_name',r.get('channel_id'))}",callback_data=f"adminextend:{uid}:{r['_id']}"))
        bot.send_message(ADMIN_ID,"Choose a Premium record to extend by 24 hours:",reply_markup=markup)
    except Exception:
        bot.send_message(ADMIN_ID,"❌ Invalid user ID.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("adminextend:"))
def admin_extend_premium(call):
    if not admin_only(call): return
    try:
        _,uid,oid=call.data.split(":")
        row=users_col.find_one({"_id":ObjectId(oid),"user_id":int(uid)})
        if not row: raise ValueError("record not found")
        current=max(float(row.get("expiry",0)),datetime.now().timestamp())
        new=current+86400
        users_col.update_one({"_id":row["_id"]},{"$set":{"expiry":new}})
        bot.answer_callback_query(call.id,"Extended 24 hours")
        bot.send_message(ADMIN_ID,f"✅ Premium for `{uid}` extended by 24 hours.",parse_mode="Markdown")
    except Exception as e:
        bot.answer_callback_query(call.id,"❌ Failed",show_alert=True); print(e)


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_MAINTENANCE)
def maintenance_toggle(message):
    current=bool(get_settings().get("maintenance_mode",False))
    update_setting("maintenance_mode",not current)
    bot.send_message(ADMIN_ID,f"🚧 Maintenance mode is now *{'ON' if not current else 'OFF'}*.",parse_mode="Markdown")


# =========================================================
# PREMIUM EXPIRY NOTIFICATION JOB
# =========================================================
def notify_expiring_premium():
    now=datetime.now().timestamp()
    for hours in (24,1):
        lo=now+hours*3600-60
        hi=now+hours*3600+60
        rows=users_col.find({"expiry":{"$gte":lo,"$lte":hi}})
        for r in rows:
            uid=r.get("user_id")
            key=f"expiry_notice_{hours}h"
            if r.get(key): continue
            try:
                bot.send_message(uid,f"🔔 Your Premium access expires in approximately *{hours} hour(s)*.\n\n⏰ Expiry: {format_bot_time(datetime.fromtimestamp(r['expiry']))}",parse_mode="Markdown")
                users_col.update_one({"_id":r["_id"]},{"$set":{key:True}})
            except Exception: pass


# =========================================================
# ADVANCED CONTROL CENTER / USER EXPERIENCE EXTENSION
# =========================================================
#
# This extension intentionally lives in one section so the original bot
# remains easy to maintain. It adds admin-controllable user tools without
# removing the existing systems.
# =========================================================

def feature_enabled(name, default=True):
    """Read one feature flag. Missing flags remain enabled for compatibility."""
    try:
        flags = get_settings().get("feature_flags", {}) or {}
        return bool(flags.get(name, default))
    except Exception:
        return default


def set_feature(name, enabled):
    settings = get_settings()
    flags = dict(settings.get("feature_flags", {}) or {})
    flags[name] = bool(enabled)
    update_setting("feature_flags", flags)
    write_audit(
        ADMIN_ID,
        "feature_toggle",
        {"feature": name, "enabled": bool(enabled)}
    )


def write_audit(actor_id, action, details=None):
    """Write a compact audit record for important administrative actions."""
    try:
        if not get_settings().get("audit_log_enabled", True):
            return
        audit_log_col.insert_one({
            "actor_id": actor_id,
            "action": action,
            "details": details or {},
            "created_at": bot_time_now(),
        })
    except Exception as e:
        print("Audit error:", e)


def record_notification(user_id, kind, text):
    """Store a lightweight notification record for user history."""
    try:
        notification_col.insert_one({
            "user_id": user_id,
            "kind": kind,
            "text": text,
            "read": False,
            "created_at": bot_time_now(),
        })
    except Exception:
        pass


def get_unread_notifications(user_id):
    return notification_col.count_documents({
        "user_id": user_id,
        "read": {"$ne": True}
    })


def mark_notifications_read(user_id):
    notification_col.update_many(
        {"user_id": user_id, "read": {"$ne": True}},
        {"$set": {"read": True, "read_at": bot_time_now()}}
    )


def safe_username(user):
    if not user:
        return "-"
    username = user.get("username")
    return f"@{username}" if username else "-"


def get_active_premium_count(user_id):
    now = datetime.now().timestamp()
    return users_col.count_documents({
        "user_id": user_id,
        "expiry": {"$gt": now}
    })


def get_user_purchase_total(user_id):
    rows = list(purchase_history_col.find({"user_id": user_id}))
    return sum(int(r.get("amount", 0) or 0) for r in rows)


def get_user_purchase_count(user_id):
    return purchase_history_col.count_documents({"user_id": user_id})


def get_user_referral_count(user_id):
    u = get_user(user_id) or {}
    return int(u.get("referral_count", 0) or 0)


def build_wallet_text(user_id):
    user = get_user(user_id) or {}
    settings = get_settings()
    coins = int(user.get("coins", 0) or 0)
    active = get_active_premium_count(user_id)
    purchases = get_user_purchase_count(user_id)
    spent = get_user_purchase_total(user_id)
    unread = get_unread_notifications(user_id)

    return (
        "💳 *My Wallet*\\n\\n"
        f"🪙 Balance: *{coins} {settings['coin_name']}*\\n"
        f"👑 Active Premium: *{active}*\\n"
        f"🛒 Purchases: *{purchases}*\\n"
        f"💸 Total spent: *{spent} {settings['coin_name']}*\\n"
        f"🔔 Notifications: *{unread} unread*"
    )


def build_user_status_text(user_id):
    user = get_user(user_id) or {}
    settings = get_settings()
    now = datetime.now().timestamp()
    premium_rows = list(users_col.find({
        "user_id": user_id,
        "expiry": {"$gt": now}
    }).sort("expiry", 1).limit(20))

    lines = [
        "📊 *My Account Status*",
        "",
        f"👤 {user.get('first_name', 'User')} {safe_username(user)}",
        f"🆔 `{user_id}`",
        f"🪙 Coins: *{int(user.get('coins', 0) or 0)} {settings['coin_name']}*",
        f"🔗 Referrals: *{int(user.get('referral_count', 0) or 0)}*",
        f"🛒 Purchases: *{get_user_purchase_count(user_id)}*",
        "",
        "👑 *Active Premium*",
    ]

    if not premium_rows:
        lines.append("No active Premium access.")
    else:
        for row in premium_rows:
            name = row.get("channel_name") or row.get("channel_id") or "Channel"
            expiry = row.get("expiry")
            if expiry:
                expiry_text = format_bot_time(
                    datetime.fromtimestamp(float(expiry), tz=ZoneInfo("UTC"))
                )
            else:
                expiry_text = "Unknown"
            lines.append(f"• {name} — {expiry_text}")

    return "\\n".join(lines)


def user_history_markup(user_id):
    markup = InlineKeyboardMarkup()
    if feature_enabled("notifications"):
        markup.add(InlineKeyboardButton(
            "🔔 Notifications",
            callback_data="adv_notifications"
        ))
    markup.add(InlineKeyboardButton(
        "🔄 Refresh",
        callback_data="adv_refresh_wallet"
    ))
    return markup


def show_wallet(message_or_call, user_id=None):
    if user_id is None:
        user_id = message_or_call.from_user.id
        chat_id = message_or_call.chat.id
    else:
        chat_id = message_or_call

    if not feature_enabled("wallet"):
        bot.send_message(chat_id, "⚠️ Wallet is currently disabled by Admin.")
        return

    bot.send_message(
        chat_id,
        build_wallet_text(user_id),
        reply_markup=user_history_markup(user_id),
        parse_mode="Markdown"
    )


def show_user_history(chat_id, user_id):
    if not feature_enabled("purchase_history"):
        bot.send_message(chat_id, "⚠️ Purchase history is currently disabled.")
        return

    settings = get_settings()
    rows = list(
        purchase_history_col.find({"user_id": user_id})
        .sort("created_at", DESCENDING)
        .limit(20)
    )

    if not rows:
        bot.send_message(chat_id, "🧾 You don't have any purchase history yet.")
        return

    lines = ["🧾 *My Purchase History*", ""]
    for index, row in enumerate(rows, 1):
        amount = row.get("amount", 0)
        source = str(row.get("source", "purchase")).replace("_", " ").title()
        created = format_bot_time(row.get("created_at"))
        extra = row.get("metadata") or {}
        channel_count = extra.get("channels")
        suffix = f" • {channel_count} channels" if channel_count else ""
        lines.append(
            f"{index}. *{source}* — {amount} {settings['coin_name']}{suffix}"
        )
        lines.append(f"   🕒 {created}")

    bot.send_message(chat_id, "\\n".join(lines), parse_mode="Markdown")


def notification_preferences(user_id):
    user = get_user(user_id) or {}
    prefs = user.get("notification_preferences", {})
    return {
        "purchase": bool(prefs.get("purchase", True)),
        "expiry": bool(prefs.get("expiry", True)),
        "coins": bool(prefs.get("coins", True)),
        "announcements": bool(prefs.get("announcements", True)),
    }


def save_notification_preferences(user_id, prefs):
    bot_users_col.update_one(
        {"user_id": user_id},
        {"$set": {"notification_preferences": prefs}},
        upsert=True
    )


def notification_markup(user_id):
    prefs = notification_preferences(user_id)
    markup = InlineKeyboardMarkup()
    labels = [
        ("purchase", "🛒 Purchase notifications"),
        ("expiry", "⏰ Expiry notifications"),
        ("coins", "🪙 Coin notifications"),
        ("announcements", "📣 Announcement notifications"),
    ]
    for key, label in labels:
        state = "ON" if prefs[key] else "OFF"
        markup.add(InlineKeyboardButton(
            f"{label}: {state}",
            callback_data=f"advnotif:{key}"
        ))
    markup.add(InlineKeyboardButton(
        "✅ Done",
        callback_data="advnotif_done"
    ))
    return markup


def show_notifications(chat_id, user_id):
    if not feature_enabled("notifications"):
        bot.send_message(chat_id, "⚠️ Notifications are disabled by Admin.")
        return
    bot.send_message(
        chat_id,
        "🔔 *Notification Preferences*\\n\\n"
        "Choose which private notifications you want to receive. "
        "Admin announcements still remain subject to the bot's global controls.",
        reply_markup=notification_markup(user_id),
        parse_mode="Markdown"
    )


def daily_bonus_status(user_id):
    row = daily_claims_col.find_one({"user_id": user_id}) or {}
    today = bot_time_now().date().isoformat()
    last = row.get("last_claim_date")
    streak = int(row.get("streak", 0) or 0)
    if last == today:
        return True, streak, int(row.get("today_reward", 0) or 0)
    return False, streak, 0


def calculate_daily_reward(streak):
    settings = get_settings()
    base = max(0, int(settings.get("daily_bonus", 5)))
    extra = max(0, int(settings.get("daily_streak_bonus", 2))) * max(0, streak - 1)
    maximum = max(base, int(settings.get("daily_bonus_max", 25)))
    return min(maximum, base + extra)


def claim_daily_bonus(user_id):
    if not feature_enabled("daily_bonus"):
        return False, "⚠️ Daily Bonus is currently disabled by Admin.", 0

    now = bot_time_now()
    today = now.date().isoformat()
    row = daily_claims_col.find_one({"user_id": user_id}) or {}

    if row.get("last_claim_date") == today:
        reward = int(row.get("today_reward", 0) or 0)
        return False, f"⏳ You already claimed today's bonus: *{reward} coins*.", 0

    yesterday = (now.date() - timedelta(days=1)).isoformat()
    old_last = row.get("last_claim_date")
    old_streak = int(row.get("streak", 0) or 0)
    streak = old_streak + 1 if old_last == yesterday else 1
    reward = calculate_daily_reward(streak)

    add_coins(user_id, reward)
    daily_claims_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "last_claim_date": today,
            "streak": streak,
            "today_reward": reward,
            "updated_at": now,
        }},
        upsert=True
    )
    log_coin_change(user_id, reward, "daily_bonus", user_id)
    record_notification(
        user_id,
        "daily_bonus",
        f"Daily bonus: +{reward} coins"
    )
    write_audit(user_id, "daily_bonus_claim", {
        "reward": reward,
        "streak": streak
    })
    return True, (
        f"🎁 *Daily Bonus Claimed!*\\n\\n"
        f"🪙 Reward: *+{reward} coins*\\n"
        f"🔥 Streak: *{streak} day(s)*"
    ), reward


def build_daily_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(
        "🎁 Claim Today's Bonus",
        callback_data="adv_daily_claim"
    ))
    return markup


def show_daily_bonus(chat_id, user_id):
    claimed, streak, reward = daily_bonus_status(user_id)
    settings = get_settings()
    if claimed:
        bot.send_message(
            chat_id,
            f"🎁 *Daily Bonus*\\n\\n"
            f"✅ Already claimed today.\\n"
            f"🔥 Current streak: *{streak}*\\n"
            f"🪙 Today's reward: *{reward} {settings['coin_name']}*",
            parse_mode="Markdown"
        )
    else:
        next_reward = calculate_daily_reward(streak + 1)
        bot.send_message(
            chat_id,
            f"🎁 *Daily Bonus*\\n\\n"
            f"🔥 Current streak: *{streak}*\\n"
            f"🪙 Next reward: *{next_reward} {settings['coin_name']}*\\n\\n"
            "Claim once every bot-timezone day.",
            reply_markup=build_daily_markup(),
            parse_mode="Markdown"
        )


def admin_feature_markup():
    settings = get_settings()
    flags = settings.get("feature_flags", {}) or {}
    markup = InlineKeyboardMarkup()

    names = [
        ("referrals", "🔗 Referrals"),
        ("milestones", "🎯 Milestones"),
        ("coupons", "🎟️ Coupons"),
        ("leaderboard", "🏆 Leaderboard"),
        ("feedback", "💬 Feedback"),
        ("daily_bonus", "🎁 Daily Bonus"),
        ("wallet", "💳 Wallet"),
        ("purchase_history", "🧾 Purchase History"),
        ("notifications", "🔔 Notifications"),
        ("bulk_redeem", "📦 Bulk Redeem"),
        ("single_redeem", "🎁 Single Redeem"),
        ("force_join", "📣 Force Join"),
        ("premium_expiry_notice", "⏰ Expiry Notices"),
        ("broadcast", "📨 Broadcast"),
    ]

    for key, label in names:
        state = bool(flags.get(key, True))
        markup.add(InlineKeyboardButton(
            f"{label}: {'ON' if state else 'OFF'}",
            callback_data=f"advfeature:{key}"
        ))

    markup.add(InlineKeyboardButton(
        "🔄 Refresh",
        callback_data="advfeature_refresh"
    ))
    return markup


def show_feature_control(chat_id):
    if chat_id != ADMIN_ID:
        return
    bot.send_message(
        chat_id,
        "🎛️ *Feature Control Center*\\n\\n"
        "Every optional user-facing module can be switched independently. "
        "Existing database records are preserved when a feature is disabled.",
        reply_markup=admin_feature_markup(),
        parse_mode="Markdown"
    )


def bulk_rules_text():
    settings = get_settings()
    rules = settings.get("bulk_discount_rules", []) or []
    lines = [
        "📦 *Bulk Discount Rules*",
        "",
        "Bulk cost = single-channel price × selected channels − discount.",
        "The system always shows the original and final cost before confirmation.",
        "",
    ]
    if not rules:
        lines.append("No discount rules configured.")
    else:
        for r in sorted(rules, key=lambda x: int(x.get("min_channels", 0))):
            typ = r.get("discount_type", "percent")
            value = r.get("discount_value", 0)
            unit = "%" if typ == "percent" else " coins"
            lines.append(
                f"• {r.get('min_channels', 0)}+ channels → {value}{unit}"
            )
    lines.extend([
        "",
        f"📏 Maximum selectable channels: *{settings.get('bulk_max_channels', 50)}*",
        "",
        "Admin commands:",
        "`/bulkdiscount ADD min percent value`",
        "`/bulkdiscount ADD min fixed value`",
        "`/bulkdiscount REMOVE min`",
        "`/bulkdiscount MAX number`",
    ])
    return "\\n".join(lines)


def parse_bulk_rule_command(text):
    parts = text.strip().split()
    if len(parts) < 2:
        return False, "Invalid command."
    action = parts[1].upper()

    if action == "MAX" and len(parts) == 3:
        maximum = max(1, min(200, int(parts[2])))
        update_setting("bulk_max_channels", maximum)
        write_audit(ADMIN_ID, "bulk_max_channels", {"value": maximum})
        return True, f"✅ Maximum bulk channels set to {maximum}."

    if action == "REMOVE" and len(parts) == 3:
        minimum = int(parts[2])
        rules = [
            r for r in (get_settings().get("bulk_discount_rules", []) or [])
            if int(r.get("min_channels", 0)) != minimum
        ]
        update_setting("bulk_discount_rules", rules)
        write_audit(ADMIN_ID, "bulk_discount_remove", {"min_channels": minimum})
        return True, f"✅ Removed the {minimum}+ channel discount rule."

    if action == "ADD" and len(parts) == 5:
        minimum = int(parts[2])
        dtype = parts[3].lower()
        value = float(parts[4])
        if minimum < 1:
            raise ValueError("Minimum channels must be at least 1.")
        if dtype not in ("percent", "fixed"):
            raise ValueError("Type must be percent or fixed.")
        if value < 0 or (dtype == "percent" and value > 100):
            raise ValueError("Invalid discount value.")

        rules = [
            r for r in (get_settings().get("bulk_discount_rules", []) or [])
            if int(r.get("min_channels", 0)) != minimum
        ]
        rules.append({
            "min_channels": minimum,
            "discount_type": dtype,
            "discount_value": value,
        })
        rules.sort(key=lambda x: int(x.get("min_channels", 0)))
        update_setting("bulk_discount_rules", rules)
        write_audit(ADMIN_ID, "bulk_discount_add", {
            "min_channels": minimum,
            "discount_type": dtype,
            "discount_value": value,
        })
        return True, f"✅ {minimum}+ channel discount saved."
    return False, "Usage: /bulkdiscount ADD min percent value"


def admin_analytics_text():
    now = datetime.now().timestamp()
    total_users = bot_users_col.count_documents({})
    active_premium = users_col.count_documents({"expiry": {"$gt": now}})
    total_purchase_docs = purchase_history_col.count_documents({})
    total_spent = sum(
        int(r.get("amount", 0) or 0)
        for r in purchase_history_col.find({}, {"amount": 1})
    )
    total_coins = sum(
        int(r.get("coins", 0) or 0)
        for r in bot_users_col.find({}, {"coins": 1})
    )
    referrals = sum(
        int(r.get("referral_count", 0) or 0)
        for r in bot_users_col.find({}, {"referral_count": 1})
    )
    today = bot_time_now().date().isoformat()
    daily_claims = daily_claims_col.count_documents({"last_claim_date": today})

    top_spenders = list(
        purchase_history_col.aggregate([
            {"$group": {
                "_id": "$user_id",
                "spent": {"$sum": "$amount"},
                "orders": {"$sum": 1}
            }},
            {"$sort": {"spent": -1}},
            {"$limit": 5}
        ])
    )

    lines = [
        "📈 *Advanced Analytics*",
        "",
        f"👥 Total users: *{total_users}*",
        f"👑 Active Premium records: *{active_premium}*",
        f"🛒 Purchase records: *{total_purchase_docs}*",
        f"💰 Logged coins spent: *{total_spent}*",
        f"🪙 Current user coins: *{total_coins}*",
        f"🔗 Total referrals: *{referrals}*",
        f"🎁 Today's daily claims: *{daily_claims}*",
        "",
        "🏆 *Top Spenders*",
    ]

    if not top_spenders:
        lines.append("No purchase data yet.")
    else:
        for index, row in enumerate(top_spenders, 1):
            lines.append(
                f"{index}. `{row['_id']}` — {row.get('spent', 0)} coins "
                f"({row.get('orders', 0)} orders)"
            )

    return "\\n".join(lines)


def system_health_text():
    settings = get_settings()
    collections = {
        "users": users_col,
        "bot_users": bot_users_col,
        "premium_channels": premium_channels_col,
        "premium_plans": premium_plans_col,
        "coupons": coupons_col,
        "purchase_history": purchase_history_col,
        "audit_logs": audit_log_col,
    }

    lines = [
        "💾 *System Health*",
        "",
        f"🕒 Bot time: *{format_bot_time(bot_time_now())}*",
        f"🌍 Timezone: `{settings.get('timezone', 'Asia/Kathmandu')}`",
        f"🚧 Maintenance: *{'ON' if settings.get('maintenance_mode') else 'OFF'}*",
        "",
    ]

    for name, collection in collections.items():
        try:
            lines.append(f"• {name}: {collection.count_documents({})}")
        except Exception:
            lines.append(f"• {name}: unavailable")

    lines.extend([
        "",
        f"🧠 Pending payments: {len(pending_payments)}",
        f"📦 Bulk selections: {len(bulk_redeem_selections)}",
        f"🕒 Scheduler: background jobs active while bot process is running.",
    ])
    return "\\n".join(lines)


def admin_audit_text(limit=30):
    rows = list(
        audit_log_col.find().sort("created_at", DESCENDING).limit(limit)
    )
    if not rows:
        return "🧾 *Audit Log*\\n\\nNo administrative audit entries yet."

    lines = ["🧾 *Audit Log*", ""]
    for row in rows:
        action = row.get("action", "unknown")
        actor = row.get("actor_id", "-")
        created = format_bot_time(row.get("created_at"))
        details = row.get("details") or {}
        compact = " ".join(f"{k}={v}" for k, v in details.items())
        if len(compact) > 120:
            compact = compact[:117] + "..."
        lines.append(f"• `{created}` — `{actor}` — *{action}*")
        if compact:
            lines.append(f"  {compact}")
    return "\\n".join(lines)


def admin_announcement_markup():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📣 Broadcast to All", callback_data="adv_announce_all"),
        InlineKeyboardButton("🧪 Test Mode", callback_data="adv_announce_test"),
    )
    return markup


def send_announcement_text(text, test_only=False):
    users = list(bot_users_col.find({}, {"user_id": 1}))
    sent = 0
    failed = 0

    if test_only:
        try:
            bot.send_message(ADMIN_ID, text)
            return 1, 0
        except Exception:
            return 0, 1

    for row in users:
        uid = row.get("user_id")
        if not uid:
            continue
        prefs = notification_preferences(uid)
        if not prefs["announcements"]:
            continue
        try:
            bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1

    announcement_col.insert_one({
        "admin_id": ADMIN_ID,
        "text": text,
        "sent": sent,
        "failed": failed,
        "created_at": bot_time_now(),
    })
    write_audit(ADMIN_ID, "announcement", {
        "sent": sent,
        "failed": failed
    })
    return sent, failed


def admin_control_summary():
    settings = get_settings()
    flags = settings.get("feature_flags", {}) or {}
    on = sum(1 for value in flags.values() if value)
    off = len(flags) - on
    return (
        "🎛️ *Control Summary*\\n\\n"
        f"🟢 Enabled: *{on}*\\n"
        f"🔴 Disabled: *{off}*\\n"
        f"📦 Bulk max: *{settings.get('bulk_max_channels', 50)}*\\n"
        f"🎁 Daily bonus: *{settings.get('daily_bonus', 5)}*\\n"
        f"🔥 Streak bonus: *{settings.get('daily_streak_bonus', 2)}*\\n"
        f"💾 Audit logging: *{'ON' if settings.get('audit_log_enabled', True) else 'OFF'}*"
    )


_base_admin_menu_markup = admin_menu_markup


def advanced_admin_menu_markup():
    markup = _base_admin_menu_markup()
    markup.row(KeyboardButton(ADMIN_FEATURES))
    markup.row(KeyboardButton(ADMIN_ANALYTICS))
    markup.row(KeyboardButton(ADMIN_BULK_RULES))
    markup.row(KeyboardButton(ADMIN_AUDIT))
    markup.row(KeyboardButton(ADMIN_BACKUP_INFO))
    markup.row(KeyboardButton(ADMIN_ANNOUNCEMENTS))
    return markup


def advanced_user_menu_markup(user_id=None):
    settings = get_settings()
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    # Preserve the original buttons while exposing advanced tools.
    markup.row(
        KeyboardButton(settings["btn_profile"]),
        KeyboardButton(settings["btn_refer"])
    )
    markup.row(
        KeyboardButton(settings["btn_redeem"]),
        KeyboardButton(settings["btn_coupon"])
    )
    markup.row(
        KeyboardButton(settings["btn_referrals"]),
        KeyboardButton(settings["btn_milestones"])
    )
    markup.row(
        KeyboardButton(settings["btn_leaderboard"]),
        KeyboardButton(settings["btn_how"])
    )
    markup.row(
        KeyboardButton(USER_HISTORY),
        KeyboardButton(USER_STATUS)
    )
    markup.row(
        KeyboardButton(USER_DAILY),
        KeyboardButton(USER_NOTIFICATIONS)
    )
    markup.row(
        KeyboardButton(USER_HELP)
    )
    markup.row(
        KeyboardButton(settings["btn_feedback"]),
        KeyboardButton(settings["btn_contact"])
    )

    if user_id == ADMIN_ID:
        markup.row(KeyboardButton(ADMIN_PANEL_BUTTON))
    return markup


# Replace menu functions at runtime so every existing call benefits.
user_menu_markup = advanced_user_menu_markup
admin_menu_markup = advanced_admin_menu_markup


def send_feature_denied(chat_id, feature):
    bot.send_message(
        chat_id,
        f"⚠️ *{feature}* is currently disabled by Admin.\\n\\n"
        "Please try again later.",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_FEATURES)
def advanced_feature_control_handler(message):
    show_feature_control(message.chat.id)


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_ANALYTICS)
def advanced_analytics_handler(message):
    bot.send_message(
        message.chat.id,
        admin_analytics_text(),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_BULK_RULES)
def advanced_bulk_rules_handler(message):
    bot.send_message(
        message.chat.id,
        bulk_rules_text(),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_AUDIT)
def advanced_audit_handler(message):
    bot.send_message(
        message.chat.id,
        admin_audit_text(),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_BACKUP_INFO)
def advanced_health_handler(message):
    bot.send_message(
        message.chat.id,
        system_health_text(),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_ANNOUNCEMENTS)
def advanced_announcement_handler(message):
    bot.send_message(
        message.chat.id,
        "📣 *Announcement Center*\\n\\n"
        "Send an announcement by using:\\n"
        "`/announce your message here`\\n\\n"
        "It respects each user's announcement notification preference.",
        reply_markup=admin_announcement_markup(),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["bulkdiscount"])
def bulkdiscount_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        ok, result = parse_bulk_rule_command(message.text)
        bot.send_message(
            ADMIN_ID,
            result if ok else bulk_rules_text(),
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Bulk rule error: {e}")


@bot.message_handler(commands=["announce"])
def announce_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, "Usage: `/announce your message`", parse_mode="Markdown")
        return
    if not feature_enabled("broadcast"):
        bot.send_message(ADMIN_ID, "⚠️ Broadcast is disabled in Feature Control.")
        return

    sent, failed = send_announcement_text(parts[1])
    bot.send_message(
        ADMIN_ID,
        f"📣 Announcement completed.\\n\\n✅ Sent: {sent}\\n❌ Failed: {failed}"
    )


@bot.callback_query_handler(func=lambda c: c.data == "advfeature_refresh")
def advanced_feature_refresh(call):
    if not admin_only(call):
        return
    bot.edit_message_reply_markup(
        call.message.chat.id,
        call.message.message_id,
        reply_markup=admin_feature_markup()
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("advfeature:"))
def advanced_feature_toggle(call):
    if not admin_only(call):
        return
    key = call.data.split(":", 1)[1]
    settings = get_settings()
    flags = settings.get("feature_flags", {}) or {}
    current = bool(flags.get(key, True))
    set_feature(key, not current)
    bot.answer_callback_query(
        call.id,
        f"{key}: {'ON' if not current else 'OFF'}"
    )
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_feature_markup()
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "adv_daily_claim")
def advanced_daily_claim(call):
    user_id = call.from_user.id
    ok, result, reward = claim_daily_bonus(user_id)
    bot.answer_callback_query(
        call.id,
        "Bonus claimed!" if ok else result[:180],
        show_alert=not ok
    )
    if ok:
        bot.send_message(user_id, result, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv_refresh_wallet")
def advanced_wallet_refresh(call):
    if not feature_enabled("wallet"):
        bot.answer_callback_query(call.id, "Wallet disabled.", show_alert=True)
        return
    bot.send_message(
        call.from_user.id,
        build_wallet_text(call.from_user.id),
        reply_markup=user_history_markup(call.from_user.id),
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "adv_notifications")
def advanced_notifications(call):
    show_notifications(call.message.chat.id, call.from_user.id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("advnotif:"))
def advanced_notification_toggle(call):
    key = call.data.split(":", 1)[1]
    prefs = notification_preferences(call.from_user.id)
    if key not in prefs:
        bot.answer_callback_query(call.id, "Unknown option.", show_alert=True)
        return
    prefs[key] = not prefs[key]
    save_notification_preferences(call.from_user.id, prefs)
    bot.answer_callback_query(
        call.id,
        f"{key.title()} notifications {'ON' if prefs[key] else 'OFF'}"
    )
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=notification_markup(call.from_user.id)
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "advnotif_done")
def advanced_notification_done(call):
    bot.answer_callback_query(call.id, "Preferences saved.")
    bot.send_message(call.from_user.id, "✅ Notification preferences saved.")


@bot.callback_query_handler(func=lambda c: c.data == "adv_announce_test")
def advanced_announce_test(call):
    if not admin_only(call):
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        ADMIN_ID,
        "🧪 Send the exact test announcement text."
    )
    bot.register_next_step_handler(msg, advanced_process_test_announcement)


def advanced_process_test_announcement(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        sent, failed = send_announcement_text(message.text, test_only=True)
        bot.send_message(
            ADMIN_ID,
            f"🧪 Test complete. Sent: {sent}, failed: {failed}"
        )
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Test failed: {e}")


@bot.callback_query_handler(func=lambda c: c.data == "adv_announce_all")
def advanced_announce_all(call):
    if not admin_only(call):
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        ADMIN_ID,
        "📣 Send the announcement text to broadcast to eligible users."
    )
    bot.register_next_step_handler(msg, advanced_process_announcement)


def advanced_process_announcement(message):
    if message.from_user.id != ADMIN_ID:
        return
    if not feature_enabled("broadcast"):
        bot.send_message(ADMIN_ID, "⚠️ Broadcast is disabled.")
        return
    try:
        sent, failed = send_announcement_text(message.text)
        bot.send_message(
            ADMIN_ID,
            f"📣 Broadcast complete.\\n\\n✅ Sent: {sent}\\n❌ Failed: {failed}"
        )
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Broadcast failed: {e}")


@bot.message_handler(func=lambda m: m.text == USER_WALLET)
def advanced_user_wallet_handler(message):
    show_wallet(message)


@bot.message_handler(func=lambda m: m.text == USER_HISTORY)
def advanced_user_history_handler(message):
    show_user_history(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == USER_DAILY)
def advanced_user_daily_handler(message):
    show_daily_bonus(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == USER_STATUS)
def advanced_user_status_handler(message):
    if is_banned(message.from_user.id):
        return
    bot.send_message(
        message.chat.id,
        build_user_status_text(message.from_user.id),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == USER_NOTIFICATIONS)
def advanced_user_notifications_handler(message):
    show_notifications(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == USER_HELP)
def advanced_user_help_handler(message):
    settings = get_settings()
    bot.send_message(
        message.chat.id,
        f"""🆘 *Help & Rules*

🪙 Currency: *{settings['coin_name']}*
🌍 Bot timezone: `{settings.get('timezone', 'Asia/Kathmandu')}`

• Premium access is delivered using Telegram invite links.
• Bulk purchases use the normal channel price × channel count.
• Any discount is controlled by Admin.
• Invite links are intended for the purchasing user.
• Never share a private Premium invite link.
• Your coin balance is checked atomically during redemption.

Need help? Contact Admin from the main menu.""",
        parse_mode="Markdown"
    )


# Extra administrative utility commands.
@bot.message_handler(commands=["feature"])
def feature_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 3 or parts[1] not in (get_settings().get("feature_flags", {}) or {}):
        bot.send_message(
            ADMIN_ID,
            "Usage: `/feature NAME on|off`",
            parse_mode="Markdown"
        )
        return
    enabled = parts[2].lower() in ("on", "1", "true", "yes")
    set_feature(parts[1], enabled)
    bot.send_message(
        ADMIN_ID,
        f"✅ Feature `{parts[1]}` is now *{'ON' if enabled else 'OFF'}*.",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["audit"])
def audit_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.send_message(ADMIN_ID, admin_audit_text(50), parse_mode="Markdown")


@bot.message_handler(commands=["analytics"])
def analytics_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.send_message(ADMIN_ID, admin_analytics_text(), parse_mode="Markdown")


@bot.message_handler(commands=["health"])
def health_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.send_message(ADMIN_ID, system_health_text(), parse_mode="Markdown")


def initialize_advanced_defaults():
    """Initialize advanced settings and indexes without touching old records."""
    settings = get_settings()
    defaults = {
        "feature_flags": {
            "referrals": True,
            "milestones": True,
            "coupons": True,
            "leaderboard": True,
            "feedback": True,
            "daily_bonus": True,
            "wallet": True,
            "purchase_history": True,
            "notifications": True,
            "bulk_redeem": True,
            "single_redeem": True,
            "force_join": True,
            "maintenance": True,
            "premium_expiry_notice": True,
            "broadcast": True,
        },
        "bulk_discount_rules": [
            {"min_channels": 2, "discount_type": "percent", "discount_value": 0},
            {"min_channels": 4, "discount_type": "percent", "discount_value": 0},
            {"min_channels": 5, "discount_type": "percent", "discount_value": 0},
        ],
        "bulk_max_channels": 50,
        "daily_bonus": 5,
        "daily_streak_bonus": 2,
        "daily_bonus_max": 25,
        "welcome_bonus": 0,
        "referral_multiplier": 1.0,
        "purchase_receipt": True,
        "purchase_notification_admin": True,
        "coin_notification": True,
        "audit_log_enabled": True,
        "health_log_enabled": True,
        "auto_cleanup_days": 0,
    }

    for key, value in defaults.items():
        if key not in settings:
            update_setting(key, value)

    indexes = [
        (daily_claims_col, [("user_id", 1)], {}),
        (audit_log_col, [("created_at", -1)], {}),
        (notification_col, [("user_id", 1), ("created_at", -1)], {}),
        (announcement_col, [("created_at", -1)], {}),
    ]

    for collection, fields, options in indexes:
        try:
            collection.create_index(fields, **options)
        except Exception:
            pass


def advanced_housekeeping():
    """Small safe cleanup job; disabled by default."""
    settings = get_settings()
    days = int(settings.get("auto_cleanup_days", 0) or 0)
    if days <= 0:
        return

    cutoff = bot_time_now() - timedelta(days=days)
    try:
        notification_col.delete_many({"created_at": {"$lt": cutoff}})
        audit_log_col.delete_many({"created_at": {"$lt": cutoff}})
    except Exception as e:
        print("Housekeeping error:", e)


def notify_purchase_to_user(user_id, amount, source, metadata=None):
    if not get_settings().get("purchase_receipt", True):
        return
    if not notification_preferences(user_id)["purchase"]:
        return

    settings = get_settings()
    source_text = str(source).replace("_", " ").title()
    details = metadata or {}
    extra = ""
    if details.get("channels"):
        extra = f"\\n📦 Channels: *{details['channels']}*"

    text = (
        "🧾 *Purchase Receipt*\\n\\n"
        f"🛒 Type: *{source_text}*\\n"
        f"💰 Paid: *{amount} {settings['coin_name']}*"
        f"{extra}\\n"
        f"🕒 Time: *{format_bot_time(bot_time_now())}*"
    )
    record_notification(user_id, "purchase", text)
    try:
        bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception:
        pass


def notify_admin_purchase(user_id, amount, source, metadata=None):
    settings = get_settings()
    if not settings.get("purchase_notification_admin", True):
        return
    details = metadata or {}
    bot.send_message(
        ADMIN_ID,
        "🛒 *New Premium Purchase*\\n\\n"
        f"👤 User: `{user_id}`\\n"
        f"💰 Amount: *{amount} {settings['coin_name']}*\\n"
        f"📦 Type: *{source}*\\n"
        f"🔢 Channels: *{details.get('channels', 1)}*",
        parse_mode="Markdown"
    )


def advanced_purchase_postprocess(user_id, amount, source, metadata=None):
    """Reusable receipt/audit hook for old and new purchase flows."""
    try:
        notify_purchase_to_user(user_id, amount, source, metadata)
    except Exception:
        pass
    try:
        notify_admin_purchase(user_id, amount, source, metadata)
    except Exception:
        pass
    try:
        write_audit(user_id, "purchase_completed", {
            "amount": amount,
            "source": source,
            **(metadata or {})
        })
    except Exception:
        pass


# Keep a scheduled housekeeping job available to the main scheduler.
# It is intentionally a no-op unless auto_cleanup_days is configured.

# =========================================================
# UNKNOWN MESSAGE FALLBACK
# =========================================================

@bot.message_handler(
    func=lambda m: not (
        m.content_type == "text" and m.text in {
            globals().get("USER_DAILY"), globals().get("USER_SPIN"), globals().get("USER_WALLET"),
            globals().get("USER_VIP"), globals().get("USER_RENEW"), globals().get("USER_GIFT"),
            globals().get("USER_NOTIFICATIONS"), globals().get("USER_DASHBOARD"), globals().get("USER_DEALS"),
            globals().get("USER_PROMOS"), globals().get("USER_HISTORY"), globals().get("USER_STATUS"),
            globals().get("USER_HELP"), globals().get("ADMIN_ADVANCED"), globals().get("ADMIN_FEATURES"),
            globals().get("ADMIN_REWARDS"), globals().get("ADMIN_VIP"), globals().get("ADMIN_DEALS"),
            globals().get("ADMIN_GROWTH"), globals().get("ADMIN_SECURITY"), globals().get("ADMIN_NOTIFY"),
            globals().get("ADMIN_RECOVERY"), globals().get("ADMIN_CAMPAIGNS"), globals().get("ADMIN_BROADCAST_TARGET"),
            globals().get("ADMIN_GIFTS"), globals().get("ADMIN_PROMOS")
        }
    ),
    content_types=["text"]
)
def unknown_message(message):

    if not message.text:
        return

    # Do not interrupt commands
    if message.text.startswith("/"):
        return

    # Admin is allowed to use admin keyboard
    if message.from_user.id == ADMIN_ID:

        if is_admin_mode(ADMIN_ID):
            return

    # Normal user guidance
    if (
        not is_banned(message.from_user.id)
        and message.from_user.id != ADMIN_ID
    ):
        bot.send_message(
            message.chat.id,
            "ℹ️ Use Me And Get Free Premium Subscription."
        )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    keep_alive()

    get_settings()
    setup_database()
    initialize_advanced_defaults()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        kick_expired_users,
        "interval",
        minutes=1,
        max_instances=1,
        replace_existing=True
    )

    scheduler.add_job(
        notify_expiring_premium,
        "interval",
        minutes=1,
        max_instances=1,
        replace_existing=True
    )

    scheduler.add_job(
        clear_pending_payments,
        "interval",
        minutes=1,
        max_instances=1,
        replace_existing=True
    )

    scheduler.add_job(
        advanced_housekeeping,
        "interval",
        hours=6,
        max_instances=1,
        replace_existing=True
    )

    scheduler.start()

    bot.remove_webhook()

    print("✅ Bot is running...")

    try:
        bot.infinity_polling(
            timeout=20,
            long_polling_timeout=10,
            skip_pending=True
        )

    except Exception as e:
        print(f"Polling error: {e}")# =========================================================
# ULTIMATE ADVANCED USER GROWTH + ADMIN CONTROL MODULE
# Added without replacing the existing systems.
# =========================================================

# Additional collections (safe because MongoDB creates them lazily)
daily_streak_col = db["daily_streaks"]
lucky_spin_col = db["lucky_spins"]
vip_col = db["vip_levels"]
flash_deals_col = db["flash_deals"]
promotions_col = db["promotions"]
gift_col = db["premium_gifts"]
recovery_col = db["recovery_notifications"]
referral_campaign_col = db["referral_campaigns"]
security_col = db["security_events"]
notification_pref_col = db["notification_preferences"]
user_coupon_col = db["personal_coupons"]
admin_config_col = db["advanced_config"]
user_activity_col = db["user_activity"]
spin_prize_col = db["spin_prizes"]

ADVANCED_DEFAULT_FLAGS = {
    "daily_checkin": True,
    "lucky_spin": True,
    "vip_levels": True,
    "flash_deals": True,
    "gift_premium": True,
    "renewal": True,
    "targeted_broadcast": True,
    "inactive_recovery": True,
    "referral_campaigns": True,
    "anti_abuse": True,
    "personal_coupons": True,
    "smart_notifications": True,
    "streak_rewards": True,
    "promotions": True,
}

ADVANCED_DEFAULT_CONFIG = {
    "daily_reward": 10,
    "streak_rewards": {1: 10, 3: 20, 7: 50, 14: 100, 30: 250},
    "daily_max_claim": 1,
    "spin_cooldown_hours": 24,
    "spin_rewards": [
        {"label": "5 Coins", "type": "coins", "value": 5, "weight": 35},
        {"label": "10 Coins", "type": "coins", "value": 10, "weight": 30},
        {"label": "25 Coins", "type": "coins", "value": 25, "weight": 18},
        {"label": "50 Coins", "type": "coins", "value": 50, "weight": 10},
        {"label": "Extra Spin", "type": "spin", "value": 1, "weight": 5},
        {"label": "Try Again", "type": "none", "value": 0, "weight": 2},
    ],
    "vip_levels": [
        {"name": "Bronze", "spend": 0, "discount": 0},
        {"name": "Silver", "spend": 500, "discount": 2},
        {"name": "Gold", "spend": 1500, "discount": 5},
        {"name": "Diamond", "spend": 5000, "discount": 10},
    ],
    "max_gift_value": 100000,
    "inactive_after_days": 7,
    "recovery_reward": 10,
    "referral_campaign_multiplier": 2,
    "flash_deal_discount": 10,
    "flash_deal_duration_hours": 2,
    "notification_expiry_hours": [24, 6, 1],
    "anti_abuse_max_referrals_per_day": 50,
}


def advanced_settings():
    settings = get_settings()
    flags = dict(settings.get("feature_flags", {}) or {})
    changed = False
    for key, value in ADVANCED_DEFAULT_FLAGS.items():
        if key not in flags:
            flags[key] = value
            changed = True
    if changed:
        update_setting("feature_flags", flags)
    config = admin_config_col.find_one({"_id": "advanced"})
    if not config:
        admin_config_col.insert_one({"_id": "advanced", **ADVANCED_DEFAULT_CONFIG})
        return dict(ADVANCED_DEFAULT_CONFIG)
    return config


def adv_flag(name):
    advanced_settings()
    return feature_enabled(name, True)


def adv_now():
    return bot_time_now()


def adv_date_key(value=None):
    value = value or adv_now()
    return value.strftime("%Y-%m-%d")


def track_activity(user_id, action="open"):
    try:
        user_activity_col.update_one(
            {"user_id": user_id},
            {"$set": {"last_seen": adv_now()}, "$inc": {f"actions.{action}": 1}},
            upsert=True,
        )
    except Exception:
        pass


def adv_add_coins(user_id, amount, reason="advanced_reward"):
    amount = int(amount)
    if amount <= 0:
        return False
    add_coins(user_id, amount)
    try:
        coin_history_col.insert_one({
            "user_id": user_id,
            "amount": amount,
            "type": "credit",
            "reason": reason,
            "created_at": adv_now(),
        })
    except Exception:
        pass
    record_notification(user_id, "coins", f"+{amount} coins: {reason}")
    return True


def adv_spend_coins(user_id, amount, reason="advanced_purchase"):
    amount = int(amount)
    if amount <= 0:
        return True
    result = bot_users_col.update_one(
        {"user_id": user_id, "coins": {"$gte": amount}, "banned": {"$ne": True}},
        {"$inc": {"coins": -amount}},
    )
    if result.modified_count != 1:
        return False
    try:
        coin_history_col.insert_one({
            "user_id": user_id,
            "amount": -amount,
            "type": "debit",
            "reason": reason,
            "created_at": adv_now(),
        })
    except Exception:
        pass
    return True


def get_vip_level(user_id):
    total = get_user_purchase_total(user_id)
    levels = sorted(advanced_settings().get("vip_levels", []), key=lambda x: int(x.get("spend", 0)))
    selected = levels[0] if levels else {"name": "Member", "spend": 0, "discount": 0}
    for level in levels:
        if total >= int(level.get("spend", 0)):
            selected = level
    return selected, total


def vip_text(user_id):
    level, total = get_vip_level(user_id)
    return f"💎 VIP: *{level.get('name', 'Member')}*\n💰 Lifetime spend: *{total} coins*\n🏷️ VIP discount: *{level.get('discount', 0)}%*"


def notification_enabled(user_id, kind="all"):
    row = notification_pref_col.find_one({"user_id": user_id}) or {}
    if row.get("disabled_all"):
        return False
    if kind != "all" and row.get(kind) is False:
        return False
    return True


def notify_user(user_id, text, kind="general", markup=None):
    record_notification(user_id, kind, text)
    if not notification_enabled(user_id, kind):
        return False
    try:
        bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")
        return True
    except Exception:
        return False


# ------------------------- USER ADVANCED KEYBOARD -------------------------
USER_DAILY = "🎁 Daily Check-in"
USER_SPIN = "🎡 Lucky Spin"
USER_WALLET = "💰 Wallet"
USER_VIP = "💎 VIP Status"
USER_RENEW = "🔄 Renew Premium"
USER_GIFT = "🎁 Gift Premium"
USER_NOTIFICATIONS = "🔔 Notifications"
USER_DASHBOARD = "📊 My Dashboard"
USER_DEALS = "⚡ Flash Deals"
USER_PROMOS = "🎉 Promotions"
USER_BACK = "🔙 Back"

# ------------------------- ADMIN ADVANCED KEYBOARD -------------------------
ADMIN_ADVANCED = "🧠 Advanced Features"
ADMIN_FEATURES = "🎛️ Feature Controls"
ADMIN_REWARDS = "🎁 Reward Settings"
ADMIN_VIP = "💎 VIP Levels"
ADMIN_DEALS = "⚡ Flash Deals"
ADMIN_GROWTH = "📈 Growth Tools"
ADMIN_SECURITY = "🛡️ Anti-Abuse"
ADMIN_NOTIFY = "🔔 Notifications"
ADMIN_RECOVERY = "♻️ User Recovery"
ADMIN_CAMPAIGNS = "🚀 Referral Campaigns"
ADMIN_BROADCAST_TARGET = "📣 Targeted Broadcast"
ADMIN_GIFTS = "🎁 Gift Manager"
ADMIN_PROMOS = "🎉 Promotions"


def ultimate_user_menu_markup(user_id=None):
    settings = get_settings()
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.row(KeyboardButton(settings["btn_profile"]), KeyboardButton(settings["btn_refer"]))
    markup.row(KeyboardButton(settings["btn_redeem"]), KeyboardButton(settings["btn_coupon"]))
    markup.row(KeyboardButton(settings["btn_referrals"]), KeyboardButton(settings["btn_milestones"]))
    markup.row(KeyboardButton(settings["btn_leaderboard"]), KeyboardButton(settings["btn_how"]))
    markup.row(KeyboardButton(settings["btn_feedback"]), KeyboardButton(settings["btn_contact"]))

    # Advanced features are compact and only appear when enabled by Admin.
    if adv_flag("daily_checkin") or adv_flag("lucky_spin"):
        row = []
        if adv_flag("daily_checkin"):
            row.append(KeyboardButton(USER_DAILY))
        if adv_flag("lucky_spin"):
            row.append(KeyboardButton(USER_SPIN))
        markup.row(*row)
    if adv_flag("flash_deals") or adv_flag("promotions"):
        row = []
        if adv_flag("flash_deals"):
            row.append(KeyboardButton(USER_DEALS))
        if adv_flag("promotions"):
            row.append(KeyboardButton(USER_PROMOS))
        markup.row(*row)
    if adv_flag("vip_levels"):
        markup.row(KeyboardButton(USER_VIP), KeyboardButton(USER_DASHBOARD))
    if adv_flag("renewal") or adv_flag("gift_premium"):
        row = []
        if adv_flag("renewal"):
            row.append(KeyboardButton(USER_RENEW))
        if adv_flag("gift_premium"):
            row.append(KeyboardButton(USER_GIFT))
        markup.row(*row)
    if adv_flag("smart_notifications"):
        markup.row(KeyboardButton(USER_NOTIFICATIONS))
    if user_id == ADMIN_ID:
        markup.row(KeyboardButton(ADMIN_PANEL_BUTTON))
    return markup

# Redefinition is intentional: existing handlers call this function at runtime.
def user_menu_markup(user_id=None):
    return ultimate_user_menu_markup(user_id)


def ultimate_admin_menu_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    # Preserve existing admin controls.
    for button in [ADMIN_CHANNELS, ADMIN_PREMIUM, ADMIN_MILESTONES, ADMIN_VERIFICATION,
                   ADMIN_USERS, ADMIN_COUPONS, ADMIN_SETTINGS, ADMIN_DASHBOARD,
                   ADMIN_PURCHASES, ADMIN_PREMIUM_BUYERS, ADMIN_USER_SEARCH,
                   ADMIN_COIN_ADD, ADMIN_SINGLE_BROADCAST, ADMIN_PREMIUM_MANAGE,
                   ADMIN_MAINTENANCE, ADMIN_MODE]:
        markup.row(KeyboardButton(button))
    markup.row(KeyboardButton(ADMIN_ADVANCED))
    markup.row(KeyboardButton(ADMIN_FEATURES), KeyboardButton(ADMIN_REWARDS))
    markup.row(KeyboardButton(ADMIN_VIP), KeyboardButton(ADMIN_DEALS))
    markup.row(KeyboardButton(ADMIN_GROWTH), KeyboardButton(ADMIN_SECURITY))
    markup.row(KeyboardButton(ADMIN_NOTIFY), KeyboardButton(ADMIN_RECOVERY))
    markup.row(KeyboardButton(ADMIN_CAMPAIGNS), KeyboardButton(ADMIN_BROADCAST_TARGET))
    markup.row(KeyboardButton(ADMIN_GIFTS), KeyboardButton(ADMIN_PROMOS))
    return markup


def admin_menu_markup():
    return ultimate_admin_menu_markup()



# ------------------------- PROMOTIONAL CAMPAIGN SYSTEM -------------------------
def promo_now():
    try:
        return bot_time_now()
    except Exception:
        return datetime.now(ZoneInfo("Asia/Kathmandu"))


def get_active_promotions(limit=20):
    now = promo_now()
    return list(promotions_col.find({
        "enabled": True,
        "$or": [
            {"start_at": {"$exists": False}},
            {"start_at": {"$lte": now}}
        ],
        "end_at": {"$gte": now}
    }).sort("created_at", DESCENDING).limit(limit))


def promotion_text(p):
    ptype = p.get("type", "coins")
    value = p.get("value", 0)
    if ptype == "coins":
        reward = f"🪙 +{int(value)} {get_settings().get('coin_name', 'coins')}"
    elif ptype == "discount":
        reward = f"🏷️ {float(value):g}% Premium discount"
    elif ptype == "spin":
        reward = f"🎡 +{int(value)} Lucky Spin(s)"
    else:
        reward = str(value)
    return (
        f"🎉 *{p.get('title', 'Promotion')}*\n\n"
        f"{p.get('description', 'Limited-time promotion.')}\n\n"
        f"🎁 Reward: *{reward}*\n"
        f"👥 Remaining uses: *{max(0, int(p.get('max_uses', 0)) - int(p.get('used_count', 0)))}*\n"
        f"⏰ Ends: *{format_bot_time(p.get('end_at'))}*"
    )


def promotion_user_markup(p):
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton("🎁 Claim Promotion", callback_data=f"promo:claim:{p['_id']}")
    )


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_PROMOS)
def user_promotions(message):
    if not adv_flag("promotions"):
        bot.send_message(message.chat.id, "🚫 Promotions are currently disabled by Admin.")
        return
    promos = get_active_promotions()
    if not promos:
        bot.send_message(message.chat.id, "🎉 *Promotions*\n\nNo active promotions right now. Check again later!", parse_mode="Markdown")
        return
    bot.send_message(message.chat.id, "🎉 *ACTIVE PROMOTIONS*\n\nChoose an offer below:", parse_mode="Markdown")
    for promo in promos:
        bot.send_message(message.chat.id, promotion_text(promo), reply_markup=promotion_user_markup(promo), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data.startswith("promo:claim:"))
def claim_promotion(call):
    if not adv_flag("promotions"):
        bot.answer_callback_query(call.id, "Promotions disabled.", show_alert=True)
        return
    try:
        promo_id = ObjectId(call.data.split(":", 2)[2])
    except Exception:
        bot.answer_callback_query(call.id, "Invalid promotion.", show_alert=True)
        return
    uid = call.from_user.id
    now = promo_now()
    promo = promotions_col.find_one({"_id": promo_id, "enabled": True, "end_at": {"$gte": now}})
    if not promo:
        bot.answer_callback_query(call.id, "This promotion has ended.", show_alert=True)
        return
    max_uses = int(promo.get("max_uses", 0) or 0)
    used = int(promo.get("used_count", 0) or 0)
    if max_uses > 0 and used >= max_uses:
        bot.answer_callback_query(call.id, "This promotion is fully claimed.", show_alert=True)
        return
    if promotions_col.find_one({"_id": promo_id, "claimed_users": uid}):
        bot.answer_callback_query(call.id, "You already claimed this promotion.", show_alert=True)
        return
    # Atomically reserve one use and record the user.
    query = {"_id": promo_id, "enabled": True, "end_at": {"$gte": now}}
    if max_uses > 0:
        query["used_count"] = {"$lt": max_uses}
    result = promotions_col.update_one(query, {"$inc": {"used_count": 1}, "$addToSet": {"claimed_users": uid}})
    if result.modified_count != 1:
        bot.answer_callback_query(call.id, "Promotion is no longer available.", show_alert=True)
        return
    ptype = promo.get("type", "coins")
    value = int(promo.get("value", 0) or 0)
    if ptype == "coins" and value > 0:
        adv_add_coins(uid, value, f"promotion: {promo.get('title', 'Promotion')}")
        result_text = f"🎉 *Promotion Claimed!*\n\n🪙 You received *+{value} {get_settings().get('coin_name', 'coins')}*."
    elif ptype == "spin" and value > 0:
        user_doc = bot_users_col.find_one({"user_id": uid}) or {}
        current = int(user_doc.get("promo_spins", 0) or 0)
        bot_users_col.update_one({"user_id": uid}, {"$set": {"promo_spins": current + value}}, upsert=True)
        result_text = f"🎉 *Promotion Claimed!*\n\n🎡 You received *+{value} Lucky Spin(s)*."
    elif ptype == "discount":
        # Store the promotion as a temporary discount entitlement. Redemption code can consume it.
        bot_users_col.update_one({"user_id": uid}, {"$set": {"promo_discount": float(value), "promo_discount_id": promo_id, "promo_discount_expires": promo.get("end_at")}}, upsert=True)
        result_text = f"🎉 *Promotion Claimed!*\n\n🏷️ You received a *{float(value):g}% Premium discount* until *{format_bot_time(promo.get('end_at'))}*."
    else:
        result_text = "🎉 *Promotion Claimed!*\n\nYour promotional reward has been added."
    bot.answer_callback_query(call.id, "Promotion claimed!")
    bot.send_message(uid, result_text, parse_mode="Markdown")
    try:
        write_audit(uid, "promotion_claimed", {"promotion_id": str(promo_id), "type": ptype, "value": value})
    except Exception:
        pass


# ------------------------- PROMOTION ADMIN -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_PROMOS)
def admin_promotions_menu(message):
    rows = list(promotions_col.find().sort("created_at", DESCENDING).limit(15))
    text = "🎉 *PROMOTION MANAGER*\n\n"
    if not rows:
        text += "No promotions created yet.\n"
    for p in rows:
        state = "ON" if p.get("enabled") else "OFF"
        text += f"• `{p.get('_id')}` — *{p.get('title','Promotion')}* — {p.get('type','coins')} {p.get('value',0)} — {state}\n"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("➕ Create", callback_data="promoadmin:create"), InlineKeyboardButton("🗑️ Delete", callback_data="promoadmin:delete"))
    markup.row(InlineKeyboardButton("🔄 Toggle", callback_data="promoadmin:toggle"), InlineKeyboardButton("📊 Stats", callback_data="promoadmin:stats"))
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("promoadmin:"))
def promotion_admin_callback(call):
    action = call.data.split(":", 1)[1]
    if action == "create":
        msg = bot.send_message(call.message.chat.id, "Send:\n`Title | Description | type | value | max_uses | hours`\n\nType: `coins`, `discount`, or `spin`. Use max_uses=0 for unlimited.", parse_mode="Markdown")
        bot.register_next_step_handler(msg, create_promotion)
    elif action == "delete":
        msg = bot.send_message(call.message.chat.id, "Send the promotion ObjectId to delete:")
        bot.register_next_step_handler(msg, delete_promotion)
    elif action == "toggle":
        msg = bot.send_message(call.message.chat.id, "Send the promotion ObjectId to toggle:")
        bot.register_next_step_handler(msg, toggle_promotion)
    elif action == "stats":
        rows = list(promotions_col.find().sort("used_count", DESCENDING).limit(10))
        text = "📊 *PROMOTION STATS*\n\n" + ("\n".join(f"• {p.get('title','Promotion')}: *{p.get('used_count',0)} claimed*" for p in rows) if rows else "No promotions yet.")
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


def create_promotion(message):
    try:
        title, description, ptype, value, max_uses, hours = [x.strip() for x in message.text.split("|", 5)]
        ptype = ptype.lower()
        if ptype not in ("coins", "discount", "spin"):
            raise ValueError("type")
        value = float(value)
        if value < 0:
            raise ValueError("value")
        max_uses = int(max_uses)
        hours = float(hours)
        if hours <= 0:
            raise ValueError("hours")
        now = promo_now()
        doc = {"title": title[:80], "description": description[:500], "type": ptype, "value": value, "max_uses": max_uses, "used_count": 0, "claimed_users": [], "start_at": now, "end_at": now + timedelta(hours=hours), "enabled": True, "created_at": now, "created_by": ADMIN_ID}
        promotions_col.insert_one(doc)
        write_audit(ADMIN_ID, "promotion_created", {"title": title, "type": ptype, "value": value})
        bot.send_message(message.chat.id, "✅ Promotion created and activated.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid format. Example:\n`Weekend Bonus | Get extra coins today | coins | 50 | 100 | 24`", parse_mode="Markdown")


def delete_promotion(message):
    try:
        result = promotions_col.delete_one({"_id": ObjectId(message.text.strip())})
        bot.send_message(message.chat.id, "✅ Promotion deleted." if result.deleted_count else "❌ Promotion not found.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid ObjectId.")


def toggle_promotion(message):
    try:
        oid = ObjectId(message.text.strip())
        row = promotions_col.find_one({"_id": oid})
        if not row:
            bot.send_message(message.chat.id, "❌ Promotion not found.")
            return
        new_state = not bool(row.get("enabled"))
        promotions_col.update_one({"_id": oid}, {"$set": {"enabled": new_state}})
        bot.send_message(message.chat.id, f"✅ Promotion is now {'ON' if new_state else 'OFF'}.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid ObjectId.")


# ------------------------- DAILY CHECK-IN + STREAK -------------------------
@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_DAILY)
def advanced_daily_checkin(message):
    if not adv_flag("daily_checkin"):
        bot.send_message(message.chat.id, "🚫 Daily Check-in is currently disabled by Admin.")
        return
    user_id = message.from_user.id
    register_user(message.from_user)
    now = adv_now()
    key = adv_date_key(now)
    row = daily_streak_col.find_one({"user_id": user_id}) or {}
    if row.get("last_claim_key") == key:
        streak = int(row.get("streak", 1))
        bot.send_message(message.chat.id, f"⏳ You already claimed today's reward.\n\n🔥 Current streak: *{streak} days*", parse_mode="Markdown")
        return
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = int(row.get("streak", 0)) + 1 if row.get("last_claim_key") == yesterday else 1
    cfg = advanced_settings()
    base = int(cfg.get("daily_reward", 10))
    streak_rewards = {int(k): int(v) for k, v in (cfg.get("streak_rewards", {}) or {}).items()}
    reward = streak_rewards.get(streak, base)
    daily_streak_col.update_one({"user_id": user_id}, {"$set": {"last_claim_key": key, "streak": streak, "claimed_at": now}, "$inc": {"total_claims": 1}}, upsert=True)
    adv_add_coins(user_id, reward, f"daily check-in (streak {streak})")
    bot.send_message(message.chat.id, f"🎁 *Daily Check-in Claimed!*\n\n🔥 Streak: *{streak} days*\n🪙 Reward: *{reward} coins*\n\nCome back tomorrow to keep your streak!", parse_mode="Markdown")


# ------------------------- LUCKY SPIN -------------------------
def weighted_spin(rewards):
    import random
    valid = [r for r in rewards if int(r.get("weight", 0)) > 0]
    total = sum(int(r.get("weight", 0)) for r in valid)
    if total <= 0:
        return {"label": "Try Again", "type": "none", "value": 0, "weight": 1}
    pick = random.randint(1, total)
    running = 0
    for reward in valid:
        running += int(reward.get("weight", 0))
        if pick <= running:
            return reward
    return valid[-1]


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_SPIN)
def advanced_lucky_spin(message):
    if not adv_flag("lucky_spin"):
        bot.send_message(message.chat.id, "🚫 Lucky Spin is currently disabled by Admin.")
        return
    user_id = message.from_user.id
    register_user(message.from_user)
    now = adv_now()
    cfg = advanced_settings()
    cooldown = int(cfg.get("spin_cooldown_hours", 24))
    row = lucky_spin_col.find_one({"user_id": user_id}) or {}
    extra = int(row.get("extra_spins", 0))
    last = row.get("last_spin")
    if last and isinstance(last, datetime) and now - last < timedelta(hours=cooldown) and extra <= 0:
        remaining = timedelta(hours=cooldown) - (now - last)
        hours = max(0, int(remaining.total_seconds() // 3600))
        bot.send_message(message.chat.id, f"⏳ Your next free spin is available in about *{hours}h*.\n\n🎡 Come back later!", parse_mode="Markdown")
        return
    reward = weighted_spin(cfg.get("spin_rewards", []))
    update = {"last_spin": now}
    if extra > 0:
        update["extra_spins"] = extra - 1
    lucky_spin_col.update_one({"user_id": user_id}, {"$set": update, "$inc": {"total_spins": 1}}, upsert=True)
    kind = reward.get("type")
    value = int(reward.get("value", 0))
    if kind == "coins" and value:
        adv_add_coins(user_id, value, "lucky spin")
    elif kind == "spin":
        lucky_spin_col.update_one({"user_id": user_id}, {"$inc": {"extra_spins": value}}, upsert=True)
    bot.send_message(message.chat.id, f"🎡 *Lucky Spin Result*\n\n🎉 You got: *{reward.get('label', 'Try Again')}*\n\n{('🪙 Reward added to your balance.' if kind == 'coins' else '🔥 Extra spin added!' if kind == 'spin' else '😄 Better luck next time!')}", parse_mode="Markdown")


# ------------------------- WALLET / VIP / DASHBOARD -------------------------
@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_WALLET)
def advanced_wallet(message):
    user_id = message.from_user.id
    register_user(message.from_user)
    user = get_user(user_id) or {}
    unread = get_unread_notifications(user_id)
    level, total = get_vip_level(user_id)
    bot.send_message(message.chat.id, f"💰 *Wallet*\n\n🪙 Balance: *{get_coin_balance(user_id)} coins*\n💎 VIP: *{level.get('name', 'Member')}*\n📈 Lifetime spend: *{total} coins*\n🔔 Unread notifications: *{unread}*", parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_VIP)
def advanced_vip(message):
    if not adv_flag("vip_levels"):
        bot.send_message(message.chat.id, "🚫 VIP system is disabled by Admin.")
        return
    bot.send_message(message.chat.id, "💎 *VIP Status*\n\n" + vip_text(message.from_user.id) + "\n\nHigher levels can receive better promotions and discounts.", parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_DASHBOARD)
def advanced_dashboard(message):
    user_id = message.from_user.id
    register_user(message.from_user)
    u = get_user(user_id) or {}
    purchases = get_user_purchase_count(user_id)
    referrals = get_user_referral_count(user_id)
    level, spend = get_vip_level(user_id)
    streak = (daily_streak_col.find_one({"user_id": user_id}) or {}).get("streak", 0)
    spins = (lucky_spin_col.find_one({"user_id": user_id}) or {}).get("total_spins", 0)
    bot.send_message(message.chat.id, f"📊 *My Dashboard*\n\n🪙 Coins: *{get_coin_balance(user_id)}*\n💎 VIP: *{level.get('name', 'Member')}*\n💰 Lifetime spend: *{spend}*\n📦 Purchases: *{purchases}*\n👥 Referrals: *{referrals}*\n🔥 Check-in streak: *{streak} days*\n🎡 Spins used: *{spins}*\n🔔 Notifications: *{get_unread_notifications(user_id)} unread*", parse_mode="Markdown")


# ------------------------- NOTIFICATION CENTER -------------------------
@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_NOTIFICATIONS)
def advanced_notifications(message):
    user_id = message.from_user.id
    rows = list(notification_col.find({"user_id": user_id}).sort("created_at", DESCENDING).limit(10))
    if not rows:
        bot.send_message(message.chat.id, "🔔 *Notifications*\n\nYou have no notifications.", parse_mode="Markdown")
        return
    text = "🔔 *Recent Notifications*\n\n"
    for row in rows:
        when = format_bot_time(row.get("created_at"))
        text += f"• {row.get('text', '')}\n🕒 {when}\n\n"
    mark_notifications_read(user_id)
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


# ------------------------- FLASH DEALS -------------------------
def get_active_flash_deals():
    now = adv_now()
    return list(flash_deals_col.find({"enabled": True, "start_at": {"$lte": now}, "end_at": {"$gte": now}}).sort("created_at", DESCENDING))


@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_DEALS)
def advanced_flash_deals(message):
    if not adv_flag("flash_deals"):
        bot.send_message(message.chat.id, "🚫 Flash Deals are disabled by Admin.")
        return
    deals = get_active_flash_deals()
    if not deals:
        bot.send_message(message.chat.id, "⚡ *Flash Deals*\n\nNo active deals right now. Check again later!", parse_mode="Markdown")
        return
    text = "⚡ *ACTIVE FLASH DEALS*\n\n"
    for d in deals:
        text += f"🔥 *{d.get('title', 'Special Deal')}*\n🏷️ Discount: *{d.get('discount', 0)}%*\n⏰ Ends: *{format_bot_time(d.get('end_at'))}*\n\n"
    bot.send_message(message.chat.id, text + "Tap 🎁 Redeem Premium to purchase while the deal is active.", parse_mode="Markdown")


# ------------------------- GIFT PREMIUM: coin gifting -------------------------
@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_GIFT)
def gift_premium_start(message):
    if not adv_flag("gift_premium"):
        bot.send_message(message.chat.id, "🚫 Gift Premium is disabled by Admin.")
        return
    msg = bot.send_message(message.chat.id, "🎁 *Gift Premium*\n\nSend the recipient's Telegram username (example: @username).", parse_mode="Markdown")
    bot.register_next_step_handler(msg, gift_premium_username)


def gift_premium_username(message):
    username = (message.text or "").strip().lstrip("@").lower()
    if not username:
        bot.send_message(message.chat.id, "❌ Invalid username.")
        return
    recipient = bot_users_col.find_one({"username": username}) or bot_users_col.find_one({"username": "@" + username})
    if not recipient:
        bot.send_message(message.chat.id, "❌ This user has not started the bot yet. Ask them to start the bot first.")
        return
    msg = bot.send_message(message.chat.id, "Send the amount of coins you want to gift: ")
    bot.register_next_step_handler(msg, lambda m: process_coin_gift(m, int(recipient.get("user_id"))))


def process_coin_gift(message, recipient_id):
    try:
        amount = int(message.text.strip())
    except Exception:
        bot.send_message(message.chat.id, "❌ Enter a valid whole number.")
        return
    if amount <= 0 or amount > int(advanced_settings().get("max_gift_value", 100000)):
        bot.send_message(message.chat.id, "❌ Gift amount is outside the allowed range.")
        return
    sender = message.from_user.id
    if sender == recipient_id:
        bot.send_message(sender, "❌ You cannot gift coins to yourself.")
        return
    if not adv_spend_coins(sender, amount, "gift to user"):
        bot.send_message(sender, "❌ Insufficient coins.")
        return
    adv_add_coins(recipient_id, amount, "received coin gift")
    gift_col.insert_one({"sender_id": sender, "recipient_id": recipient_id, "amount": amount, "created_at": adv_now(), "type": "coins"})
    bot.send_message(sender, f"✅ *Gift sent!*\n\n🪙 {amount} coins were sent successfully.", parse_mode="Markdown")
    notify_user(recipient_id, f"🎁 *You received a gift!*\n\n🪙 *{amount} coins* were sent to you.", "gift")


# ------------------------- ADMIN ADVANCED HUB -------------------------
def advanced_admin_text():
    cfg = advanced_settings()
    flags = get_settings().get("feature_flags", {}) or {}
    enabled = sum(1 for k in ADVANCED_DEFAULT_FLAGS if flags.get(k, True))
    deals = len(get_active_flash_deals())
    active_campaigns = referral_campaign_col.count_documents({"enabled": True})
    return f"🧠 *ADVANCED CONTROL CENTER*\n\n🎛️ Advanced systems enabled: *{enabled}/{len(ADVANCED_DEFAULT_FLAGS)}*\n⚡ Active flash deals: *{deals}*\n🚀 Campaigns: *{active_campaigns}*\n🛡️ Security events: *{security_col.count_documents({})}*\n👤 Registered users: *{bot_users_col.count_documents({})}*\n\nEverything below is controlled through Admin buttons."


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_ADVANCED)
def advanced_admin_hub(message):
    bot.send_message(message.chat.id, advanced_admin_text(), reply_markup=advanced_admin_inline(), parse_mode="Markdown")


def advanced_admin_inline():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("🎛️ Features", callback_data="adv:features"), InlineKeyboardButton("🎁 Rewards", callback_data="adv:rewards"))
    markup.row(InlineKeyboardButton("💎 VIP", callback_data="adv:vip"), InlineKeyboardButton("⚡ Deals", callback_data="adv:deals"))
    markup.row(InlineKeyboardButton("📈 Growth", callback_data="adv:growth"), InlineKeyboardButton("🛡️ Security", callback_data="adv:security"))
    markup.row(InlineKeyboardButton("🔔 Notifications", callback_data="adv:notify"), InlineKeyboardButton("♻️ Recovery", callback_data="adv:recovery"))
    markup.row(InlineKeyboardButton("🚀 Campaigns", callback_data="adv:campaigns"), InlineKeyboardButton("📣 Target Broadcast", callback_data="adv:targetbroadcast"))
    return markup


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("adv:"))
def advanced_admin_callback(call):
    section = call.data.split(":", 1)[1]
    if section == "features":
        advanced_feature_control(call.message.chat.id)
    elif section == "rewards":
        advanced_rewards_control(call.message.chat.id)
    elif section == "vip":
        advanced_vip_control(call.message.chat.id)
    elif section == "deals":
        advanced_deals_control(call.message.chat.id)
    elif section == "growth":
        advanced_growth_control(call.message.chat.id)
    elif section == "security":
        advanced_security_control(call.message.chat.id)
    elif section == "notify":
        advanced_notify_control(call.message.chat.id)
    elif section == "recovery":
        advanced_recovery_control(call.message.chat.id)
    elif section == "campaigns":
        advanced_campaign_control(call.message.chat.id)
    elif section == "targetbroadcast":
        advanced_target_broadcast_info(call.message.chat.id)
    bot.answer_callback_query(call.id)


# ------------------------- FEATURE TOGGLE KEYBOARD -------------------------
def feature_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    flags = get_settings().get("feature_flags", {}) or {}
    items = list(ADVANCED_DEFAULT_FLAGS.keys())
    for i in range(0, len(items), 2):
        row = []
        for name in items[i:i+2]:
            state = "ON" if flags.get(name, True) else "OFF"
            row.append(InlineKeyboardButton(f"{'🟢' if state == 'ON' else '🔴'} {name.replace('_',' ').title()}: {state}", callback_data=f"advflag:{name}"))
        markup.row(*row)
    return markup


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_FEATURES)
def advanced_feature_menu(message):
    advanced_feature_control(message.chat.id)


def advanced_feature_control(chat_id):
    bot.send_message(chat_id, "🎛️ *FEATURE CONTROLS*\n\nTap any button to turn that feature ON/OFF. Changes apply immediately to the user panel.", reply_markup=feature_keyboard(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("advflag:"))
def advanced_toggle_flag(call):
    name = call.data.split(":", 1)[1]
    current = feature_enabled(name, True)
    set_feature(name, not current)
    bot.answer_callback_query(call.id, f"{name}: {'ON' if not current else 'OFF'}")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=feature_keyboard())
    except Exception:
        pass


# ------------------------- ADMIN REWARD SETTINGS -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_REWARDS)
def advanced_rewards_menu(message):
    advanced_rewards_control(message.chat.id)


def advanced_rewards_control(chat_id):
    cfg = advanced_settings()
    text = f"🎁 *REWARD SETTINGS*\n\n🪙 Daily reward: *{cfg.get('daily_reward', 10)}*\n🔥 Streak rewards: *{cfg.get('streak_rewards', {})}*\n🎡 Spin cooldown: *{cfg.get('spin_cooldown_hours', 24)} hours*\n\nUse the buttons to change values."
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("🪙 Daily Reward", callback_data="advset:daily"), InlineKeyboardButton("🔥 Streaks", callback_data="advset:streak"))
    markup.row(InlineKeyboardButton("🎡 Spin Cooldown", callback_data="advset:spin"), InlineKeyboardButton("🎡 Spin Rewards", callback_data="advset:spinrewards"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("advset:"))
def advanced_reward_setting_callback(call):
    key = call.data.split(":", 1)[1]
    prompts = {
        "daily": "Send the new daily coin reward:",
        "spin": "Send Lucky Spin cooldown in hours:",
        "streak": "Send streak rewards like `1=10,3=25,7=100,30=500`:",
        "spinrewards": "Send spin rewards like `5:coins:35,10:coins:30,25:coins:10,1:spin:5` where last value is weight:",
    }
    msg = bot.send_message(call.message.chat.id, prompts.get(key, "Send the new value:"), parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: save_advanced_setting(m, key))
    bot.answer_callback_query(call.id)


def save_advanced_setting(message, key):
    cfg = advanced_settings()
    try:
        if key == "daily":
            cfg["daily_reward"] = max(0, int(message.text.strip()))
        elif key == "spin":
            cfg["spin_cooldown_hours"] = max(1, int(message.text.strip()))
        elif key == "streak":
            data = {}
            for item in message.text.split(","):
                k, v = item.strip().split("=", 1)
                data[int(k)] = int(v)
            cfg["streak_rewards"] = data
        elif key == "spinrewards":
            arr = []
            for item in message.text.split(","):
                value, typ, weight = item.strip().split(":")
                arr.append({"label": f"{value} {typ}", "type": typ, "value": int(value), "weight": int(weight)})
            cfg["spin_rewards"] = arr
        admin_config_col.update_one({"_id": "advanced"}, {"$set": cfg}, upsert=True)
        write_audit(ADMIN_ID, "advanced_setting_changed", {"key": key})
        bot.send_message(message.chat.id, "✅ Setting updated successfully.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Invalid format. Nothing was changed.\n\n{e}")


# ------------------------- VIP ADMIN -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_VIP)
def advanced_vip_menu(message):
    advanced_vip_control(message.chat.id)


def advanced_vip_control(chat_id):
    levels = sorted(advanced_settings().get("vip_levels", []), key=lambda x: int(x.get("spend", 0)))
    text = "💎 *VIP LEVELS*\n\n"
    for level in levels:
        text += f"• *{level.get('name')}* — spend {level.get('spend',0)}, discount {level.get('discount',0)}%\n"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✏️ Replace VIP Levels", callback_data="vipadmin:replace"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "vipadmin:replace")
def vip_replace_prompt(call):
    msg = bot.send_message(call.message.chat.id, "Send levels like `Bronze=0=0,Silver=500=2,Gold=1500=5,Diamond=5000=10`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, save_vip_levels)
    bot.answer_callback_query(call.id)


def save_vip_levels(message):
    try:
        levels = []
        for item in message.text.split(","):
            name, spend, discount = item.strip().split("=")
            levels.append({"name": name, "spend": int(spend), "discount": float(discount)})
        levels.sort(key=lambda x: x["spend"])
        admin_config_col.update_one({"_id": "advanced"}, {"$set": {"vip_levels": levels}}, upsert=True)
        bot.send_message(message.chat.id, "✅ VIP levels updated.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid format. Example: Bronze=0=0,Silver=500=2,Gold=1500=5")


# ------------------------- FLASH DEAL ADMIN -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_DEALS)
def advanced_deals_menu(message):
    advanced_deals_control(message.chat.id)


def advanced_deals_control(chat_id):
    deals = list(flash_deals_col.find().sort("created_at", DESCENDING).limit(10))
    text = "⚡ *FLASH DEAL MANAGER*\n\n"
    if not deals:
        text += "No deals created yet.\n"
    for d in deals:
        text += f"• {d.get('title')} — {d.get('discount')}% — {'ON' if d.get('enabled') else 'OFF'}\n"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("➕ Create Deal", callback_data="dealadmin:create"), InlineKeyboardButton("🗑️ Delete Deal", callback_data="dealadmin:delete"))
    markup.row(InlineKeyboardButton("🔄 Toggle Deal", callback_data="dealadmin:toggle"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("dealadmin:"))
def deal_admin_callback(call):
    action = call.data.split(":", 1)[1]
    if action == "create":
        msg = bot.send_message(call.message.chat.id, "Send: `Title | discount% | duration_hours`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, create_flash_deal)
    elif action == "delete":
        msg = bot.send_message(call.message.chat.id, "Send the deal ObjectId to delete:")
        bot.register_next_step_handler(msg, delete_flash_deal)
    elif action == "toggle":
        msg = bot.send_message(call.message.chat.id, "Send the deal ObjectId to toggle:")
        bot.register_next_step_handler(msg, toggle_flash_deal)
    bot.answer_callback_query(call.id)


def create_flash_deal(message):
    try:
        title, discount, hours = [x.strip() for x in message.text.split("|")]
        hours = float(hours)
        now = adv_now()
        doc = {"title": title, "discount": float(discount), "start_at": now, "end_at": now + timedelta(hours=hours), "enabled": True, "created_at": now, "created_by": ADMIN_ID}
        flash_deals_col.insert_one(doc)
        write_audit(ADMIN_ID, "flash_deal_created", {"title": title})
        bot.send_message(message.chat.id, "✅ Flash deal created and activated.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid format.")


def delete_flash_deal(message):
    try:
        result = flash_deals_col.delete_one({"_id": ObjectId(message.text.strip())})
        bot.send_message(message.chat.id, "✅ Deleted." if result.deleted_count else "❌ Deal not found.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid ObjectId.")


def toggle_flash_deal(message):
    try:
        row = flash_deals_col.find_one({"_id": ObjectId(message.text.strip())})
        if not row:
            bot.send_message(message.chat.id, "❌ Deal not found.")
            return
        new = not bool(row.get("enabled"))
        flash_deals_col.update_one({"_id": row["_id"]}, {"$set": {"enabled": new}})
        bot.send_message(message.chat.id, f"✅ Deal is now {'ON' if new else 'OFF'}.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid ObjectId.")


# ------------------------- GROWTH TOOLS -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_GROWTH)
def advanced_growth_menu(message):
    advanced_growth_control(message.chat.id)


def advanced_growth_control(chat_id):
    users = bot_users_col.count_documents({})
    active7 = user_activity_col.count_documents({"last_seen": {"$gte": adv_now() - timedelta(days=7)}})
    purchases = purchase_history_col.count_documents({})
    referrals = bot_users_col.aggregate([{"$group": {"_id": None, "total": {"$sum": "$referral_count"}}}])
    ref_total = next(referrals, {}).get("total", 0)
    text = f"📈 *GROWTH CENTER*\n\n👤 Users: *{users}*\n🟢 Active 7d: *{active7}*\n📦 Purchases: *{purchases}*\n👥 Successful referrals: *{ref_total}*\n\nUse targeted broadcast and referral campaigns to grow the community."
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🚀 Create Referral Campaign", callback_data="campaignadmin:create"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


# ------------------------- REFERRAL CAMPAIGNS -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_CAMPAIGNS)
def advanced_campaign_menu(message):
    advanced_campaign_control(message.chat.id)


def advanced_campaign_control(chat_id):
    rows = list(referral_campaign_col.find().sort("created_at", DESCENDING).limit(10))
    text = "🚀 *REFERRAL CAMPAIGNS*\n\n"
    for r in rows:
        text += f"• {r.get('title')} — x{r.get('multiplier',1)} — {'ON' if r.get('enabled') else 'OFF'}\n"
    if not rows:
        text += "No campaigns created.\n"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Create Campaign", callback_data="campaignadmin:create"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "campaignadmin:create")
def create_campaign_prompt(call):
    msg = bot.send_message(call.message.chat.id, "Send: `Title | multiplier | duration_hours`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, create_referral_campaign)
    bot.answer_callback_query(call.id)


def create_referral_campaign(message):
    try:
        title, multiplier, hours = [x.strip() for x in message.text.split("|")]
        now = adv_now()
        referral_campaign_col.insert_one({"title": title, "multiplier": float(multiplier), "start_at": now, "end_at": now + timedelta(hours=float(hours)), "enabled": True, "created_at": now})
        bot.send_message(message.chat.id, "✅ Referral campaign activated.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid campaign format.")


def active_referral_multiplier():
    now = adv_now()
    rows = list(referral_campaign_col.find({"enabled": True, "start_at": {"$lte": now}, "end_at": {"$gte": now}}))
    return max([float(r.get("multiplier", 1)) for r in rows] or [1])


# ------------------------- SECURITY / ANTI ABUSE -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_SECURITY)
def advanced_security_menu(message):
    advanced_security_control(message.chat.id)


def advanced_security_control(chat_id):
    cfg = advanced_settings()
    recent = list(security_col.find().sort("created_at", DESCENDING).limit(10))
    text = f"🛡️ *ANTI-ABUSE CENTER*\n\n📌 Referral daily limit: *{cfg.get('anti_abuse_max_referrals_per_day',50)}*\n🚨 Recent security events: *{security_col.count_documents({})}*\n\n"
    for r in recent:
        text += f"• {r.get('type')} — `{r.get('user_id')}` — {format_bot_time(r.get('created_at'))}\n"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✏️ Set Referral Limit", callback_data="security:setlimit"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "security:setlimit")
def security_limit_prompt(call):
    msg = bot.send_message(call.message.chat.id, "Send maximum successful referrals allowed per user per day:")
    bot.register_next_step_handler(msg, save_security_limit)
    bot.answer_callback_query(call.id)


def save_security_limit(message):
    try:
        value = max(1, int(message.text.strip()))
        admin_config_col.update_one({"_id": "advanced"}, {"$set": {"anti_abuse_max_referrals_per_day": value}}, upsert=True)
        bot.send_message(message.chat.id, f"✅ Daily referral limit set to {value}.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid number.")


def security_referral_allowed(user_id):
    if not adv_flag("anti_abuse"):
        return True
    cfg = advanced_settings()
    key = adv_date_key()
    count = security_col.count_documents({"type": "referral", "user_id": user_id, "date_key": key})
    limit = int(cfg.get("anti_abuse_max_referrals_per_day", 50))
    return count < limit


# ------------------------- TARGETED BROADCAST -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_BROADCAST_TARGET)
def advanced_target_broadcast_menu(message):
    advanced_target_broadcast_info(message.chat.id)


def advanced_target_broadcast_info(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("👥 All Users", callback_data="tb:all"), InlineKeyboardButton("💎 Premium", callback_data="tb:premium"))
    markup.row(InlineKeyboardButton("⌛ Expired", callback_data="tb:expired"), InlineKeyboardButton("🔥 Active 7d", callback_data="tb:active7"))
    markup.row(InlineKeyboardButton("🪙 Coins > 0", callback_data="tb:coins"), InlineKeyboardButton("👥 Referrers", callback_data="tb:referrers"))
    bot.send_message(chat_id, "📣 *TARGETED BROADCAST*\n\nChoose your audience. The next message you send will be broadcast to that segment.", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("tb:"))
def target_broadcast_select(call):
    segment = call.data.split(":", 1)[1]
    admin_config_col.update_one({"_id": "advanced"}, {"$set": {"broadcast_segment": segment}}, upsert=True)
    msg = bot.send_message(call.message.chat.id, f"📣 Segment selected: *{segment}*\n\nSend the broadcast message now.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, send_targeted_broadcast)
    bot.answer_callback_query(call.id)


def targeted_user_cursor(segment):
    now = adv_now()
    if segment == "all":
        return bot_users_col.find({"banned": {"$ne": True}})
    if segment == "premium":
        ids = users_col.distinct("user_id", {"expiry": {"$gt": now.timestamp()}})
        return bot_users_col.find({"user_id": {"$in": ids}, "banned": {"$ne": True}})
    if segment == "expired":
        ids = users_col.distinct("user_id", {"expiry": {"$lte": now.timestamp()}})
        return bot_users_col.find({"user_id": {"$in": ids}, "banned": {"$ne": True}})
    if segment == "active7":
        return bot_users_col.find({"last_seen": {"$gte": now - timedelta(days=7)}, "banned": {"$ne": True}})
    if segment == "coins":
        return bot_users_col.find({"coins": {"$gt": 0}, "banned": {"$ne": True}})
    if segment == "referrers":
        return bot_users_col.find({"referral_count": {"$gt": 0}, "banned": {"$ne": True}})
    return bot_users_col.find({"banned": {"$ne": True}})


def send_targeted_broadcast(message):
    segment = (admin_config_col.find_one({"_id": "advanced"}) or {}).get("broadcast_segment", "all")
    text = message.text or ""
    sent = 0
    failed = 0
    for user in targeted_user_cursor(segment):
        uid = user.get("user_id")
        if not uid:
            continue
        try:
            bot.send_message(uid, text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
    write_audit(ADMIN_ID, "targeted_broadcast", {"segment": segment, "sent": sent, "failed": failed})
    bot.send_message(message.chat.id, f"✅ Broadcast completed.\n\n📣 Segment: {segment}\n✅ Sent: {sent}\n❌ Failed: {failed}")


# ------------------------- RECOVERY / RE-ENGAGEMENT -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_RECOVERY)
def advanced_recovery_menu(message):
    advanced_recovery_control(message.chat.id)


def advanced_recovery_control(chat_id):
    cfg = advanced_settings()
    days = int(cfg.get("inactive_after_days", 7))
    reward = int(cfg.get("recovery_reward", 10))
    count = bot_users_col.count_documents({"last_seen": {"$lt": adv_now() - timedelta(days=days)}, "banned": {"$ne": True}})
    text = f"♻️ *USER RECOVERY*\n\n⏳ Inactive after: *{days} days*\n🎁 Return reward: *{reward} coins*\n👤 Current inactive users: *{count}*\n\nThe system can send one re-engagement message per inactive user."
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📣 Send Recovery Campaign", callback_data="recovery:send"))
    markup.add(InlineKeyboardButton("⚙️ Settings", callback_data="recovery:settings"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("recovery:"))
def recovery_callback(call):
    action = call.data.split(":", 1)[1]
    if action == "send":
        run_recovery_campaign(call.message.chat.id)
    else:
        msg = bot.send_message(call.message.chat.id, "Send: `inactive_days | reward_coins`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, save_recovery_settings)
    bot.answer_callback_query(call.id)


def save_recovery_settings(message):
    try:
        days, reward = [int(x.strip()) for x in message.text.split("|")]
        admin_config_col.update_one({"_id": "advanced"}, {"$set": {"inactive_after_days": max(1, days), "recovery_reward": max(0, reward)}}, upsert=True)
        bot.send_message(message.chat.id, "✅ Recovery settings updated.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid format.")


def run_recovery_campaign(admin_chat_id):
    if not adv_flag("inactive_recovery"):
        bot.send_message(admin_chat_id, "🚫 Recovery is disabled.")
        return
    cfg = advanced_settings()
    days = int(cfg.get("inactive_after_days", 7))
    reward = int(cfg.get("recovery_reward", 10))
    cutoff = adv_now() - timedelta(days=days)
    sent = 0
    for user in bot_users_col.find({"last_seen": {"$lt": cutoff}, "banned": {"$ne": True}}).limit(500):
        uid = user.get("user_id")
        if not uid:
            continue
        if recovery_col.find_one({"user_id": uid, "campaign_cutoff": cutoff}):
            continue
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎁 Open Bot & Claim", callback_data="recovery:claim"))
        if notify_user(uid, f"👋 *We miss you!*\n\nCome back today and check your Premium offers.\n🎁 Return bonus: *{reward} coins*", "recovery", markup):
            recovery_col.insert_one({"user_id": uid, "campaign_cutoff": cutoff, "sent_at": adv_now()})
            sent += 1
    bot.send_message(admin_chat_id, f"♻️ Recovery campaign sent to *{sent}* users.", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "recovery:claim")
def recovery_claim(call):
    uid = call.from_user.id
    cfg = advanced_settings()
    row = recovery_col.find_one({"user_id": uid}, sort=[("sent_at", DESCENDING)])
    if not row or row.get("claimed"):
        bot.answer_callback_query(call.id, "No new recovery reward available.", show_alert=True)
        return
    recovery_col.update_one({"_id": row["_id"], "claimed": {"$ne": True}}, {"$set": {"claimed": True, "claimed_at": adv_now()}})
    reward = int(cfg.get("recovery_reward", 10))
    adv_add_coins(uid, reward, "inactive-user return reward")
    bot.answer_callback_query(call.id, f"You received {reward} coins!")


# ------------------------- PERSONAL COUPON -------------------------
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_GIFTS)
def advanced_gift_manager(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎟️ Create Personal Coupon", callback_data="personal:create"))
    bot.send_message(message.chat.id, "🎁 *GIFT / PERSONAL REWARD MANAGER*\n\nCreate a coupon for one specific Telegram user.", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "personal:create")
def personal_coupon_prompt(call):
    msg = bot.send_message(call.message.chat.id, "Send: `user_id | code | discount_percent | max_uses | hours_valid`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, create_personal_coupon)
    bot.answer_callback_query(call.id)


def create_personal_coupon(message):
    try:
        uid, code, discount, uses, hours = [x.strip() for x in message.text.split("|")]
        now = adv_now()
        user_coupon_col.insert_one({"user_id": int(uid), "code": code.upper(), "discount": float(discount), "max_uses": int(uses), "uses": 0, "created_at": now, "expires_at": now + timedelta(hours=float(hours)), "enabled": True})
        notify_user(int(uid), f"🎟️ *You received a personal coupon!*\n\nCode: `{code.upper()}`\nDiscount: *{discount}%*\nExpires: *{format_bot_time(now + timedelta(hours=float(hours)))}*", "coupon")
        bot.send_message(message.chat.id, "✅ Personal coupon created and user notified.")
    except Exception:
        bot.send_message(message.chat.id, "❌ Invalid format.")


# ------------------------- SMART RENEWAL MENU -------------------------
@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_RENEW)
def advanced_renew_menu(message):
    if not adv_flag("renewal"):
        bot.send_message(message.chat.id, "🚫 Renewal is disabled by Admin.")
        return
    uid = message.from_user.id
    now_ts = adv_now().timestamp()
    rows = list(users_col.find({"user_id": uid, "expiry": {"$exists": True}}).sort("expiry", DESCENDING).limit(20))
    active = [r for r in rows if float(r.get("expiry", 0) or 0) > now_ts]
    if not active:
        bot.send_message(message.chat.id, "🔄 *Renew Premium*\n\nNo previous Premium subscription was found to renew. Tap 🎁 Redeem Premium to purchase a new one.", parse_mode="Markdown")
        return
    text = "🔄 *Renew Premium*\n\nYour current Premium access is active. To avoid duplicate access, use the normal Premium purchase screen to choose the same channel and duration again.\n\n"
    for row in active[:10]:
        text += f"📢 Channel: `{row.get('channel_id')}`\n⏰ Expires: *{format_bot_time(datetime.fromtimestamp(float(row.get('expiry'))))}*\n\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


# ------------------------- SCHEDULED SMART EXPIRY NOTIFICATIONS -------------------------
def run_smart_expiry_notifications():
    if not adv_flag("smart_notifications"):
        return
    now = adv_now()
    now_ts = now.timestamp()
    hours_list = advanced_settings().get("notification_expiry_hours", [24, 6, 1])
    for hours in hours_list:
        target = now_ts + int(hours) * 3600
        lower = target - 180
        upper = target + 180
        for row in users_col.find({"expiry": {"$gte": lower, "$lte": upper}}).limit(500):
            uid = row.get("user_id")
            marker = f"expiry:{row.get('_id')}:{hours}"
            if notification_col.find_one({"user_id": uid, "kind": marker}):
                continue
            text = f"⏰ *Premium Expiry Reminder*\n\nYour Premium access expires in about *{hours} hour(s)*.\n\nOpen 🎁 Redeem Premium to renew."
            notify_user(uid, text, marker)


# ------------------------- PERIODIC MAINTENANCE -------------------------
def run_advanced_maintenance():
    try:
        advanced_settings()
        run_smart_expiry_notifications()
        now = adv_now()
        # Automatically disable expired flash deals.
        flash_deals_col.update_many({"enabled": True, "end_at": {"$lt": now}}, {"$set": {"enabled": False, "auto_disabled_at": now}})
        promotions_col.update_many({"enabled": True, "end_at": {"$lt": now}}, {"$set": {"enabled": False, "auto_disabled_at": now}})
        # Automatically disable expired referral campaigns.
        referral_campaign_col.update_many({"enabled": True, "end_at": {"$lt": now}}, {"$set": {"enabled": False, "auto_disabled_at": now}})
    except Exception as e:
        print("Advanced maintenance error:", e)


# Install into the existing scheduler if available.
try:
    scheduler.add_job(run_advanced_maintenance, "interval", minutes=5, id="advanced_maintenance", replace_existing=True)
except Exception:
    pass


# ------------------------- ACTIVITY TRACKING -------------------------
@bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID, content_types=["text"])
def advanced_activity_tracker(message):
    # This handler is deliberately placed last so existing specific handlers win.
    try:
        register_user(message.from_user)
        track_activity(message.from_user.id, "message")
    except Exception:
        pass
