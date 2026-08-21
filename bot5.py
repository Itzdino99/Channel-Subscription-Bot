import os
import time
import telebot

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from pymongo import MongoClient
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from flask import Flask
from threading import Thread


# ============================================================
# RENDER KEEP ALIVE
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running and healthy!"


def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

UPI_ID = os.getenv("UPI_ID")
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME")

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client["sub_management"]

channels_col = db["channels"]
users_col = db["users"]

# New collections
referrals_col = db["referrals"]
ref_settings_col = db["referral_settings"]
competition_col = db["competition"]
broadcast_col = db["broadcasts"]


# ============================================================
# TEMP STORAGE
# ============================================================

pending_payments = {}

pending_admin_actions = {}

pending_broadcast = set()


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_REF_SETTINGS = {
    "coins_per_referral": 10,
    "new_user_bonus": 0,
    "redeem_plans": {
        "1440": 20,
        "10080": 100,
        "43200": 300
    }
}


# ============================================================
# USER DATABASE
# ============================================================

def register_user(user):

    if not user:
        return

    users_col.update_one(
        {"user_id": user.id},
        {
            "$set": {
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "updated_at": datetime.now()
            },
            "$setOnInsert": {
                "user_id": user.id,
                "coins": 0,
                "total_referrals": 0,
                "created_at": datetime.now()
            }
        },
        upsert=True
    )


def get_user(user_id):

    user = users_col.find_one({
        "user_id": user_id
    })

    if not user:
        users_col.insert_one({
            "user_id": user_id,
            "coins": 0,
            "total_referrals": 0,
            "created_at": datetime.now()
        })

        user = users_col.find_one({
            "user_id": user_id
        })

    return user


# ============================================================
# REFERRAL SETTINGS
# ============================================================

def get_ref_settings():

    settings = ref_settings_col.find_one({
        "type": "global"
    })

    if not settings:

        settings = DEFAULT_REF_SETTINGS.copy()

        ref_settings_col.insert_one({
            "type": "global",
            **settings
        })

    return ref_settings_col.find_one({
        "type": "global"
    })


# ============================================================
# MAIN MENU
# ============================================================

def user_main_menu():

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            "🛒 Premium Plans",
            callback_data="user_plans"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🪙 My Balance",
            callback_data="my_balance"
        ),
        InlineKeyboardButton(
            "🔗 Refer & Earn",
            callback_data="refer_menu"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🎁 Redeem Premium",
            callback_data="redeem_menu"
        ),
        InlineKeyboardButton(
            "🏆 Leaderboard",
            callback_data="leaderboard"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "👥 My Referrals",
            callback_data="my_referrals"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📖 How It Works",
            callback_data="how_it_works"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    return markup


def admin_main_menu():

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            "📢 Manage Channels",
            callback_data="admin_channels"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🏆 Competition",
            callback_data="admin_competition"
        ),
        InlineKeyboardButton(
            "🪙 Referral Settings",
            callback_data="admin_referral"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🎁 Redeem Settings",
            callback_data="admin_redeem"
        ),
        InlineKeyboardButton(
            "📢 Broadcast",
            callback_data="admin_broadcast"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "👥 User Statistics",
            callback_data="admin_stats"
        )
    )

    return markup


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start_handler(message):

    user_id = message.from_user.id

    register_user(message.from_user)

    args = message.text.split(maxsplit=1)

    # --------------------------------------------------------
    # REFERRAL DEEP LINK
    # --------------------------------------------------------

    if len(args) > 1:

        parameter = args[1].strip()

        if parameter.startswith("ref_"):

            try:

                referrer_id = int(
                    parameter.replace("ref_", "")
                )

                handle_referral_start(
                    message,
                    referrer_id
                )

                return

            except Exception as e:

                print(
                    "REFERRAL START ERROR:",
                    e
                )

    # --------------------------------------------------------
    # OLD CHANNEL DEEP LINK
    # --------------------------------------------------------

    if len(args) > 1:

        try:

            ch_id = int(args[1])

            ch_data = channels_col.find_one({
                "channel_id": ch_id
            })

            if ch_data:

                send_channel_plans(
                    message.chat.id,
                    ch_data
                )

                return

        except Exception as e:

            print(
                "CHANNEL START ERROR:",
                e
            )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if user_id == ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "👑 *Admin Panel*\n\n"
            "Manage your channels, referrals, "
            "competition, broadcast and users.",
            reply_markup=admin_main_menu(),
            parse_mode="Markdown"
        )

        return

    # --------------------------------------------------------
    # NORMAL USER
    # --------------------------------------------------------

    bot.send_message(
        message.chat.id,
        "✨ *Welcome!*\n\n"
        "Choose an option below.",
        reply_markup=user_main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# CHANNEL PLAN DISPLAY
# EXISTING FEATURE
# ============================================================

def send_channel_plans(chat_id, ch_data):

    markup = InlineKeyboardMarkup()

    rejoin_url = "https://t.me/+lSW2hYbgrUNkMzFl"

    markup.add(
        InlineKeyboardButton(
            "🔗 ᴅᴇᴍᴏ",
            url=rejoin_url
        )
    )

    for p_time, p_price in ch_data["plans"].items():

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
                callback_data=f"select_{ch_data['channel_id']}_{p_time}"
            )
        )

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    bot.send_message(
        chat_id,
        f"""✨ *Welcome!*

📢 *Channel:* `{ch_data['name']}`

Select a subscription plan below.
""",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.send_message(
        chat_id,
        """📌 *Notice*

• Demo access is for testing only.
• Read all instructions before making a payment.
""",
        parse_mode="Markdown"
    )


# ============================================================
# ADMIN /CHANNELS
# ============================================================

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
        "📢 *Your Managed Channels:*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["add"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Please ensure the bot is an Admin in your channel.\n\n"
        "Then FORWARD any message from that channel here."
    )

    bot.register_next_step_handler(
        msg,
        get_plans
    )


@bot.callback_query_handler(
    func=lambda call: call.data == "admin_channels"
)
def cb_admin_channels(call):

    bot.answer_callback_query(call.id)

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Add New Channel",
            callback_data="add_new"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📋 Existing Channels",
            callback_data="list_existing_channels"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="back_main"
        )
    )

    bot.edit_message_text(
        "📢 *Channel Management*",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data == "list_existing_channels"
)
def cb_existing_channels(call):

    bot.answer_callback_query(call.id)

    markup = InlineKeyboardMarkup()

    cursor = channels_col.find({
        "admin_id": ADMIN_ID
    })

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
            "🔙 Back",
            callback_data="admin_channels"
        )
    )

    bot.edit_message_text(
        "Your channels:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(
    func=lambda call: call.data == "add_new"
)
def cb_add_new(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        "Please FORWARD any message from your channel here."
    )

    bot.register_next_step_handler(
        msg,
        get_plans
    )


def get_plans(message):

    if message.forward_from_chat:

        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title

        msg = bot.send_message(
            ADMIN_ID,
            f"""✅ Channel Detected: {ch_name}

Enter plans:

1440:99,43200:199

Example:
1440 = 1 Day
43200 = 30 Days
""",
            parse_mode="Markdown"
        )

        bot.register_next_step_handler(
            msg,
            finalize_channel,
            ch_id,
            ch_name
        )

    else:

        bot.send_message(
            ADMIN_ID,
            "❌ Message was not forwarded.\n\nUse /add again."
        )


def finalize_channel(message, ch_id, ch_name):

    try:

        raw_plans = message.text.split(",")

        plans_dict = {}

        for p in raw_plans:

            t, pr = p.strip().split(":")

            plans_dict[t] = pr

        channels_col.update_one(
            {
                "channel_id": ch_id
            },
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
            f"""✅ *Setup Successful!*

Invite Link:

`https://t.me/{bot_username}?start={ch_id}`
""",
            parse_mode="Markdown"
        )

    except Exception as e:

        print(e)

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\n"
            "`1440:99,43200:199`",
            parse_mode="Markdown"
        )


# ============================================================
# EXISTING PAYMENT FLOW
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("select_")
)
def user_pays(call):

    _, ch_id, mins = call.data.split("_")

    ch_data = channels_col.find_one({
        "channel_id": int(ch_id)
    })

    if not ch_data:
        bot.answer_callback_query(
            call.id,
            "Channel not found.",
            show_alert=True
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
        plan_name = f"📅 {minutes // 1440} Days"

    else:
        plan_name = f"⏱ {minutes} Min"

    qr_url = "https://i.ibb.co/v4yw96tb/IMG-20260712-103503.jpg"

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "✅ I Have Paid",
            callback_data=f"paid_{ch_id}_{mins}"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
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
            "*USDT (BNB) Address:*\n"
            "`0x5a854d50bfaefb616387cd47fb15f32f1a8cb5e2`\n\n"
            "📋 Tap payment details to copy.\n\n"
            "✅ After payment tap *I Have Paid*.\n"
            "📷 Then send your screenshot to admin."
        ),
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.send_message(
        call.message.chat.id,
        """📌 *Notice*

• Send the exact payment amount.
• Keep your payment screenshot.
• Tap ✅ *I Have Paid*.
• Then send your screenshot to admin.
• Verification usually takes a few minutes.

🙏 Thank you!""",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("paid_")
)
def payment_screenshot_request(call):

    _, ch_id, mins = call.data.split("_")

    user_id = call.from_user.id

    if user_id in pending_payments:

        bot.answer_callback_query(
            call.id,
            "⚠️ You already have a pending verification.",
            show_alert=True
        )

        return

    ch_data = channels_col.find_one({
        "channel_id": int(ch_id)
    })

    price = ch_data["plans"][mins]

    pending_payments[user_id] = {
        "channel_id": int(ch_id),
        "channel_name": ch_data["name"],
        "plan": mins,
        "price": price,
        "time": datetime.now()
    }

    bot.answer_callback_query(call.id)

    bot.send_message(
        user_id,
        """📷 *Upload Payment Screenshot*

Please send your payment screenshot as a PHOTO.

⚠️ Do NOT send:
• Screenshot as a file
• Video
• Text

⏳ Please upload it within 10 minutes.
""",
        parse_mode="Markdown"
    )


# ============================================================
# WAITING PAYMENT TEXT
# ============================================================

@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=["text"]
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "📷 Please upload the payment screenshot as a PHOTO."
    )


# ============================================================
# PAYMENT DOCUMENT
# ============================================================

@bot.message_handler(
    content_types=["document"]
)
def document_handler(message):

    if message.from_user.id not in pending_payments:
        return

    bot.reply_to(
        message,
        "❌ Please send the screenshot as a PHOTO."
    )


# ============================================================
# PAYMENT PHOTO
# ============================================================

@bot.message_handler(
    content_types=["photo"]
)
def photo_handler(message):

    try:

        user_id = message.from_user.id

        if user_id not in pending_payments:
            return

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
            f"""🔔 Payment Verification Required!

👤 Name: {message.from_user.first_name}
🆔 User ID: {user_id}
🌐 Username: {username}

📢 Channel: {payment['channel_name']}
💎 Plan: {payment['plan']}
💰 Price: NPR {payment['price']}

📷 Screenshot forwarded above."""
        )

        markup = InlineKeyboardMarkup(row_width=2)

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

        user_markup = InlineKeyboardMarkup()

        user_markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )

        bot.send_message(
            user_id,
            """✅ Screenshot Uploaded Successfully!

📷 Your screenshot was forwarded to admin.

⏳ Status: Waiting for verification.

🔔 After approval, your invite link will be sent automatically.
""",
            reply_markup=user_markup
        )

        del pending_payments[user_id]

    except Exception as e:

        print(
            f"PHOTO_HANDLER ERROR: {e}"
        )


# ============================================================
# APPROVE PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("app_")
)
def approve_now(call):

    _, u_id, ch_id, mins = call.data.split("_")

    u_id = int(u_id)
    ch_id = int(ch_id)
    mins = int(mins)

    try:

        expiry_datetime = (
            datetime.now() +
            timedelta(minutes=mins)
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
                    "expiry": expiry_datetime.timestamp()
                }
            },
            upsert=True
        )

        if u_id in pending_payments:
            del pending_payments[u_id]

        if mins > 525600:
            plan_name = "💎 Lifetime"

        elif mins >= 1440:
            plan_name = f"📅 {mins // 1440} Days"

        else:
            plan_name = f"⏱ {mins} Minutes"

        bot.send_message(
            u_id,
            f"""🎉 *Payment Approved!*

Your payment has been verified.

💎 *Plan:* {plan_name}

🔗 *Join Link:*
{link.invite_link}

⚠️ This invite link can only be used once.
""",
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


# ============================================================
# REJECT PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("rej_")
)
def reject_payment(call):

    user_id = int(
        call.data.split("_")[1]
    )

    if user_id in pending_payments:
        del pending_payments[user_id]

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    bot.send_message(
        user_id,
        """❌ *Payment Rejected*

Your payment could not be verified.

Please check your payment and submit a new screenshot.

If you believe this is a mistake, contact admin.
""",
        parse_mode="Markdown",
        reply_markup=markup
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# ============================================================
# REFERRAL SYSTEM
# ============================================================

def get_bot_ref_link(user_id):

    username = bot.get_me().username

    return (
        f"https://t.me/{username}"
        f"?start=ref_{user_id}"
    )


def handle_referral_start(message, referrer_id):

    user_id = message.from_user.id

    # Register current user
    register_user(message.from_user)

    # Can't refer yourself
    if user_id == referrer_id:

        bot.send_message(
            user_id,
            "❌ You cannot refer yourself.",
            reply_markup=user_main_menu()
        )

        return

    referrer = users_col.find_one({
        "user_id": referrer_id
    })

    if not referrer:

        bot.send_message(
            user_id,
            "❌ Referral is invalid.",
            reply_markup=user_main_menu()
        )

        return

    # Already has a referrer
    current = users_col.find_one({
        "user_id": user_id
    })

    if current and current.get("referred_by"):

        show_referral_verification(
            message,
            current["referred_by"]
        )

        return

    # Save referral
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "referred_by": referrer_id,
                "referral_started_at": datetime.now(),
                "referral_verified": False
            }
        }
    )

    show_referral_verification(
        message,
        referrer_id
    )


# ============================================================
# REQUIRED GROUPS
# ============================================================

def get_required_groups():

    settings = get_ref_settings()

    return settings.get(
        "required_groups",
        []
    )


def check_membership(user_id):

    groups = get_required_groups()

    results = []

    for group in groups:

        try:

            member = bot.get_chat_member(
                group["chat_id"],
                user_id
            )

            status = member.status

            joined = status in [
                "member",
                "administrator",
                "creator"
            ]

            if status == "restricted":
                joined = getattr(
                    member,
                    "is_member",
                    False
                )

            results.append({
                "chat_id": group["chat_id"],
                "name": group["name"],
                "url": group["url"],
                "joined": joined
            })

        except Exception as e:

            print(
                f"Membership check error "
                f"{group['chat_id']}: {e}"
            )

            results.append({
                "chat_id": group["chat_id"],
                "name": group["name"],
                "url": group["url"],
                "joined": False
            })

    return results


def show_referral_verification(
    message,
    referrer_id
):

    user_id = message.from_user.id

    results = check_membership(
        user_id
    )

    markup = InlineKeyboardMarkup()

    all_joined = True

    for group in results:

        if group["joined"]:

            markup.add(
                InlineKeyboardButton(
                    f"✅ {group['name']}",
                    callback_data="nothing"
                )
            )

        else:

            all_joined = False

            markup.add(
                InlineKeyboardButton(
                    f"📢 Join {group['name']}",
                    url=group["url"]
                )
            )

    if all_joined:

        markup.add(
            InlineKeyboardButton(
                "✅ Verify Referral",
                callback_data="verify_referral"
            )
        )

    else:

        markup.add(
            InlineKeyboardButton(
                "🔄 Verify Membership",
                callback_data="verify_referral"
            )
        )

    bot.send_message(
        user_id,
        """🔐 *Referral Verification*

To activate your referral, you must join all required groups/channels.

After joining everything, press:
🔄 *Verify Membership*

Your referrer will receive the reward only after verification.
""",
        reply_markup=markup,
        parse_mode="Markdown"
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

    user = users_col.find_one({
        "user_id": user_id
    })

    if not user:

        bot.answer_callback_query(
            call.id,
            "User not found.",
            show_alert=True
        )

        return

    if user.get("referral_verified"):

        bot.answer_callback_query(
            call.id,
            "Already verified.",
            show_alert=True
        )

        return

    referrer_id = user.get(
        "referred_by"
    )

    if not referrer_id:

        bot.answer_callback_query(
            call.id,
            "No referral found.",
            show_alert=True
        )

        return

    results = check_membership(
        user_id
    )

    not_joined = [
        x for x in results
        if not x["joined"]
    ]

    if not_joined:

        bot.answer_callback_query(
            call.id,
            "❌ Please join all required groups first.",
            show_alert=True
        )

        return

    # --------------------------------------------------------
    # Reward referral
    # --------------------------------------------------------

    settings = get_ref_settings()

    reward = int(
        settings.get(
            "coins_per_referral",
            10
        )
    )

    # Atomic protection
    updated = users_col.update_one(
        {
            "user_id": user_id,
            "referral_verified": {
                "$ne": True
            }
        },
        {
            "$set": {
                "referral_verified": True,
                "referral_verified_at": datetime.now()
            }
        }
    )

    if updated.modified_count == 0:

        bot.answer_callback_query(
            call.id,
            "Already processed.",
            show_alert=True
        )

        return

    # Give referrer coins
    users_col.update_one(
        {
            "user_id": referrer_id
        },
        {
            "$inc": {
                "coins": reward,
                "total_referrals": 1
            }
        }
    )

    # Referral history
    referrals_col.insert_one({
        "referrer_id": referrer_id,
        "referred_user_id": user_id,
        "coins": reward,
        "created_at": datetime.now()
    })

    # New user bonus
    new_user_bonus = int(
        settings.get(
            "new_user_bonus",
            0
        )
    )

    if new_user_bonus > 0:

        users_col.update_one(
            {
                "user_id": user_id
            },
            {
                "$inc": {
                    "coins": new_user_bonus
                }
            }
        )

    # Competition score
    competition = competition_col.find_one({
        "type": "global"
    })

    if competition and competition.get("active"):

        users_col.update_one(
            {
                "user_id": referrer_id
            },
            {
                "$inc": {
                    "competition_score": 1
                }
            }
        )

    bot.answer_callback_query(
        call.id,
        "🎉 Referral verified!",
        show_alert=True
    )

    try:

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )

    except:
        pass

    bot.send_message(
        user_id,
        "✅ *Referral Verified!*\n\n"
        "You have completed the required membership verification.\n\n"
        "🎉 Your referrer has received the referral reward.",
        reply_markup=user_main_menu(),
        parse_mode="Markdown"
    )

    try:

        bot.send_message(
            referrer_id,
            f"""🎉 *New Successful Referral!*

👤 New user: {message_user_name(call.from_user)}

🪙 Coins earned: +{reward}

Check your balance below.
""",
            reply_markup=user_main_menu(),
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            "Referrer notification error:",
            e
        )


def message_user_name(user):

    if user.username:
        return f"@{user.username}"

    return user.first_name or "User"


# ============================================================
# USER BALANCE
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "my_balance"
)
def my_balance(call):

    user = get_user(
        call.from_user.id
    )

    coins = user.get(
        "coins",
        0
    )

    referrals = user.get(
        "total_referrals",
        0
    )

    score = user.get(
        "competition_score",
        0
    )

    rank = get_user_rank(
        call.from_user.id
    )

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🔗 Refer & Earn",
            callback_data="refer_menu"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🎁 Redeem Premium",
            callback_data="redeem_menu"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 Main Menu",
            callback_data="back_main"
        )
    )

    bot.edit_message_text(
        f"""🪙 *My Balance*

💰 Coins: *{coins}*

👥 Successful Referrals:
*{referrals}*

🏆 Competition Score:
*{score}*

📊 Current Rank:
*#{rank}*
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# REFERRAL MENU
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "refer_menu"
)
def referral_menu(call):

    user = get_user(
        call.from_user.id
    )

    coins = user.get(
        "coins",
        0
    )

    referrals = user.get(
        "total_referrals",
        0
    )

    link = get_bot_ref_link(
        call.from_user.id
    )

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📤 Share Referral Link",
            switch_inline_query=""
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🏆 Leaderboard",
            callback_data="leaderboard"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🪙 My Balance",
            callback_data="my_balance"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 Main Menu",
            callback_data="back_main"
        )
    )

    bot.edit_message_text(
        f"""🔗 *Refer & Earn*

Invite your friends using your personal link:

`{link}`

👥 Successful Referrals:
*{referrals}*

🪙 Your Coins:
*{coins}*

💡 Your friend must join all required groups/channels and verify membership before the referral is counted.
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# MY REFERRALS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "my_referrals"
)
def my_referrals(call):

    count = referrals_col.count_documents({
        "referrer_id": call.from_user.id
    })

    recent = list(
        referrals_col.find({
            "referrer_id": call.from_user.id
        }).sort(
            "created_at",
            -1
        ).limit(10)
    )

    text = (
        "👥 *My Referrals*\n\n"
        f"✅ Successful referrals: *{count}*\n\n"
    )

    if recent:

        text += "Recent:\n"

        for i, ref in enumerate(
            recent,
            1
        ):

            text += (
                f"{i}. User ID: "
                f"`{ref['referred_user_id']}` "
                f"🪙 +{ref['coins']}\n"
            )

    else:

        text += "No successful referrals yet."

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="back_main"
        )
    )

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# RANK
# ============================================================

def get_user_rank(user_id):

    user = users_col.find_one({
        "user_id": user_id
    })

    if not user:
        return 1

    score = user.get(
        "competition_score",
        0
    )

    higher = users_col.count_documents({
        "competition_score": {
            "$gt": score
        }
    })

    return higher + 1


# ============================================================
# LEADERBOARD
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "leaderboard"
)
def leaderboard(call):

    users = users_col.find(
        {
            "competition_score": {
                "$gt": 0
            }
        }
    ).sort(
        "competition_score",
        -1
    ).limit(5)

    text = "🏆 *TOP 5 REFERRERS*\n\n"

    found = False

    medals = [
        "🥇",
        "🥈",
        "🥉",
        "4️⃣",
        "5️⃣"
    ]

    for index, user in enumerate(
        users
    ):

        found = True

        name = (
            f"@{user['username']}"
            if user.get("username")
            else user.get(
                "first_name",
                "User"
            )
        )

        score = user.get(
            "competition_score",
            0
        )

        text += (
            f"{medals[index]} "
            f"{name} — *{score}*\n"
        )

    if not found:

        text += "No referrals yet."

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🔄 Refresh",
            callback_data="leaderboard"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 Main Menu",
            callback_data="back_main"
        )
    )

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# REDEEM PREMIUM
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "redeem_menu"
)
def redeem_menu(call):

    user = get_user(
        call.from_user.id
    )

    coins = user.get(
        "coins",
        0
    )

    settings = get_ref_settings()

    markup = InlineKeyboardMarkup()

    for mins, coin_price in settings.get(
        "redeem_plans",
        {}
    ).items():

        minutes = int(mins)

        if minutes >= 1440:

            days = minutes // 1440

            label = (
                f"📅 {days} Days "
                f"— 🪙 {coin_price}"
            )

        else:

            label = (
                f"⏱ {minutes} Min "
                f"— 🪙 {coin_price}"
            )

        markup.add(
            InlineKeyboardButton(
                label,
                callback_data=f"redeem_{mins}"
            )
        )

    markup.add(
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="back_main"
        )
    )

    bot.edit_message_text(
        f"""🎁 *Redeem Premium*

🪙 Your Balance:
*{coins} Coins*

Choose a Premium duration:
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("redeem_")
)
def redeem_plan_select(call):

    mins = call.data.replace(
        "redeem_",
        ""
    )

    settings = get_ref_settings()

    cost = int(
        settings.get(
            "redeem_plans",
            {}
        ).get(
            mins,
            0
        )
    )

    user = get_user(
        call.from_user.id
    )

    coins = user.get(
        "coins",
        0
    )

    if coins < cost:

        bot.answer_callback_query(
            call.id,
            f"❌ You need {cost} coins. You have {coins}.",
            show_alert=True
        )

        return

    # Get available channels
    channels = list(
        channels_col.find({
            "admin_id": ADMIN_ID
        })
    )

    if not channels:

        bot.answer_callback_query(
            call.id,
            "No Premium channels available.",
            show_alert=True
        )

        return

    markup = InlineKeyboardMarkup()

    for ch in channels:

        markup.add(
            InlineKeyboardButton(
                f"📢 {ch['name']}",
                callback_data=(
                    f"redeemconfirm_"
                    f"{ch['channel_id']}_"
                    f"{mins}"
                )
            )
        )

    markup.add(
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="redeem_menu"
        )
    )

    bot.edit_message_text(
        f"""🎁 *Redeem Premium*

Plan: *{mins} minutes*

Cost: 🪙 *{cost} Coins*

Choose the Premium channel:
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("redeemconfirm_")
)
def redeem_confirm(call):

    _, ch_id, mins = call.data.split("_")

    ch_id = int(ch_id)
    mins = int(mins)

    settings = get_ref_settings()

    cost = int(
        settings.get(
            "redeem_plans",
            {}
        ).get(
            str(mins),
            0
        )
    )

    # Atomic coin deduction
    updated = users_col.update_one(
        {
            "user_id": call.from_user.id,
            "coins": {
                "$gte": cost
            }
        },
        {
            "$inc": {
                "coins": -cost
            }
        }
    )

    if updated.modified_count == 0:

        bot.answer_callback_query(
            call.id,
            "❌ Not enough coins.",
            show_alert=True
        )

        return

    try:

        expiry_datetime = (
            datetime.now() +
            timedelta(minutes=mins)
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
                "user_id": call.from_user.id,
                "channel_id": ch_id
            },
            {
                "$set": {
                    "expiry": expiry_ts
                }
            },
            upsert=True
        )

        bot.answer_callback_query(
            call.id,
            "🎉 Premium Redeemed!",
            show_alert=True
        )

        bot.edit_message_text(
            f"""🎉 *Premium Redeemed!*

🪙 Coins spent: *{cost}*

⏱ Duration:
*{mins} Minutes*

🔗 *Join Link:*
{link.invite_link}

⚠️ This link can only be used once.
""",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=user_main_menu(),
            parse_mode="Markdown"
        )

    except Exception as e:

        # Refund if generation failed
        users_col.update_one(
            {
                "user_id": call.from_user.id
            },
            {
                "$inc": {
                    "coins": cost
                }
            }
        )

        bot.answer_callback_query(
            call.id,
            "❌ Unable to create Premium link.",
            show_alert=True
        )

        print(
            "REDEEM ERROR:",
            e
        )


# ============================================================
# HOW IT WORKS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "how_it_works"
)
def how_it_works(call):

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🔙 Main Menu",
            callback_data="back_main"
        )
    )

    bot.edit_message_text(
        """📖 *How It Works*

🔗 *1. Refer*
Get your personal referral link.

👥 *2. Invite*
Send the link to your friends.

🔐 *3. Verification*
Your friend must join all required groups/channels.

🪙 *4. Earn*
After successful verification, you receive coins.

🎁 *5. Redeem*
Use your coins to get Premium.

🏆 *6. Competition*
The highest referrers can receive additional free Premium.

⚠️ Each Telegram account can only count as one successful referral.
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# ADMIN REFERRAL SETTINGS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "admin_referral"
)
def admin_referral(call):

    settings = get_ref_settings()

    reward = settings.get(
        "coins_per_referral",
        10
    )

    bonus = settings.get(
        "new_user_bonus",
        0
    )

    groups = get_required_groups()

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🪙 Set Coins / Referral",
            callback_data="set_ref_coins"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🎁 Set New User Bonus",
            callback_data="set_new_bonus"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "➕ Add Required Group",
            callback_data="add_required_group"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "➖ Remove Required Group",
            callback_data="remove_required_group"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📋 Required Groups",
            callback_data="required_groups"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 Admin Panel",
            callback_data="admin_main"
        )
    )

    bot.edit_message_text(
        f"""🪙 *Referral Settings*

🪙 Coins per referral:
*{reward}*

🎁 New user bonus:
*{bonus}*

🔐 Required groups:
*{len(groups)}*
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# SET REFERRAL COINS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "set_ref_coins"
)
def set_ref_coins(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        "🪙 Enter coins given for every successful referral:\n\n"
        "Example: `10`",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        save_ref_coins
    )


def save_ref_coins(message):

    try:

        value = int(
            message.text.strip()
        )

        ref_settings_col.update_one(
            {
                "type": "global"
            },
            {
                "$set": {
                    "coins_per_referral": value
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Referral reward set to *{value} coins*.",
            parse_mode="Markdown"
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Enter a valid number."
        )


# ============================================================
# NEW USER BONUS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "set_new_bonus"
)
def set_new_bonus(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        "🎁 Enter new-user bonus coins:\n\n"
        "Example: `2`"
    )

    bot.register_next_step_handler(
        msg,
        save_new_bonus
    )


def save_new_bonus(message):

    try:

        value = int(
            message.text.strip()
        )

        ref_settings_col.update_one(
            {
                "type": "global"
            },
            {
                "$set": {
                    "new_user_bonus": value
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ New user bonus: *{value} coins*",
            parse_mode="Markdown"
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid number."
        )


# ============================================================
# ADD REQUIRED GROUP
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "add_required_group"
)
def add_required_group(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        """➕ *Add Required Group/Channel*

Forward any message from the group/channel to this bot.

The bot must be an administrator there.
""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        receive_required_group
    )


def receive_required_group(message):

    try:

        if not message.forward_from_chat:

            bot.send_message(
                ADMIN_ID,
                "❌ Please forward a message from the target group/channel."
            )

            return

        chat = message.forward_from_chat

        chat_id = chat.id
        name = chat.title or "Required Group"

        # Generate a public link if possible
        if getattr(chat, "username", None):

            url = (
                f"https://t.me/"
                f"{chat.username}"
            )

        else:

            # For private groups, ask admin for invite URL
            bot.send_message(
                ADMIN_ID,
                "⚠️ This is a private group/channel.\n\n"
                "Send its invite link now:"
            )

            pending_admin_actions[
                ADMIN_ID
            ] = {
                "type": "private_required_group",
                "chat_id": chat_id,
                "name": name
            }

            return

        settings = get_ref_settings()

        groups = settings.get(
            "required_groups",
            []
        )

        # Prevent duplicates
        if any(
            str(x["chat_id"]) ==
            str(chat_id)
            for x in groups
        ):

            bot.send_message(
                ADMIN_ID,
                "⚠️ This group is already added."
            )

            return

        groups.append({
            "chat_id": chat_id,
            "name": name,
            "url": url
        })

        ref_settings_col.update_one(
            {
                "type": "global"
            },
            {
                "$set": {
                    "required_groups": groups
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"""✅ *Required Target Added*

📢 {name}

ID:
`{chat_id}`
""",
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            "ADD GROUP ERROR:",
            e
        )

        bot.send_message(
            ADMIN_ID,
            f"❌ Error:\n{e}"
        )


# ============================================================
# PRIVATE GROUP INVITE LINK FOLLOWUP
# ============================================================

@bot.message_handler(
    func=lambda m:
    m.from_user.id == ADMIN_ID
    and m.from_user.id in pending_admin_actions
    and pending_admin_actions[m.from_user.id].get("type")
    == "private_required_group",
    content_types=["text"]
)
def private_group_link(message):

    data = pending_admin_actions.pop(
        ADMIN_ID
    )

    url = message.text.strip()

    groups = get_required_groups()

    groups.append({
        "chat_id": data["chat_id"],
        "name": data["name"],
        "url": url
    })

    ref_settings_col.update_one(
        {
            "type": "global"
        },
        {
            "$set": {
                "required_groups": groups
            }
        },
        upsert=True
    )

    bot.send_message(
        ADMIN_ID,
        "✅ Private required group added."
    )


# ============================================================
# REQUIRED GROUP LIST
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "required_groups"
)
def required_groups(call):

    groups = get_required_groups()

    markup = InlineKeyboardMarkup()

    if not groups:

        text = (
            "🔐 *Required Groups*\n\n"
            "No groups/channels configured."
        )

    else:

        text = (
            "🔐 *Required Groups/Channels*\n\n"
        )

        for i, group in enumerate(
            groups,
            1
        ):

            text += (
                f"{i}. {group['name']}\n"
                f"ID: `{group['chat_id']}`\n\n"
            )

    markup.add(
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="admin_referral"
        )
    )

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# REMOVE REQUIRED GROUP
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "remove_required_group"
)
def remove_required_group(call):

    groups = get_required_groups()

    markup = InlineKeyboardMarkup()

    for group in groups:

        markup.add(
            InlineKeyboardButton(
                f"❌ {group['name']}",
                callback_data=(
                    f"removegroup_"
                    f"{group['chat_id']}"
                )
            )
        )

    markup.add(
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="admin_referral"
        )
    )

    bot.edit_message_text(
        "Select group/channel to remove:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("removegroup_")
)
def remove_group_confirm(call):

    chat_id = int(
        call.data.replace(
            "removegroup_",
            ""
        )
    )

    groups = [
        x for x in get_required_groups()
        if int(x["chat_id"]) != chat_id
    ]

    ref_settings_col.update_one(
        {
            "type": "global"
        },
        {
            "$set": {
                "required_groups": groups
            }
        },
        upsert=True
    )

    bot.answer_callback_query(
        call.id,
        "Removed."
    )

    admin_referral(call)


# ============================================================
# ADMIN REDEEM SETTINGS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "admin_redeem"
)
def admin_redeem(call):

    settings = get_ref_settings()

    plans = settings.get(
        "redeem_plans",
        {}
    )

    text = "🎁 *Redeem Settings*\n\n"

    for mins, coins in plans.items():

        text += (
            f"⏱ {mins} minutes "
            f"= 🪙 {coins} coins\n"
        )

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Add/Edit Redeem Plan",
            callback_data="set_redeem_plan"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 Admin Panel",
            callback_data="admin_main"
        )
    )

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data == "set_redeem_plan"
)
def set_redeem_plan(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        """🎁 Enter redeem plan:

FORMAT:
minutes:coins

Example:
1440:20

Meaning:
1 Day = 20 coins
"""
    )

    bot.register_next_step_handler(
        msg,
        save_redeem_plan
    )


def save_redeem_plan(message):

    try:

        mins, coins = message.text.strip().split(":")

        mins = str(
            int(mins)
        )

        coins = int(
            coins
        )

        ref_settings_col.update_one(
            {
                "type": "global"
            },
            {
                "$set": {
                    f"redeem_plans.{mins}": coins
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Redeem plan saved.\n\n"
            f"{mins} minutes = {coins} coins"
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\n"
            "Example:\n"
            "`1440:20`",
            parse_mode="Markdown"
        )


# ============================================================
# COMPETITION
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "admin_competition"
)
def admin_competition(call):

    competition = competition_col.find_one({
        "type": "global"
    })

    if not competition:

        competition = {
            "active": False,
            "duration_hours": 168,
            "rewards": {
                "1": 43200,
                "2": 21600,
                "3": 10080,
                "4": 4320,
                "5": 1440
            }
        }

    status = (
        "🟢 ACTIVE"
        if competition.get("active")
        else "🔴 STOPPED"
    )

    markup = InlineKeyboardMarkup()

    if competition.get("active"):

        markup.add(
            InlineKeyboardButton(
                "⏹ Stop Competition",
                callback_data="stop_competition"
            )
        )

    else:

        markup.add(
            InlineKeyboardButton(
                "▶️ Start Competition",
                callback_data="start_competition"
            )
        )

    markup.add(
        InlineKeyboardButton(
            "⏱ Set Duration",
            callback_data="competition_duration"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🏆 Set Rewards",
            callback_data="competition_rewards"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔄 Reset Scores",
            callback_data="reset_scores"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📊 View Leaderboard",
            callback_data="leaderboard"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 Admin Panel",
            callback_data="admin_main"
        )
    )

    bot.edit_message_text(
        f"""🏆 *Referral Competition*

Status: *{status}*

When active, every verified referral gives
the referrer +1 competition score.

Top 5 winners receive configured Premium.
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# START COMPETITION
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "start_competition"
)
def start_competition(call):

    existing = competition_col.find_one({
        "type": "global"
    })

    duration = (
        existing.get(
            "duration_hours",
            168
        )
        if existing
        else 168
    )

    rewards = (
        existing.get(
            "rewards",
            {
                "1": 43200,
                "2": 21600,
                "3": 10080,
                "4": 4320,
                "5": 1440
            }
        )
        if existing
        else {
            "1": 43200,
            "2": 21600,
            "3": 10080,
            "4": 4320,
            "5": 1440
        }
    )

    start = datetime.now()

    end = (
        start +
        timedelta(
            hours=duration
        )
    )

    competition_col.update_one(
        {
            "type": "global"
        },
        {
            "$set": {
                "type": "global",
                "active": True,
                "started_at": start,
                "ends_at": end,
                "duration_hours": duration,
                "rewards": rewards
            }
        },
        upsert=True
    )

    bot.answer_callback_query(
        call.id,
        "🏆 Competition Started!"
    )

    bot.send_message(
        ADMIN_ID,
        f"""🏆 *Competition Started!*

⏱ Duration:
{duration} hours

🏁 Ends:
{end.strftime('%Y-%m-%d %H:%M')}
""",
        parse_mode="Markdown"
    )


# ============================================================
# STOP COMPETITION
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "stop_competition"
)
def stop_competition(call):

    competition_col.update_one(
        {
            "type": "global"
        },
        {
            "$set": {
                "active": False
            }
        }
    )

    bot.answer_callback_query(
        call.id,
        "Competition stopped."
    )

    bot.edit_message_text(
        "⏹ *Competition Stopped*",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=admin_main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# COMPETITION DURATION
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "competition_duration"
)
def competition_duration(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        """⏱ Enter competition duration in HOURS.

Example:
168

= 7 days
"""
    )

    bot.register_next_step_handler(
        msg,
        save_competition_duration
    )


def save_competition_duration(message):

    try:

        hours = int(
            message.text.strip()
        )

        competition_col.update_one(
            {
                "type": "global"
            },
            {
                "$set": {
                    "duration_hours": hours
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Competition duration set to {hours} hours."
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Enter a valid number."
        )


# ============================================================
# COMPETITION REWARDS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "competition_rewards"
)
def competition_rewards(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        """🏆 Enter Top 5 Premium rewards.

FORMAT:
1st_minutes,2nd_minutes,3rd_minutes,4th_minutes,5th_minutes

Example:

43200,21600,10080,4320,1440

Meaning:

🥇 30 days
🥈 15 days
🥉 7 days
4️⃣ 3 days
5️⃣ 1 day
"""
    )

    bot.register_next_step_handler(
        msg,
        save_competition_rewards
    )


def save_competition_rewards(message):

    try:

        values = [
            int(x.strip())
            for x in message.text.split(",")
        ]

        if len(values) != 5:

            raise ValueError(
                "Need exactly 5 values"
            )

        rewards = {
            str(i + 1): values[i]
            for i in range(5)
        }

        competition_col.update_one(
            {
                "type": "global"
            },
            {
                "$set": {
                    "rewards": rewards
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            "✅ Top 5 rewards updated."
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


# ============================================================
# RESET COMPETITION SCORES
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "reset_scores"
)
def reset_scores(call):

    users_col.update_many(
        {},
        {
            "$set": {
                "competition_score": 0
            }
        }
    )

    bot.answer_callback_query(
        call.id,
        "🔄 Scores reset."
    )

    bot.send_message(
        ADMIN_ID,
        "✅ Competition scores have been reset."
    )


# ============================================================
# FINISH COMPETITION
# ============================================================

def finish_competition():

    competition = competition_col.find_one({
        "type": "global",
        "active": True
    })

    if not competition:
        return

    if datetime.now() < competition.get(
        "ends_at",
        datetime.now()
    ):
        return

    winners = list(
        users_col.find(
            {
                "competition_score": {
                    "$gt": 0
                }
            }
        ).sort(
            "competition_score",
            -1
        ).limit(5)
    )

    rewards = competition.get(
        "rewards",
        {}
    )

    for index, winner in enumerate(
        winners
    ):

        position = str(
            index + 1
        )

        mins = int(
            rewards.get(
                position,
                0
            )
        )

        if mins <= 0:
            continue

        try:

            # Give Premium to winner.
            # Existing channel must exist.
            channel = channels_col.find_one({
                "admin_id": ADMIN_ID
            })

            if not channel:
                continue

            ch_id = channel["channel_id"]

            expiry = (
                datetime.now() +
                timedelta(
                    minutes=mins
                )
            )

            link = bot.create_chat_invite_link(
                ch_id,
                member_limit=1,
                expire_date=int(
                    expiry.timestamp()
                )
            )

            users_col.update_one(
                {
                    "user_id":
                    winner["user_id"],
                    "channel_id":
                    ch_id
                },
                {
                    "$set": {
                        "expiry":
                        expiry.timestamp()
                    }
                },
                upsert=True
            )

            bot.send_message(
                winner["user_id"],
                f"""🏆 *Competition Result!*

Congratulations!

Your position:
*#{index + 1}*

🎁 Premium Reward:
*{mins} Minutes*

🔗 Join:
{link.invite_link}

⚠️ This link can only be used once.
""",
                parse_mode="Markdown"
            )

        except Exception as e:

            print(
                "WINNER REWARD ERROR:",
                e
            )

    competition_col.update_one(
        {
            "_id": competition["_id"]
        },
        {
            "$set": {
                "active": False,
                "finished_at": datetime.now()
            }
        }
    )

    # Reset competition scores
    users_col.update_many(
        {},
        {
            "$set": {
                "competition_score": 0
            }
        }
    )

    bot.send_message(
        ADMIN_ID,
        "🏁 Competition finished and Top 5 rewards processed."
    )


# ============================================================
# ADMIN BROADCAST
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "admin_broadcast"
)
def admin_broadcast(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        """📢 *Broadcast*

Send the message you want to broadcast.

Supported:
• Text
• Photo
• Video
• Document
• Audio
• Sticker

The bot will copy the message to registered users.
""",
        parse_mode="Markdown"
    )

    pending_broadcast.add(
        ADMIN_ID
    )

    bot.register_next_step_handler(
        msg,
        receive_broadcast
    )


def receive_broadcast(message):

    if ADMIN_ID in pending_broadcast:

        pending_broadcast.discard(
            ADMIN_ID
        )

    users = users_col.find(
        {},
        {
            "user_id": 1
        }
    )

    total = users_col.count_documents({})

    sent = 0
    failed = 0

    status_message = bot.send_message(
        ADMIN_ID,
        f"""📢 *Broadcast Started*

👥 Total: {total}
✅ Sent: 0
❌ Failed: 0
""",
        parse_mode="Markdown"
    )

    for user in users:

        uid = user.get(
            "user_id"
        )

        if not uid:
            continue

        try:

            bot.copy_message(
                uid,
                message.chat.id,
                message.message_id
            )

            sent += 1

            # Avoid Telegram flood limits
            time.sleep(0.05)

        except Exception as e:

            failed += 1

            print(
                f"Broadcast failed {uid}: {e}"
            )

    try:

        bot.edit_message_text(
            f"""📢 *Broadcast Complete*

👥 Total: {total}

✅ Sent: {sent}

❌ Failed: {failed}
""",
            ADMIN_ID,
            status_message.message_id,
            parse_mode="Markdown"
        )

    except:

        bot.send_message(
            ADMIN_ID,
            f"""📢 Broadcast Complete

Total: {total}
Sent: {sent}
Failed: {failed}
"""
        )


# ============================================================
# ADMIN USER STATISTICS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "admin_stats"
)
def admin_stats(call):

    total_users = users_col.count_documents({})

    total_referrals = referrals_col.count_documents({})

    total_channels = channels_col.count_documents({
        "admin_id": ADMIN_ID
    })

    competition = competition_col.find_one({
        "type": "global"
    })

    active_comp = (
        "🟢 Yes"
        if competition and
        competition.get("active")
        else "🔴 No"
    )

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🔙 Admin Panel",
            callback_data="admin_main"
        )
    )

    bot.edit_message_text(
        f"""📊 *Bot Statistics*

👥 Registered Users:
*{total_users}*

🔗 Successful Referrals:
*{total_referrals}*

📢 Premium Channels:
*{total_channels}*

🏆 Competition:
{active_comp}
""",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# ADMIN ADD COINS
# ============================================================

@bot.message_handler(
    commands=["addcoins"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_add_coins(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Format:\n\n"
        "`USER_ID COINS`\n\n"
        "Example:\n"
        "`123456789 100`",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        process_add_coins
    )


def process_add_coins(message):

    try:

        user_id, coins = message.text.split()

        user_id = int(user_id)
        coins = int(coins)

        users_col.update_one(
            {
                "user_id": user_id
            },
            {
                "$inc": {
                    "coins": coins
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Added {coins} coins to {user_id}."
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


# ============================================================
# ADMIN REMOVE COINS
# ============================================================

@bot.message_handler(
    commands=["removecoins"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_remove_coins(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Format:\n\n"
        "`USER_ID COINS`\n\n"
        "Example:\n"
        "`123456789 50`",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        process_remove_coins
    )


def process_remove_coins(message):

    try:

        user_id, coins = message.text.split()

        user_id = int(user_id)
        coins = int(coins)

        users_col.update_one(
            {
                "user_id": user_id
            },
            {
                "$inc": {
                    "coins": -coins
                }
            }
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Removed {coins} coins from {user_id}."
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


# ============================================================
# COMMAND SHORTCUTS
# ============================================================

@bot.message_handler(
    commands=["refer"]
)
def refer_command(message):

    register_user(
        message.from_user
    )

    fake_call = None

    link = get_bot_ref_link(
        message.from_user.id
    )

    user = get_user(
        message.from_user.id
    )

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🎁 Redeem Premium",
            callback_data="redeem_menu"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🏆 Leaderboard",
            callback_data="leaderboard"
        )
    )

    bot.send_message(
        message.chat.id,
        f"""🔗 *Refer & Earn*

Your personal referral link:

`{link}`

👥 Successful Referrals:
*{user.get('total_referrals', 0)}*

🪙 Coins:
*{user.get('coins', 0)}*

Share your link with friends.
""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["balance"]
)
def balance_command(message):

    register_user(
        message.from_user
    )

    user = get_user(
        message.from_user.id
    )

    bot.send_message(
        message.chat.id,
        f"""🪙 *Your Balance*

Coins: *{user.get('coins', 0)}*

Successful Referrals:
*{user.get('total_referrals', 0)}*
""",
        reply_markup=user_main_menu(),
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=["leaderboard"]
)
def leaderboard_command(message):

    # Use a normal message version
    users = users_col.find(
        {
            "competition_score": {
                "$gt": 0
            }
        }
    ).sort(
        "competition_score",
        -1
    ).limit(5)

    text = "🏆 *TOP 5 REFERRERS*\n\n"

    medals = [
        "🥇",
        "🥈",
        "🥉",
        "4️⃣",
        "5️⃣"
    ]

    found = False

    for index, user in enumerate(
        users
    ):

        found = True

        name = (
            f"@{user['username']}"
            if user.get("username")
            else user.get(
                "first_name",
                "User"
            )
        )

        text += (
            f"{medals[index]} "
            f"{name} — "
            f"*{user.get('competition_score', 0)}*\n"
        )

    if not found:
        text += "No referrals yet."

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# ADMIN /COMPETITION COMMAND
# ============================================================

@bot.message_handler(
    commands=["competition"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def competition_command(message):

    # Send a fresh admin competition menu
    competition = competition_col.find_one({
        "type": "global"
    })

    active = (
        competition and
        competition.get("active")
    )

    markup = InlineKeyboardMarkup()

    if active:

        markup.add(
            InlineKeyboardButton(
                "⏹ Stop",
                callback_data="stop_competition"
            )
        )

    else:

        markup.add(
            InlineKeyboardButton(
                "▶️ Start",
                callback_data="start_competition"
            )
        )

    markup.add(
        InlineKeyboardButton(
            "⏱ Duration",
            callback_data="competition_duration"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🏆 Rewards",
            callback_data="competition_rewards"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔄 Reset Scores",
            callback_data="reset_scores"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "📊 Leaderboard",
            callback_data="leaderboard"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "🏆 *Competition Control*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# BACK BUTTONS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "back_main"
)
def back_main(call):

    bot.answer_callback_query(call.id)

    bot.edit_message_text(
        "🎛 *Main Menu*\n\nChoose an option:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=(
            admin_main_menu()
            if call.from_user.id == ADMIN_ID
            else user_main_menu()
        ),
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data == "admin_main"
)
def admin_main(call):

    bot.answer_callback_query(call.id)

    bot.edit_message_text(
        "👑 *Admin Panel*",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=admin_main_menu(),
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call:
    call.data == "admin_main_menu"
)
def admin_main_menu_callback(call):

    admin_main(call)


# ============================================================
# IGNORE BUTTON
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data == "nothing"
)
def nothing_button(call):

    bot.answer_callback_query(
        call.id
    )


# ============================================================
# CLEAR PENDING PAYMENTS
# ============================================================

def clear_pending_payments():

    now = datetime.now()

    expired = []

    for user_id, data in list(
        pending_payments.items()
    ):

        if (
            now -
            data["time"]
        ).total_seconds() >= 600:

            try:

                bot.send_message(
                    user_id,
                    "⌛ Your payment verification request expired.\n\n"
                    "Please tap *I Have Paid* again.",
                    parse_mode="Markdown"
                )

            except:

                pass

            expired.append(
                user_id
            )

    for user_id in expired:

        pending_payments.pop(
            user_id,
            None
        )


# ============================================================
# AUTO REMOVE EXPIRED USERS
# EXISTING FEATURE
# ============================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find({
        "expiry": {
            "$lte": now
        }
    })

    bot_username = bot.get_me().username

    for user in expired_users:

        try:

            if not user.get(
                "channel_id"
            ):
                continue

            bot.ban_chat_member(
                user["channel_id"],
                user["user_id"]
            )

            bot.unban_chat_member(
                user["channel_id"],
                user["user_id"]
            )

            rejoin_url = (
                f"https://t.me/{bot_username}"
                f"?start={user['channel_id']}"
            )

            markup = InlineKeyboardMarkup()

            markup.add(
                InlineKeyboardButton(
                    "🔁 Re-Join / Renew",
                    url=rejoin_url
                )
            )

            bot.send_message(
                user["user_id"],
                "⚠️ Your subscription has expired.\n\n"
                "Click below to renew.",
                reply_markup=markup
            )

            users_col.delete_one({
                "_id": user["_id"]
            })

        except Exception as e:

            print(
                "EXPIRY ERROR:",
                e
            )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    keep_alive()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        kick_expired_users,
        "interval",
        minutes=1
    )

    scheduler.add_job(
        clear_pending_payments,
        "interval",
        minutes=1
    )

    scheduler.add_job(
        finish_competition,
        "interval",
        minutes=1
    )

    scheduler.start()

    bot.remove_webhook()

    try:

        print(
            "✅ Bot is running..."
        )

        bot.infinity_polling(
            timeout=20,
            long_polling_timeout=10,
            allowed_updates=[
                "message",
                "callback_query"
            ]
        )

    except Exception as e:

        print(
            f"Polling error: {e}"
        )