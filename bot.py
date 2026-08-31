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


# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "_id": "bot_settings",

    "coin_name": "KP",
    "coin_emoji": "🌽",
    "referral_reward": 10,
    "timezone": "Asia/Kathmandu",

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

    channels = get_premium_channels()

    if not channels:
        bot.send_message(
            chat_id,
            "⚠️ Premium rewards are not available yet."
        )
        return

    # One channel: directly show plans
    if len(channels) == 1:
        show_redeem_plans(
            user_id,
            chat_id,
            channels[0]["channel_id"]
        )
        return

    markup = InlineKeyboardMarkup()

    # Bulk redemption uses one fixed price set by the admin, regardless of
    # how many Premium channels the user selects.
    bulk_price = get_settings().get("bulk_redeem_price")
    if bulk_price is not None:
        markup.add(
            InlineKeyboardButton(
                f"📦 Bulk Redeem — {bulk_price} {get_settings()['coin_name']}",
                callback_data="bulk:start"
            )
        )

    for channel in channels:
        markup.add(
            InlineKeyboardButton(
                f"📢 {channel['name']}",
                callback_data=(
                    f"rchannel:{channel['channel_id']}"
                )
            )
        )

    bot.send_message(
        chat_id,
        "🎁 *Choose Premium Channel*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


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
    """Return the admin-set Bulk Redeem price for a specific duration."""
    settings = get_settings()
    prices = settings.get("bulk_redeem_prices", {}) or {}
    price = prices.get(str(plan_id))
    if price is not None:
        return int(price)

    # Keep existing installations working if they only have the old fixed price.
    legacy_price = settings.get("bulk_redeem_price")
    return int(legacy_price) if legacy_price is not None else None



@bot.callback_query_handler(
    func=lambda c: c.data == "bulk:start"
)
def bulk_redeem_start(call):

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
    bulk_price = get_bulk_price_for_plan(plan_id)

    if not plan or not channels or bulk_price is None:
        bot.send_message(
            chat_id,
            "❌ This bulk redeem option is no longer available."
        )
        return

    state = bulk_redeem_selections.get(user_id)
    if not state or state.get("plan_id") != plan_id:
        state = {
            "plan_id": plan_id,
            "channel_ids": []
        }
        bulk_redeem_selections[user_id] = state

    selected = set(state.get("channel_ids", []))
    markup = InlineKeyboardMarkup()

    for channel in channels:
        channel_id = channel["channel_id"]
        prefix = "✅" if channel_id in selected else "☐"
        markup.add(
            InlineKeyboardButton(
                f"{prefix} {channel['name']}",
                callback_data=f"bulktoggle:{plan_id}:{channel_id}"
            )
        )

    markup.add(
        InlineKeyboardButton(
            f"🎉 Confirm Bulk Redeem ({bulk_price} {settings['coin_name']})",
            callback_data=f"bulkconfirm:{plan_id}"
        )
    )

    bot.send_message(
        chat_id,
        f"""📦 *Select Premium Channels*

🎁 *Duration:* {format_duration(plan['amount'], plan['unit'])}
💰 *Fixed Bulk Price:* {bulk_price} {settings['coin_name']}
📌 *Selected:* {len(selected)} channel(s)

Tap channels to select or unselect them, then confirm.""",
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

        if channel_id in selected:
            selected.remove(channel_id)
        else:
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
        bulk_price = get_bulk_price_for_plan(plan_id)

        if not plan or bulk_price is None:
            bot.answer_callback_query(
                call.id,
                "This bulk option is no longer available.",
                show_alert=True
            )
            return

        bulk_price = int(bulk_price)

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

        bulk_redeem_selections.pop(user_id, None)

        lines = [
            "🎉 *Bulk Premium Redeemed Successfully!*",
            "",
            f"🎁 *Duration:* {format_duration(plan['amount'], plan['unit'])}",
            f"📦 *Channels:* {len(created_links)}",
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
# ADVANCED MANAGEMENT + PREMIUM COMMERCE EXTENSION
# Added without removing the original bot systems.
# =========================================================

advanced_orders_col = db["advanced_orders"]
advanced_coin_ledger_col = db["advanced_coin_ledger"]
advanced_gifts_col = db["advanced_gifts"]
advanced_campaigns_col = db["advanced_campaigns"]
advanced_notifications_col = db["advanced_notifications"]
advanced_audit_col = db["advanced_audit"]

ADVANCED_MENU = "🚀 Advanced"
ADVANCED_BACK = "⬅️ Back"


def adv_now():
    return datetime.now(get_bot_timezone())


def adv_ts(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=get_bot_timezone())
        return value.timestamp()
    try:
        return float(value)
    except Exception:
        return None


def adv_money(value):
    try:
        return int(value)
    except Exception:
        return 0


def adv_audit(action, user_id=None, **extra):
    try:
        advanced_audit_col.insert_one({
            "action": action,
            "user_id": user_id,
            "admin_id": ADMIN_ID,
            "created_at": adv_now(),
            **extra
        })
    except Exception as e:
        print(f"Advanced audit error: {e}")


def adv_init():
    try:
        advanced_orders_col.create_index("order_id", unique=True)
        advanced_orders_col.create_index([("user_id", 1), ("created_at", DESCENDING)])
        advanced_coin_ledger_col.create_index([("user_id", 1), ("created_at", DESCENDING)])
        advanced_gifts_col.create_index("gift_code", unique=True)
        advanced_campaigns_col.create_index("campaign_id", unique=True)
        advanced_notifications_col.create_index([("user_id", 1), ("kind", 1), ("created_at", DESCENDING)])
    except Exception as e:
        print(f"Advanced index setup: {e}")


def adv_make_order(user_id, amount=0, item_type="premium", items=None,
                   discount=0, status="completed", source="system",
                   plan_id=None, channel_ids=None, expiry=None):
    order_id = "ORD-" + uuid.uuid4().hex[:10].upper()
    doc = {
        "order_id": order_id,
        "user_id": int(user_id),
        "item_type": item_type,
        "items": items or [],
        "channel_ids": channel_ids or [],
        "plan_id": plan_id,
        "original_cost": adv_money(amount) + adv_money(discount),
        "discount": adv_money(discount),
        "paid": adv_money(amount),
        "status": status,
        "source": source,
        "expiry": expiry,
        "created_at": adv_now()
    }
    try:
        advanced_orders_col.insert_one(doc)
    except Exception as e:
        print(f"Order log error: {e}")
    return order_id


def adv_record_coin(user_id, amount, reason, balance=None, actor=None):
    try:
        if balance is None:
            balance = get_coin_balance(user_id)
        advanced_coin_ledger_col.insert_one({
            "user_id": int(user_id),
            "amount": int(amount),
            "reason": reason,
            "balance": int(balance),
            "actor": actor or ADMIN_ID,
            "created_at": adv_now()
        })
    except Exception as e:
        print(f"Coin ledger error: {e}")


def adv_set_coins(user_id, amount, reason="Admin adjustment"):
    user_id = int(user_id)
    amount = int(amount)
    add_coins(user_id, amount)
    balance = get_coin_balance(user_id)
    adv_record_coin(user_id, amount, reason, balance, ADMIN_ID)
    adv_audit("coin_adjustment", user_id, amount=amount, reason=reason, balance=balance)
    return balance


def adv_get_active_premium(user_id):
    now = adv_now().timestamp()
    return list(users_col.find({
        "user_id": int(user_id),
        "expiry": {"$gt": now}
    }))


def adv_user_summary(user_id):
    user = get_user(int(user_id))
    if not user:
        return None
    premium = adv_get_active_premium(user_id)
    return {
        "user": user,
        "premium": premium,
        "coins": get_coin_balance(user_id),
        "orders": advanced_orders_col.count_documents({"user_id": int(user_id)}),
        "referrals": int(user.get("referral_count", 0))
    }


def adv_admin_markup():
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton("📊 Advanced Dashboard", callback_data="adv:dashboard"))
    m.row(InlineKeyboardButton("🧾 Orders / Sales", callback_data="adv:orders"))
    m.row(InlineKeyboardButton("💳 Payment Queue", callback_data="adv:payments"))
    m.row(InlineKeyboardButton("👑 Premium Buyers", callback_data="adv:buyers"))
    m.row(InlineKeyboardButton("🔎 Search User", callback_data="adv:search"))
    m.row(InlineKeyboardButton("🪙 Coin Management", callback_data="adv:coins"))
    m.row(InlineKeyboardButton("📨 Single User Message", callback_data="adv:singlemsg"))
    m.row(InlineKeyboardButton("🎁 Gift Premium", callback_data="adv:gift"))
    m.row(InlineKeyboardButton("🔄 Renewal", callback_data="adv:renew"))
    m.row(InlineKeyboardButton("📣 Channel Announcement", callback_data="adv:announcement"))
    m.row(InlineKeyboardButton("🎯 Campaigns", callback_data="adv:campaigns"))
    m.row(InlineKeyboardButton("🏆 Buyer Leaderboard", callback_data="adv:leaderboard"))
    m.row(InlineKeyboardButton("💾 Backup Data", callback_data="adv:backup"))
    m.row(InlineKeyboardButton("🚧 Maintenance Mode", callback_data="adv:maintenance"))
    return m


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADVANCED_MENU)
def advanced_menu_message(message):
    bot.send_message(ADMIN_ID, "🚀 *Advanced Management*\n\nChoose an advanced function:", reply_markup=adv_admin_markup(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:dashboard")
def adv_dashboard(call):
    if not admin_only(call): return
    users = bot_users_col.count_documents({})
    banned = bot_users_col.count_documents({"banned": True})
    active = users_col.count_documents({"expiry": {"$gt": adv_now().timestamp()}})
    expired = users_col.count_documents({"expiry": {"$lte": adv_now().timestamp()}})
    sales = list(advanced_orders_col.aggregate([{"$match": {"status": "completed"}}, {"$group": {"_id": None, "total": {"$sum": "$paid"}, "count": {"$sum": 1}}}]))
    total_sales = sales[0]["total"] if sales else 0
    order_count = sales[0]["count"] if sales else 0
    coins = list(bot_users_col.aggregate([{"$group": {"_id": None, "total": {"$sum": "$coins"}}}]))
    total_coins = coins[0]["total"] if coins else 0
    settings = get_settings()
    text = (
        "📊 *Advanced Dashboard*\n\n"
        f"👥 Users: *{users}*\n"
        f"🚫 Banned: *{banned}*\n"
        f"👑 Active Premium Entries: *{active}*\n"
        f"⌛ Expired Entries: *{expired}*\n"
        f"🧾 Completed Orders: *{order_count}*\n"
        f"💰 Recorded Sales: *{total_sales} {settings['coin_name']}*\n"
        f"🪙 Coins Held: *{total_coins}*\n"
        f"🌐 Timezone: `{settings.get('timezone', 'Asia/Kathmandu')}`"
    )
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, text, parse_mode="Markdown", reply_markup=adv_admin_markup())


@bot.callback_query_handler(func=lambda c: c.data == "adv:orders")
def adv_orders(call):
    if not admin_only(call): return
    rows = list(advanced_orders_col.find().sort("created_at", DESCENDING).limit(25))
    if not rows:
        text = "🧾 No recorded orders yet."
    else:
        lines = ["🧾 *Recent Orders*", ""]
        for r in rows:
            lines.append(f"`{r.get('order_id')}` — User `{r.get('user_id')}`")
            lines.append(f"💰 {r.get('paid', 0)} | Discount {r.get('discount', 0)} | {r.get('status', 'unknown')}")
            lines.append(f"📅 {format_bot_time(r.get('created_at'))}")
            lines.append("")
        text = "\n".join(lines)
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, text, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:buyers")
def adv_buyers(call):
    if not admin_only(call): return
    now = adv_now().timestamp()
    rows = list(users_col.find({"expiry": {"$gt": now}}).sort("expiry", 1).limit(80))
    lines = ["👑 *Active Premium Buyers*", ""]
    if not rows:
        lines.append("No active Premium buyers.")
    for i, r in enumerate(rows, 1):
        u = get_user(r.get("user_id")) or {}
        name = user_display_name(u)
        channel = premium_channels_col.find_one({"channel_id": r.get("channel_id")})
        cname = channel.get("name", str(r.get("channel_id"))) if channel else str(r.get("channel_id"))
        lines.append(f"{i}. {name}\n🆔 `{r.get('user_id')}`\n📢 {cname}\n⏰ {format_bot_time(r.get('expiry'))}\n")
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:search")
def adv_search_start(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "🔎 Send a Telegram User ID or @username:")
    bot.register_next_step_handler(msg, adv_search_process)
    bot.answer_callback_query(call.id)


def adv_search_process(message):
    query = (message.text or "").strip().replace("@", "")
    user = None
    if query.isdigit():
        user = get_user(int(query))
    else:
        user = bot_users_col.find_one({"username": query})
    if not user:
        bot.send_message(ADMIN_ID, "❌ User not found.")
        return
    s = adv_user_summary(user["user_id"])
    lines = [
        "👤 *User Details*", "",
        f"Name: {user.get('first_name', 'User')}",
        f"Username: @{user.get('username') or 'Not set'}",
        f"ID: `{user.get('user_id')}`",
        f"🪙 Coins: *{s['coins']}*",
        f"👥 Referrals: *{s['referrals']}*",
        f"🧾 Orders: *{s['orders']}*",
        f"🚫 Banned: *{user.get('banned', False)}*", ""
    ]
    for p in s["premium"]:
        ch = premium_channels_col.find_one({"channel_id": p.get("channel_id")})
        lines.append(f"👑 {ch.get('name') if ch else p.get('channel_id')} — {format_bot_time(p.get('expiry'))}")
    bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:coins")
def adv_coins_start(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "🪙 Send: `USER_ID AMOUNT [reason]`\nExample: `123456 500 Promo reward`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, adv_coins_process)
    bot.answer_callback_query(call.id)


def adv_coins_process(message):
    try:
        parts = (message.text or "").split()
        uid = int(parts[0]); amount = int(parts[1])
        reason = " ".join(parts[2:]) or "Admin adjustment"
        balance = adv_set_coins(uid, amount, reason)
        bot.send_message(ADMIN_ID, f"✅ Updated `{uid}` by *{amount}*.\n🪙 New balance: *{balance}*", parse_mode="Markdown")
        try:
            bot.send_message(uid, f"🪙 Your coin balance was adjusted by admin.\nCurrent balance: *{balance}*", parse_mode="Markdown")
        except Exception: pass
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid format.")


@bot.callback_query_handler(func=lambda c: c.data == "adv:singlemsg")
def adv_singlemsg_start(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "📨 Send: `USER_ID message`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, adv_singlemsg_process)
    bot.answer_callback_query(call.id)


def adv_singlemsg_process(message):
    try:
        parts = (message.text or "").split(maxsplit=1)
        uid = int(parts[0]); text = parts[1]
        bot.send_message(uid, text)
        adv_audit("single_user_message", uid)
        bot.send_message(ADMIN_ID, "✅ Message sent.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Could not send message: {e}")


@bot.callback_query_handler(func=lambda c: c.data == "adv:leaderboard")
def adv_leaderboard(call):
    if not admin_only(call): return
    rows = list(advanced_orders_col.aggregate([
        {"$match": {"status": "completed"}},
        {"$group": {"_id": "$user_id", "spent": {"$sum": "$paid"}, "orders": {"$sum": 1}}},
        {"$sort": {"spent": -1}}, {"$limit": 20}
    ]))
    lines = ["🏆 *Top Buyers*", ""]
    for i, r in enumerate(rows, 1):
        u = get_user(r["_id"]) or {}
        lines.append(f"{i}. {user_display_name(u)} — {r['spent']} coins ({r['orders']} orders)")
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, "\n".join(lines) if rows else "No completed orders recorded.", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:payments")
def adv_payments(call):
    if not admin_only(call): return
    if not pending_payments:
        text = "💳 No pending payments in memory."
    else:
        lines = ["💳 *Pending Payment Queue*", ""]
        for uid, data in pending_payments.items():
            lines.append(f"🆔 `{uid}` — {data.get('time')}")
        text = "\n".join(lines)
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, text, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:gift")
def adv_gift_start(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "🎁 Send: `USER_ID PLAN_ID CHANNEL_ID DAYS` to create a gift for that user.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, adv_gift_process)
    bot.answer_callback_query(call.id)


def adv_gift_process(message):
    try:
        p = (message.text or "").split()
        uid, plan_id, channel_id, days = int(p[0]), p[1], int(p[2]), int(p[3])
        code = "GIFT-" + uuid.uuid4().hex[:10].upper()
        advanced_gifts_col.insert_one({
            "gift_code": code, "user_id": uid, "plan_id": plan_id,
            "channel_id": channel_id, "days": days, "used": False, "created_at": adv_now()
        })
        bot.send_message(ADMIN_ID, f"🎁 Gift created: `{code}`", parse_mode="Markdown")
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid gift format.")


@bot.message_handler(commands=["gift"])
def adv_gift_redeem(message):
    code = (message.text or "").split(maxsplit=1)
    if len(code) != 2:
        bot.reply_to(message, "Usage: /gift GIFT-CODE")
        return
    gift = advanced_gifts_col.find_one({"gift_code": code[1].upper(), "used": False})
    if not gift or gift.get("user_id") != message.from_user.id:
        bot.reply_to(message, "❌ Gift code is invalid or not assigned to you.")
        return
    expiry = adv_now() + timedelta(days=int(gift.get("days", 30)))
    try:
        link = bot.create_chat_invite_link(gift["channel_id"], member_limit=1, expire_date=int(expiry.timestamp()))
        users_col.update_one({"user_id": message.from_user.id, "channel_id": gift["channel_id"]}, {"$set": {"expiry": expiry.timestamp(), "source": "gift", "plan_id": gift.get("plan_id")}}, upsert=True)
        advanced_gifts_col.update_one({"_id": gift["_id"]}, {"$set": {"used": True, "used_at": adv_now()}})
        adv_make_order(message.from_user.id, 0, "gift", [gift["channel_id"]], 0, "completed", "gift", gift.get("plan_id"), [gift["channel_id"]], expiry.timestamp())
        bot.reply_to(message, f"🎁 Gift redeemed!\n\n🔗 {link.invite_link}\n⏰ Expires: {format_bot_time(expiry)}")
    except Exception as e:
        bot.reply_to(message, f"❌ Gift could not be redeemed: {e}")


@bot.callback_query_handler(func=lambda c: c.data == "adv:renew")
def adv_renew_start(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "🔄 Send: `USER_ID CHANNEL_ID PLAN_ID` to extend Premium.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, adv_renew_process)
    bot.answer_callback_query(call.id)


def adv_renew_process(message):
    try:
        p = (message.text or "").split()
        uid, cid, plan_id = int(p[0]), int(p[1]), p[2]
        plan = premium_plans_col.find_one({"plan_id": plan_id})
        if not plan: raise ValueError("Plan not found")
        old = users_col.find_one({"user_id": uid, "channel_id": cid})
        base = max(adv_now().timestamp(), float(old.get("expiry", 0)) if old else 0)
        expiry = datetime.fromtimestamp(base, get_bot_timezone()) + timedelta(seconds=int(plan["duration_seconds"]))
        users_col.update_one({"user_id": uid, "channel_id": cid}, {"$set": {"expiry": expiry.timestamp(), "plan_id": plan_id}}, upsert=True)
        adv_make_order(uid, int(plan.get("cost", 0)), "renewal", [cid], 0, "completed", "admin_renewal", plan_id, [cid], expiry.timestamp())
        bot.send_message(ADMIN_ID, f"✅ Premium renewed for `{uid}` until {format_bot_time(expiry)}", parse_mode="Markdown")
        try: bot.send_message(uid, f"🔄 Your Premium has been renewed.\n⏰ New expiry: {format_bot_time(expiry)}")
        except Exception: pass
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Renewal failed: {e}")


@bot.callback_query_handler(func=lambda c: c.data == "adv:announcement")
def adv_announcement_start(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "📣 Send: `CHANNEL_ID message` to notify active buyers of one channel.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, adv_announcement_process)
    bot.answer_callback_query(call.id)


def adv_announcement_process(message):
    try:
        p = (message.text or "").split(maxsplit=1)
        cid = int(p[0]); text = p[1]
        rows = users_col.find({"channel_id": cid, "expiry": {"$gt": adv_now().timestamp()}}, {"user_id": 1})
        sent = failed = 0
        seen = set()
        for r in rows:
            uid = r.get("user_id")
            if uid in seen: continue
            seen.add(uid)
            try: bot.send_message(uid, "📣 *Premium Channel Announcement*\n\n" + text, parse_mode="Markdown"); sent += 1
            except Exception: failed += 1
        bot.send_message(ADMIN_ID, f"✅ Announcement complete.\nSent: {sent}\nFailed: {failed}")
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid format.")


@bot.callback_query_handler(func=lambda c: c.data == "adv:campaigns")
def adv_campaigns(call):
    if not admin_only(call): return
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton("➕ Create Campaign", callback_data="adv:campaign_create"))
    m.row(InlineKeyboardButton("📋 List Campaigns", callback_data="adv:campaign_list"))
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, "🎯 *Promotional Campaigns*", reply_markup=m, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:campaign_create")
def adv_campaign_create(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "Send: `NAME TYPE VALUE HOURS`\nTYPE = percent, fixed, coins\nExample: `Weekend percent 20 24`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, adv_campaign_process)
    bot.answer_callback_query(call.id)


def adv_campaign_process(message):
    try:
        p = (message.text or "").split()
        name, typ, value, hours = p[0], p[1].lower(), int(p[2]), int(p[3])
        if typ not in ("percent", "fixed", "coins"): raise ValueError
        cid = "CMP-" + uuid.uuid4().hex[:8].upper()
        advanced_campaigns_col.insert_one({"campaign_id": cid, "name": name, "type": typ, "value": value, "created_at": adv_now(), "expires_at": adv_now() + timedelta(hours=hours), "active": True})
        bot.send_message(ADMIN_ID, f"✅ Campaign `{cid}` created.", parse_mode="Markdown")
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid campaign format.")


@bot.callback_query_handler(func=lambda c: c.data == "adv:campaign_list")
def adv_campaign_list(call):
    if not admin_only(call): return
    rows = list(advanced_campaigns_col.find().sort("created_at", DESCENDING).limit(30))
    lines = ["🎯 *Campaigns*", ""]
    for r in rows:
        active = r.get("active", True) and adv_ts(r.get("expires_at")) > adv_now().timestamp()
        lines.append(f"`{r.get('campaign_id')}` {r.get('name')} — {r.get('type')} {r.get('value')} — {'🟢' if active else '🔴'}")
        if r.get("expires_at"): lines.append(f"Expires: {format_bot_time(r['expires_at'])}")
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, "\n".join(lines) if rows else "No campaigns.", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "adv:backup")
def adv_backup(call):
    if not admin_only(call): return
    path = f"/tmp/bot_backup_{int(time.time())}.json"
    try:
        import json
        data = {
            "created_at": adv_now().isoformat(),
            "settings": get_settings(),
            "users": list(bot_users_col.find({}, {"_id": 0})),
            "premium": list(users_col.find({}, {"_id": 0})),
            "orders": list(advanced_orders_col.find({}, {"_id": 0})),
            "coin_ledger": list(advanced_coin_ledger_col.find({}, {"_id": 0}))
        }
        def clean(x):
            if isinstance(x, dict): return {k: clean(v) for k, v in x.items()}
            if isinstance(x, list): return [clean(v) for v in x]
            if isinstance(x, datetime): return x.isoformat()
            return x
        with open(path, "w", encoding="utf-8") as f: json.dump(clean(data), f, ensure_ascii=False, indent=2)
        with open(path, "rb") as f: bot.send_document(ADMIN_ID, f, caption="💾 Advanced bot backup")
        os.remove(path)
        adv_audit("backup_created", ADMIN_ID)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Backup failed: {e}")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "adv:maintenance")
def adv_maintenance(call):
    if not admin_only(call): return
    enabled = bool(get_settings().get("maintenance_mode", False))
    update_setting("maintenance_mode", not enabled)
    bot.answer_callback_query(call.id, "Maintenance enabled" if not enabled else "Maintenance disabled")
    bot.send_message(ADMIN_ID, f"🚧 Maintenance mode is now *{'ON' if not enabled else 'OFF'}*.", parse_mode="Markdown")


# Admin-only commands for fast access to advanced tools.
@bot.message_handler(commands=["advanced", "dashboard"])
def adv_command(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(ADMIN_ID, "🚀 *Advanced Management*", reply_markup=adv_admin_markup(), parse_mode="Markdown")


# Future-proof bulk pricing: use the normal plan price multiplied by selected
# channels, then apply admin-configured tier discounts. The old fixed bulk
# setting remains readable for backward compatibility but is no longer required.
def get_bulk_discount_for_count(plan_id, count):
    settings = get_settings()
    tiers = settings.get("bulk_discount_tiers", {}) or {}
    candidates = []
    if isinstance(tiers, dict):
        for key, value in tiers.items():
            try:
                minimum = int(key)
                if minimum <= count:
                    if isinstance(value, dict):
                        candidates.append((minimum, value))
                    else:
                        candidates.append((minimum, {"type": "percent", "value": int(value)}))
            except Exception:
                pass
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1] if candidates else {"type": "percent", "value": 0}


def calculate_bulk_price(plan, count):
    if not plan or count <= 0:
        return 0, 0, 0
    original = int(plan.get("cost", 0)) * int(count)
    rule = get_bulk_discount_for_count(plan.get("plan_id"), count)
    value = max(0, int(rule.get("value", 0)))
    typ = rule.get("type", "percent")
    if typ == "fixed":
        discount = min(original, value)
    else:
        discount = min(original, (original * value) // 100)
    return original, discount, original - discount


@bot.callback_query_handler(func=lambda c: c.data == "adv:bulkdiscount")
def adv_bulkdiscount_menu(call):
    if not admin_only(call): return
    msg = bot.send_message(ADMIN_ID, "Send tier: `MIN_CHANNELS TYPE VALUE`\nExample: `4 percent 20` or `2 fixed 50`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, adv_bulkdiscount_process)
    bot.answer_callback_query(call.id)


def adv_bulkdiscount_process(message):
    try:
        p = (message.text or "").split()
        minimum, typ, value = int(p[0]), p[1].lower(), int(p[2])
        if minimum < 2 or typ not in ("percent", "fixed") or value < 0: raise ValueError
        settings = get_settings()
        tiers = settings.get("bulk_discount_tiers", {}) or {}
        tiers[str(minimum)] = {"type": typ, "value": value}
        update_setting("bulk_discount_tiers", tiers)
        bot.send_message(ADMIN_ID, f"✅ Bulk discount tier saved: {minimum}+ → {value}{'%' if typ == 'percent' else ' coins'}")
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid tier.")


# Background expiry reminders. Existing expiry cleanup remains untouched.
def adv_expiry_reminder_job():
    now = adv_now().timestamp()
    for hours, kind in ((24, "24h"), (1, "1h")):
        low = now + (hours * 3600) - 180
        high = now + (hours * 3600) + 180
        rows = users_col.find({"expiry": {"$gte": low, "$lte": high}})
        for row in rows:
            uid = row.get("user_id")
            key = {"user_id": uid, "kind": kind, "channel_id": row.get("channel_id"), "expiry": row.get("expiry")}
            if advanced_notifications_col.find_one(key): continue
            try:
                ch = premium_channels_col.find_one({"channel_id": row.get("channel_id")})
                name = ch.get("name", "Premium Channel") if ch else "Premium Channel"
                bot.send_message(uid, f"🔔 *Premium Expiry Reminder*\n\n📢 {name}\n⏰ Your access expires in about *{hours} hour(s)*.\n\nRenew before it expires to keep access.", parse_mode="Markdown")
                advanced_notifications_col.insert_one({**key, "created_at": adv_now()})
            except Exception:
                pass


def adv_campaign_cleanup_job():
    now = adv_now()
    advanced_campaigns_col.update_many({"expires_at": {"$lte": now}, "active": True}, {"$set": {"active": False}})


def adv_background_loop():
    while True:
        try:
            adv_expiry_reminder_job()
            adv_campaign_cleanup_job()
        except Exception as e:
            print(f"Advanced background error: {e}")
        time.sleep(180)


adv_init()
Thread(target=adv_background_loop, daemon=True).start()




# Add the Advanced button while preserving the original admin keyboard function.
_original_admin_menu_markup = admin_menu_markup
def admin_menu_markup():
    markup = _original_admin_menu_markup()
    markup.row(KeyboardButton(ADVANCED_MENU))
    return markup

# =========================================================
# UNKNOWN MESSAGE FALLBACK
# =========================================================

@bot.message_handler(
    func=lambda m: True,
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
            "ℹ️ Please use the buttons below to use the bot."
        )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    keep_alive()

    get_settings()
    setup_database()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        kick_expired_users,
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
        print(f"Polling error: {e}")