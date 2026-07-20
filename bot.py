import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running and healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

#--- CONFIGURATION (Environment Variables) ---

BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
channels_col = db['channels']
users_col = db['users']

#--- ADMIN LOGIC ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    text = message.text.split()

# User entry via Deep Link
if len(text) > 1:
    try:
        ch_id = int(text[1])
        ch_data = channels_col.find_one({"channel_id": ch_id})

        if ch_data:
            markup = InlineKeyboardMarkup()

            # Demo URL
            rejoin_url = "https://t.me/+lSW2hYbgrUNkMzFl"
            markup.add(
                InlineKeyboardButton("🔗 ᴅᴇᴍᴏ", url=rejoin_url)
            )

            USD_RATE = 80
            INR_RATE = 2

            # Display Plans
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
                        callback_data=f"select_{ch_id}_{p_time}"
                    )
                )

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

Select a subscription plan below.
""",
                reply_markup=markup,
                parse_mode="Markdown"
            )

            bot.send_message(
                message.chat.id,
                """📌 *Notice*

• Demo access is for testing only.
• Read all instructions before making a payment.
""",
                parse_mode="Markdown"
            )

            return

    except Exception as e:
        print(e)
        
# ==========================
# ADMIN PANEL
# ==========================

# Admin Panel Greeting
if user_id == ADMIN_ID:
    bot.send_message(
        message.chat.id,
        "✅ Admin Panel Active!\n\n"
        "/add - Add/Edit Channel & Prices\n"
        "/channels - Manage Existing Channels"
    )
else:
    bot.send_message(
        message.chat.id,
        "Welcome! To join a channel, please use the link provided by the Admin."
    )


@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_channels(message):

    markup = InlineKeyboardMarkup()

    # Fetch all channels managed by this admin
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

    if count == 0:
        bot.send_message(
            ADMIN_ID,
            "No channels found. Click below to add one.",
            reply_markup=markup
        )
    else:
        bot.send_message(
            ADMIN_ID,
            "Your Managed Channels:",
            reply_markup=markup
        )


@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Please ensure the bot is an Admin in your channel.\n\n"
        "Then FORWARD any message from that channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


# Callback for Add New button
@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def cb_add_new(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        "Please FORWARD any message from your channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


def get_plans(message):

    if message.forward_from_chat:

        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title

        msg = bot.send_message(
            ADMIN_ID,
            f"✅ Channel Detected: {ch_name}\n\n"
            "Enter plans in this format:\n\n"
            "1440:99,43200:199\n\n"
            "Example:\n"
            "1440 = 1 Day\n"
            "43200 = 30 Days",
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
            "❌ Error: Message was not forwarded.\n\nUse /add again."
        )


def finalize_channel(message, ch_id, ch_name):

    try:

        raw_plans = message.text.split(",")

        plans_dict = {}

        for p in raw_plans:
            t, pr = p.strip().split(":")
            plans_dict[t] = pr

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
            f"✅ Setup Successful!\n\n"
            f"Invite Link:\n"
            f"`https://t.me/{bot_username}?start={ch_id}`",
            parse_mode="Markdown"
        )

    except Exception as e:

        print(e)

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\n"
            "Use:\n"
            "`1440:99,43200:199`",
            parse_mode="Markdown"
        )

# ==========================
# USER PAYMENT FLOW
# ==========================

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_"))
def user_pays(call):

    _, ch_id, mins = call.data.split("_")

    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = float(ch_data["plans"][mins])

    USD_RATE = 80
    INR_RATE = 2

    usd_price = price / USD_RATE
    inr_price = price / INR_RATE

    # Plan Name
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
            "📋 Tap the payment details to copy them.\n\n"
            "✅ After payment, tap *I Have Paid*.\n"
            "📷 Then send your payment screenshot to the admin."
        ),
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.send_message(
        call.message.chat.id,
        """📌 *Notice*

• Send the exact payment amount.
• Keep your payment screenshot.
• Tap ✅ *I Have Paid* after payment.
• Then send your screenshot to the admin.
• Verification usually takes a few minutes.

• Contact the admin if you are paying from India.

🙏 Thank you for your purchase!""",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("paid_"))
def admin_notify(call):

    _, ch_id, mins = call.data.split("_")

    user = call.from_user

    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data["plans"][mins]

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "✅ Approve",
            callback_data=f"app_{user.id}_{ch_id}_{mins}"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "❌ Reject",
            callback_data=f"rej_{user.id}"
        )
    )

    bot.send_message(
        ADMIN_ID,
        f"""🔔 *Payment Verification Required!*

👤 User: {user.first_name}
📢 Channel: {ch_data['name']}
💎 Plan: {mins} Minutes
💰 Price: NPR {price}
""",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    u_markup = InlineKeyboardMarkup()

    u_markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    bot.send_message(
        call.message.chat.id,
        "✅ Your payment request has been sent.\n\nPlease wait for the admin to verify your payment. Once approved, you will receive your join link here.",
        reply_markup=u_markup
    )

# ==========================
# APPROVAL & EXPIRY
# ==========================

@bot.callback_query_handler(func=lambda call: call.data.startswith("app_"))
def approve_now(call):

    _, u_id, ch_id, mins = call.data.split("_")

    u_id = int(u_id)
    ch_id = int(ch_id)
    mins = int(mins)

    try:

        expiry_datetime = datetime.now() + timedelta(minutes=mins)
        expiry_ts = int(expiry_datetime.timestamp())

        # Create one-time invite link
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

        bot.send_message(
            u_id,
            f"""🥳 *Payment Approved!*

💎 Subscription: {mins} Minutes

🔗 Join Link:
{link.invite_link}

⚠️ This link and your subscription will expire in {mins} minutes.
""",
            parse_mode="Markdown"
        )

        bot.edit_message_text(
            f"✅ Approved user {u_id} for {mins} minutes.",
            call.message.chat.id,
            call.message.message_id
        )

    except Exception as e:
        bot.send_message(
            ADMIN_ID,
            f"❌ Error:\n{e}"
        )


# ==========================
# AUTO REMOVE EXPIRED USERS
# ==========================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find(
        {"expiry": {"$lte": now}}
    )

    bot_username = bot.get_me().username

    for user in expired_users:

        try:

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
                "Click below to renew your subscription.",
                reply_markup=markup
            )

            users_col.delete_one(
                {"_id": user["_id"]}
            )

        except Exception as e:
            print(e)


# ==========================
# START BOT
# ==========================

if __name__ == "__main__":

    keep_alive()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        kick_expired_users,
        "interval",
        minutes=1
    )

    scheduler.start()

    bot.remove_webhook()

    print("✅ Bot is running...")

    bot.infinity_polling(
        timeout=20,
        long_polling_timeout=10
    )
