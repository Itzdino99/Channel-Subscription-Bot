import os
import time
import telebot

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from pymongo import MongoClient, DESCENDING
from datetime import datetime, timedelta
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

# Existing collections
channels_col = db["channels"]
users_col = db["users"]

# Referral / bot collections
bot_users_col = db["bot_users"]
settings_col = db["settings"]
force_channels_col = db["force_channels"]
coupons_col = db["coupons"]
coupon_uses_col = db["coupon_uses"]
feedback_col = db["feedback"]


pending_payments = {}


# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "_id": "bot_settings",

    # Coins
    "coin_name": "Coins",
    "coin_emoji": "🪙",
    "referral_reward": 10,

    # Premium reward channel
    "reward_channel_id": None,
    "reward_channel_name": "Premium Channel",

    # Reward costs
    "reward_1_day_cost": 50,
    "reward_7_day_cost": 250,
    "reward_30_day_cost": 800,

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
        "5️⃣ You automatically receive coins.\n"
        "6️⃣ Redeem coins for Premium!"
    ),

    "feedback_text": (
        "💬 *Send Feedback*\n\n"
        "Please send your feedback, suggestion or problem. "
        "It will be delivered to the admin."
    ),

    # Button names
    "btn_profile": "🌐 My Profile",
    "btn_refer": "🔗 Refer & Earn",
    "btn_redeem": "🎁 Redeem Premium",
    "btn_coupon": "🎟 Claim Coupon",
    "btn_leaderboard": "🏆 Leaderboard",
    "btn_referrals": "👥 My Referrals",
    "btn_how": "📖 How It Works",
    "btn_feedback": "💬 Feedback",
    "btn_contact": "📞 Contact Admin"
}


def get_settings():
    settings = settings_col.find_one({"_id": "bot_settings"})

    if not settings:
        settings_col.insert_one(DEFAULT_SETTINGS.copy())
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


# =========================================================
# USER HELPERS
# =========================================================

def get_user(user_id):
    return bot_users_col.find_one({"user_id": user_id})


def is_banned(user_id):
    user = get_user(user_id)
    return bool(user and user.get("banned", False))


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
                "banned": False
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


# =========================================================
# USER MAIN MENU
# =========================================================

def main_menu(user_id, chat_id=None):

    if chat_id is None:
        chat_id = user_id

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
        KeyboardButton(settings["btn_leaderboard"])
    )

    markup.row(
        KeyboardButton(settings["btn_how"]),
        KeyboardButton(settings["btn_feedback"])
    )

    markup.row(
        KeyboardButton(settings["btn_contact"])
    )

    bot.send_message(
        chat_id,
        settings["welcome_text"],
        reply_markup=markup,
        parse_mode="Markdown"
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
            "⚠️ Required verification channels have not been configured yet. Please contact the admin."
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
    register_user(message.from_user)

    if is_banned(user_id):
        bot.send_message(
            message.chat.id,
            "🚫 Your access to this bot has been restricted. Please contact the admin if you believe this is a mistake."
        )
        return

    parts = message.text.split(maxsplit=1)
    start_argument = parts[1].strip() if len(parts) > 1 else None

    # -----------------------------------------------------
    # OLD PAID CHANNEL DEEP LINK
    # -----------------------------------------------------

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
                                callback_data=f"select_{possible_channel_id}_{p_time}"
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

    # -----------------------------------------------------
    # PENDING REFERRAL: NEVER BYPASS VERIFICATION
    # -----------------------------------------------------

    user_data = get_user(user_id)

    if (
        user_data
        and user_data.get("pending_referrer") is not None
        and not user_data.get("verified_referral", False)
    ):
        show_force_join(message.chat.id)
        return

    # -----------------------------------------------------
    # NEW REFERRAL
    # -----------------------------------------------------

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

                show_force_join(message.chat.id)
                return

        except ValueError:
            pass

    # Normal start goes directly to menu
    if user_id == ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "👑 *Admin Account*\n\nUse /admin to open the admin panel.",
            parse_mode="Markdown"
        )

    main_menu(user_id, message.chat.id)


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
            "You don't have a pending referral verification.",
            show_alert=True
        )
        return

    if not check_all_force_channels(user_id):
        bot.answer_callback_query(
            call.id,
            "❌ You haven't joined all required channels yet. Please join every channel and try again.",
            show_alert=True
        )
        return

    settings = get_settings()
    reward = int(settings["referral_reward"])

    # Prevent duplicate rewards
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
            "This verification was already processed.",
            show_alert=True
        )
        return

    # Add reward to referrer
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

    # Referral notification with the person's name
    new_user = get_user(user_id)
    person_name = user_display_name(new_user)

    try:
        bot.send_message(
            referrer_id,
            f"""🎉 *New Successful Referral!*

👤 *{person_name}* joined through your referral link and completed verification.

{settings['coin_emoji']} You received *{reward} {settings['coin_name']}*!""",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Referral notification error: {e}")

    bot.send_message(
        user_id,
        settings["verification_success_text"],
        parse_mode="Markdown"
    )

    main_menu(user_id)


# =========================================================
# PROFILE
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_profile"]
)
def my_profile(message):

    user_id = message.from_user.id
    user = get_user(user_id)
    settings = get_settings()

    if not user:
        register_user(message.from_user)
        user = get_user(user_id)

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

👤 Name: {message.from_user.first_name}
🌐 Username: {username}
🆔 ID: `{user_id}`
📅 Joined: {joined_text}

👥 Successful Referrals: *{user.get('referral_count', 0)}*
{settings['coin_emoji']} Coins: *{user.get('coins', 0)} {settings['coin_name']}*

🔗 Referred By: *{referrer_text}*""",
        parse_mode="Markdown"
    )


# =========================================================
# REFERRAL
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_refer"]
)
def refer_and_earn(message):

    user_id = message.from_user.id
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

📌 Your friend must start the bot using this link, join all required channels and successfully verify before you receive the reward.""",
        parse_mode="Markdown"
    )


# =========================================================
# MY REFERRALS
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_referrals"]
)
def my_referrals(message):

    referred_users = list(
        bot_users_col.find({
            "referrer_id": message.from_user.id,
            "verified_referral": True
        }).sort("verified_at", DESCENDING).limit(30)
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

    text += f"\n🎉 *Total:* {len(referred_users)} shown"

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# HOW IT WORKS
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_how"]
)
def how_it_works(message):

    bot.send_message(
        message.chat.id,
        get_settings()["how_it_works_text"],
        parse_mode="Markdown"
    )


# =========================================================
# CONTACT ADMIN
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_contact"]
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


# =========================================================
# FEEDBACK SYSTEM
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_feedback"]
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
            "❌ Please send feedback as a text message."
        )
        return

    feedback_col.insert_one({
        "user_id": message.from_user.id,
        "name": message.from_user.first_name or "",
        "username": message.from_user.username or "",
        "text": message.text,
        "created_at": datetime.now()
    })

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "No username"
    )

    try:
        bot.send_message(
            ADMIN_ID,
            f"""💬 *New Feedback*

👤 {message.from_user.first_name}
🌐 {username}
🆔 `{message.from_user.id}`

📝 *Message:*
{message.text}""",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(e)

    bot.send_message(
        message.chat.id,
        "✅ Thank you! Your feedback has been sent to the admin."
    )


# =========================================================
# REDEEM PREMIUM
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_redeem"]
)
def redeem_premium_menu(message):

    settings = get_settings()

    if not settings.get("reward_channel_id"):
        bot.send_message(
            message.chat.id,
            "⚠️ Premium rewards are not available yet."
        )
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            f"🎁 1 Day — {settings['reward_1_day_cost']} {settings['coin_name']}",
            callback_data="redeem_1"
        )
    )
    markup.add(
        InlineKeyboardButton(
            f"🎁 7 Days — {settings['reward_7_day_cost']} {settings['coin_name']}",
            callback_data="redeem_7"
        )
    )
    markup.add(
        InlineKeyboardButton(
            f"🎁 30 Days — {settings['reward_30_day_cost']} {settings['coin_name']}",
            callback_data="redeem_30"
        )
    )

    bot.send_message(
        message.chat.id,
        f"""🎁 *Redeem Premium*

{settings['coin_emoji']} Your balance: *{get_coin_balance(message.from_user.id)} {settings['coin_name']}*

Choose a Premium reward below:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data in ("redeem_1", "redeem_7", "redeem_30")
)
def redeem_premium(call):

    user_id = call.from_user.id
    settings = get_settings()

    if is_banned(user_id):
        bot.answer_callback_query(
            call.id,
            "Your account is restricted.",
            show_alert=True
        )
        return

    reward_map = {
        "redeem_1": (1, int(settings["reward_1_day_cost"])),
        "redeem_7": (7, int(settings["reward_7_day_cost"])),
        "redeem_30": (30, int(settings["reward_30_day_cost"]))
    }

    days, cost = reward_map[call.data]
    channel_id = settings.get("reward_channel_id")

    if not channel_id:
        bot.answer_callback_query(
            call.id,
            "Premium channel is not configured.",
            show_alert=True
        )
        return

    # Deduct coins only if enough balance
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

    try:
        expiry_datetime = datetime.now() + timedelta(days=days)

        link = bot.create_chat_invite_link(
            channel_id,
            member_limit=1,
            expire_date=int(expiry_datetime.timestamp())
        )

        users_col.update_one(
            {
                "user_id": user_id,
                "channel_id": channel_id
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp(),
                    "source": "coin_reward",
                    "reward_days": days
                }
            },
            upsert=True
        )

        bot.answer_callback_query(
            call.id,
            "Premium redeemed successfully!"
        )

        bot.send_message(
            user_id,
            f"""🎉 *Premium Redeemed Successfully!*

🎁 *Reward:* {days} Day Premium
📢 *Channel:* {settings['reward_channel_name']}
⏰ *Expires:* {expiry_datetime.strftime("%d %b %Y, %H:%M")}

🔗 *Join Premium Channel:*
{link.invite_link}

⚠️ This link can only be used once.

⏳ When your Premium period ends, you will automatically be removed from the channel.""",
            parse_mode="Markdown"
        )

    except Exception as e:

        # Refund on failure
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
    func=lambda m: m.text == get_settings()["btn_coupon"]
)
def claim_coupon_prompt(message):

    msg = bot.send_message(
        message.chat.id,
        "🎟 Send the coupon code you want to claim."
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
        bot.send_message(
            message.chat.id,
            "🚫 Your account is restricted."
        )
        return

    coupon = coupons_col.find_one({"code": code})

    if not coupon:
        bot.send_message(message.chat.id, "❌ Invalid coupon code.")
        return

    if coupon.get("expires_at") and coupon["expires_at"] < datetime.now():
        bot.send_message(message.chat.id, "⌛ This coupon has expired.")
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

    try:
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

    except Exception as e:
        # Refund usage slot if database operation fails
        coupons_col.update_one(
            {"code": code},
            {"$inc": {"used_count": -1}}
        )
        print(f"Coupon error: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Something went wrong. Please try again."
        )


# =========================================================
# LEADERBOARD
# =========================================================

@bot.message_handler(
    func=lambda m: m.text == get_settings()["btn_leaderboard"]
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

    for position, user in enumerate(users, start=1):
        text += (
            f"{position}. {user.get('first_name', 'User')} — "
            f"*{user.get('referral_count', 0)} referrals*\n"
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
    cursor = channels_col.find({"admin_id": ADMIN_ID})

    count = 0

    for ch in cursor:
        markup.add(
            InlineKeyboardButton(
                f"📢 {ch['name']}",
                callback_data=f"manage_{ch['channel_id']}"
            )
        )
        count += 1

    markup.add(
        InlineKeyboardButton(
            "➕ Add New Channel",
            callback_data="add_new"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "Your Managed Channels:" if count else "No channels found.",
        reply_markup=markup
    )


@bot.message_handler(
    commands=["add"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Please make sure the bot is an Admin in your channel.\n\n"
        "Then FORWARD any message from that channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


@bot.callback_query_handler(
    func=lambda call: call.data == "add_new"
)
def cb_add_new(call):

    if call.from_user.id != ADMIN_ID:
        return

    msg = bot.send_message(
        ADMIN_ID,
        "Please FORWARD any message from your channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


def get_plans(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Error: Message was not forwarded. Use /add again."
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

    except Exception as e:
        print(e)
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\nUse: `1440:99,43200:199`",
            parse_mode="Markdown"
        )


# =========================================================
# OLD PAID PAYMENT SYSTEM
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
            bot.answer_callback_query(call.id, "Channel not found.")
            return

        price = float(ch_data["plans"][mins])

        usd_price = price / 100
        inr_price = price / 2
        minutes = int(mins)

        if minutes > 525600:
            plan_name = "💎 Lifetime"
        elif minutes >= 1440:
            plan_name = f"📅 {minutes // 1440} Days"
        else:
            plan_name = f"⏱ {minutes} Min"

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "✅ I Have Paid",
                callback_data=f"paid_{ch_id}_{mins}"
            )
        )

        if CONTACT_USERNAME:
            markup.add(
                InlineKeyboardButton(
                    "📞 Contact Admin",
                    url=f"https://t.me/{CONTACT_USERNAME}"
                )
            )

        qr_url = "https://i.ibb.co/v4yw96tb/IMG-20260712-103503.jpg"

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
                "📋 After payment, tap *I Have Paid* and send your screenshot."
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
        "📷 *Upload Payment Screenshot*\n\nPlease send your payment screenshot as a *PHOTO*.",
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

        markup = InlineKeyboardMarkup(row_width=2)

        markup.add(
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"app_{user_id}_{payment['channel_id']}_{payment['plan']}"
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
            "✅ Screenshot uploaded successfully!\n\n⏳ Waiting for admin verification."
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

        expiry_datetime = datetime.now() + timedelta(minutes=mins)

        link = bot.create_chat_invite_link(
            ch_id,
            member_limit=1,
            expire_date=int(expiry_datetime.timestamp())
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
            plan_name = f"📅 {mins // 1440} Days"
        else:
            plan_name = f"⏱ {mins} Minutes"

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

    user_id = int(call.data.split("_")[1])

    pending_payments.pop(user_id, None)

    bot.send_message(
        user_id,
        "❌ *Payment Rejected*\n\nYour payment could not be verified. Contact the admin if you believe this is a mistake.",
        parse_mode="Markdown"
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
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

    bot.send_message(
        ADMIN_ID,
        f"""👑 *ADMIN PANEL*

🪙 Currency: *{settings['coin_name']}*
🎁 Referral Reward: *{settings['referral_reward']}*
📢 Required Channels: *{force_channels_col.count_documents({})}*

━━━━━━━━━━━━━━

*CHANNELS*
📢 `/add` — Add paid channel
📋 `/channels` — View paid channels
📢 `/forceadd` — Add verification channel
📋 `/forcelist` — Manage verification channels
🎁 `/setpremium` — Set reward Premium channel

*COINS & REWARDS*
🪙 `/setcoin NAME`
😀 `/setemoji EMOJI`
🎁 `/setreward AMOUNT`
💰 `/setcost DAYS COINS`

*COUPONS*
🎟 `/coupon CODE COINS MAX_USERS HOURS`
📋 `/coupons`

*USER MANAGEMENT*
🚫 `/ban USER_ID`
✅ `/unban USER_ID`
👤 `/userinfo USER_ID`

*CONTENT*
✏️ `/edittext KEY NEW_TEXT`
📋 `/texts` — View editable text keys
🔘 `/setbutton KEY NEW_NAME`

*BOT*
📢 `/broadcast`
📊 `/stats`
💬 `/feedbacks`""",
        parse_mode="Markdown"
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

📢 Reward Channel: *{s['reward_channel_name']}*""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["setcoin"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_coin(message):

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(message, "Usage: `/setcoin CoinName`", parse_mode="Markdown")
        return

    update_setting("coin_name", parts[1].strip())
    bot.reply_to(message, "✅ Coin name updated.")


@bot.message_handler(
    commands=["setemoji"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_emoji(message):

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(message, "Usage: `/setemoji 🪙`", parse_mode="Markdown")
        return

    update_setting("coin_emoji", parts[1].strip())
    bot.reply_to(message, "✅ Coin emoji updated.")


@bot.message_handler(
    commands=["setreward"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_referral_reward(message):

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: `/setreward 10`", parse_mode="Markdown")
        return

    update_setting("referral_reward", int(parts[1]))
    bot.reply_to(message, "✅ Referral reward updated.")


@bot.message_handler(
    commands=["setcost"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_reward_cost(message):

    parts = message.text.split()

    if len(parts) != 3:
        bot.reply_to(message, "Usage: `/setcost 1 50`")
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

        update_setting(key_map[days], cost)
        bot.reply_to(message, "✅ Reward cost updated.")

    except ValueError:
        bot.reply_to(message, "❌ Days must be 1, 7 or 30 and cost must be a number.")


# =========================================================
# EDITABLE TEXT SYSTEM
# =========================================================

EDITABLE_TEXT_KEYS = {
    "welcome": "welcome_text",
    "forcejoin": "force_join_text",
    "verified": "verification_success_text",
    "how": "how_it_works_text",
    "feedback": "feedback_text"
}


@bot.message_handler(
    commands=["texts"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def show_editable_texts(message):

    bot.send_message(
        ADMIN_ID,
        """✏️ *Editable Text Keys*

`welcome` — Main menu welcome text
`forcejoin` — Referral verification message
`verified` — Successful verification message
`how` — How It Works message
`feedback` — Feedback instruction

Use:

`/edittext KEY Your new text`

You can use emojis and Markdown formatting.""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["edittext"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def edit_text(message):

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        bot.reply_to(
            message,
            "Usage: `/edittext welcome Your new message`",
            parse_mode="Markdown"
        )
        return

    key = parts[1].lower()
    new_text = parts[2]

    if key not in EDITABLE_TEXT_KEYS:
        bot.reply_to(message, "❌ Invalid text key. Use /texts.")
        return

    update_setting(EDITABLE_TEXT_KEYS[key], new_text)
    bot.reply_to(message, "✅ Text updated successfully.")


BUTTON_KEYS = {
    "profile": "btn_profile",
    "refer": "btn_refer",
    "redeem": "btn_redeem",
    "coupon": "btn_coupon",
    "leaderboard": "btn_leaderboard",
    "referrals": "btn_referrals",
    "how": "btn_how",
    "feedback": "btn_feedback",
    "contact": "btn_contact"
}


@bot.message_handler(
    commands=["setbutton"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_button(message):

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        bot.reply_to(
            message,
            "Usage: `/setbutton profile 🌐 Profile`"
        )
        return

    key = parts[1].lower()

    if key not in BUTTON_KEYS:
        bot.reply_to(
            message,
            f"❌ Invalid button key.\nAvailable: {', '.join(BUTTON_KEYS.keys())}"
        )
        return

    update_setting(BUTTON_KEYS[key], parts[2])
    bot.reply_to(message, "✅ Button name updated. Users will see it when they reopen the menu.")


# =========================================================
# BAN / UNBAN SYSTEM
# =========================================================

@bot.message_handler(
    commands=["ban"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def ban_user(message):

    parts = message.text.split()

    if len(parts) != 2:
        bot.reply_to(message, "Usage: `/ban USER_ID`", parse_mode="Markdown")
        return

    try:
        user_id = int(parts[1])

        if user_id == ADMIN_ID:
            bot.reply_to(message, "❌ You cannot ban the admin.")
            return

        bot_users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "banned": True,
                    "banned_at": datetime.now(),
                    "banned_by": ADMIN_ID
                }
            },
            upsert=False
        )

        bot.reply_to(message, f"🚫 User `{user_id}` has been banned.", parse_mode="Markdown")

        try:
            bot.send_message(
                user_id,
                "🚫 Your access to this bot has been restricted by the administrator."
            )
        except Exception:
            pass

    except ValueError:
        bot.reply_to(message, "❌ Invalid User ID.")


@bot.message_handler(
    commands=["unban"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def unban_user(message):

    parts = message.text.split()

    if len(parts) != 2:
        bot.reply_to(message, "Usage: `/unban USER_ID`", parse_mode="Markdown")
        return

    try:
        user_id = int(parts[1])

        bot_users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "banned": False,
                    "unbanned_at": datetime.now()
                }
            }
        )

        bot.reply_to(message, f"✅ User `{user_id}` has been unbanned.", parse_mode="Markdown")

    except ValueError:
        bot.reply_to(message, "❌ Invalid User ID.")


@bot.message_handler(
    commands=["userinfo"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_user_info(message):

    parts = message.text.split()

    if len(parts) != 2:
        bot.reply_to(message, "Usage: `/userinfo USER_ID`")
        return

    try:
        user = get_user(int(parts[1]))

        if not user:
            bot.reply_to(message, "❌ User not found.")
            return

        bot.send_message(
            ADMIN_ID,
            f"""👤 *User Information*

Name: {user.get('first_name', 'Unknown')}
Username: @{user.get('username') or 'Not set'}
ID: `{user['user_id']}`

🪙 Coins: {user.get('coins', 0)}
👥 Referrals: {user.get('referral_count', 0)}
🔗 Referred By: {user.get('referrer_id', 'Nobody')}
🚫 Banned: {user.get('banned', False)}""",
            parse_mode="Markdown"
        )

    except ValueError:
        bot.reply_to(message, "❌ Invalid User ID.")


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
        "📢 Forward a message from the channel/group users must join.\n\nMake sure the bot is an administrator there."
    )

    bot.register_next_step_handler(msg, save_force_channel)


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
            invite = bot.create_chat_invite_link(channel_id)
            join_url = invite.invite_link
        except Exception as e:
            print(e)
            bot.send_message(
                ADMIN_ID,
                "❌ Could not create a join link. Make the bot an admin and try again."
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


@bot.message_handler(
    commands=["forcelist"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def force_list(message):

    channels = list(force_channels_col.find())

    if not channels:
        bot.send_message(ADMIN_ID, "No required channels configured.")
        return

    markup = InlineKeyboardMarkup()

    for channel in channels:
        markup.add(
            InlineKeyboardButton(
                f"🗑 Remove {channel['name']}",
                callback_data=f"force_remove_{channel['channel_id']}"
            )
        )

    bot.send_message(
        ADMIN_ID,
        "📢 *Required Verification Channels*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("force_remove_")
)
def remove_force_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    try:
        channel_id = int(
            call.data.replace("force_remove_", "")
        )

        force_channels_col.delete_one(
            {"channel_id": channel_id}
        )

        bot.answer_callback_query(call.id, "Channel removed!")
        bot.edit_message_text(
            "✅ Required channel removed.",
            call.message.chat.id,
            call.message.message_id
        )

    except Exception as e:
        print(e)


# =========================================================
# SET REWARD PREMIUM CHANNEL
# =========================================================

@bot.message_handler(
    commands=["setpremium"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_premium_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "🎁 Forward any message from the separate Premium reward channel.\n\nThe bot must be an administrator in that channel."
    )

    bot.register_next_step_handler(
        msg,
        save_premium_channel
    )


def save_premium_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the Premium channel."
        )
        return

    chat = message.forward_from_chat

    update_setting("reward_channel_id", chat.id)
    update_setting(
        "reward_channel_name",
        chat.title or "Premium Channel"
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Separate Premium reward channel set to *{chat.title}*.",
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
            "Usage:\n`/coupon CODE COINS MAX_USERS HOURS`\n\nExample:\n`/coupon WELCOME100 100 50 24`",
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
                    "expires_at": datetime.now() + timedelta(hours=hours),
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )

        bot.reply_to(
            message,
            f"""✅ *Coupon Created!*

🎟 Code: `{code}`
🪙 Coins: {coins}
👥 Maximum Users: {max_users}
⏰ Expires in: {hours} hours""",
            parse_mode="Markdown"
        )

    except ValueError:
        bot.reply_to(message, "❌ Values must be valid positive numbers.")


@bot.message_handler(
    commands=["coupons"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_coupons(message):

    coupons = list(
        coupons_col.find().sort(
            "created_at",
            DESCENDING
        ).limit(20)
    )

    if not coupons:
        bot.send_message(ADMIN_ID, "No coupons found.")
        return

    text = "🎟 *Recent Coupons*\n\n"

    for coupon in coupons:
        expired = (
            "⌛ Expired"
            if coupon.get("expires_at") and coupon["expires_at"] < datetime.now()
            else "✅ Active"
        )

        text += (
            f"`{coupon['code']}` — {coupon['coins']} coins\n"
            f"Uses: {coupon.get('used_count', 0)}/{coupon['max_uses']} — {expired}\n\n"
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
        "📢 Send the message you want to broadcast.\n\nIt will be sent to all registered users."
    )

    bot.register_next_step_handler(
        msg,
        broadcast_message
    )


def broadcast_message(message):

    users = bot_users_col.find(
        {"banned": {"$ne": True}},
        {"user_id": 1}
    )

    success = 0
    failed = 0

    bot.send_message(ADMIN_ID, "📢 Broadcasting started...")

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


# =========================================================
# ADMIN FEEDBACK VIEW
# =========================================================

@bot.message_handler(
    commands=["feedbacks"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_feedbacks(message):

    feedbacks = list(
        feedback_col.find().sort(
            "created_at",
            DESCENDING
        ).limit(10)
    )

    if not feedbacks:
        bot.send_message(ADMIN_ID, "💬 No feedback yet.")
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


# =========================================================
# STATS
# =========================================================

@bot.message_handler(
    commands=["stats"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def bot_stats(message):

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
                    "total": {"$sum": "$coins"}
                }
            }
        ])
    )

    coins = total_coins[0]["total"] if total_coins else 0

    bot.send_message(
        ADMIN_ID,
        f"""📊 *Bot Statistics*

👥 Total Users: *{total_users}*
🔗 Verified Referrals: *{verified_referrals}*
🚫 Banned Users: *{banned_users}*
🪙 Total User Coins: *{coins}*

📢 Paid Channels: *{channels_col.count_documents({})}*
📢 Required Channels: *{force_channels_col.count_documents({})}*
🎟 Coupons: *{coupons_col.count_documents({})}*""",
        parse_mode="Markdown"
    )


# =========================================================
# CLEAR EXPIRED PENDING PAYMENTS
# =========================================================

def clear_pending_payments():

    now = datetime.now()
    expired = []

    for user_id, data in list(pending_payments.items()):

        if (now - data["time"]).total_seconds() >= 600:

            try:
                bot.send_message(
                    user_id,
                    "⌛ Your payment verification request expired. Please try again."
                )
            except Exception:
                pass

            expired.append(user_id)

    for user_id in expired:
        pending_payments.pop(user_id, None)


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

            # Ban then unban = removes the user but allows future rejoin
            bot.ban_chat_member(channel_id, user_id)
            bot.unban_chat_member(channel_id, user_id)

            source = user.get("source", "paid_subscription")

            if source == "coin_reward":

                bot.send_message(
                    user_id,
                    """⏰ *Your Premium Membership Has Expired*

Your redeemed Premium time has ended and you have been removed from the Premium channel.

🪙 Earn more coins through referrals and redeem Premium again!""",
                    parse_mode="Markdown"
                )

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
                        "⚠️ Your subscription has expired.\n\nClick below to renew.",
                        reply_markup=markup
                    )

                except Exception:
                    pass

            users_col.delete_one(
                {"_id": user["_id"]}
            )

        except Exception as e:
            # Keep record so scheduler tries again later
            print(f"Kick expired user error: {e}")


# =========================================================
# ERROR / UNKNOWN MESSAGE FALLBACK
# =========================================================

@bot.message_handler(
    func=lambda m: True,
    content_types=["text"]
)
def unknown_message(message):

    # Do not interrupt commands
    if message.text and message.text.startswith("/"):
        return

    # Only show menu guidance for normal users
    if not is_banned(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "ℹ️ Please use the buttons below to use the bot."
        )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    keep_alive()

    # Create/update settings
    get_settings()

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