import os
import time
import telebot

from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from pymongo import MongoClient, DESCENDING
from apscheduler.schedulers.background import BackgroundScheduler
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from bson import ObjectId


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
UPI_ID = os.getenv("UPI_ID", "")
CONTACT_USERNAME = os.getenv(
    "CONTACT_USERNAME",
    ""
).replace("@", "")

if not BOT_TOKEN or not MONGO_URI or not ADMIN_ID:
    raise ValueError(
        "BOT_TOKEN, MONGO_URI and ADMIN_ID are required!"
    )

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client["sub_management"]

# Existing collections
channels_col = db["channels"]
users_col = db["users"]

# Bot system collections
bot_users_col = db["bot_users"]
settings_col = db["settings"]
force_channels_col = db["force_channels"]
reward_channels_col = db["reward_channels"]
coupons_col = db["coupons"]
coupon_uses_col = db["coupon_uses"]
feedback_col = db["feedback"]
milestones_col = db["milestones"]

pending_payments = {}


# ============================================================
# KEEP ALIVE SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running and healthy!"


def run_web():
    port = int(os.getenv("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port
    )


def keep_alive():
    Thread(
        target=run_web,
        daemon=True
    ).start()


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_SETTINGS = {
    "_id": "bot_settings",

    # Coin system
    "coin_name": "Coins",
    "coin_emoji": "🪙",
    "referral_reward": 10,

    # Old premium channel compatibility
    "reward_channel_id": None,
    "reward_channel_name": "Premium Channel",

    # Premium reward durations
    "reward_options": [
        {
            "minutes": 1440,
            "cost": 50,
            "label": "1 Day"
        },
        {
            "minutes": 10080,
            "cost": 250,
            "label": "7 Days"
        },
        {
            "minutes": 43200,
            "cost": 800,
            "label": "30 Days"
        }
    ],

    # Old settings compatibility
    "reward_1_day_cost": 50,
    "reward_7_day_cost": 250,
    "reward_30_day_cost": 800,

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
        "To continue, please join all the required "
        "channels/groups below and then press "
        "*Verify & Continue*."
    ),

    "verification_success_text": (
        "✅ *Verification Successful!*\n\n"
        "Welcome! You can now use all bot features."
    ),

    "how_it_works_text": (
        "📖 *How It Works*\n\n"
        "1️⃣ Share your referral link.\n"
        "2️⃣ Your friend starts the bot using your link.\n"
        "3️⃣ They join required channels.\n"
        "4️⃣ They verify.\n"
        "5️⃣ You receive coins.\n"
        "6️⃣ Complete milestones and redeem Premium!"
    ),

    "feedback_text": (
        "💬 *Send Feedback*\n\n"
        "Please send your feedback, suggestion or problem. "
        "It will be delivered to the admin."
    ),

    # User buttons
    "btn_profile": "🌐 My Profile",
    "btn_refer": "🔗 Refer & Earn",
    "btn_redeem": "🎁 Redeem Premium",
    "btn_coupon": "🎟 Claim Coupon",
    "btn_leaderboard": "🏆 Leaderboard",
    "btn_referrals": "👥 My Referrals",
    "btn_milestones": "🎯 Milestones",
    "btn_how": "📖 How It Works",
    "btn_feedback": "💬 Feedback",
    "btn_contact": "📞 Contact Admin"
}


# ============================================================
# SETTINGS HELPERS
# ============================================================

def get_settings():

    settings = settings_col.find_one({
        "_id": "bot_settings"
    })

    if not settings:

        settings_col.insert_one(
            DEFAULT_SETTINGS.copy()
        )

        return DEFAULT_SETTINGS.copy()

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


# ============================================================
# GENERAL HELPERS
# ============================================================

def escape_markdown(text):

    return str(text or "").replace(
        "*", "\\*"
    ).replace(
        "_", "\\_"
    ).replace(
        "`", "\\`"
    ).replace(
        "[", "\\["
    )


def get_user(user_id):

    return bot_users_col.find_one({
        "user_id": user_id
    })


def is_banned(user_id):

    user = get_user(user_id)

    return bool(
        user and user.get("banned", False)
    )


def register_user(user):

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
                "start_logged": False,
                "milestones_claimed": []
            },

            "$set": {
                "first_name": user.first_name or "",
                "username": user.username or ""
            }
        },
        upsert=True
    )


def get_coin_balance(user_id):

    user = get_user(user_id)

    if not user:
        return 0

    return int(
        user.get("coins", 0)
    )


def add_coins(user_id, amount):

    bot_users_col.update_one(
        {"user_id": user_id},
        {
            "$inc": {
                "coins": int(amount)
            }
        },
        upsert=True
    )


def user_display_name(user):

    if not user:
        return "Unknown User"

    name = user.get(
        "first_name"
    ) or "User"

    username = user.get("username")

    if username:
        return f"{name} (@{username})"

    return name


def format_duration(minutes):

    minutes = int(minutes)

    if minutes > 525600:
        return "💎 Lifetime"

    if minutes % 1440 == 0:

        days = minutes // 1440

        return (
            f"{days} Day"
            if days == 1
            else f"{days} Days"
        )

    if minutes % 60 == 0:

        hours = minutes // 60

        return (
            f"{hours} Hour"
            if hours == 1
            else f"{hours} Hours"
        )

    return f"{minutes} Minutes"


def get_reward_options():

    options = get_settings().get(
        "reward_options",
        []
    )

    if not options:

        options = DEFAULT_SETTINGS[
            "reward_options"
        ]

        update_setting(
            "reward_options",
            options
        )

    return sorted(
        options,
        key=lambda item: int(
            item["minutes"]
        )
    )


def get_reward_channels():

    channels = list(
        reward_channels_col.find().sort(
            "added_at",
            1
        )
    )

    # Compatibility with old single premium channel
    if not channels:

        settings = get_settings()

        old_channel_id = settings.get(
            "reward_channel_id"
        )

        if old_channel_id:

            reward_channels_col.update_one(
                {
                    "channel_id": old_channel_id
                },
                {
                    "$set": {
                        "channel_id": old_channel_id,
                        "name": settings.get(
                            "reward_channel_name",
                            "Premium Channel"
                        ),
                        "added_at": datetime.now()
                    }
                },
                upsert=True
            )

            channels = list(
                reward_channels_col.find()
            )

    return channels


# ============================================================
# USER MAIN MENU
# ============================================================

def create_main_menu():

    settings = get_settings()

    markup = ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row(
        KeyboardButton(
            settings["btn_profile"]
        ),
        KeyboardButton(
            settings["btn_refer"]
        )
    )

    markup.row(
        KeyboardButton(
            settings["btn_redeem"]
        ),
        KeyboardButton(
            settings["btn_coupon"]
        )
    )

    markup.row(
        KeyboardButton(
            settings["btn_referrals"]
        ),
        KeyboardButton(
            settings["btn_milestones"]
        )
    )

    markup.row(
        KeyboardButton(
            settings["btn_leaderboard"]
        ),
        KeyboardButton(
            settings["btn_how"]
        )
    )

    markup.row(
        KeyboardButton(
            settings["btn_feedback"]
        ),
        KeyboardButton(
            settings["btn_contact"]
        )
    )

    return markup


def show_main_menu(
    chat_id,
    welcome=True
):

    text = (
        get_settings()["welcome_text"]
        if welcome
        else "👇 Choose an option below."
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=create_main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# START USER LOGGING SYSTEM
# ============================================================

def log_bot_start(user_id):

    settings = get_settings()

    log_channel = settings.get(
        "start_log_channel_id"
    )

    user = get_user(user_id)

    if (
        not log_channel
        or not user
        or user.get("start_logged")
    ):
        return

    referrer_id = (
        user.get("pending_referrer")
        or user.get("referrer_id")
    )

    referrer = (
        get_user(referrer_id)
        if referrer_id
        else None
    )

    if referrer:

        referrer_text = (
            f"{escape_markdown(user_display_name(referrer))} "
            f"(`{referrer_id}`)"
        )

    elif referrer_id:

        referrer_text = (
            f"ID `{referrer_id}`"
        )

    else:

        referrer_text = "No referrer"

    try:

        bot.send_message(
            log_channel,
            f"""🤖 *New Bot User Started*

👤 {escape_markdown(user.get('first_name'))}
🌐 @{escape_markdown(user.get('username') or 'Not set')}
🆔 `{user_id}`
🔗 Referrer: {referrer_text}""",
            parse_mode="Markdown"
        )

        bot_users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "start_logged": True
                }
            }
        )

    except Exception as error:

        print(
            "Start log error:",
            error
        )


# ============================================================
# FORCE JOIN SYSTEM
# ============================================================

def get_force_join_markup():

    markup = InlineKeyboardMarkup()

    for channel in force_channels_col.find():

        join_url = channel.get(
            "join_url"
        )

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

    bot.send_message(
        chat_id,
        get_settings()["force_join_text"],
        reply_markup=get_force_join_markup(),
        parse_mode="Markdown"
    )


def is_user_in_channel(
    channel_id,
    user_id
):

    try:

        member = bot.get_chat_member(
            channel_id,
            user_id
        )

        return member.status in (
            "creator",
            "administrator",
            "member",
            "restricted"
        )

    except Exception:

        return False


def check_all_force_channels(user_id):

    channels = list(
        force_channels_col.find()
    )

    if not channels:
        return False

    for channel in channels:

        if not is_user_in_channel(
            channel["channel_id"],
            user_id
        ):
            return False

    return True


# ============================================================
# START COMMAND
# ============================================================

@bot.message_handler(commands=["start"])
def start_handler(message):

    user_id = message.from_user.id

    register_user(
        message.from_user
    )

    if is_banned(user_id):

        bot.send_message(
            message.chat.id,
            "🚫 Your access to this bot has been restricted."
        )

        return

    parts = message.text.split(
        maxsplit=1
    )

    start_argument = (
        parts[1].strip()
        if len(parts) > 1
        else None
    )

    # --------------------------------------------------------
    # OLD PAID CHANNEL DEEP LINK
    # --------------------------------------------------------

    if start_argument:

        try:

            possible_channel_id = int(
                start_argument
            )

            if possible_channel_id < 0:

                channel_data = channels_col.find_one(
                    {
                        "channel_id":
                        possible_channel_id
                    }
                )

                if channel_data:

                    markup = InlineKeyboardMarkup()

                    markup.add(
                        InlineKeyboardButton(
                            "🔗 Demo",
                            url="https://t.me/+lSW2hYbgrUNkMzFl"
                        )
                    )

                    for plan_minutes in channel_data.get(
                        "plans",
                        {}
                    ):

                        markup.add(
                            InlineKeyboardButton(
                                f"💎 {format_duration(plan_minutes)}",
                                callback_data=(
                                    f"select_{possible_channel_id}_"
                                    f"{plan_minutes}"
                                )
                            )
                        )

                    if CONTACT_USERNAME:

                        markup.add(
                            InlineKeyboardButton(
                                "📞 Contact Admin",
                                url=(
                                    f"https://t.me/"
                                    f"{CONTACT_USERNAME}"
                                )
                            )
                        )

                    bot.send_message(
                        message.chat.id,
                        f"""✨ *Welcome!*

📢 *Channel:* `{escape_markdown(channel_data['name'])}`

Select a subscription plan below.""",
                        reply_markup=markup,
                        parse_mode="Markdown"
                    )

                    return

        except Exception:
            pass

    user_data = get_user(user_id)

    # Pending referral must verify first
    if (
        user_data.get("pending_referrer")
        is not None
        and not user_data.get(
            "verified_referral",
            False
        )
    ):

        log_bot_start(user_id)

        show_force_join(
            message.chat.id
        )

        return

    # New referral
    if start_argument:

        try:

            referrer_id = int(
                start_argument
            )

            referrer = get_user(
                referrer_id
            )

            if (
                referrer_id != user_id
                and referrer
                and not is_banned(referrer_id)
                and not user_data.get(
                    "verified_referral",
                    False
                )
                and user_data.get(
                    "pending_referrer"
                ) is None
                and user_data.get(
                    "referrer_id"
                ) is None
            ):

                bot_users_col.update_one(
                    {
                        "user_id": user_id
                    },
                    {
                        "$set": {
                            "pending_referrer":
                            referrer_id,

                            "referred_at":
                            datetime.now()
                        }
                    }
                )

                log_bot_start(user_id)

                show_force_join(
                    message.chat.id
                )

                return

        except Exception:
            pass

    log_bot_start(user_id)

    if user_id == ADMIN_ID:

        bot.send_message(
            user_id,
            "👑 *Admin Account*\n\n"
            "Use /admin to open the admin panel.",
            parse_mode="Markdown"
        )

    show_main_menu(
        message.chat.id
    )


# ============================================================
# VERIFY REFERRAL
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "verify_referral"
)
def verify_referral(call):

    user_id = call.from_user.id

    user_data = get_user(user_id)

    referrer_id = (
        user_data or {}
    ).get("pending_referrer")

    if not user_data or referrer_id is None:

        bot.answer_callback_query(
            call.id,
            "No pending referral.",
            show_alert=True
        )

        return

    if not check_all_force_channels(
        user_id
    ):

        bot.answer_callback_query(
            call.id,
            "❌ Join all required channels first.",
            show_alert=True
        )

        return

    result = bot_users_col.update_one(
        {
            "user_id": user_id,
            "verified_referral": False,
            "pending_referrer":
            referrer_id
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

    settings = get_settings()

    reward = int(
        settings["referral_reward"]
    )

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

    try:

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )

    except Exception:
        pass

    try:

        bot.send_message(
            referrer_id,
            f"""🎉 *New Successful Referral!*

👤 {escape_markdown(user_display_name(get_user(user_id)))} completed verification.

{settings['coin_emoji']} You received *{reward} {settings['coin_name']}*!""",
            parse_mode="Markdown"
        )

    except Exception:
        pass

    # Check milestones after every successful referral
    check_milestones(
        referrer_id
    )

    bot.answer_callback_query(
        call.id,
        "Verification successful!"
    )

    bot.send_message(
        user_id,
        settings[
            "verification_success_text"
        ],
        parse_mode="Markdown"
    )

    show_main_menu(
        user_id,
        welcome=False
    )


# ============================================================
# PROFILE
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_profile"]
)
def my_profile(message):

    register_user(
        message.from_user
    )

    user_id = message.from_user.id

    user = get_user(user_id)

    settings = get_settings()

    joined = user.get(
        "joined_at"
    )

    referrer_id = user.get(
        "referrer_id"
    )

    referrer = (
        get_user(referrer_id)
        if referrer_id
        else None
    )

    joined_text = (
        joined.strftime("%d %b %Y")
        if isinstance(joined, datetime)
        else "Unknown"
    )

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Not set"
    )

    bot.send_message(
        message.chat.id,
        f"""👤 *My Profile*

👤 Name: {escape_markdown(message.from_user.first_name)}
🌐 Username: {escape_markdown(username)}
🆔 ID: `{user_id}`
📅 Joined: {joined_text}

👥 Successful Referrals: *{user.get('referral_count', 0)}*
{settings['coin_emoji']} Balance: *{user.get('coins', 0)} {settings['coin_name']}*

🔗 Referred By: *{escape_markdown(user_display_name(referrer)) if referrer else 'No one'}*""",
        parse_mode="Markdown"
    )


# ============================================================
# REFER & EARN
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_refer"]
)
def refer_and_earn(message):

    settings = get_settings()

    user = (
        get_user(message.from_user.id)
        or {}
    )

    try:

        username = bot.get_me().username

        link = (
            f"https://t.me/{username}"
            f"?start={message.from_user.id}"
        )

    except Exception:

        link = "Unable to generate link."

    bot.send_message(
        message.chat.id,
        f"""🔗 *Refer & Earn*

🎁 Reward per successful referral:
{settings['coin_emoji']} *{settings['referral_reward']} {settings['coin_name']}*

👥 Successful Referrals: *{user.get('referral_count', 0)}*

🔗 *Your Referral Link:*

`{link}`

📌 Your friend must join all required channels and verify successfully before you receive the reward.""",
        parse_mode="Markdown"
    )


# ============================================================
# MY REFERRALS
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_referrals"]
)
def my_referrals(message):

    users = list(
        bot_users_col.find(
            {
                "referrer_id":
                message.from_user.id,

                "verified_referral":
                True
            }
        ).sort(
            "verified_at",
            DESCENDING
        ).limit(30)
    )

    if not users:

        bot.send_message(
            message.chat.id,
            "👥 *My Referrals*\n\n"
            "You don't have any successful referrals yet.",
            parse_mode="Markdown"
        )

        return

    text = (
        "👥 *My Successful Referrals*\n\n"
    )

    for number, user in enumerate(
        users,
        1
    ):

        text += (
            f"{number}. "
            f"{escape_markdown(user_display_name(user))}\n"
        )

    total = (
        get_user(
            message.from_user.id
        )
        or {}
    ).get(
        "referral_count",
        len(users)
    )

    text += f"\n🎉 *Total:* {total}"

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# HOW IT WORKS / CONTACT
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_how"]
)
def how_it_works(message):

    bot.send_message(
        message.chat.id,
        get_settings()["how_it_works_text"],
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_contact"]
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
            url=(
                f"https://t.me/"
                f"{CONTACT_USERNAME}"
            )
        )
    )

    bot.send_message(
        message.chat.id,
        "📞 *Need help?*\n\nContact the admin below:",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# FEEDBACK
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_feedback"]
)
def feedback_start(message):

    sent = bot.send_message(
        message.chat.id,
        get_settings()["feedback_text"],
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        sent,
        receive_feedback
    )


def receive_feedback(message):

    if not message.text:

        bot.send_message(
            message.chat.id,
            "❌ Please send text feedback."
        )

        return

    feedback_col.insert_one(
        {
            "user_id": message.from_user.id,
            "name":
            message.from_user.first_name or "",
            "username":
            message.from_user.username or "",
            "text": message.text,
            "created_at": datetime.now()
        }
    )

    try:

        bot.send_message(
            ADMIN_ID,
            f"""💬 *New Feedback*

👤 {escape_markdown(message.from_user.first_name)}
🆔 `{message.from_user.id}`

📝 {escape_markdown(message.text)}""",
            parse_mode="Markdown"
        )

    except Exception:
        pass

    bot.send_message(
        message.chat.id,
        "✅ Thank you! Your feedback has been sent to the admin."
    )


# ============================================================
# MILESTONE SYSTEM
# ============================================================

def progress_bar(
    current,
    target,
    length=10
):

    if target <= 0:
        return "█" * length

    filled = min(
        length,
        int(
            current / target * length
        )
    )

    return (
        "█" * filled
        + "░" * (length - filled)
    )


def get_milestone_text(user_id):

    user = get_user(user_id) or {}

    referral_count = int(
        user.get("referral_count", 0)
    )

    settings = get_settings()

    milestones = list(
        milestones_col.find(
            {
                "active": {
                    "$ne": False
                }
            }
        ).sort(
            "target",
            1
        )
    )

    if not milestones:

        return (
            "🎯 *Referral Milestones*\n\n"
            "No milestones have been set yet."
        )

    text = (
        "🎯 *Referral Milestones*\n\n"
        f"👥 Your successful referrals: *{referral_count}*\n\n"
    )

    for milestone in milestones:

        target = int(
            milestone["target"]
        )

        current = min(
            referral_count,
            target
        )

        percentage = min(
            100,
            int(
                current / target * 100
            )
        )

        milestone_name = (
            milestone.get("name")
            or f"{target} Referrals"
        )

        status = (
            "✅"
            if referral_count >= target
            else "🎯"
        )

        text += (
            f"{status} *{escape_markdown(milestone_name)}*\n"
            f"👥 {current}/{target} ({percentage}%)\n"
            f"`{progress_bar(current, target)}`\n"
            f"🎁 Reward: *{milestone['reward']} "
            f"{settings['coin_name']}*\n\n"
        )

    return text


@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_milestones"]
)
def user_milestones(message):

    bot.send_message(
        message.chat.id,
        get_milestone_text(
            message.from_user.id
        ),
        parse_mode="Markdown"
    )


def check_milestones(user_id):

    user = get_user(user_id)

    if not user:
        return

    referral_count = int(
        user.get("referral_count", 0)
    )

    settings = get_settings()

    milestones = milestones_col.find(
        {
            "active": {"$ne": False},
            "target": {
                "$lte": referral_count
            }
        }
    ).sort(
        "target",
        1
    )

    for milestone in milestones:

        milestone_id = str(
            milestone["_id"]
        )

        result = bot_users_col.update_one(
            {
                "user_id": user_id,
                "milestones_claimed": {
                    "$ne": milestone_id
                }
            },
            {
                "$addToSet": {
                    "milestones_claimed":
                    milestone_id
                }
            }
        )

        if result.modified_count != 1:
            continue

        reward = int(
            milestone["reward"]
        )

        add_coins(
            user_id,
            reward
        )

        milestone_name = (
            milestone.get("name")
            or f"{milestone['target']} Referrals"
        )

        try:

            bot.send_message(
                user_id,
                f"""🎉 *Milestone Completed!*

🏆 *Milestone:* {escape_markdown(milestone_name)}
👥 Target: *{milestone['target']} referrals*
{settings['coin_emoji']} *Reward Added:* {reward} {settings['coin_name']}

💰 The reward was added automatically!""",
                parse_mode="Markdown"
            )

        except Exception:
            pass

        log_channel = settings.get(
            "milestone_log_channel_id"
        )

        if log_channel:

            try:

                bot.send_message(
                    log_channel,
                    f"""🏆 *Milestone Completed*

👤 {escape_markdown(user_display_name(get_user(user_id)))}
🆔 `{user_id}`
🎯 {escape_markdown(milestone_name)}
👥 Referrals: *{referral_count}*
🎁 Reward: *{reward} {settings['coin_name']}*""",
                    parse_mode="Markdown"
                )

            except Exception:
                pass


# ============================================================
# PREMIUM REWARD SYSTEM
# MULTIPLE CHANNELS + MINUTES / HOURS / DAYS
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_redeem"]
)
def redeem_premium_menu(message):

    channels = get_reward_channels()

    settings = get_settings()

    if not channels:

        bot.send_message(
            message.chat.id,
            "⚠️ Premium rewards are not available yet."
        )

        return

    if len(channels) == 1:

        show_duration_menu(
            message.chat.id,
            message.from_user.id,
            channels[0]
        )

        return

    markup = InlineKeyboardMarkup()

    for channel in channels:

        markup.add(
            InlineKeyboardButton(
                f"📢 {channel.get('name', 'Premium Channel')}",
                callback_data=(
                    f"rewardch_"
                    f"{channel['channel_id']}"
                )
            )
        )

    bot.send_message(
        message.chat.id,
        f"""🎁 *Redeem Premium*

{settings['coin_emoji']} Balance: *{get_coin_balance(message.from_user.id)} {settings['coin_name']}*

Choose a Premium channel:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


def show_duration_menu(
    chat_id,
    user_id,
    channel
):

    settings = get_settings()

    markup = InlineKeyboardMarkup()

    for index, option in enumerate(
        get_reward_options()
    ):

        label = (
            option.get("label")
            or format_duration(
                option["minutes"]
            )
        )

        markup.add(
            InlineKeyboardButton(
                f"🎁 {label} — {option['cost']} "
                f"{settings['coin_name']}",
                callback_data=(
                    f"redeem_{channel['channel_id']}_"
                    f"{index}"
                )
            )
        )

    bot.send_message(
        chat_id,
        f"""🎁 *Redeem Premium*

📢 *Channel:* {escape_markdown(channel.get('name', 'Premium Channel'))}
{settings['coin_emoji']} Balance: *{get_coin_balance(user_id)} {settings['coin_name']}*

Choose your Premium duration:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("rewardch_")
)
def choose_reward_channel(call):

    try:

        channel_id = int(
            call.data.split(
                "_",
                1
            )[1]
        )

        channel = reward_channels_col.find_one(
            {
                "channel_id": channel_id
            }
        )

    except Exception:
        return

    if not channel:

        bot.answer_callback_query(
            call.id,
            "Channel unavailable.",
            show_alert=True
        )

        return

    bot.answer_callback_query(
        call.id
    )

    show_duration_menu(
        call.message.chat.id,
        call.from_user.id,
        channel
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("redeem_")
)
def redeem_premium(call):

    try:

        _, channel_id, option_index = (
            call.data.split("_")
        )

        channel_id = int(channel_id)

        option = get_reward_options()[
            int(option_index)
        ]

    except Exception:

        bot.answer_callback_query(
            call.id,
            "Invalid option.",
            show_alert=True
        )

        return

    channel = reward_channels_col.find_one(
        {
            "channel_id": channel_id
        }
    )

    if not channel:

        bot.answer_callback_query(
            call.id,
            "Channel unavailable.",
            show_alert=True
        )

        return

    cost = int(
        option["cost"]
    )

    result = bot_users_col.update_one(
        {
            "user_id": call.from_user.id,
            "coins": {"$gte": cost},
            "banned": {"$ne": True}
        },
        {
            "$inc": {
                "coins": -cost
            }
        }
    )

    if result.modified_count != 1:

        bot.answer_callback_query(
            call.id,
            "❌ You don't have enough coins!",
            show_alert=True
        )

        return

    try:

        minutes = int(
            option["minutes"]
        )

        expiry_datetime = (
            None
            if minutes > 525600
            else datetime.now()
            + timedelta(minutes=minutes)
        )

        # Invite link expiration is separate from membership expiry.
        invite_expiry = (
            expiry_datetime
            if expiry_datetime
            else datetime.now()
            + timedelta(days=1)
        )

        invite = bot.create_chat_invite_link(
            channel_id,
            member_limit=1,
            expire_date=int(
                invite_expiry.timestamp()
            )
        )

        users_col.delete_many(
            {
                "user_id": call.from_user.id,
                "channel_id": channel_id,
                "source": "coin_reward"
            }
        )

        users_col.update_one(
            {
                "user_id": call.from_user.id,
                "channel_id": channel_id
            },
            {
                "$set": {
                    "expiry": (
                        float("inf")
                        if expiry_datetime is None
                        else expiry_datetime.timestamp()
                    ),
                    "source": "coin_reward",
                    "reward_minutes": minutes
                }
            },
            upsert=True
        )

        label = (
            option.get("label")
            or format_duration(minutes)
        )

        bot.answer_callback_query(
            call.id,
            "Premium redeemed successfully!"
        )

        bot.send_message(
            call.from_user.id,
            f"""🎉 *Premium Redeemed Successfully!*

🎁 *Reward:* {escape_markdown(label)}
📢 *Channel:* {escape_markdown(channel.get('name', 'Premium Channel'))}
⏰ *Membership Ends:* {expiry_datetime.strftime('%d %b %Y, %H:%M') if expiry_datetime else 'Never'}

🔗 *Join Link:*
{invite.invite_link}

⚠️ This link can only be used once.""",
            parse_mode="Markdown"
        )

    except Exception as error:

        add_coins(
            call.from_user.id,
            cost
        )

        print(
            "Premium redeem error:",
            error
        )

        bot.answer_callback_query(
            call.id,
            "❌ Error. Your coins were refunded.",
            show_alert=True
        )


# ============================================================
# COUPON SYSTEM
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_coupon"]
)
def coupon_prompt(message):

    sent = bot.send_message(
        message.chat.id,
        "🎟 Send the coupon code you want to claim."
    )

    bot.register_next_step_handler(
        sent,
        claim_coupon
    )


def claim_coupon(message):

    if not message.text:
        return

    code = message.text.strip().upper()

    coupon = coupons_col.find_one(
        {
            "code": code
        }
    )

    if not coupon:

        bot.send_message(
            message.chat.id,
            "❌ Invalid coupon code."
        )

        return

    if (
        coupon.get("expires_at")
        and coupon["expires_at"]
        < datetime.now()
    ):

        bot.send_message(
            message.chat.id,
            "⌛ This coupon has expired."
        )

        return

    already_used = coupon_uses_col.find_one(
        {
            "coupon_code": code,
            "user_id": message.from_user.id
        }
    )

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
                "$lt": coupon.get(
                    "max_uses",
                    1
                )
            }
        },
        {
            "$inc": {
                "used_count": 1
            }
        }
    )

    if result.modified_count != 1:

        bot.send_message(
            message.chat.id,
            "❌ This coupon is no longer available."
        )

        return

    coupon_uses_col.insert_one(
        {
            "coupon_code": code,
            "user_id": message.from_user.id,
            "claimed_at": datetime.now()
        }
    )

    add_coins(
        message.from_user.id,
        int(coupon["coins"])
    )

    settings = get_settings()

    bot.send_message(
        message.chat.id,
        f"""🎉 *Coupon Claimed Successfully!*

{settings['coin_emoji']} You received *{coupon['coins']} {settings['coin_name']}*!""",
        parse_mode="Markdown"
    )


# ============================================================
# LEADERBOARD
# ============================================================

@bot.message_handler(
    func=lambda message:
    bool(message.text)
    and message.text
    == get_settings()["btn_leaderboard"]
)
def leaderboard(message):

    users = list(
        bot_users_col.find(
            {
                "referral_count": {
                    "$gt": 0
                },
                "banned": {
                    "$ne": True
                }
            }
        ).sort(
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

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    text = (
        "🏆 *Referral Leaderboard*\n\n"
    )

    for position, user in enumerate(users):

        rank = (
            medals[position]
            if position < 3
            else f"{position + 1}."
        )

        text += (
            f"{rank} "
            f"{escape_markdown(user.get('first_name', 'User'))} "
            f"— *{user.get('referral_count', 0)} referrals*\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# OLD PAID SUBSCRIPTION / CHANNEL SYSTEM
# ============================================================

@bot.message_handler(
    commands=["add"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def add_paid_channel(message):

    sent = bot.send_message(
        ADMIN_ID,
        "Make sure the bot is Admin in your channel.\n\n"
        "Then FORWARD any message from that channel."
    )

    bot.register_next_step_handler(
        sent,
        get_paid_plans
    )


def get_paid_plans(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Message was not forwarded. Use /add again."
        )

        return

    chat = message.forward_from_chat

    sent = bot.send_message(
        ADMIN_ID,
        f"""✅ Channel Detected: {escape_markdown(chat.title)}

Enter plans:

`1440:99,43200:199`

1440 = 1 Day
43200 = 30 Days""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        sent,
        finish_paid_channel,
        chat.id,
        chat.title
    )


def finish_paid_channel(
    message,
    channel_id,
    channel_name
):

    try:

        plans = {}

        for plan in message.text.split(","):

            duration, price = (
                plan.strip().split(":")
            )

            plans[
                duration.strip()
            ] = price.strip()

        channels_col.update_one(
            {
                "channel_id": channel_id
            },
            {
                "$set": {
                    "name": channel_name,
                    "plans": plans,
                    "admin_id": ADMIN_ID
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"""✅ Setup Successful!

Invite Link:
`https://t.me/{bot.get_me().username}?start={channel_id}`""",
            parse_mode="Markdown"
        )

    except Exception:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\n"
            "Use: `1440:99,43200:199`",
            parse_mode="Markdown"
        )


@bot.message_handler(
    commands=["channels"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def list_paid_channels(message):

    channels = list(
        channels_col.find(
            {
                "admin_id": ADMIN_ID
            }
        )
    )

    text = (
        "📢 *Paid Channels*\n\n"
    )

    if channels:

        for channel in channels:

            text += (
                f"• {escape_markdown(channel['name'])} "
                f"— `{channel['channel_id']}`\n"
            )

    else:

        text += "No channels found."

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("select_")
)
def select_paid_plan(call):

    try:

        _, channel_id, minutes = (
            call.data.split("_")
        )

        channel = channels_col.find_one(
            {
                "channel_id": int(channel_id)
            }
        )

        price = float(
            channel["plans"][minutes]
        )

    except Exception:
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "✅ I Have Paid",
            callback_data=(
                f"paid_{channel_id}_{minutes}"
            )
        )
    )

    if CONTACT_USERNAME:

        markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=(
                    f"https://t.me/"
                    f"{CONTACT_USERNAME}"
                )
            )
        )

    bot.send_message(
        call.message.chat.id,
        f"""📢 *{escape_markdown(channel['name'])}*

💎 *Plan:* {format_duration(minutes)}
💰 NPR: *{price:.0f}*

*Binance ID:*
`{UPI_ID}`

After payment tap *I Have Paid* and send your screenshot.""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("paid_")
)
def paid_plan_selected(call):

    try:

        _, channel_id, minutes = (
            call.data.split("_")
        )

        channel = channels_col.find_one(
            {
                "channel_id": int(channel_id)
            }
        )

    except Exception:
        return

    user_id = call.from_user.id

    if user_id in pending_payments:

        bot.answer_callback_query(
            call.id,
            "⚠️ You already have a pending payment.",
            show_alert=True
        )

        return

    pending_payments[user_id] = {
        "channel_id": int(channel_id),
        "channel_name": channel["name"],
        "plan": minutes,
        "price": channel["plans"][minutes],
        "time": datetime.now()
    }

    bot.answer_callback_query(
        call.id
    )

    bot.send_message(
        user_id,
        "📷 *Upload Payment Screenshot*\n\n"
        "Please send it as a *PHOTO*.",
        parse_mode="Markdown"
    )


@bot.message_handler(
    content_types=["photo"]
)
def payment_photo_handler(message):

    user_id = message.from_user.id

    if user_id not in pending_payments:
        return

    payment = pending_payments.pop(
        user_id
    )

    try:

        bot.forward_message(
            ADMIN_ID,
            message.chat.id,
            message.message_id
        )

    except Exception:
        pass

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
            callback_data=(
                f"rej_{user_id}"
            )
        )
    )

    bot.send_message(
        ADMIN_ID,
        f"""🔔 *Payment Verification Required*

👤 {escape_markdown(message.from_user.first_name)}
🆔 `{user_id}`
📢 {escape_markdown(payment['channel_name'])}
💎 {payment['plan']}
💰 NPR {payment['price']}""",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.send_message(
        user_id,
        "✅ Screenshot uploaded!\n\n"
        "⏳ Waiting for admin verification."
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("app_")
)
def approve_payment(call):

    if call.from_user.id != ADMIN_ID:
        return

    try:

        _, user_id, channel_id, minutes = (
            call.data.split("_")
        )

        user_id = int(user_id)
        channel_id = int(channel_id)
        minutes = int(minutes)

        expiry_datetime = (
            None
            if minutes > 525600
            else datetime.now()
            + timedelta(minutes=minutes)
        )

        invite_expiry = (
            expiry_datetime
            if expiry_datetime
            else datetime.now()
            + timedelta(days=1)
        )

        invite = bot.create_chat_invite_link(
            channel_id,
            member_limit=1,
            expire_date=int(
                invite_expiry.timestamp()
            )
        )

        users_col.update_one(
            {
                "user_id": user_id,
                "channel_id": channel_id
            },
            {
                "$set": {
                    "expiry": (
                        float("inf")
                        if expiry_datetime is None
                        else expiry_datetime.timestamp()
                    ),
                    "source":
                    "paid_subscription"
                }
            },
            upsert=True
        )

        bot.send_message(
            user_id,
            f"""🎉 *Payment Approved!*

💎 *Plan:* {format_duration(minutes)}

🔗 *Join Link:*
{invite.invite_link}

⚠️ This link can only be used once.""",
            parse_mode="Markdown"
        )

        bot.edit_message_text(
            "✅ Payment Approved Successfully.",
            call.message.chat.id,
            call.message.message_id
        )

    except Exception as error:

        bot.send_message(
            ADMIN_ID,
            f"❌ Approval Error:\n{error}"
        )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("rej_")
)
def reject_payment(call):

    if call.from_user.id != ADMIN_ID:
        return

    user_id = int(
        call.data.split("_")[1]
    )

    try:

        bot.send_message(
            user_id,
            "❌ *Payment Rejected*\n\n"
            "Contact admin if this is a mistake.",
            parse_mode="Markdown"
        )

    except Exception:
        pass

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# ============================================================
# ADMIN PANEL
# ============================================================

def create_admin_keyboard():

    markup = InlineKeyboardMarkup(
        row_width=2
    )

    buttons = [
        ("📢 Channels", "ach"),
        ("🎁 Premium", "arp"),
        ("🎯 Milestones", "ami"),
        ("📢 Verification", "afv"),
        ("👥 Users", "aus"),
        ("🎟 Coupons", "aco"),
        ("⚙️ Settings", "ase"),
        ("🔄 User Mode", "aum")
    ]

    for text, callback in buttons:

        markup.add(
            InlineKeyboardButton(
                text,
                callback_data=callback
            )
        )

    return markup


@bot.message_handler(
    commands=["admin"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def admin_panel(message):

    settings = get_settings()

    bot.send_message(
        ADMIN_ID,
        f"""👑 *ADMIN PANEL*

🪙 Currency: *{escape_markdown(settings['coin_name'])}*
🎁 Reward Channels: *{len(get_reward_channels())}*
🎯 Milestones: *{milestones_col.count_documents({})}*

👇 Use the buttons below.""",
        reply_markup=create_admin_keyboard(),
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data in (
        "ach",
        "arp",
        "ami",
        "afv",
        "aus",
        "aco",
        "ase",
        "aum"
    )
)
def admin_panel_buttons(call):

    if call.from_user.id != ADMIN_ID:
        return

    help_text = {
        "ach": (
            "📢 *Paid Channels*\n\n"
            "/add — Add paid channel\n"
            "/channels — View channels"
        ),

        "arp": (
            "🎁 *Premium Rewards*\n\n"
            "/rewardadd — Add Premium channel\n"
            "/rewardlist — View/remove channels\n\n"
            "/rewardoption HOURS 6 50 6 Hours\n"
            "/rewardoptions — View/remove durations"
        ),

        "ami": (
            "🎯 *Milestones*\n\n"
            "/milestone TARGET REWARD NAME\n\n"
            "Example:\n"
            "`/milestone 50 500 50 Referrals`\n\n"
            "/milestones — View/remove\n"
            "/setmilestonelog — Set completion log channel"
        ),

        "afv": (
            "📢 *Verification*\n\n"
            "/forceadd — Add required channel\n"
            "/forcelist — Remove/view"
        ),

        "aus": (
            "👥 *Users*\n\n"
            "/users — Recent users\n"
            "/stats — Statistics\n"
            "/setstartlog — Set start-record channel\n"
            "/userinfo USER_ID\n"
            "/ban USER_ID\n"
            "/unban USER_ID"
        ),

        "aco": (
            "🎟 *Coupons*\n\n"
            "/coupon CODE COINS MAX_USERS HOURS\n"
            "/coupons"
        ),

        "ase": (
            "⚙️ *Settings*\n\n"
            "/setcoin NAME\n"
            "/setemoji EMOJI\n"
            "/setreward AMOUNT\n"
            "/setcost DAYS COINS"
        )
    }

    if call.data == "aum":

        bot.answer_callback_query(
            call.id
        )

        show_main_menu(
            ADMIN_ID
        )

        return

    bot.answer_callback_query(
        call.id
    )

    bot.send_message(
        ADMIN_ID,
        help_text[call.data],
        parse_mode="Markdown"
    )


# ============================================================
# PREMIUM REWARD CHANNEL ADMIN
# ============================================================

@bot.message_handler(
    commands=["rewardadd", "setpremium"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def reward_channel_start(message):

    sent = bot.send_message(
        ADMIN_ID,
        "🎁 Forward a message from the Premium reward channel.\n\n"
        "The bot must be an administrator there."
    )

    bot.register_next_step_handler(
        sent,
        save_reward_channel
    )


def save_reward_channel(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a channel message."
        )

        return

    chat = message.forward_from_chat

    reward_channels_col.update_one(
        {
            "channel_id": chat.id
        },
        {
            "$set": {
                "channel_id": chat.id,
                "name": (
                    chat.title
                    or "Premium Channel"
                ),
                "added_at": datetime.now()
            }
        },
        upsert=True
    )

    # Keep old system compatible
    update_setting(
        "reward_channel_id",
        chat.id
    )

    update_setting(
        "reward_channel_name",
        chat.title or "Premium Channel"
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Premium reward channel added: "
        f"*{escape_markdown(chat.title)}*",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["rewardlist"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def reward_channel_list(message):

    channels = get_reward_channels()

    markup = InlineKeyboardMarkup()

    for channel in channels:

        markup.add(
            InlineKeyboardButton(
                f"🗑 Remove {channel['name']}",
                callback_data=(
                    f"rr_{channel['channel_id']}"
                )
            )
        )

    text = (
        "🎁 *Premium Reward Channels*\n\n"
    )

    if channels:

        for channel in channels:

            text += (
                f"📢 {escape_markdown(channel['name'])} "
                f"— `{channel['channel_id']}`\n"
            )

    else:

        text += "No channels."

    bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("rr_")
)
def remove_reward_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        call.data[3:]
    )

    reward_channels_col.delete_one(
        {
            "channel_id": channel_id
        }
    )

    bot.answer_callback_query(
        call.id,
        "Removed!"
    )

    bot.edit_message_text(
        "✅ Reward channel removed. Use /rewardlist to refresh.",
        call.message.chat.id,
        call.message.message_id
    )


# ============================================================
# EDITABLE PREMIUM DURATIONS
# ============================================================

@bot.message_handler(
    commands=["rewardoption"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def add_reward_option(message):

    parts = message.text.split(
        maxsplit=4
    )

    if len(parts) < 5:

        bot.reply_to(
            message,
            "Usage:\n"
            "`/rewardoption HOURS 6 50 6 Hours`\n\n"
            "Supported: MINUTES, HOURS, DAYS",
            parse_mode="Markdown"
        )

        return

    try:

        amount = int(parts[2])
        cost = int(parts[3])

    except ValueError:

        bot.reply_to(
            message,
            "❌ Amount and cost must be numbers."
        )

        return

    multiplier = {
        "MINUTE": 1,
        "MINUTES": 1,
        "MIN": 1,
        "HOUR": 60,
        "HOURS": 60,
        "HR": 60,
        "DAY": 1440,
        "DAYS": 1440
    }.get(
        parts[1].upper()
    )

    if (
        not multiplier
        or amount <= 0
        or cost < 0
    ):

        bot.reply_to(
            message,
            "❌ Use MINUTES, HOURS or DAYS with valid values."
        )

        return

    minutes = amount * multiplier

    options = get_reward_options()

    options = [
        option
        for option in options
        if int(option["minutes"]) != minutes
    ]

    options.append(
        {
            "minutes": minutes,
            "cost": cost,
            "label": parts[4]
        }
    )

    options.sort(
        key=lambda item:
        int(item["minutes"])
    )

    update_setting(
        "reward_options",
        options
    )

    bot.reply_to(
        message,
        "✅ Premium duration added/updated."
    )


@bot.message_handler(
    commands=["rewardoptions"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def list_reward_options(message):

    options = get_reward_options()

    markup = InlineKeyboardMarkup()

    text = (
        "🎁 *Premium Durations*\n\n"
    )

    for option in options:

        label = (
            option.get("label")
            or format_duration(
                option["minutes"]
            )
        )

        text += (
            f"• {escape_markdown(label)} — "
            f"{option['cost']} "
            f"{escape_markdown(get_settings()['coin_name'])}\n"
        )

        markup.add(
            InlineKeyboardButton(
                f"🗑 Remove {label}",
                callback_data=(
                    f"ro_{option['minutes']}"
                )
            )
        )

    bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("ro_")
)
def remove_reward_option(call):

    if call.from_user.id != ADMIN_ID:
        return

    minutes = int(
        call.data[3:]
    )

    options = [
        option
        for option in get_reward_options()
        if int(option["minutes"]) != minutes
    ]

    if not options:

        bot.answer_callback_query(
            call.id,
            "Keep at least one option.",
            show_alert=True
        )

        return

    update_setting(
        "reward_options",
        options
    )

    bot.answer_callback_query(
        call.id,
        "Removed!"
    )

    bot.edit_message_text(
        "✅ Duration removed. Use /rewardoptions to refresh.",
        call.message.chat.id,
        call.message.message_id
    )


# ============================================================
# MILESTONE ADMIN
# ============================================================

@bot.message_handler(
    commands=["milestone"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def add_milestone(message):

    parts = message.text.split(
        maxsplit=3
    )

    if len(parts) < 4:

        bot.reply_to(
            message,
            "Usage:\n"
            "`/milestone TARGET REWARD NAME`\n\n"
            "Example:\n"
            "`/milestone 50 500 50 Referrals`",
            parse_mode="Markdown"
        )

        return

    try:

        target = int(parts[1])
        reward = int(parts[2])

    except ValueError:

        bot.reply_to(
            message,
            "❌ Target and reward must be numbers."
        )

        return

    if target <= 0 or reward < 0:

        bot.reply_to(
            message,
            "❌ Invalid values."
        )

        return

    milestones_col.update_one(
        {
            "target": target
        },
        {
            "$set": {
                "target": target,
                "reward": reward,
                "name": parts[3],
                "active": True,
                "updated_at": datetime.now()
            }
        },
        upsert=True
    )

    bot.reply_to(
        message,
        "✅ Milestone created/updated."
    )


@bot.message_handler(
    commands=["milestones"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def admin_milestones(message):

    milestones = list(
        milestones_col.find(
            {
                "active": {
                    "$ne": False
                }
            }
        ).sort(
            "target",
            1
        )
    )

    markup = InlineKeyboardMarkup()

    text = (
        "🎯 *Milestones*\n\n"
    )

    if milestones:

        for milestone in milestones:

            text += (
                f"🎯 {escape_markdown(milestone.get('name'))}: "
                f"{milestone['target']} referrals → "
                f"{milestone['reward']} "
                f"{escape_markdown(get_settings()['coin_name'])}\n"
            )

            markup.add(
                InlineKeyboardButton(
                    f"🗑 Remove {milestone['target']} referrals",
                    callback_data=(
                        f"mr_{milestone['_id']}"
                    )
                )
            )

    else:

        text += "No milestones."

    bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("mr_")
)
def remove_milestone(call):

    if call.from_user.id != ADMIN_ID:
        return

    try:

        milestone_id = ObjectId(
            call.data[3:]
        )

        milestones_col.delete_one(
            {
                "_id": milestone_id
            }
        )

        bot.answer_callback_query(
            call.id,
            "Removed!"
        )

        bot.edit_message_text(
            "✅ Milestone removed. Use /milestones to refresh.",
            call.message.chat.id,
            call.message.message_id
        )

    except Exception:
        pass


# ============================================================
# LOG CHANNEL ADMIN
# ============================================================

def set_log_channel_prompt(
    message,
    setting_key,
    channel_name
):

    sent = bot.send_message(
        ADMIN_ID,
        f"📢 Forward a message from the {channel_name}."
    )

    bot.register_next_step_handler(
        sent,
        lambda reply:
        save_log_channel(
            reply,
            setting_key,
            channel_name
        )
    )


def save_log_channel(
    message,
    setting_key,
    channel_name
):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a channel message."
        )

        return

    chat = message.forward_from_chat

    update_setting(
        setting_key,
        chat.id
    )

    update_setting(
        setting_key + "_name",
        chat.title or channel_name
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ {channel_name} set successfully."
    )


@bot.message_handler(
    commands=["setstartlog"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def set_start_log(message):

    set_log_channel_prompt(
        message,
        "start_log_channel_id",
        "Start Log Channel"
    )


@bot.message_handler(
    commands=["setmilestonelog"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def set_milestone_log(message):

    set_log_channel_prompt(
        message,
        "milestone_log_channel_id",
        "Milestone Log Channel"
    )


@bot.message_handler(
    commands=["removestartlog"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def remove_start_log(message):

    update_setting(
        "start_log_channel_id",
        None
    )

    bot.reply_to(
        message,
        "✅ Start log channel removed."
    )


@bot.message_handler(
    commands=["removemilestonelog"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def remove_milestone_log(message):

    update_setting(
        "milestone_log_channel_id",
        None
    )

    bot.reply_to(
        message,
        "✅ Milestone log channel removed."
    )


# ============================================================
# FORCE JOIN ADMIN
# ============================================================

@bot.message_handler(
    commands=["forceadd"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def force_add_start(message):

    sent = bot.send_message(
        ADMIN_ID,
        "📢 Forward a message from the required "
        "channel/group.\n\n"
        "The bot must be an admin."
    )

    bot.register_next_step_handler(
        sent,
        save_force_channel
    )


def save_force_channel(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Forward a channel/group message."
        )

        return

    chat = message.forward_from_chat

    try:

        if chat.username:

            join_url = (
                f"https://t.me/"
                f"{chat.username}"
            )

        else:

            invite = (
                bot.create_chat_invite_link(
                    chat.id
                )
            )

            join_url = invite.invite_link

    except Exception:

        bot.send_message(
            ADMIN_ID,
            "❌ Could not create invite. "
            "Make the bot admin."
        )

        return

    force_channels_col.update_one(
        {
            "channel_id": chat.id
        },
        {
            "$set": {
                "channel_id": chat.id,
                "name": (
                    chat.title
                    or "Required Channel"
                ),
                "join_url": join_url
            }
        },
        upsert=True
    )

    bot.send_message(
        ADMIN_ID,
        "✅ Required channel added."
    )


@bot.message_handler(
    commands=["forcelist"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def force_channel_list(message):

    channels = list(
        force_channels_col.find()
    )

    markup = InlineKeyboardMarkup()

    text = (
        "📢 *Required Channels*\n\n"
    )

    if channels:

        for channel in channels:

            text += (
                f"• {escape_markdown(channel['name'])}\n"
            )

            markup.add(
                InlineKeyboardButton(
                    f"🗑 Remove {channel['name']}",
                    callback_data=(
                        f"fr_{channel['channel_id']}"
                    )
                )
            )

    else:

        text += "None."

    bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("fr_")
)
def remove_force_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        call.data[3:]
    )

    force_channels_col.delete_one(
        {
            "channel_id": channel_id
        }
    )

    bot.answer_callback_query(
        call.id,
        "Removed!"
    )

    bot.edit_message_text(
        "✅ Required channel removed.",
        call.message.chat.id,
        call.message.message_id
    )


# ============================================================
# COIN SETTINGS ADMIN
# ============================================================

@bot.message_handler(
    commands=["setcoin"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def set_coin_name(message):

    parts = message.text.split(
        maxsplit=1
    )

    if len(parts) < 2:

        bot.reply_to(
            message,
            "Usage: /setcoin NAME"
        )

        return

    update_setting(
        "coin_name",
        parts[1]
    )

    bot.reply_to(
        message,
        "✅ Coin name updated."
    )


@bot.message_handler(
    commands=["setemoji"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def set_coin_emoji(message):

    parts = message.text.split(
        maxsplit=1
    )

    if len(parts) < 2:

        bot.reply_to(
            message,
            "Usage: /setemoji 🪙"
        )

        return

    update_setting(
        "coin_emoji",
        parts[1]
    )

    bot.reply_to(
        message,
        "✅ Coin emoji updated."
    )


@bot.message_handler(
    commands=["setreward"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def set_referral_reward(message):

    try:

        reward = int(
            message.text.split()[1]
        )

        update_setting(
            "referral_reward",
            reward
        )

        bot.reply_to(
            message,
            "✅ Referral reward updated."
        )

    except Exception:

        bot.reply_to(
            message,
            "Usage: /setreward AMOUNT"
        )


# Old command kept for compatibility
@bot.message_handler(
    commands=["setcost"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def set_reward_cost(message):

    try:

        days = int(
            message.text.split()[1]
        )

        cost = int(
            message.text.split()[2]
        )

    except Exception:

        bot.reply_to(
            message,
            "Usage: /setcost DAYS COINS"
        )

        return

    minutes = days * 1440

    options = get_reward_options()

    found = False

    for option in options:

        if int(option["minutes"]) == minutes:

            option["cost"] = cost
            found = True

    if not found:

        options.append(
            {
                "minutes": minutes,
                "cost": cost,
                "label":
                format_duration(minutes)
            }
        )

    update_setting(
        "reward_options",
        options
    )

    bot.reply_to(
        message,
        "✅ Premium cost updated."
    )


@bot.message_handler(
    commands=["settings"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def show_settings(message):

    settings = get_settings()

    bot.send_message(
        ADMIN_ID,
        f"""⚙️ *Settings*

🪙 Coin: {escape_markdown(settings['coin_name'])}
🎁 Referral Reward: {settings['referral_reward']}
🎁 Reward Channels: {len(get_reward_channels())}
🎯 Milestones: {milestones_col.count_documents({})}""",
        parse_mode="Markdown"
    )


# ============================================================
# EDITABLE TEXT AND BUTTONS
# ============================================================

EDITABLE_TEXT_KEYS = {
    "welcome": "welcome_text",
    "forcejoin": "force_join_text",
    "verified":
    "verification_success_text",
    "how": "how_it_works_text",
    "feedback": "feedback_text"
}

BUTTON_KEYS = {
    "profile": "btn_profile",
    "refer": "btn_refer",
    "redeem": "btn_redeem",
    "coupon": "btn_coupon",
    "leaderboard": "btn_leaderboard",
    "referrals": "btn_referrals",
    "milestones": "btn_milestones",
    "how": "btn_how",
    "feedback": "btn_feedback",
    "contact": "btn_contact"
}


@bot.message_handler(
    commands=["texts"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def show_text_keys(message):

    bot.send_message(
        ADMIN_ID,
        "✏️ *Editable Text Keys*\n\n"
        "`welcome, forcejoin, verified, how, feedback`\n\n"
        "Use:\n"
        "`/edittext KEY NEW_TEXT`",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["edittext"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def edit_text(message):

    parts = message.text.split(
        maxsplit=2
    )

    if (
        len(parts) < 3
        or parts[1] not in EDITABLE_TEXT_KEYS
    ):

        bot.reply_to(
            message,
            "❌ Invalid text key. Use /texts."
        )

        return

    update_setting(
        EDITABLE_TEXT_KEYS[
            parts[1]
        ],
        parts[2]
    )

    bot.reply_to(
        message,
        "✅ Text updated."
    )


@bot.message_handler(
    commands=["setbutton"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def set_button(message):

    parts = message.text.split(
        maxsplit=2
    )

    if (
        len(parts) < 3
        or parts[1] not in BUTTON_KEYS
    ):

        bot.reply_to(
            message,
            "❌ Invalid button key."
        )

        return

    update_setting(
        BUTTON_KEYS[
            parts[1]
        ],
        parts[2]
    )

    bot.reply_to(
        message,
        "✅ Button updated."
    )


# ============================================================
# BAN / UNBAN / USER MANAGEMENT
# ============================================================

@bot.message_handler(
    commands=["ban", "unban"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def ban_unban_user(message):

    try:

        user_id = int(
            message.text.split()[1]
        )

    except Exception:

        bot.reply_to(
            message,
            "Usage: /ban USER_ID or /unban USER_ID"
        )

        return

    if user_id == ADMIN_ID:

        bot.reply_to(
            message,
            "❌ Cannot ban admin."
        )

        return

    banned = message.text.startswith(
        "/ban"
    )

    bot_users_col.update_one(
        {
            "user_id": user_id
        },
        {
            "$set": {
                "banned": banned
            }
        },
        upsert=False
    )

    bot.reply_to(
        message,
        "🚫 User banned."
        if banned
        else "✅ User unbanned."
    )


@bot.message_handler(
    commands=["userinfo"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def user_info(message):

    try:

        user_id = int(
            message.text.split()[1]
        )

        user = get_user(user_id)

    except Exception:

        user = None

    if not user:

        bot.reply_to(
            message,
            "❌ User not found."
        )

        return

    bot.send_message(
        ADMIN_ID,
        f"""👤 *User Information*

Name: {escape_markdown(user.get('first_name'))}
Username: @{escape_markdown(user.get('username') or 'Not set')}
ID: `{user['user_id']}`

🪙 Coins: {user.get('coins', 0)}
👥 Referrals: {user.get('referral_count', 0)}
🔗 Referred By: {user.get('referrer_id', 'Nobody')}
🚫 Banned: {user.get('banned', False)}""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["users"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def recent_users(message):

    users = list(
        bot_users_col.find().sort(
            "joined_at",
            DESCENDING
        ).limit(30)
    )

    text = (
        "👥 *Recent Users*\n\n"
    )

    if users:

        for number, user in enumerate(
            users,
            1
        ):

            text += (
                f"{number}. "
                f"{escape_markdown(user.get('first_name'))} "
                f"— `{user['user_id']}` "
                f"| 👥 {user.get('referral_count', 0)}\n"
            )

    else:

        text += "No users."

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# COUPON ADMIN
# ============================================================

@bot.message_handler(
    commands=["coupon"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def create_coupon(message):

    parts = message.text.split()

    if len(parts) != 5:

        bot.reply_to(
            message,
            "Usage:\n"
            "`/coupon CODE COINS MAX_USERS HOURS`",
            parse_mode="Markdown"
        )

        return

    try:

        code = parts[1].upper()
        coins = int(parts[2])
        max_users = int(parts[3])
        hours = int(parts[4])

    except ValueError:

        bot.reply_to(
            message,
            "❌ Invalid values."
        )

        return

    coupons_col.update_one(
        {
            "code": code
        },
        {
            "$set": {
                "code": code,
                "coins": coins,
                "max_uses": max_users,
                "used_count": 0,
                "expires_at":
                datetime.now()
                + timedelta(hours=hours),
                "created_at": datetime.now()
            }
        },
        upsert=True
    )

    bot.reply_to(
        message,
        "✅ Coupon created."
    )


@bot.message_handler(
    commands=["coupons"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def list_coupons(message):

    coupons = list(
        coupons_col.find().sort(
            "created_at",
            DESCENDING
        ).limit(20)
    )

    text = "🎟 *Coupons*\n\n"

    if coupons:

        for coupon in coupons:

            text += (
                f"`{coupon['code']}` — "
                f"{coupon['coins']} coins | "
                f"{coupon.get('used_count', 0)}/"
                f"{coupon['max_uses']}\n"
            )

    else:

        text += "No coupons."

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# BROADCAST SYSTEM
# ============================================================

@bot.message_handler(
    commands=["broadcast"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def broadcast_start(message):

    sent = bot.send_message(
        ADMIN_ID,
        "📢 Send the message you want to broadcast."
    )

    bot.register_next_step_handler(
        sent,
        broadcast_message
    )


def broadcast_message(message):

    success = 0
    failed = 0

    users = bot_users_col.find(
        {
            "banned": {
                "$ne": True
            }
        },
        {
            "user_id": 1
        }
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


# ============================================================
# FEEDBACK ADMIN
# ============================================================

@bot.message_handler(
    commands=["feedbacks"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def list_feedbacks(message):

    feedbacks = list(
        feedback_col.find().sort(
            "created_at",
            DESCENDING
        ).limit(10)
    )

    text = (
        "💬 *Recent Feedback*\n\n"
    )

    if feedbacks:

        for feedback in feedbacks:

            text += (
                f"👤 {escape_markdown(feedback.get('name'))}\n"
                f"📝 {escape_markdown(feedback.get('text', '')[:300])}\n\n"
            )

    else:

        text += "No feedback."

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# STATISTICS
# ============================================================

@bot.message_handler(
    commands=["stats"],
    func=lambda message:
    message.from_user.id == ADMIN_ID
)
def bot_stats(message):

    total_users = bot_users_col.count_documents(
        {}
    )

    verified = bot_users_col.count_documents(
        {
            "verified_referral": True
        }
    )

    banned_users = bot_users_col.count_documents(
        {
            "banned": True
        }
    )

    aggregate = list(
        bot_users_col.aggregate(
            [
                {
                    "$group": {
                        "_id": None,
                        "total": {
                            "$sum": "$coins"
                        }
                    }
                }
            ]
        )
    )

    total_coins = (
        aggregate[0]["total"]
        if aggregate
        else 0
    )

    bot.send_message(
        ADMIN_ID,
        f"""📊 *Bot Statistics*

👥 Total Users: *{total_users}*
🔗 Verified Referrals: *{verified}*
🚫 Banned Users: *{banned_users}*
🪙 Total User Coins: *{total_coins}*

📢 Paid Channels: *{channels_col.count_documents({})}*
🎁 Reward Channels: *{len(get_reward_channels())}*
🎯 Milestones: *{milestones_col.count_documents({})}*
🎟 Coupons: *{coupons_col.count_documents({})}*""",
        parse_mode="Markdown"
    )


# ============================================================
# PAYMENT CLEANUP
# ============================================================

def clear_pending_payments():

    now = datetime.now()

    for user_id, payment in list(
        pending_payments.items()
    ):

        if (
            now - payment["time"]
        ).total_seconds() >= 600:

            try:

                bot.send_message(
                    user_id,
                    "⌛ Your payment verification request expired. "
                    "Please try again."
                )

            except Exception:
                pass

            pending_payments.pop(
                user_id,
                None
            )


# ============================================================
# AUTO REMOVE EXPIRED MEMBERS
# IMPORTANT: USER IS NOT PERMANENTLY BANNED
# ============================================================

def remove_expired_members():

    now = datetime.now().timestamp()

    expired_users = users_col.find(
        {
            "expiry": {
                "$lte": now
            }
        }
    )

    for user_data in list(
        expired_users
    ):

        try:

            channel_id = user_data[
                "channel_id"
            ]

            user_id = user_data[
                "user_id"
            ]

            # Telegram does not have a separate kick method.
            # Ban + immediate unban removes the user but DOES NOT
            # permanently ban them. They can purchase again and rejoin.
            bot.ban_chat_member(
                channel_id,
                user_id
            )

            bot.unban_chat_member(
                channel_id,
                user_id
            )

            source = user_data.get(
                "source",
                "paid_subscription"
            )

            if source == "coin_reward":

                settings = get_settings()

                balance = get_coin_balance(
                    user_id
                )

                text = (
                    "⏰ *Your Premium Membership Has Expired*\n\n"
                    "Your Premium time has ended and you have been "
                    "removed from the channel.\n\n"
                )

                if balance > 0:

                    text += (
                        f"{settings['coin_emoji']} You have "
                        f"*{balance} {settings['coin_name']}*.\n\n"
                        "🎁 You can buy Premium again using your coins!"
                    )

                else:

                    text += (
                        f"🔗 Please refer more friends to earn "
                        f"{settings['coin_name']} and redeem Premium again!"
                    )

                try:

                    bot.send_message(
                        user_id,
                        text,
                        parse_mode="Markdown"
                    )

                except Exception:
                    pass

            else:

                try:

                    bot_username = (
                        bot.get_me().username
                    )

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
                {
                    "_id": user_data["_id"]
                }
            )

        except Exception as error:

            # Keep record if removal fails so it can retry
            print(
                "Expiry removal error:",
                error
            )


# ============================================================
# UNKNOWN MESSAGE FALLBACK
# ============================================================

@bot.message_handler(
    func=lambda message: True,
    content_types=["text"]
)
def unknown_message(message):

    if (
        message.text
        and message.text.startswith("/")
    ):
        return

    if not is_banned(
        message.from_user.id
    ):

        bot.send_message(
            message.chat.id,
            "ℹ️ Please use the buttons below.",
            reply_markup=create_main_menu()
        )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    keep_alive()

    # Create/update settings
    get_settings()

    # Convert old reward channel automatically if needed
    get_reward_channels()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        remove_expired_members,
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

    bot.infinity_polling(
        timeout=20,
        long_polling_timeout=10,
        skip_pending=True
    )