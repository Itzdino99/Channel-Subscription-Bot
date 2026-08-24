import os
import time
import telebot

from datetime import datetime, timedelta
from threading import Thread

from flask import Flask
from pymongo import MongoClient, DESCENDING, ASCENDING
from apscheduler.schedulers.background import BackgroundScheduler

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)


# =========================================================
# KEEP ALIVE SERVER
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


# =========================================================
# DATABASE COLLECTIONS
# =========================================================

# OLD SYSTEM COLLECTIONS
channels_col = db["channels"]
users_col = db["users"]

# NEW SYSTEM COLLECTIONS
bot_users_col = db["bot_users"]
settings_col = db["settings"]
texts_col = db["texts"]
buttons_col = db["buttons"]

force_channels_col = db["force_channels"]
reward_channels_col = db["reward_channels"]

coupons_col = db["coupons"]
coupon_uses_col = db["coupon_uses"]

feedback_col = db["feedback"]
bans_col = db["bans"]

admin_logs_col = db["admin_logs"]


# =========================================================
# TEMPORARY MEMORY
# =========================================================

pending_payments = {}
user_states = {}
broadcast_cancel = set()


# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "_id": "bot_settings",

    # Coin system
    "coin_name": "Coins",
    "coin_emoji": "🪙",
    "referral_reward": 10,

    # Reward costs
    "reward_1_day_cost": 50,
    "reward_7_day_cost": 250,
    "reward_30_day_cost": 800,

    # Contact
    "contact_username": CONTACT_USERNAME,

    # Referral
    "referral_enabled": True,

    # Features
    "coupon_enabled": True,
    "feedback_enabled": True,
    "leaderboard_enabled": True,

    # General
    "maintenance_mode": False,

    # Paid subscription settings
    "demo_url": ""
}


# =========================================================
# DEFAULT TEXTS
# =========================================================

DEFAULT_TEXTS = {

    "welcome_text": (
        "✨ *Welcome!*\n\n"
        "Choose an option below to continue."
    ),

    "force_join_text": (
        "🎉 *Welcome!*\n\n"
        "You joined the bot through a referral link.\n\n"
        "To complete registration, please join all the required "
        "channels/groups below and then press *Verify & Continue*."
    ),

    "verification_success_text": (
        "✅ *Verification Successful!*\n\n"
        "Welcome! You can now use all bot features."
    ),

    "referral_notification": (
        "🎉 *New Successful Referral!*\n\n"
        "👤 *{name}* has successfully joined through your referral link.\n\n"
        "{coin_emoji} You received *{reward} {coin_name}*!"
    ),

    "how_it_works_text": (
        "📖 *How It Works*\n\n"
        "1️⃣ Share your referral link.\n"
        "2️⃣ A new user starts the bot using your link.\n"
        "3️⃣ They join the required channels.\n"
        "4️⃣ They press Verify.\n"
        "5️⃣ After successful verification, you receive coins.\n\n"
        "🪙 Use your coins to redeem Premium rewards!"
    ),

    "premium_expired_text": (
        "⏰ *Your Premium Membership Has Expired*\n\n"
        "Your Premium reward time has ended and you have been "
        "removed from the Premium channel.\n\n"
        "🪙 Refer more friends to earn coins and redeem again!"
    ),

    "feedback_thanks_text": (
        "✅ *Thank you for your feedback!*\n\n"
        "Your feedback has been sent to the admin."
    )
}


# =========================================================
# DEFAULT BUTTONS
# =========================================================

DEFAULT_BUTTONS = {
    "profile": "🌐 My Profile",
    "refer": "🔗 Refer & Earn",
    "redeem": "🎁 Redeem Premium",
    "coupon": "🎟 Claim Coupon",
    "leaderboard": "🏆 Leaderboard",
    "my_referrals": "👥 My Referrals",
    "how_it_works": "📖 How It Works",
    "feedback": "💬 Feedback",
    "contact": "📞 Contact Admin"
}


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def initialize_database():

    settings = settings_col.find_one({"_id": "bot_settings"})

    if not settings:
        settings_col.insert_one(DEFAULT_SETTINGS.copy())
    else:
        missing = {}

        for key, value in DEFAULT_SETTINGS.items():
            if key not in settings:
                missing[key] = value

        if missing:
            settings_col.update_one(
                {"_id": "bot_settings"},
                {"$set": missing}
            )

    for key, value in DEFAULT_TEXTS.items():
        texts_col.update_one(
            {"_id": key},
            {"$setOnInsert": {"value": value}},
            upsert=True
        )

    for key, value in DEFAULT_BUTTONS.items():
        buttons_col.update_one(
            {"_id": key},
            {"$setOnInsert": {"value": value}},
            upsert=True
        )

    # Useful indexes
    bot_users_col.create_index("user_id", unique=True)
    coupons_col.create_index("code", unique=True)
    coupon_uses_col.create_index(
        [("coupon_code", ASCENDING), ("user_id", ASCENDING)],
        unique=True
    )


# =========================================================
# SETTINGS HELPERS
# =========================================================

def get_settings():
    settings = settings_col.find_one({"_id": "bot_settings"})
    return settings or DEFAULT_SETTINGS.copy()


def update_setting(key, value):
    settings_col.update_one(
        {"_id": "bot_settings"},
        {"$set": {key: value}},
        upsert=True
    )


def get_text(key):
    data = texts_col.find_one({"_id": key})
    return data["value"] if data else DEFAULT_TEXTS.get(key, "")


def set_text(key, value):
    texts_col.update_one(
        {"_id": key},
        {"$set": {"value": value}},
        upsert=True
    )


def get_button(key):
    data = buttons_col.find_one({"_id": key})
    return data["value"] if data else DEFAULT_BUTTONS.get(key, key)


def set_button(key, value):
    buttons_col.update_one(
        {"_id": key},
        {"$set": {"value": value}},
        upsert=True
    )


# =========================================================
# ADMIN LOG
# =========================================================

def admin_log(action, admin_id=ADMIN_ID, details=""):
    try:
        admin_logs_col.insert_one({
            "action": action,
            "admin_id": admin_id,
            "details": details,
            "created_at": datetime.now()
        })
    except:
        pass


# =========================================================
# USER HELPERS
# =========================================================

def get_user(user_id):
    return bot_users_col.find_one({"user_id": user_id})


def register_user(user):

    bot_users_col.update_one(
        {"user_id": user.id},
        {
            "$setOnInsert": {
                "user_id": user.id,
                "joined_at": datetime.now(),

                "coins": 0,
                "referral_count": 0,

                # Referral state
                "pending_referrer": None,
                "referrer_id": None,
                "verified_referral": False,

                # Security
                "banned": False
            },

            "$set": {
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "username": user.username or ""
            }
        },
        upsert=True
    )


def is_banned(user_id):

    user = get_user(user_id)

    if user and user.get("banned", False):
        return True

    ban = bans_col.find_one({"user_id": user_id})
    return ban is not None


def ban_user(user_id, reason="No reason provided"):

    bot_users_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "banned": True,
            "ban_reason": reason,
            "banned_at": datetime.now()
        }},
        upsert=True
    )

    bans_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "reason": reason,
            "banned_at": datetime.now()
        }},
        upsert=True
    )


def unban_user(user_id):

    bot_users_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "banned": False
        },
         "$unset": {
             "ban_reason": "",
             "banned_at": ""
         }}
    )

    bans_col.delete_one({"user_id": user_id})


def add_coins(user_id, amount):

    bot_users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"coins": amount}},
        upsert=True
    )


def get_coin_balance(user_id):

    user = get_user(user_id)
    return int(user.get("coins", 0)) if user else 0


def get_user_display(user):

    if not user:
        return "Unknown User"

    name = user.get("first_name") or "User"

    username = user.get("username")

    if username:
        return f"{name} (@{username})"

    return name


# =========================================================
# USER ACCESS CHECK
# =========================================================

def can_use_bot(message):

    user_id = message.from_user.id

    if user_id == ADMIN_ID:
        return True

    settings = get_settings()

    if settings.get("maintenance_mode", False):
        bot.reply_to(
            message,
            "🚧 *The bot is currently under maintenance.*\n\n"
            "Please try again later.",
            parse_mode="Markdown"
        )
        return False

    if is_banned(user_id):
        bot.reply_to(
            message,
            "🚫 *You have been banned from using this bot.*\n\n"
            "Contact the administrator if you believe this is a mistake.",
            parse_mode="Markdown"
        )
        return False

    return True


# =========================================================
# MAIN USER MENU
# =========================================================

def main_menu(user_id, chat_id=None):

    if chat_id is None:
        chat_id = user_id

    markup = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    # Profile contains balance as requested
    markup.row(
        KeyboardButton(get_button("profile")),
        KeyboardButton(get_button("refer"))
    )

    markup.row(
        KeyboardButton(get_button("redeem")),
        KeyboardButton(get_button("coupon"))
    )

    markup.row(
        KeyboardButton(get_button("my_referrals")),
        KeyboardButton(get_button("leaderboard"))
    )

    markup.row(
        KeyboardButton(get_button("how_it_works")),
        KeyboardButton(get_button("feedback"))
    )

    markup.row(
        KeyboardButton(get_button("contact"))
    )

    bot.send_message(
        chat_id,
        get_text("welcome_text"),
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# FORCE JOIN SYSTEM
# =========================================================

def get_force_join_markup():

    markup = InlineKeyboardMarkup()

    channels = list(
        force_channels_col.find().sort("added_at", ASCENDING)
    )

    for channel in channels:

        name = channel.get("name", "Channel")
        url = channel.get("join_url")

        if url:
            markup.add(
                InlineKeyboardButton(
                    f"📢 Join {name}",
                    url=url
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

    if not channels:

        bot.send_message(
            chat_id,
            "⚠️ Required verification channels have not been configured.\n\n"
            "Please contact the administrator."
        )
        return

    bot.send_message(
        chat_id,
        get_text("force_join_text"),
        reply_markup=get_force_join_markup(),
        parse_mode="Markdown"
    )


def is_user_in_channel(channel_id, user_id):

    try:

        member = bot.get_chat_member(
            channel_id,
            user_id
        )

        return member.status in [
            "creator",
            "administrator",
            "member",
            "restricted"
        ]

    except Exception as e:

        print(
            f"Membership check error "
            f"channel={channel_id} user={user_id}: {e}"
        )

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

    register_user(message.from_user)

    if not can_use_bot(message):
        return

    parts = message.text.split(maxsplit=1)
    start_argument = parts[1].strip() if len(parts) > 1 else None

    user_data = get_user(user_id)

    # =====================================================
    # 1. PENDING REFERRAL - NEVER ALLOW BYPASS
    # =====================================================

    if (
        user_data
        and user_data.get("pending_referrer") is not None
        and not user_data.get("verified_referral", False)
    ):

        show_force_join(message.chat.id)
        return


    # =====================================================
    # 2. OLD PAID CHANNEL DEEP LINK
    # =====================================================

    if start_argument:

        try:

            possible_channel_id = int(start_argument)

            if possible_channel_id < 0:

                ch_data = channels_col.find_one(
                    {"channel_id": possible_channel_id}
                )

                if ch_data:

                    markup = InlineKeyboardMarkup()

                    settings = get_settings()
                    demo_url = settings.get("demo_url", "")

                    if demo_url:
                        markup.add(
                            InlineKeyboardButton(
                                "🔗 Demo",
                                url=demo_url
                            )
                        )

                    for p_time in ch_data.get("plans", {}):

                        minutes = int(p_time)

                        if minutes > 525600:
                            label = "💎 Lifetime"

                        elif minutes >= 1440:
                            label = (
                                f"📅 {minutes // 1440} Days"
                            )

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

                    contact = get_settings().get(
                        "contact_username",
                        ""
                    )

                    if contact:
                        markup.add(
                            InlineKeyboardButton(
                                "📞 Contact Admin",
                                url=f"https://t.me/{contact}"
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


    # =====================================================
    # 3. NEW REFERRAL LINK
    # =====================================================

    settings = get_settings()

    if start_argument and settings.get(
        "referral_enabled",
        True
    ):

        try:

            referrer_id = int(start_argument)

            referrer = get_user(referrer_id)

            # Only first-time un-referred users can receive referral
            # Pending referral is saved BEFORE verification.
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

                show_force_join(message.chat.id)
                return

        except ValueError:
            pass


    # =====================================================
    # 4. NORMAL USER
    # =====================================================

    if user_id == ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "👑 *Admin Account*\n\n"
            "Use /admin to open the admin panel.",
            parse_mode="Markdown"
        )

    main_menu(user_id, message.chat.id)


# =========================================================
# REFERRAL VERIFICATION
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "verify_referral"
)
def verify_referral(call):

    user_id = call.from_user.id

    if is_banned(user_id):

        bot.answer_callback_query(
            call.id,
            "You cannot use this feature.",
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
            "No pending referral verification found.",
            show_alert=True
        )
        return

    if user_data.get("verified_referral", False):

        bot.answer_callback_query(
            call.id,
            "You are already verified.",
            show_alert=True
        )
        return

    if not check_all_force_channels(user_id):

        bot.answer_callback_query(
            call.id,
            "❌ Please join ALL required channels first.",
            show_alert=True
        )
        return

    # Check referrer still exists and isn't banned
    if is_banned(referrer_id):

        bot.answer_callback_query(
            call.id,
            "Referral is no longer valid.",
            show_alert=True
        )

        return


    # =====================================================
    # ATOMIC ONE-TIME REFERRAL VERIFICATION
    # =====================================================

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
            "This referral was already processed.",
            show_alert=True
        )
        return


    # =====================================================
    # REWARD REFERRER
    # =====================================================

    settings = get_settings()
    reward = int(settings.get("referral_reward", 10))

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

    admin_log(
        "Referral verified",
        details=f"{user_id} referred by {referrer_id}"
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
    except:
        pass

    # Notify referrer
    try:

        new_user = get_user(user_id)

        notification = get_text(
            "referral_notification"
        ).format(
            name=get_user_display(new_user),
            reward=reward,
            coin_name=settings["coin_name"],
            coin_emoji=settings["coin_emoji"]
        )

        bot.send_message(
            referrer_id,
            notification,
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Referrer notification error: {e}")

    bot.send_message(
        user_id,
        get_text("verification_success_text"),
        parse_mode="Markdown"
    )

    main_menu(user_id)


# =========================================================
# USER PROFILE
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_button("profile")
)
def my_profile(message):

    if not can_use_bot(message):
        return

    user = get_user(message.from_user.id)
    settings = get_settings()

    if not user:
        register_user(message.from_user)
        user = get_user(message.from_user.id)

    joined = user.get("joined_at")

    if isinstance(joined, datetime):
        joined_text = joined.strftime("%d %b %Y")
    else:
        joined_text = "Unknown"

    referrer_text = "No one"

    referrer_id = user.get("referrer_id")

    if referrer_id:

        referrer = get_user(referrer_id)

        if referrer:
            referrer_text = get_user_display(referrer)
        else:
            referrer_text = f"User ID: {referrer_id}"

    bot.send_message(
        message.chat.id,
        f"""👤 *My Profile*

👤 *Name:* {get_user_display(user)}
🆔 *User ID:* `{message.from_user.id}`
📅 *Joined:* {joined_text}

{settings['coin_emoji']} *Balance:* {user.get('coins', 0)} {settings['coin_name']}
👥 *Successful Referrals:* {user.get('referral_count', 0)}

🔗 *Referred By:* {referrer_text}""",
        parse_mode="Markdown"
    )


# =========================================================
# REFER & EARN
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_button("refer")
)
def refer_and_earn(message):

    if not can_use_bot(message):
        return

    user_id = message.from_user.id
    user = get_user(user_id)
    settings = get_settings()

    username = bot.get_me().username
    link = f"https://t.me/{username}?start={user_id}"

    bot.send_message(
        message.chat.id,
        f"""🔗 *Refer & Earn*

🎁 *Reward per successful referral:*
{settings['coin_emoji']} *{settings['referral_reward']} {settings['coin_name']}*

👥 *Successful Referrals:* {user.get('referral_count', 0)}

🔗 *Your Personal Referral Link:*

`{link}`

📌 Your friend must:
1️⃣ Start the bot using your link
2️⃣ Join all required channels
3️⃣ Press Verify

Only after successful verification will you receive your reward.""",
        parse_mode="Markdown"
    )


# =========================================================
# MY REFERRALS - SHOW ACTUAL USERS
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_button("my_referrals")
)
def my_referrals(message):

    if not can_use_bot(message):
        return

    user_id = message.from_user.id

    referrals = list(
        bot_users_col.find(
            {
                "referrer_id": user_id,
                "verified_referral": True
            }
        ).sort(
            "verified_at",
            DESCENDING
        ).limit(30)
    )

    if not referrals:

        bot.send_message(
            message.chat.id,
            "👥 *My Referrals*\n\n"
            "You don't have any successful referrals yet.\n\n"
            "Share your referral link to start earning!",
            parse_mode="Markdown"
        )
        return

    text = "👥 *My Successful Referrals*\n\n"

    for index, user in enumerate(referrals, 1):

        name = user.get("first_name") or "User"
        username = user.get("username")

        if username:
            name += f" (@{username})"

        verified = user.get("verified_at")

        date_text = ""

        if isinstance(verified, datetime):
            date_text = verified.strftime("%d %b")

        text += (
            f"{index}. {name}"
            f"{' — ' + date_text if date_text else ''}\n"
        )

    total = get_user(user_id).get(
        "referral_count",
        0
    )

    text += f"\n📊 *Total Successful:* {total}"

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# HOW IT WORKS
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_button("how_it_works")
)
def how_it_works(message):

    if not can_use_bot(message):
        return

    bot.send_message(
        message.chat.id,
        get_text("how_it_works_text"),
        parse_mode="Markdown"
    )


# =========================================================
# CONTACT ADMIN
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_button("contact")
)
def contact_admin(message):

    if not can_use_bot(message):
        return

    contact = get_settings().get(
        "contact_username",
        ""
    )

    if not contact:

        bot.send_message(
            message.chat.id,
            "⚠️ Contact information has not been configured yet."
        )
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{contact}"
        )
    )

    bot.send_message(
        message.chat.id,
        "📞 *Need help?*\n\n"
        "Contact the administrator below:",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# FEEDBACK SYSTEM
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_button("feedback")
)
def feedback_start(message):

    if not can_use_bot(message):
        return

    if not get_settings().get(
        "feedback_enabled",
        True
    ):
        bot.send_message(
            message.chat.id,
            "⚠️ Feedback is currently disabled."
        )
        return

    msg = bot.send_message(
        message.chat.id,
        "💬 *Send your feedback or suggestion.*\n\n"
        "Your message will be sent directly to the administrator.",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        save_feedback
    )


def save_feedback(message):

    if not can_use_bot(message):
        return

    if not message.text:
        bot.send_message(
            message.chat.id,
            "❌ Please send feedback as a text message."
        )
        return

    feedback_col.insert_one({
        "user_id": message.from_user.id,
        "first_name": message.from_user.first_name or "",
        "username": message.from_user.username or "",
        "message": message.text,
        "created_at": datetime.now(),
        "status": "new"
    })

    user_name = message.from_user.first_name or "User"
    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "No username"
    )

    try:

        bot.send_message(
            ADMIN_ID,
            f"""💬 *New Feedback*

👤 *Name:* {user_name}
🌐 *Username:* {username}
🆔 *User ID:* `{message.from_user.id}`

📝 *Feedback:*
{message.text}""",
            parse_mode="Markdown"
        )

    except Exception as e:
        print(e)

    bot.send_message(
        message.chat.id,
        get_text("feedback_thanks_text"),
        parse_mode="Markdown"
    )


# =========================================================
# REWARD PREMIUM CHANNEL SYSTEM
# SEPARATE FROM OLD PAID CHANNEL SYSTEM
# =========================================================

def get_active_reward_channel():

    return reward_channels_col.find_one(
        {"active": True}
    )


@bot.message_handler(
    func=lambda m: m.text == get_button("redeem")
)
def redeem_premium_menu(message):

    if not can_use_bot(message):
        return

    settings = get_settings()
    channel = get_active_reward_channel()

    if not channel:

        bot.send_message(
            message.chat.id,
            "⚠️ Premium rewards are not available yet."
        )
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            f"🎁 1 Day — {settings['reward_1_day_cost']} "
            f"{settings['coin_name']}",
            callback_data="redeem_1"
        )
    )

    markup.add(
        InlineKeyboardButton(
            f"🎁 7 Days — {settings['reward_7_day_cost']} "
            f"{settings['coin_name']}",
            callback_data="redeem_7"
        )
    )

    markup.add(
        InlineKeyboardButton(
            f"🎁 30 Days — {settings['reward_30_day_cost']} "
            f"{settings['coin_name']}",
            callback_data="redeem_30"
        )
    )

    balance = get_coin_balance(
        message.from_user.id
    )

    bot.send_message(
        message.chat.id,
        f"""🎁 *Redeem Premium*

📢 *Channel:* {channel.get('name', 'Premium Channel')}

{settings['coin_emoji']} *Your Balance:*
*{balance} {settings['coin_name']}*

Choose your Premium reward:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data in [
        "redeem_1",
        "redeem_7",
        "redeem_30"
    ]
)
def redeem_premium(call):

    user_id = call.from_user.id

    if is_banned(user_id):

        bot.answer_callback_query(
            call.id,
            "You cannot redeem rewards.",
            show_alert=True
        )
        return

    settings = get_settings()

    reward_map = {
        "redeem_1": (
            1,
            int(settings["reward_1_day_cost"])
        ),

        "redeem_7": (
            7,
            int(settings["reward_7_day_cost"])
        ),

        "redeem_30": (
            30,
            int(settings["reward_30_day_cost"])
        )
    }

    days, cost = reward_map[call.data]

    channel = get_active_reward_channel()

    if not channel:

        bot.answer_callback_query(
            call.id,
            "Premium channel is not configured.",
            show_alert=True
        )
        return

    channel_id = channel["channel_id"]

    # Prevent duplicate active reward memberships
    now_ts = datetime.now().timestamp()

    existing = users_col.find_one({
        "user_id": user_id,
        "channel_id": channel_id,
        "expiry": {"$gt": now_ts},
        "source": "coin_reward"
    })

    # Atomically deduct coins
    result = bot_users_col.update_one(
        {
            "user_id": user_id,
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
            "❌ You don't have enough coins.",
            show_alert=True
        )
        return

    try:

        expiry_datetime = datetime.now() + timedelta(
            days=days
        )

        expiry_ts = int(
            expiry_datetime.timestamp()
        )

        link = bot.create_chat_invite_link(
            channel_id,
            member_limit=1,
            expire_date=expiry_ts
        )

        # If the user already has reward access,
        # extend their membership instead of creating conflicts.
        if existing:

            old_expiry = datetime.fromtimestamp(
                existing["expiry"]
            )

            new_expiry = max(
                old_expiry,
                datetime.now()
            ) + timedelta(days=days)

            users_col.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "expiry": new_expiry.timestamp(),
                        "reward_days": days,
                        "updated_at": datetime.now()
                    }
                }
            )

            expiry_datetime = new_expiry

        else:

            users_col.update_one(
                {
                    "user_id": user_id,
                    "channel_id": channel_id
                },
                {
                    "$set": {
                        "expiry": expiry_datetime.timestamp(),
                        "source": "coin_reward",
                        "reward_days": days,
                        "created_at": datetime.now()
                    }
                },
                upsert=True
            )

        admin_log(
            "Premium redeemed",
            details=f"user={user_id}, days={days}, cost={cost}"
        )

        bot.answer_callback_query(
            call.id,
            "Premium redeemed successfully!"
        )

        bot.send_message(
            user_id,
            f"""🎉 *Premium Redeemed Successfully!*

🎁 *Reward:* {days} Day Premium
⏰ *Expires:* {expiry_datetime.strftime("%d %b %Y, %H:%M")}

🔗 *Your Join Link:*
{link.invite_link}

⚠️ This link can only be used once.

After your Premium time expires, you will automatically be removed from the Premium channel.""",
            parse_mode="Markdown"
        )

    except Exception as e:

        # Refund coins if something fails
        add_coins(user_id, cost)

        print(f"Redeem error: {e}")

        bot.answer_callback_query(
            call.id,
            "❌ Something went wrong. Your coins were refunded.",
            show_alert=True
        )


# =========================================================
# COUPON SYSTEM
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_button("coupon")
)
def claim_coupon_prompt(message):

    if not can_use_bot(message):
        return

    if not get_settings().get(
        "coupon_enabled",
        True
    ):
        bot.send_message(
            message.chat.id,
            "⚠️ Coupons are currently disabled."
        )
        return

    msg = bot.send_message(
        message.chat.id,
        "🎟 *Send the coupon code you want to claim.*",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        process_coupon
    )


def process_coupon(message):

    if not can_use_bot(message):
        return

    if not message.text:
        return

    code = message.text.strip().upper()
    user_id = message.from_user.id
    settings = get_settings()

    coupon = coupons_col.find_one({
        "code": code,
        "active": {"$ne": False}
    })

    if not coupon:

        bot.send_message(
            message.chat.id,
            "❌ Invalid or inactive coupon code."
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

    # Atomic usage reservation
    result = coupons_col.update_one(
        {
            "code": code,
            "active": {"$ne": False},
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

    try:

        coupon_uses_col.insert_one({
            "coupon_code": code,
            "user_id": user_id,
            "claimed_at": datetime.now()
        })

    except Exception:

        # Duplicate safety
        coupons_col.update_one(
            {"code": code},
            {"$inc": {"used_count": -1}}
        )

        bot.send_message(
            message.chat.id,
            "⚠️ You have already used this coupon."
        )
        return

    coins = int(coupon["coins"])

    add_coins(
        user_id,
        coins
    )

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
    func=lambda m: m.text == get_button("leaderboard")
)
def leaderboard(message):

    if not can_use_bot(message):
        return

    if not get_settings().get(
        "leaderboard_enabled",
        True
    ):
        bot.send_message(
            message.chat.id,
            "⚠️ Leaderboard is currently disabled."
        )
        return

    users = list(
        bot_users_col.find(
            {
                "referral_count": {"$gt": 0},
                "banned": {"$ne": True}
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

    text = "🏆 *Referral Leaderboard*\n\n"

    medals = ["🥇", "🥈", "🥉"]

    for position, user in enumerate(
        users,
        start=1
    ):

        prefix = (
            medals[position - 1]
            if position <= 3
            else f"{position}."
        )

        name = (
            user.get("first_name")
            or "User"
        )

        count = user.get(
            "referral_count",
            0
        )

        text += (
            f"{prefix} {name} — "
            f"*{count} referrals*\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# OLD PAID CHANNEL MANAGEMENT
# =========================================================

@bot.message_handler(
    commands=["channels"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_channels(message):

    markup = InlineKeyboardMarkup()

    cursor = channels_col.find({
        "admin_id": ADMIN_ID
    })

    count = 0

    for ch in cursor:

        markup.add(
            InlineKeyboardButton(
                f"📢 {ch['name']}",
                callback_data=(
                    f"manage_paid_{ch['channel_id']}"
                )
            )
        )

        count += 1

    markup.add(
        InlineKeyboardButton(
            "➕ Add New Paid Channel",
            callback_data="add_new_paid"
        )
    )

    bot.send_message(
        ADMIN_ID,
        (
            "📢 *Your Paid Channels*"
            if count
            else "No paid channels found."
        ),
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "add_new_paid"
)
def cb_add_new_paid(call):

    if call.from_user.id != ADMIN_ID:
        return

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Please forward any message "
        "from your paid channel.\n\n"
        "Make sure the bot is an administrator."
    )

    bot.register_next_step_handler(
        msg,
        get_plans
    )


@bot.message_handler(
    commands=["add"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward any message from the "
        "paid subscription channel."
    )

    bot.register_next_step_handler(
        msg,
        get_plans
    )


def get_plans(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from a channel."
        )
        return

    chat = message.forward_from_chat

    msg = bot.send_message(
        ADMIN_ID,
        f"""✅ *Channel Detected:* {chat.title}

Enter plans in this format:

`1440:99,43200:199`

Examples:
• 1440 = 1 Day
• 10080 = 7 Days
• 43200 = 30 Days

Format: `MINUTES:PRICE`""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        finalize_channel,
        chat.id,
        chat.title
    )


def finalize_channel(message, ch_id, ch_name):

    try:

        raw_plans = message.text.split(",")
        plans_dict = {}

        for plan in raw_plans:

            t, price = plan.strip().split(":")

            int(t)
            float(price)

            plans_dict[t] = price

        channels_col.update_one(
            {"channel_id": ch_id},
            {
                "$set": {
                    "name": ch_name,
                    "plans": plans_dict,
                    "admin_id": ADMIN_ID,
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )

        username = bot.get_me().username

        bot.send_message(
            ADMIN_ID,
            f"""✅ *Paid Channel Added Successfully!*

🔗 Your subscription link:

`https://t.me/{username}?start={ch_id}`""",
            parse_mode="Markdown"
        )

    except Exception as e:

        print(e)

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\n"
            "Example:\n`1440:99,43200:199`",
            parse_mode="Markdown"
        )


# =========================================================
# PAID CHANNEL MANAGE / DELETE
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("manage_paid_")
)
def manage_paid_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        call.data.replace("manage_paid_", "")
    )

    channel = channels_col.find_one({
        "channel_id": channel_id
    })

    if not channel:

        bot.answer_callback_query(
            call.id,
            "Channel not found."
        )
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🗑 Remove Channel",
            callback_data=(
                f"delete_paid_{channel_id}"
            )
        )
    )

    bot.send_message(
        ADMIN_ID,
        f"""📢 *Paid Channel*

Name: *{channel['name']}*
ID: `{channel_id}`

Plans:
`{channel.get('plans', {})}`""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("delete_paid_")
)
def delete_paid_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        call.data.replace("delete_paid_", "")
    )

    channels_col.delete_one({
        "channel_id": channel_id
    })

    bot.answer_callback_query(
        call.id,
        "Paid channel removed."
    )

    bot.edit_message_text(
        "🗑 Paid channel removed successfully.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# OLD PAYMENT SYSTEM
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("select_")
)
def user_pays(call):

    try:

        _, ch_id, mins = call.data.split("_")

        ch_data = channels_col.find_one({
            "channel_id": int(ch_id)
        })

        if not ch_data:

            bot.answer_callback_query(
                call.id,
                "Channel not found."
            )
            return

        price = float(
            ch_data["plans"][mins]
        )

        USD_RATE = 100
        INR_RATE = 2

        usd_price = price / USD_RATE
        inr_price = price / INR_RATE

        minutes = int(mins)

        if minutes > 525600:
            plan_name = "💎 Lifetime"

        elif minutes >= 1440:
            plan_name = (
                f"📅 {minutes // 1440} Days"
            )

        else:
            plan_name = (
                f"⏱ {minutes} Minutes"
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

        contact = get_settings().get(
            "contact_username",
            ""
        )

        if contact:

            markup.add(
                InlineKeyboardButton(
                    "📞 Contact Admin",
                    url=f"https://t.me/{contact}"
                )
            )

        payment_text = f"""📢 *{ch_data['name']}*

💎 *Plan:* {plan_name}

💰 *Price*
🇳🇵 NPR: {price:.0f}
🇺🇸 USD: ${usd_price:.2f}
🇮🇳 INR: ₹{inr_price:.2f}

━━━━━━━━━━━━━━

💳 *Payment Details*

*Binance/Payment ID:*
`{UPI_ID}`

📋 After payment, tap *I Have Paid*.
📷 Then upload your payment screenshot."""

        bot.send_message(
            call.message.chat.id,
            payment_text,
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

    ch_data = channels_col.find_one({
        "channel_id": int(ch_id)
    })

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
        """📷 *Upload Payment Screenshot*

Please send your payment screenshot as a *PHOTO*.

⏳ Upload it within 10 minutes.""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=["text"]
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "?? Please upload the payment screenshot as a PHOTO."
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
            f"""🔔 *Payment Verification Required*

👤 Name: {message.from_user.first_name}
🌐 Username: {username}
🆔 User ID: `{user_id}`

📢 Channel: *{payment['channel_name']}*
💎 Plan: `{payment['plan']}`
💰 Price: NPR {payment['price']}

👇 Screenshot is above.""",
            reply_markup=markup,
            parse_mode="Markdown"
        )

        bot.send_message(
            user_id,
            "✅ *Screenshot Uploaded Successfully!*\n\n"
            "⏳ Waiting for admin verification.",
            parse_mode="Markdown"
        )

        del pending_payments[user_id]

    except Exception as e:
        print(f"Photo handler error: {e}")


# =========================================================
# PAYMENT APPROVAL
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("app_")
)
def approve_now(call):

    if call.from_user.id != ADMIN_ID:
        return

    _, u_id, ch_id, mins = call.data.split("_")

    u_id = int(u_id)
    ch_id = int(ch_id)
    mins = int(mins)

    try:

        expiry_datetime = datetime.now() + timedelta(
            minutes=mins
        )

        expiry_ts = int(
            expiry_datetime.timestamp()
        )

        link = bot.create_chat_invite_link(
            ch_id,
            member_limit=1,
            expire_date=expiry_ts
        )

        users_col.update_one(
            {
                "user_id": u_id,
                "channel_id": ch_id
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp(),
                    "source": "paid_subscription",
                    "created_at": datetime.now()
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

Your payment was verified successfully.

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

        print(e)

        bot.send_message(
            ADMIN_ID,
            f"❌ Approval error:\n`{e}`",
            parse_mode="Markdown"
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
        "Your payment could not be verified.\n"
        "Contact the admin if you believe this is a mistake.",
        parse_mode="Markdown"
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# FORCE JOIN ADMIN
# =========================================================

@bot.message_handler(
    commands=["forceadd"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def force_add_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward a message from the channel/group "
        "you want users to join.\n\n"
        "The bot should be an admin there."
    )

    bot.register_next_step_handler(
        msg,
        save_force_channel
    )


def save_force_channel(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the channel/group."
        )
        return

    chat = message.forward_from_chat

    channel_id = chat.id
    name = chat.title or "Required Channel"

    if chat.username:

        join_url = (
            f"https://t.me/{chat.username}"
        )

    else:

        try:

            invite = bot.create_chat_invite_link(
                channel_id
            )

            join_url = invite.invite_link

        except Exception as e:

            print(e)

            bot.send_message(
                ADMIN_ID,
                "❌ Could not create a join link.\n\n"
                "Make sure the bot is an administrator."
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

    admin_log(
        "Force channel added",
        details=f"{channel_id}"
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Required channel added: *{name}*",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["forcelist"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def force_list(message):

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

    text = "📢 *Required Verification Channels*\n\n"

    for channel in channels:

        text += (
            f"• {channel['name']}\n"
        )

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
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("force_remove_")
)
def remove_force_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        call.data.replace(
            "force_remove_",
            ""
        )
    )

    force_channels_col.delete_one({
        "channel_id": channel_id
    })

    bot.answer_callback_query(
        call.id,
        "Channel removed."
    )

    bot.edit_message_text(
        "✅ Required channel removed.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# REWARD CHANNEL ADMIN
# MULTIPLE CHANNELS CAN BE STORED
# ADMIN CAN ACTIVATE ONE
# =========================================================

@bot.message_handler(
    commands=["rewardadd"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def reward_add_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "🎁 Forward a message from the Premium reward channel.\n\n"
        "The bot must be an admin in that channel."
    )

    bot.register_next_step_handler(
        msg,
        save_reward_channel
    )


def save_reward_channel(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the Premium channel."
        )
        return

    chat = message.forward_from_chat

    already_exists = reward_channels_col.find_one({
        "channel_id": chat.id
    })

    if not already_exists:

        # First channel becomes active automatically
        is_first = (
            reward_channels_col.count_documents({})
            == 0
        )

        reward_channels_col.insert_one({
            "channel_id": chat.id,
            "name": chat.title or "Premium Channel",
            "active": is_first,
            "added_at": datetime.now()
        })

    bot.send_message(
        ADMIN_ID,
        f"✅ Reward channel added: *{chat.title}*",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["rewardlist"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def reward_list(message):

    channels = list(
        reward_channels_col.find()
    )

    if not channels:

        bot.send_message(
            ADMIN_ID,
            "No reward Premium channels added."
        )
        return

    markup = InlineKeyboardMarkup()

    text = "🎁 *Premium Reward Channels*\n\n"

    for channel in channels:

        status = (
            "🟢 ACTIVE"
            if channel.get("active")
            else "⚪ Inactive"
        )

        text += (
            f"{status} — *{channel['name']}*\n"
        )

        if not channel.get("active"):

            markup.add(
                InlineKeyboardButton(
                    f"✅ Activate {channel['name']}",
                    callback_data=(
                        f"reward_activate_{channel['channel_id']}"
                    )
                )
            )

        markup.add(
            InlineKeyboardButton(
                f"🗑 Remove {channel['name']}",
                callback_data=(
                    f"reward_remove_{channel['channel_id']}"
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
    func=lambda c: c.data.startswith("reward_activate_")
)
def activate_reward_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        call.data.replace(
            "reward_activate_",
            ""
        )
    )

    reward_channels_col.update_many(
        {},
        {"$set": {"active": False}}
    )

    reward_channels_col.update_one(
        {"channel_id": channel_id},
        {"$set": {"active": True}}
    )

    bot.answer_callback_query(
        call.id,
        "Reward channel activated!"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("reward_remove_")
)
def remove_reward_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        call.data.replace(
            "reward_remove_",
            ""
        )
    )

    reward_channels_col.delete_one({
        "channel_id": channel_id
    })

    # If there are channels left but no active channel,
    # automatically activate the first one.
    if not get_active_reward_channel():

        first = reward_channels_col.find_one()

        if first:

            reward_channels_col.update_one(
                {"_id": first["_id"]},
                {"$set": {"active": True}}
            )

    bot.answer_callback_query(
        call.id,
        "Reward channel removed."
    )

    bot.edit_message_text(
        "🗑 Reward channel removed.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# ADMIN BAN SYSTEM
# =========================================================

@bot.message_handler(
    commands=["ban"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_ban(message):

    parts = message.text.split(
        maxsplit=2
    )

    if len(parts) < 2:

        bot.reply_to(
            message,
            "Usage:\n`/ban USER_ID REASON`",
            parse_mode="Markdown"
        )
        return

    try:

        user_id = int(parts[1])

        if user_id == ADMIN_ID:

            bot.reply_to(
                message,
                "❌ You cannot ban yourself."
            )
            return

        reason = (
            parts[2]
            if len(parts) > 2
            else "No reason provided"
        )

        ban_user(
            user_id,
            reason
        )

        admin_log(
            "User banned",
            details=f"{user_id}: {reason}"
        )

        try:

            bot.send_message(
                user_id,
                "🚫 *You have been banned from this bot.*\n\n"
                f"*Reason:* {reason}",
                parse_mode="Markdown"
            )

        except:
            pass

        bot.reply_to(
            message,
            f"🚫 User `{user_id}` has been banned.",
            parse_mode="Markdown"
        )

    except ValueError:

        bot.reply_to(
            message,
            "❌ USER_ID must be a number."
        )


@bot.message_handler(
    commands=["unban"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_unban(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "Usage: `/unban USER_ID`",
            parse_mode="Markdown"
        )
        return

    try:

        user_id = int(parts[1])

        unban_user(user_id)

        admin_log(
            "User unbanned",
            details=str(user_id)
        )

        bot.reply_to(
            message,
            f"✅ User `{user_id}` has been unbanned.",
            parse_mode="Markdown"
        )

    except ValueError:

        bot.reply_to(
            message,
            "❌ Invalid user ID."
        )


# =========================================================
# ADMIN COIN MANAGEMENT
# =========================================================

@bot.message_handler(
    commands=["addcoins"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_add_coins(message):

    parts = message.text.split()

    if len(parts) != 3:

        bot.reply_to(
            message,
            "Usage:\n`/addcoins USER_ID AMOUNT`",
            parse_mode="Markdown"
        )
        return

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

        if amount <= 0:
            raise ValueError

        add_coins(
            user_id,
            amount
        )

        bot.reply_to(
            message,
            f"✅ Added *{amount}* coins to `{user_id}`.",
            parse_mode="Markdown"
        )

        admin_log(
            "Coins added",
            details=f"{amount} to {user_id}"
        )

    except:

        bot.reply_to(
            message,
            "❌ Invalid values."
        )


@bot.message_handler(
    commands=["removecoins"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_remove_coins(message):

    parts = message.text.split()

    if len(parts) != 3:

        bot.reply_to(
            message,
            "Usage:\n`/removecoins USER_ID AMOUNT`",
            parse_mode="Markdown"
        )
        return

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

        if amount <= 0:
            raise ValueError

        result = bot_users_col.update_one(
            {
                "user_id": user_id,
                "coins": {"$gte": amount}
            },
            {
                "$inc": {
                    "coins": -amount
                }
            }
        )

        if result.modified_count != 1:

            bot.reply_to(
                message,
                "❌ User doesn't have enough coins."
            )
            return

        bot.reply_to(
            message,
            f"✅ Removed *{amount}* coins from `{user_id}`.",
            parse_mode="Markdown"
        )

    except:

        bot.reply_to(
            message,
            "❌ Invalid values."
        )


# =========================================================
# ADMIN SETTINGS
# =========================================================

@bot.message_handler(
    commands=["settings"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def show_settings(message):

    s = get_settings()

    bot.send_message(
        ADMIN_ID,
        f"""⚙️ *Current Settings*

{s['coin_emoji']} Coin Name: *{s['coin_name']}*
🎁 Referral Reward: *{s['referral_reward']}*

🎁 1 Day Cost: *{s['reward_1_day_cost']}*
🎁 7 Day Cost: *{s['reward_7_day_cost']}*
🎁 30 Day Cost: *{s['reward_30_day_cost']}*

🔗 Referral System: *{'ON' if s.get('referral_enabled') else 'OFF'}*
🎟 Coupons: *{'ON' if s.get('coupon_enabled') else 'OFF'}*
💬 Feedback: *{'ON' if s.get('feedback_enabled') else 'OFF'}*
🚧 Maintenance: *{'ON' if s.get('maintenance_mode') else 'OFF'}*""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["setcoin"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_coin(message):

    parts = message.text.split(
        maxsplit=1
    )

    if len(parts) < 2:

        bot.reply_to(
            message,
            "Usage: `/setcoin NAME`",
            parse_mode="Markdown"
        )
        return

    update_setting(
        "coin_name",
        parts[1].strip()
    )

    bot.reply_to(
        message,
        "✅ Coin name updated."
    )


@bot.message_handler(
    commands=["setemoji"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_coin_emoji(message):

    parts = message.text.split(
        maxsplit=1
    )

    if len(parts) < 2:

        bot.reply_to(
            message,
            "Usage: `/setemoji 🪙`",
            parse_mode="Markdown"
        )
        return

    update_setting(
        "coin_emoji",
        parts[1].strip()
    )

    bot.reply_to(
        message,
        "✅ Coin emoji updated."
    )


@bot.message_handler(
    commands=["setreward"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_referral_reward(message):

    parts = message.text.split()

    try:

        amount = int(parts[1])

        if amount < 0:
            raise ValueError

        update_setting(
            "referral_reward",
            amount
        )

        bot.reply_to(
            message,
            "✅ Referral reward updated."
        )

    except:

        bot.reply_to(
            message,
            "Usage: `/setreward 10`",
            parse_mode="Markdown"
        )


@bot.message_handler(
    commands=["setcost"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_reward_cost(message):

    parts = message.text.split()

    if len(parts) != 3:

        bot.reply_to(
            message,
            "Usage: `/setcost DAYS COINS`\n"
            "Days: 1, 7 or 30"
        )
        return

    try:

        days = int(parts[1])
        cost = int(parts[2])

        key_map = {
            1: "reward_1_day_cost",
            7: "reward_7_day_cost",
            30: "reward_30_day_cost"
        }

        if days not in key_map or cost < 0:
            raise ValueError

        update_setting(
            key_map[days],
            cost
        )

        bot.reply_to(
            message,
            f"✅ {days}-day Premium cost updated."
        )

    except:

        bot.reply_to(
            message,
            "❌ Usage: `/setcost 1 50`"
        )


# =========================================================
# EDITABLE TEXT SYSTEM
# =========================================================

@bot.message_handler(
    commands=["texts"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_editable_texts(message):

    text = """📝 *Editable Messages*

Use:

`/gettext KEY`
View a message.

`/settext KEY YOUR_NEW_TEXT`
Change a message.

Available keys:

• welcome_text
• force_join_text
• verification_success_text
• referral_notification
• how_it_works_text
• premium_expired_text
• feedback_thanks_text

⚠️ Keep placeholders in referral_notification:
`{name}`
`{reward}`
`{coin_name}`
`{coin_emoji}`"""

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["gettext"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def get_editable_text(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "Usage: `/gettext welcome_text`",
            parse_mode="Markdown"
        )
        return

    key = parts[1]

    if key not in DEFAULT_TEXTS:

        bot.reply_to(
            message,
            "❌ Unknown text key."
        )
        return

    bot.send_message(
        ADMIN_ID,
        f"*{key}:*\n\n{get_text(key)}",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["settext"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_editable_text(message):

    parts = message.text.split(
        maxsplit=2
    )

    if len(parts) < 3:

        bot.reply_to(
            message,
            "Usage:\n`/settext KEY YOUR_MESSAGE`",
            parse_mode="Markdown"
        )
        return

    key = parts[1]
    value = parts[2]

    if key not in DEFAULT_TEXTS:

        bot.reply_to(
            message,
            "❌ Unknown text key."
        )
        return

    set_text(
        key,
        value
    )

    bot.reply_to(
        message,
        f"✅ Message *{key}* updated.",
        parse_mode="Markdown"
    )


# =========================================================
# EDITABLE BUTTON SYSTEM
# =========================================================

@bot.message_handler(
    commands=["buttons"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_editable_buttons(message):

    text = """🔘 *Editable Buttons*

Use:

`/getbutton KEY`
View a button.

`/setbutton KEY NEW_BUTTON_TEXT`
Change a button.

Available keys:

• profile
• refer
• redeem
• coupon
• leaderboard
• my_referrals
• how_it_works
• feedback
• contact

⚠️ After changing buttons, users will see the
new buttons the next time they open /start."""

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["getbutton"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def get_editable_button(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "Usage: `/getbutton profile`",
            parse_mode="Markdown"
        )
        return

    key = parts[1]

    if key not in DEFAULT_BUTTONS:

        bot.reply_to(
            message,
            "❌ Unknown button key."
        )
        return

    bot.reply_to(
        message,
        f"🔘 `{key}` = {get_button(key)}",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["setbutton"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_editable_button(message):

    parts = message.text.split(
        maxsplit=2
    )

    if len(parts) < 3:

        bot.reply_to(
            message,
            "Usage:\n`/setbutton profile 👤 Profile`",
            parse_mode="Markdown"
        )
        return

    key = parts[1]

    if key not in DEFAULT_BUTTONS:

        bot.reply_to(
            message,
            "❌ Unknown button key."
        )
        return

    set_button(
        key,
        parts[2]
    )

    bot.reply_to(
        message,
        f"✅ Button *{key}* updated.",
        parse_mode="Markdown"
    )


# =========================================================
# COUPON ADMIN
# =========================================================

@bot.message_handler(
    commands=["coupon"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def create_coupon(message):

    parts = message.text.split()

    if len(parts) != 5:

        bot.reply_to(
            message,
            """Usage:
`/coupon CODE COINS MAX_USERS HOURS`

Example:
`/coupon WELCOME100 100 50 24`""",
            parse_mode="Markdown"
        )
        return

    try:

        code = parts[1].upper()
        coins = int(parts[2])
        max_users = int(parts[3])
        hours = int(parts[4])

        if coins < 0 or max_users <= 0 or hours <= 0:
            raise ValueError

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
                    "active": True,
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )

        bot.reply_to(
            message,
            f"""✅ *Coupon Created!*

🎟 Code: `{code}`
🪙 Reward: {coins}
👥 Maximum Users: {max_users}
⏰ Valid for: {hours} hours""",
            parse_mode="Markdown"
        )

    except:

        bot.reply_to(
            message,
            "❌ Invalid values."
        )


@bot.message_handler(
    commands=["coupons"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_coupons(message):

    coupons = list(
        coupons_col.find()
        .sort("created_at", DESCENDING)
        .limit(20)
    )

    if not coupons:

        bot.send_message(
            ADMIN_ID,
            "No coupons found."
        )
        return

    text = "🎟 *Recent Coupons*\n\n"

    for coupon in coupons:

        status = (
            "🟢"
            if coupon.get("active", True)
            else "🔴"
        )

        text += (
            f"{status} `{coupon['code']}` — "
            f"{coupon['coins']} coins — "
            f"{coupon.get('used_count', 0)}/"
            f"{coupon['max_uses']} used\n"
        )

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# BROADCAST
# =========================================================

@bot.message_handler(
    commands=["broadcast"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def broadcast_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Send the message/photo you want to broadcast.\n\n"
        "It will be sent to all users."
    )

    bot.register_next_step_handler(
        msg,
        broadcast_message
    )


def broadcast_message(message):

    users = bot_users_col.find(
        {
            "banned": {"$ne": True}
        },
        {
            "user_id": 1
        }
    )

    success = 0
    failed = 0

    bot.send_message(
        ADMIN_ID,
        "📢 Broadcast started..."
    )

    for user in users:

        try:

            bot.copy_message(
                user["user_id"],
                message.chat.id,
                message.message_id
            )

            success += 1

            time.sleep(0.04)

        except:
            failed += 1

    bot.send_message(
        ADMIN_ID,
        f"""📢 *Broadcast Complete*

✅ Sent: *{success}*
❌ Failed: *{failed}*""",
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN USER LOOKUP
# =========================================================

@bot.message_handler(
    commands=["user"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_user_lookup(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.reply_to(
            message,
            "Usage: `/user USER_ID`",
            parse_mode="Markdown"
        )
        return

    try:

        user_id = int(parts[1])
        user = get_user(user_id)

        if not user:

            bot.reply_to(
                message,
                "❌ User not found."
            )
            return

        referrer = get_user(
            user.get("referrer_id")
        ) if user.get("referrer_id") else None

        bot.send_message(
            ADMIN_ID,
            f"""👤 *User Details*

👤 Name: {get_user_display(user)}
🆔 ID: `{user_id}`
🪙 Coins: {user.get('coins', 0)}
👥 Referrals: {user.get('referral_count', 0)}
🔗 Referred by: {get_user_display(referrer) if referrer else 'None'}
🚫 Banned: {'Yes' if user.get('banned') else 'No'}""",
            parse_mode="Markdown"
        )

    except:

        bot.reply_to(
            message,
            "❌ Invalid user ID."
        )


# =========================================================
# MAINTENANCE MODE
# =========================================================

@bot.message_handler(
    commands=["maintenance"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def maintenance_toggle(message):

    current = get_settings().get(
        "maintenance_mode",
        False
    )

    new_value = not current

    update_setting(
        "maintenance_mode",
        new_value
    )

    bot.reply_to(
        message,
        f"🚧 Maintenance mode is now "
        f"*{'ON' if new_value else 'OFF'}*.",
        parse_mode="Markdown"
    )


# =========================================================
# STATS
# =========================================================

@bot.message_handler(
    commands=["stats"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def bot_stats(message):

    total_users = bot_users_col.count_documents({})

    verified_referrals = bot_users_col.count_documents({
        "verified_referral": True
    })

    banned_users = bot_users_col.count_documents({
        "banned": True
    })

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
📌 Force Channels: *{force_channels_col.count_documents({})}*
🎁 Reward Channels: *{reward_channels_col.count_documents({})}*
🎟 Coupons: *{coupons_col.count_documents({})}*
💬 Feedback: *{feedback_col.count_documents({})}*""",
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN PANEL
# =========================================================

@bot.message_handler(
    commands=["admin"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_panel(message):

    settings = get_settings()

    text = f"""👑 *ADMIN CONTROL PANEL*

━━━━━━━━━━━━━━

🪙 Coin: *{settings['coin_name']}*
🎁 Referral Reward: *{settings['referral_reward']}*

📊 Users: *{bot_users_col.count_documents({})}*
🔗 Successful Referrals: *{bot_users_col.count_documents({'verified_referral': True})}*

━━━━━━━━━━━━━━

*📢 CHANNEL MANAGEMENT*

`/add` — Add paid subscription channel
`/channels` — View/manage paid channels

`/forceadd` — Add required channel
`/forcelist` — View/remove required channels

`/rewardadd` — Add Premium reward channel
`/rewardlist` — Manage reward channels

━━━━━━━━━━━━━━

*🪙 REWARDS & COINS*

`/setcoin NAME`
`/setemoji EMOJI`
`/setreward AMOUNT`
`/setcost DAYS COINS`

`/addcoins USER_ID AMOUNT`
`/removecoins USER_ID AMOUNT`

━━━━━━━━━━━━━━

*🎟 COUPONS*

`/coupon CODE COINS MAX_USERS HOURS`
`/coupons`

━━━━━━━━━━━━━━

*🚫 USER MANAGEMENT*

`/user USER_ID`
`/ban USER_ID REASON`
`/unban USER_ID`

━━━━━━━━━━━━━━

*✏️ CUSTOMIZATION*

`/settings`

`/texts` — Edit bot messages
`/buttons` — Edit button names

━━━━━━━━━━━━━━

*📢 ADMIN TOOLS*

`/broadcast`
`/stats`
`/maintenance`

━━━━━━━━━━━━━━

⚠️ *Important:* The reward channel system is
separate from your old paid subscription channels."""

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# CLEAR EXPIRED PAYMENT REQUESTS
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
                    "⌛ Your payment request expired.\n\n"
                    "Please start the payment process again."
                )

            except:
                pass

            expired.append(user_id)

    for user_id in expired:

        pending_payments.pop(
            user_id,
            None
        )


# =========================================================
# AUTO REMOVE EXPIRED PREMIUM/SUBSCRIPTION USERS
# =========================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find({
        "expiry": {
            "$lte": now
        }
    })

    for user in expired_users:

        try:

            channel_id = user["channel_id"]
            user_id = user["user_id"]

            # Ban + immediately unban removes the user
            bot.ban_chat_member(
                channel_id,
                user_id
            )

            bot.unban_chat_member(
                channel_id,
                user_id,
                only_if_banned=True
            )

            source = user.get(
                "source",
                "paid_subscription"
            )

            if source == "coin_reward":

                try:

                    bot.send_message(
                        user_id,
                        get_text(
                            "premium_expired_text"
                        ),
                        parse_mode="Markdown"
                    )

                except:
                    pass

            else:

                try:

                    username = bot.get_me().username

                    rejoin_url = (
                        f"https://t.me/{username}"
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
                        "⚠️ *Your subscription has expired.*\n\n"
                        "Renew your subscription below.",
                        reply_markup=markup,
                        parse_mode="Markdown"
                    )

                except:
                    pass

            # Remove only after successful Telegram action
            users_col.delete_one({
                "_id": user["_id"]
            })

            admin_log(
                "Membership expired",
                details=f"user={user_id}, channel={channel_id}"
            )

        except Exception as e:

            # Keep the database record so it retries later
            print(
                f"Kick expired user error: {e}"
            )


# =========================================================
# FALLBACK FOR UNKNOWN COMMANDS
# =========================================================

@bot.message_handler(
    func=lambda m: (
        m.text
        and m.text.startswith("/")
    )
)
def unknown_command(message):

    if message.from_user.id == ADMIN_ID:

        bot.reply_to(
            message,
            "❓ Unknown command.\n\n"
            "Use /admin to view the admin commands."
        )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    keep_alive()

    initialize_database()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        kick_expired_users,
        "interval",
        minutes=1,
        max_instances=1
    )

    scheduler.add_job(
        clear_pending_payments,
        "interval",
        minutes=1,
        max_instances=1
    )

    scheduler.start()

    bot.remove_webhook()

    print("✅ Bot is running...")

    while True:

        try:

            bot.infinity_polling(
                timeout=20,
                long_polling_timeout=10,
                skip_pending=True
            )

        except Exception as e:

            print(
                f"Polling error: {e}"
            )

            time.sleep(5)