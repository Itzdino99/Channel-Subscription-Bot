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
# ==========================
# TEMP PAYMENT STORAGE
# ==========================

pending_payments = {}

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

                USD_RATE = 100
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

    USD_RATE = 100
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
def payment_screenshot_request(call):

    _, ch_id, mins = call.data.split("_")

    user_id = call.from_user.id

    # Prevent duplicate requests
    if user_id in pending_payments:
        bot.answer_callback_query(
            call.id,
            "⚠️ You already have a pending payment verification.",
            show_alert=True
        )
        return

    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
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

Please send your payment screenshot as a *PHOTO*.

⚠️ Do NOT send:
• Screenshot as a file
• Video
• Text message

Once you upload the screenshot, it will automatically be forwarded to the admin for verification.

⏳ Please upload it within 10 minutes.
""",
        parse_mode="Markdown"
    )
  # ==========================
# RECEIVE PAYMENT SCREENSHOT
# ==========================

@bot.message_handler(content_types=['photo'])



# ==========================
# TEXT WHILE WAITING
# ==========================

@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=['text']
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "📷 Please upload your payment screenshot as a PHOTO.",
        parse_mode="Markdown"
    )


# ==========================
# DOCUMENT WHILE WAITING
# ==========================

@bot.message_handler(content_types=['document'])
def document_handler(message):

    if message.from_user.id not in pending_payments:
        return

    bot.reply_to(
        message,
        "❌ Please send the payment screenshot as a PHOTO, not as a document.",
        parse_mode="Markdown"
    )


# ==========================
# PHOTO HANDLER
# ==========================

@bot.message_handler(content_types=['photo'])
def photo_handler(message):
    try:
        user_id = message.from_user.id

        if user_id not in pending_payments:
            return

        payment = pending_payments[user_id]

        # Forward screenshot
        bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        username = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else "No Username"
        )

        # Admin payment details
        bot.send_message(
            ADMIN_ID,
            f"""🔔 *Payment Verification Required!*

👤 *Name:* {message.from_user.first_name}
🆔 *User ID:* `{user_id}`
🌐 *Username:* {username}

📢 *Channel:* {payment.get('channel_name', 'Unknown')}
💎 *Plan:* {payment.get('plan', 'Unknown')}
💰 *Price:* NPR {payment.get('price', '0')}

📷 Screenshot has been forwarded above.
""",
            parse_mode="Markdown"
        )

        # Approve / Reject buttons
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"app_{user_id}_{payment.get('channel_id')}_{payment.get('plan')}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"rej_{user_id}"
            )
        )

        bot.send_message(
            ADMIN_ID,
            "👇 *Select an action:*",
            reply_markup=markup,
            parse_mode="Markdown"
        )

        # User confirmation
        user_markup = InlineKeyboardMarkup()
        user_markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )

        bot.send_message(
            user_id,
            """✅ *Screenshot Uploaded Successfully!*

📷 Your payment screenshot has been forwarded to the admin.

⏳ *Status:* Waiting for admin verification.

🔔 Once your payment is approved, your invite link will be sent here automatically.

🙏 Thank you for your patience!""",
            reply_markup=user_markup,
            parse_mode="Markdown"
        )

        del pending_payments[user_id]

    except Exception as e:
        print(f"PHOTO_HANDLER ERROR: {e}")
        bot.send_message(
            ADMIN_ID,
            f"❌ Photo Handler Error:\n`{e}`",
            parse_mode="Markdown"
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

        # Remove pending payment
        if u_id in pending_payments:
            del pending_payments[u_id]

        # Plan Name
        if mins > 525600:
            plan_name = "💎 Lifetime"
        elif mins >= 1440:
            plan_name = f"📅 {mins // 1440} Days"
        else:
            plan_name = f"⏱ {mins} Minutes"

        bot.send_message(
            u_id,
            f"""🎉 *Payment Approved!*

Your payment has been verified successfully.

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
            f"❌ Error:\n{e}"
        )
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("rej_"))
def reject_payment(call):

    user_id = int(call.data.split("_")[1])

    if user_id in pending_payments:
        del pending_payments[user_id]

    bot.send_message(
        user_id,
        """❌ *Payment Rejected*

Your payment could not be verified.

Please check your payment and submit a new screenshot.

If you believe this is a mistake, contact the admin.
""",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )
# ==========================
# CLEAR PENDING PAYMENTS
# ==========================

def clear_pending_payments():

    now = datetime.now()

    expired = []

    for user_id, data in pending_payments.items():

        if (now - data["time"]).seconds >= 600:

            try:
                bot.send_message(
                    user_id,
                    "⌛ Your payment verification request expired.\n\nPlease tap *I Have Paid* again and upload your screenshot.",
                    parse_mode="Markdown"
                )
            except:
                pass

            expired.append(user_id)

    for user_id in expired:
        del pending_payments[user_id]


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

    scheduler.add_job(
        clear_pending_payments,
        "interval",
        minutes=1
    )

    scheduler.start()

    bot.remove_webhook()

    try:
        print("✅ Bot is running...")
        bot.infinity_polling(
            timeout=20,
            long_polling_timeout=10
        )
    except Exception as e:
        print(f"Polling error: {e}")
