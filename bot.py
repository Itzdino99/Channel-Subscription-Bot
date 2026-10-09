import os
import time
import uuid
import hmac
import hashlib
import secrets
from urllib.parse import parse_qsl, urlencode
import telebot

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)

from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, jsonify, render_template_string, send_file
from io import BytesIO
import mimetypes
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

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000)
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
user_history_col = db["user_history"]
premium_history_col = db["premium_history"]
announcement_col = db["announcements"]
admin_roles_col = db["admin_roles"]
support_tickets_col = db["support_tickets"]
# Temporary delivery-message tracking for Premium invite messages.
# Messages are removed after the user joins the purchased channel(s) or after the TTL.
premium_delivery_col = db["premium_delivery_messages"]
# Admin-configured channels for New User + Milestone notification logs.
referral_notification_channels_col = db["referral_notification_channels"]
# Admin-only safety/monitoring records. These do not replace any existing collections.
safety_events_col = db["safety_events"]
channel_monitor_col = db["channel_monitor"]
notification_channels_col = db["notification_channels"]
member_invite_jobs_col = db["member_invite_jobs"]
forward_unlocks_col = db["forward_unlocks"]
channel_content_stats_col = db["channel_content_stats"]
channel_upload_notifications_col = db["channel_upload_notifications"]
# Rewarded-ad sessions and immutable reward records.
ad_sessions_col = db["ad_sessions"]
ad_watch_history_col = db["ad_watch_history"]
# Admin-created earning tasks and submissions.
tasks_col = db["earning_tasks"]
task_submissions_col = db["task_submissions"]


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
USER_EXTRA = "🪄 Extra Features"
USER_PREMIUM = "🎁 Premium"
USER_BACK = "⬅️ Previous"

ADMIN_ROLES = "👮 Admin Roles"
ADMIN_SUPPORT_TICKETS = "🎟️ Support Tickets"

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
ADMIN_STATISTICS = "📊 Statistics & Reports"
ADMIN_ANNOUNCEMENTS = "📣 Announcement Center"

USER_WALLET = "💳 Wallet"
USER_HISTORY = "🧾 My History"
USER_COLLECTION_STATS = "📚 Collection Stats"
USER_FORWARD_ACCESS = "🔓 Forward Access"
USER_WATCH_AD = "📺 Watch Ad"
USER_TASKS = "🧩 Earn by Tasks"
ADMIN_TASKS = "🧩 Earning Tasks"
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

    # Telegram safety/operational controls. These are conservative defaults and
    # are used only by the admin broadcast/monitoring layer.
    "safety": {
        "enabled": True,
        "broadcast_delay_seconds": 0.35,
        "broadcast_batch_size": 25,
        "broadcast_batch_pause_seconds": 2.0,
        "max_consecutive_failures": 20,
        "auto_pause_on_floodwait": True,
        "monitor_channels": True,
        "monitor_interval_minutes": 15,
        "notify_on_status_change": True,
    },
    "member_invites_enabled": True,
    "forward_unlock_cost": 50,
    "forward_unlock_enabled": True,
    "content_stats_enabled": True,
    "content_notifications_enabled": True,
    "user_coin_report_enabled": True,
    "user_coin_report_interval_hours": 3,
    "rewarded_ads_enabled": False,
    # Rewarded Ad Mini App configuration. Both providers are independently configurable.
    "ad_provider": "GigaPub",
    "gigapub_enabled": True,
    "gigapub_app_id": "8548",
    "adexora_enabled": True,
    "adexora_app_id": "2210",
    "ad_block_id": "8548",
    "ad_miniapp_url": "https://channel-subscription-bot-p85l.onrender.com/ad-app?v=gp8548",
    "ad_reward_coins": 10,
    "ad_cooldown_seconds": 60,
    "ad_daily_limit": 10,
    # 0 = no referral requirement. Admin can set any positive number.
    "ad_required_referrals": 0,
    # Legacy boolean kept for backward compatibility with older settings.
    "ad_require_referral": False,
    "ad_require_force_join": True,
    "ad_session_ttl_seconds": 600,
    "ad_ui_assets": {
        "hero": "",
        "preparing": "",
        "completed": "",
        "requirements": "",
        "cooldown": "",
        "channels": "",
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
    "welcome_coupon_discount": 0,  # legacy setting key; now credits this many welcome coins
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
    "referral_log_channel_id": None,
    "referral_log_channel_name": None,

    # Editable texts
    "welcome_text": (
        "✨ *Welcome!*\n\n"
        "Choose an option below."
    ),

    "force_join_text": (
        "🎉 *Welcome!*\n\n"
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

    # Normalize supported ad providers and migrate legacy settings.
    settings = get_settings()
    provider = str(settings.get("ad_provider", "GigaPub") or "GigaPub").strip().lower()
    patch = {}
    if provider in {"adsgram", "monetag"} or not provider:
        patch["ad_provider"] = "GigaPub"
    if not str(settings.get("gigapub_app_id", "") or "").strip() or str(settings.get("gigapub_app_id")) in {"8510", "11953098"}:
        patch["gigapub_app_id"] = "8548"
    if not str(settings.get("adexora_app_id", "") or "").strip():
        patch["adexora_app_id"] = "2210"
    if not str(settings.get("ad_block_id", "") or "").strip() or str(settings.get("ad_block_id")) in {"8510", "11953098"}:
        patch["ad_block_id"] = "8548"
    if "gigapub_enabled" not in settings: patch["gigapub_enabled"] = True
    if "adexora_enabled" not in settings: patch["adexora_enabled"] = True
    if str(settings.get("ad_miniapp_url", "") or "").strip() == "https://channel-subscription-bot-p85l.onrender.com/ad-app":
        patch["ad_miniapp_url"] = "https://channel-subscription-bot-p85l.onrender.com/ad-app?v=gp8548"
    if patch:
        settings_col.update_one({"_id": "bot_settings"}, {"$set": patch}, upsert=True)

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
                "username": user.username or "",
                "last_seen": datetime.now(ZoneInfo("UTC"))
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

def get_referral_notification_channels():
    """Return all admin-configured notification channels plus legacy channels.

    New channels are stored in referral_notification_channels_col. The older
    single-channel settings are still honored so existing installations do not
    lose their configured logs.
    """
    channels = []
    seen = set()

    try:
        for row in referral_notification_channels_col.find({"enabled": True}).sort("created_at", 1):
            cid = row.get("channel_id")
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            channels.append({
                "channel_id": cid,
                "channel_name": row.get("channel_name") or str(cid),
            })
    except Exception as e:
        print(f"Referral notification channel read error: {e}")

    settings = get_settings()
    # Keep legacy settings working and avoid duplicate sends.
    for cid_key, name_key in (
        ("start_log_channel_id", "start_log_channel_name"),
        ("referral_log_channel_id", "referral_log_channel_name"),
        ("milestone_log_channel_id", "milestone_log_channel_name"),
    ):
        cid = settings.get(cid_key)
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        channels.append({
            "channel_id": cid,
            "channel_name": settings.get(name_key) or str(cid),
        })
    return channels


def add_referral_notification_channel(channel_id, channel_name):
    """Add or re-enable a channel used for new-user and milestone logs."""
    referral_notification_channels_col.update_one(
        {"channel_id": int(channel_id)},
        {
            "$set": {
                "channel_name": channel_name or str(channel_id),
                "enabled": True,
                "updated_at": bot_time_now(),
            },
            "$setOnInsert": {"created_at": bot_time_now()},
        },
        upsert=True,
    )


def send_referral_notification_log(text):
    """Send a referral/new-user/milestone log to every configured channel."""
    sent = 0
    failed = 0
    for row in get_referral_notification_channels():
        try:
            bot.send_message(row["channel_id"], text, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            failed += 1
            print(f"Referral notification log error ({row.get('channel_id')}): {e}")
    return sent, failed


def remove_referral_notification_channel(channel_id):
    return referral_notification_channels_col.update_one(
        {"channel_id": int(channel_id)},
        {"$set": {"enabled": False, "updated_at": bot_time_now()}},
    )


def send_start_log(user_id):
    settings = get_settings()
    user = get_user(user_id)
    if not user:
        return

    username = f"@{user.get('username')}" if user.get('username') else "@notfound"

    referrer_text = "No referrer"
    referrer_id = user.get("referrer_id") or user.get("pending_referrer")
    if referrer_id:
        referrer = get_user(referrer_id)
        if referrer:
            ref_name = user_display_name(referrer)
            referrer_text = f"{ref_name}\n🆔 `{referrer_id}`"
        else:
            referrer_text = f"User ID: `{referrer_id}`"

    text = f"""👤 *New User Started the Bot*

👤 Name: {user.get('first_name', 'User')}
🌐 Username: {username}
🆔 User ID: `{user_id}`

🔗 Referrer:
{referrer_text}

📅 Started: {format_bot_time(bot_time_now())}"""

    # The new admin-managed channel list is authoritative, while legacy
    # start/referral log settings are retained by get_referral_notification_channels().
    send_referral_notification_log(text)
    _send_separate_notification("referral", text)


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

    markup.row(KeyboardButton(USER_TASKS))

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
    # Final requested Main Admin Panel. All legacy admin handlers remain in
    # the source but are not linked from this main keyboard.
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.row(KeyboardButton("👥 Users"), KeyboardButton("📺 Premium & Channels"))
    markup.row(KeyboardButton("🪙 Coins & Referrals"), KeyboardButton("🎁 Rewards"))
    markup.row(KeyboardButton("🎟️ Support Tickets"), KeyboardButton("📢 Broadcast & Announcements"))
    markup.row(KeyboardButton("🎟️ Coupons"), KeyboardButton("🏷️ Offers & Discounts"))
    markup.row(KeyboardButton("⚙️ Bot Settings"), KeyboardButton("📊 Statistics"))
    markup.row(KeyboardButton("📜 Activity Logs"))
    markup.row(KeyboardButton(ADMIN_MODE))
    return markup


def show_admin_panel(chat_id):
    # Single authoritative entry point: the approved final Admin Panel.
    if chat_id != ADMIN_ID:
        return
    final_panel = globals().get("final_show_admin_panel")
    if final_panel:
        return final_panel(chat_id)
    # Import/startup fallback only; this is never used once module loading is complete.
    bot.send_message(chat_id, "👑 *ADMIN PANEL*", reply_markup=admin_menu_markup(), parse_mode="Markdown")


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


def track_premium_delivery_message(user_id, message_id, channel_ids):
    """Track a Premium invite message until the intended user joins all required channels.

    There is intentionally NO time-based expiry here. The delivery message is removed
    only after Telegram confirms that the user has joined the purchased Premium
    channel(s). This keeps the join link available until it is actually used.
    """
    try:
        premium_delivery_col.insert_one({
            "user_id": int(user_id),
            "message_id": int(message_id),
            "channel_ids": [int(cid) for cid in channel_ids],
            "created_at": bot_time_now(),
        })
    except Exception as e:
        print(f"Premium delivery tracking error: {e}")


def cleanup_premium_delivery_messages():
    """Delete Premium delivery messages only after the user has joined every channel."""
    rows = list(premium_delivery_col.find().limit(200))
    for row in rows:
        uid = row.get("user_id")
        message_id = row.get("message_id")
        channel_ids = row.get("channel_ids") or []
        if not uid or not message_id or not channel_ids:
            try:
                premium_delivery_col.delete_one({"_id": row.get("_id")})
            except Exception:
                pass
            continue

        joined_all = all(
            is_user_in_channel(int(cid), int(uid)) for cid in channel_ids
        )

        if joined_all:
            try:
                bot.delete_message(int(uid), int(message_id))
            except Exception:
                pass
            try:
                premium_delivery_col.delete_one({"_id": row.get("_id")})
            except Exception:
                pass


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

    # New users must verify configured force-join channels. Successful verification
    # can issue a one-time, user-bound first-Premium coupon.
    if force_channels_col.count_documents({}) > 0 and not user_data.get("force_join_verified", False):
        show_force_join(message.chat.id)
        return

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

        final_show_admin_panel(message.chat.id) if "final_show_admin_panel" in globals() else show_admin_panel(message.chat.id)
        return

    try:
        show_user_menu(message.chat.id)
    except Exception as e:
        print(f"START MENU ERROR for {user_id}: {e}")
        # Safe fallback keeps /start usable even if an optional advanced setting is malformed.
        try:
            fallback = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            fallback.row(KeyboardButton(USER_PROFILE), KeyboardButton(USER_REFER))
            fallback.row(KeyboardButton(USER_EXTRA), KeyboardButton(USER_PREMIUM))
            fallback.row(KeyboardButton(USER_REFERRALS), KeyboardButton(USER_LEADERBOARD))
            fallback.row(KeyboardButton(USER_CONTACT))
            bot.send_message(message.chat.id, "Choose an option:", reply_markup=fallback)
        except Exception as fallback_error:
            print(f"START FALLBACK ERROR for {user_id}: {fallback_error}")


# =========================================================
# VERIFY REFERRAL
# =========================================================

def issue_welcome_premium_coupon(user_id):
    """Grant a one-time personal welcome coin voucher after force-join verification.

    The configured amount is credited to the user's normal coin balance, so it can
    be spent through the existing Premium redemption flow. It is NOT a discount.
    """
    settings = get_settings()
    amount = max(0, int(settings.get("welcome_coupon_discount", 0) or 0))
    if amount <= 0:
        return None
    uid = int(user_id)
    existing = user_coupon_col.find_one({"user_id": uid, "coupon_type": "welcome_premium_coins"})
    if existing:
        return existing
    code = "WELCOME" + secrets.token_hex(3).upper()
    doc = {
        "user_id": uid, "code": code, "coupon_type": "welcome_premium_coins",
        "coin_amount": amount, "status": "credited", "created_at": datetime.now(),
        "first_premium_only": True, "description": "One-time welcome coins for Premium redemption"
    }
    try:
        # Insert first; the unique record prevents repeat rewards on re-verification.
        result = user_coupon_col.insert_one(doc)
        add_coins(uid, amount)
        try:
            coin_history_col.insert_one({"user_id": uid, "type": "welcome_premium_coins", "amount": amount, "description": "Welcome Premium coin voucher", "created_at": datetime.now(), "code": code})
        except Exception as history_error:
            print(f"Welcome coin history error for {uid}: {history_error}")
        doc["_id"] = result.inserted_id
        return doc
    except Exception as e:
        print(f"Welcome Premium coin voucher error for {uid}: {e}")
        return None


@bot.callback_query_handler(func=lambda call: call.data == "verify_referral")
def verify_referral(call):
    user_id=call.from_user.id
    if is_banned(user_id):
        return bot.answer_callback_query(call.id,"Your account is restricted.",show_alert=True)
    user_data=get_user(user_id)
    if not user_data:
        return bot.answer_callback_query(call.id,"Please start the bot again.",show_alert=True)
    if not check_all_force_channels(user_id):
        return bot.answer_callback_query(call.id,"❌ Join all required channels/groups first.",show_alert=True)

    referrer_id=user_data.get("pending_referrer")
    settings=get_settings()
    if referrer_id is not None and not user_data.get("verified_referral",False):
        reward=int(settings.get("referral_reward",0))
        result=bot_users_col.update_one({"user_id":user_id,"verified_referral":{"$ne":True},"pending_referrer":referrer_id},{"$set":{"verified_referral":True,"referrer_id":referrer_id,"pending_referrer":None,"verified_at":datetime.now(),"force_join_verified":True}})
        if result.modified_count:
            bot_users_col.update_one({"user_id":referrer_id,"banned":{"$ne":True}},{"$inc":{"coins":reward,"referral_count":1}})
            try:
                person_name=user_display_name(get_user(user_id))
                bot.send_message(referrer_id,f"🎉 *New Successful Referral!*\n\n👤 *{person_name}* completed verification.\n\n{settings['coin_emoji']} You received *{reward} {settings['coin_name']}*!",parse_mode="Markdown")
                send_referral_log(user_id,referrer_id,reward,person_name)
                check_and_reward_milestones(referrer_id)
            except Exception as e: print(f"Referral reward notification error: {e}")
    else:
        bot_users_col.update_one({"user_id":user_id},{"$set":{"force_join_verified":True,"force_join_verified_at":datetime.now()}},upsert=True)

    coupon=issue_welcome_premium_coupon(user_id)
    try: bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)
    except Exception: pass
    bot.answer_callback_query(call.id,"Verification successful!")
    success=settings.get("verification_success_text","✅ Verification successful!")
    if coupon:
        success += f"\n\n🎁 *Welcome Premium coins added!*\nYou received *{int(coupon.get('coin_amount', 0))} {settings.get('coin_name', 'KP')}* in your balance. These are regular coins you can use in the existing *Redeem Premium* section.\nVoucher reference: `{coupon['code']}`"
    elif int(settings.get("welcome_coupon_discount",0) or 0)>0:
        success += "\n\nYour welcome coin reward could not be credited. Please contact admin."
    bot.send_message(user_id,success,parse_mode="Markdown")
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

        # Send milestone completion to every Admin-configured notification
        # channel. Legacy single-channel settings remain supported by the
        # helper, so existing configurations continue to receive logs.
        user_data = get_user(user_id)
        milestone_text = f"""🎯 *Milestone Completed*

👤 User: {user_display_name(user_data)}
🆔 ID: `{user_id}`

🎯 Target: *{milestone['target']} Referrals*
{settings['coin_emoji']} Reward: *{reward} {settings['coin_name']}*"""
        send_referral_notification_log(milestone_text)
        _send_separate_notification("milestone", milestone_text)

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
    """Create/continue an in-bot support ticket. Uses the existing ADMIN_ID from env."""
    uid = message.from_user.id
    register_user(message.from_user)
    ticket = support_tickets_col.find_one({
        "user_id": uid,
        "status": "open"
    }, sort=[("created_at", DESCENDING)])

    if ticket:
        bot.send_message(
            uid,
            "🎟️ *Your support ticket is already open.*\n\n"
            "Send your message here and it will be delivered to the admin.\n\n"
            "You can send text, photos or documents.\n\n"
            f"Ticket: `#{str(ticket['_id'])[-6:]}`",
            parse_mode="Markdown"
        )
        return

    ticket = {
        "user_id": uid,
        "name": message.from_user.first_name or "User",
        "username": message.from_user.username or "",
        "status": "open",
        "created_at": bot_time_now(),
        "updated_at": bot_time_now(),
        "messages": []
    }
    result = support_tickets_col.insert_one(ticket)
    ticket_id = result.inserted_id

    text = (
        "🎟️ *Support Ticket Created*\n\n"
        "Please send your message now. You can send text, photos, screenshots or documents.\n\n"
        f"Ticket: `#{str(ticket_id)[-6:]}`\n\n"
        "An admin will reply here."
    )
    bot.send_message(uid, text, parse_mode="Markdown")
    notify_support_admins(ticket_id, "🆕 *New Support Ticket*", message)

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
        # Welcome rewards are credited to the normal coin balance; Premium prices
        # stay unchanged and continue using the existing redemption system.
        display_cost=int(plan["cost"])

        markup.add(
            InlineKeyboardButton(
                f"🎁 {duration} — "
                f"{display_cost} {settings['coin_name']}" + (" 🎟️" if display_cost != int(plan["cost"]) else ""),
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
    # Bulk pricing uses the normal Premium plan cost. Admin only configures
    # the discount rules; there is no separate bulk base price.
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

        expiry_datetime = bot_time_now() + timedelta(
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
        for channel, _invite_link in created_links:
            record_premium_history(
                user_id, "purchased", channel.get("channel_id"),
                channel.get("name", "Premium Channel"),
                plan_id=plan_id,
                duration=format_duration(plan["amount"], plan["unit"]),
                expiry=expiry_datetime.timestamp(),
                source="bulk_redeem",
                details={"cost": bulk_price, "channels": len(created_links)}
            )

        bulk_redeem_selections.pop(user_id, None)

        lines = [
            "🎉 Bulk Premium Redeemed Successfully!",
            "",
            f"🎁 Duration: {format_duration(plan['amount'], plan['unit'])}",
            f"📦 Channels: {len(created_links)}",
            f"💰 Original: {original_price} {settings['coin_name']}",
            f"🏷️ Discount: -{discount_amount} {settings['coin_name']}",
            f"💰 Paid: {bulk_price} {settings['coin_name']}",
            f"⏰ Expires: {format_bot_time(expiry_datetime)}",
            "",
            "🔗 Your Premium channel links:"
        ]

        bulk_markup = InlineKeyboardMarkup(row_width=1)
        for number, (channel, invite_link) in enumerate(created_links, 1):
            lines.extend([
                "",
                f"{number}. {channel.get('name', 'Premium Channel')}",
                invite_link
            ])
            bulk_markup.add(
                InlineKeyboardButton(
                    f"🔗 Join {number}. {channel.get('name', 'Premium Channel')}",
                    url=invite_link
                )
            )

        lines.extend([
            "",
            "⚠️ Each link can only be used once."
        ])

        bot.answer_callback_query(
            call.id,
            "Bulk Premium redeemed successfully!"
        )

        # Plain text avoids Markdown failures caused by channel names.
        delivery_message = bot.send_message(
            user_id,
            "\n".join(lines),
            reply_markup=bulk_markup,
            disable_web_page_preview=True
        )
        track_premium_delivery_message(
            user_id,
            delivery_message.message_id,
            [channel.get("channel_id") for channel, _ in created_links]
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

        # Welcome Premium vouchers credit normal coins at force-join verification.
        # Do not change the plan price here; existing coin redemption remains intact.
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
            bot_time_now()
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
            record_premium_history(
                user_id, "purchased", channel_id,
                channel.get("name", "Premium Channel"),
                plan_id=plan_id,
                duration=format_duration(plan["amount"], plan["unit"]),
                expiry=expiry_datetime.timestamp(),
                source="single_redeem",
                details={"cost": cost}
            )

            join_markup = InlineKeyboardMarkup()
            join_markup.add(
                InlineKeyboardButton(
                    "🔗 Join Premium Channel",
                    url=link.invite_link
                )
            )

            bot.answer_callback_query(
                call.id,
                "Premium redeemed successfully!"
            )

            # Keep this delivery message plain-text. Channel names can contain
            # Markdown characters (for example '_' or '*'), which previously
            # could make Telegram reject the whole message and leave the user
            # without the invite link.
            delivery_text = (
                "🎉 Premium Redeemed Successfully!\n\n"
                f"🎁 Duration: {format_duration(plan['amount'], plan['unit'])}\n"
                f"📢 Channel: {channel.get('name', 'Premium Channel')}\n"
                f"⏰ Expires: {format_bot_time(expiry_datetime)}\n\n"
                "🔗 Join Premium Channel:\n"
                f"{link.invite_link}\n\n"
                "⚠️ This link can only be used once."
            )
            delivery_message = bot.send_message(
                user_id,
                delivery_text,
                reply_markup=join_markup,
                disable_web_page_preview=True
            )
            track_premium_delivery_message(user_id, delivery_message.message_id, [channel_id])

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
    # Legacy admin callbacks are Main-Admin-only. Delegated admins use their
    # explicit permission-aware handlers below, preventing a single assigned
    # permission from unlocking unrelated legacy callback tools.
    return call_or_message.from_user.id == ADMIN_ID


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
    """Open the FINAL requested admin panel."""
    switch_to_admin_mode()
    final_show_admin_panel(message.chat.id) if "final_show_admin_panel" in globals() else show_admin_panel(message.chat.id)


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
    # Legacy entry point kept for compatibility, but it now enters the same
    # authoritative final User Mode used by the new Admin Panel.
    switch_to_user_mode()
    return final_show_user_menu(ADMIN_ID, text="🔄 *User Mode Activated*\n\nYou can now use the normal user panel.") if "final_show_user_menu" in globals() else show_user_menu(ADMIN_ID)


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

    markup.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))

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

    markup.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))

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

    markup.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))

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

    markup.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))

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

    markup.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))

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

    markup.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))

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

    markup.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))

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
        "?? Forward any message from the Premium channel.\n\n"
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
                "username": getattr(chat, "username", None),
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


@bot.callback_query_handler(
    func=lambda c: c.data == "referral:set_log"
)
def set_referral_log_channel(call):
    if not admin_only(call):
        return
    msg = bot.send_message(
        ADMIN_ID,
        "📢 Forward a message from the channel where successful referral events should be logged."
    )
    bot.register_next_step_handler(msg, save_referral_log_channel)
    bot.answer_callback_query(call.id)


def save_referral_log_channel(message):
    if not message.forward_from_chat:
        bot.send_message(ADMIN_ID, "❌ Please forward a channel message.")
        return
    chat = message.forward_from_chat
    update_setting("referral_log_channel_id", chat.id)
    update_setting("referral_log_channel_name", chat.title)
    bot.send_message(
        ADMIN_ID,
        f"✅ Referral log channel set to *{chat.title}*.",
        parse_mode="Markdown"
    )


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
# REFERRAL / NEW USER NOTIFICATION CHANNEL MANAGER
# =========================================================

def referral_notification_channels_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    channels = list(referral_notification_channels_col.find({"enabled": True}).sort("created_at", 1))
    if channels:
        for row in channels:
            cid = row.get("channel_id")
            name = row.get("channel_name") or str(cid)
            markup.add(InlineKeyboardButton(
                f"🗑️ Remove {name}",
                callback_data=f"refnotify:remove:{cid}"
            ))
    markup.add(InlineKeyboardButton("➕ Add Notification Channel", callback_data="refnotify:add"))
    markup.add(InlineKeyboardButton("🔄 Refresh", callback_data="refnotify:menu"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    return markup


def referral_notification_channels_menu(chat_id=ADMIN_ID):
    if chat_id != ADMIN_ID:
        return
    channels = list(referral_notification_channels_col.find({"enabled": True}).sort("created_at", 1))
    lines = [
        "📢 *Referral Notification Channels*",
        "",
        "These Admin-configured channels receive:",
        "• 👤 New User Started the Bot",
        "• 🎯 Milestone Completed",
        "",
    ]
    if channels:
        lines.append("*Configured channels:*")
        for i, row in enumerate(channels, 1):
            lines.append(f"{i}. {row.get('channel_name', 'Channel')} — `{row.get('channel_id')}`")
    else:
        lines.append("No channels added yet.")
    lines.append("")
    lines.append("Forward any message from a channel to the bot to add it.")
    bot.send_message(chat_id, "\n".join(lines), reply_markup=referral_notification_channels_markup(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "refnotify:menu")
def referral_notification_channels_menu_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(
            "📢 *Referral Notification Channels*\n\n"
            "All channels added here receive both *New User Started the Bot* and *Milestone Completed* logs.\n\n"
            "Use ➕ Add Notification Channel and forward a message from the target channel.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=referral_notification_channels_markup(),
            parse_mode="Markdown"
        )
    except Exception:
        referral_notification_channels_menu(ADMIN_ID)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "refnotify:add")
def referral_notification_channel_add_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        ADMIN_ID,
        "📢 *Add Notification Channel*\n\nForward a message from the channel where you want the bot to send:\n"
        "• 👤 New User Started the Bot\n"
        "• 🎯 Milestone Completed",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, save_referral_notification_channel)


def save_referral_notification_channel(message):
    if message.from_user.id != ADMIN_ID:
        return
    chat = getattr(message, "forward_from_chat", None)
    if chat is None:
        origin = getattr(message, "forward_origin", None)
        chat = getattr(origin, "chat", None) if origin else None
    if chat is None:
        bot.send_message(ADMIN_ID, "❌ Please forward a message from a channel/group.")
        return
    add_referral_notification_channel(chat.id, getattr(chat, "title", None) or str(chat.id))
    bot.send_message(ADMIN_ID, f"✅ *{getattr(chat, 'title', str(chat.id))}* added.\n\nNew-user and milestone logs will now be sent there.", parse_mode="Markdown")
    referral_notification_channels_menu(ADMIN_ID)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("refnotify:remove:"))
def referral_notification_channel_remove_callback(call):
    bot.answer_callback_query(call.id)
    try:
        cid = int(call.data.split(":")[-1])
        row = referral_notification_channels_col.find_one({"channel_id": cid, "enabled": True})
        remove_referral_notification_channel(cid)
        name = row.get("channel_name", str(cid)) if row else str(cid)
        bot.send_message(ADMIN_ID, f"🗑️ Removed *{name}* from referral notification channels.", parse_mode="Markdown")
        referral_notification_channels_menu(ADMIN_ID)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Unable to remove channel: {e}")


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

            premium_channel = premium_channels_col.find_one({"channel_id": channel_id}) or {}
            record_premium_history(
                user_id, "expired", channel_id,
                premium_channel.get("name", "Premium Channel"),
                plan_id=user.get("plan_id"),
                duration=user.get("duration"),
                expiry=user.get("expiry"),
                source=user.get("source"),
                details={"expired_at": format_bot_time(bot_time_now())}
            )

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

def record_user_history(user_id, event_type, title, details=None, amount=None, created_at=None):
    """Unified user history. Referral events are intentionally excluded."""
    if event_type == "referral":
        return
    try:
        user_history_col.insert_one({
            "user_id": int(user_id),
            "event_type": str(event_type),
            "title": str(title),
            "details": details or {},
            "amount": amount,
            "created_at": created_at or bot_time_now(),
        })
    except Exception as e:
        print(f"Unified history error: {e}")


def record_premium_history(user_id, event_type, channel_id, channel_name,
                           plan_id=None, duration=None, expiry=None,
                           source=None, details=None):
    try:
        premium_history_col.insert_one({
            "user_id": int(user_id),
            "event_type": event_type,
            "channel_id": int(channel_id) if channel_id is not None else None,
            "channel_name": channel_name or "Premium Channel",
            "plan_id": plan_id,
            "duration": duration,
            "expiry": expiry,
            "source": source,
            "details": details or {},
            "created_at": bot_time_now(),
        })
    except Exception as e:
        print(f"Premium history error: {e}")


def send_referral_log(user_id, referrer_id, reward, person_name):
    settings = get_settings()
    text = f"""🎉 *Successful Referral*

👤 New User: *{person_name}*
🆔 New User ID: `{user_id}`
🔗 Referrer ID: `{referrer_id}`
{settings.get('coin_emoji', '🪙')} Reward: *{reward} {settings.get('coin_name', 'Coins')}*
📅 Completed: {format_bot_time(bot_time_now())}"""
    send_referral_notification_log(text)
    _send_separate_notification("referral", text)


def log_purchase(user_id, source, amount, coin_name, details=None):
    created_at = bot_time_now()
    try:
        purchase_history_col.insert_one({
            "user_id": int(user_id),
            "source": source,
            "amount": int(amount),
            "coin_name": coin_name,
            "details": details or {},
            "created_at": created_at
        })
    except Exception as e:
        print(f"Purchase history error: {e}")
    record_user_history(
        user_id, "purchase",
        f"Premium purchase — {str(source).replace('_', ' ').title()}",
        details=details or {}, amount=int(amount), created_at=created_at
    )


def log_coin_change(user_id, amount, reason, admin_id=None):
    created_at = bot_time_now()
    try:
        coin_history_col.insert_one({
            "user_id": int(user_id),
            "amount": int(amount),
            "reason": reason,
            "admin_id": admin_id,
            "created_at": created_at
        })
    except Exception as e:
        print(f"Coin history error: {e}")
    reason_text = str(reason or "").lower()
    if "referral" not in reason_text and "refer" not in reason_text:
        record_user_history(
            user_id,
            "coin_change",
            f"Coins {'Added' if int(amount) > 0 else 'Deducted'}"
            + (f" by Admin `{admin_id}`" if admin_id else ""),
            details={"reason": reason, "admin_id": admin_id},
            amount=int(amount),
            created_at=created_at
        )


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
        lines.append(f"  ⏰ {format_bot_time(datetime.fromtimestamp(r['expiry'], tz=ZoneInfo('UTC')))}")
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
        text += f"\n• {r.get('channel_name',r.get('channel_id'))} — {format_bot_time(datetime.fromtimestamp(r['expiry'], tz=ZoneInfo('UTC'))) if r.get('expiry') else '-'}"
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
                bot.send_message(uid,f"🔔 Your Premium access expires in approximately *{hours} hour(s)*.\n\n⏰ Expiry: {format_bot_time(datetime.fromtimestamp(r['expiry'], tz=ZoneInfo('UTC')))}",parse_mode="Markdown")
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
        "💳 *My Wallet*\n\n"
        f"🪙 Balance: *{coins} {settings['coin_name']}*\n"
        f"👑 Active Premium: *{active}*\n"
        f"🛒 Purchases: *{purchases}*\n"
        f"💸 Total spent: *{spent} {settings['coin_name']}*\n"
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

    return "\n".join(lines)


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
        bot.send_message(chat_id, "⚠️ History is currently disabled by Admin.")
        return

    settings = get_settings()
    events = []
    for row in user_history_col.find({"user_id": int(user_id)}).sort("created_at", DESCENDING).limit(50):
        if str(row.get("event_type", "")).lower() == "referral":
            continue
        events.append({
            "created_at": row.get("created_at"),
            "title": row.get("title", "Activity"),
            "details": row.get("details") or {},
            "amount": row.get("amount"),
        })

    for row in premium_history_col.find({"user_id": int(user_id)}).sort("created_at", DESCENDING).limit(50):
        kind = row.get("event_type", "premium")
        name = row.get("channel_name") or "Premium Channel"
        duration = row.get("duration") or ""
        labels = {
            "purchased": "💎 Premium purchased",
            "renewed": "🔄 Premium renewed",
            "gift_received": "🎁 Premium gift received",
            "expired": "⏰ Premium expired",
        }
        title = f"{labels.get(kind, '💎 Premium')} — {name}"
        if duration:
            title += f" ({duration})"
        details = dict(row.get("details") or {})
        if row.get("expiry"):
            details["expiry"] = format_bot_time(
                datetime.fromtimestamp(float(row["expiry"]), tz=ZoneInfo("UTC"))
            )
        events.append({
            "created_at": row.get("created_at"),
            "title": title,
            "details": details,
            "amount": None,
        })

    events.sort(key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=ZoneInfo("UTC")), reverse=True)
    if not events:
        bot.send_message(chat_id, "🧾 *My History*\n\nNo history yet.", parse_mode="Markdown")
        return

    lines = ["🧾 *My History*", "", "Referral activity is intentionally not shown here."]
    for i, event in enumerate(events[:50], 1):
        amount = event.get("amount")
        amount_text = f" — {int(amount):+d} {settings.get('coin_name','Coins')}" if amount is not None else ""
        lines.append(f"\n{i}. *{event['title']}*{amount_text}")
        lines.append(f"   🕒 {format_bot_time(event.get('created_at'))}")
        details = event.get("details") or {}
        if details.get("reason"):
            lines.append(f"   📝 {details['reason']}")
        if details.get("expiry"):
            lines.append(f"   ⏰ Expiry: {details['expiry']}")
        if details.get("admin_id"):
            lines.append(f"   👑 Admin: `{details['admin_id']}`")
    bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")


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
        "🔔 *Notification Preferences*\n\n"
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
        f"🎁 *Daily Bonus Claimed!*\n\n"
        f"🪙 Reward: *+{reward} coins*\n"
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
            f"🎁 *Daily Bonus*\n\n"
            f"✅ Already claimed today.\n"
            f"🔥 Current streak: *{streak}*\n"
            f"🪙 Today's reward: *{reward} {settings['coin_name']}*",
            parse_mode="Markdown"
        )
    else:
        next_reward = calculate_daily_reward(streak + 1)
        bot.send_message(
            chat_id,
            f"🎁 *Daily Bonus*\n\n"
            f"🔥 Current streak: *{streak}*\n"
            f"🪙 Next reward: *{next_reward} {settings['coin_name']}*\n\n"
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
        "🎛️ *Feature Control Center*\n\n"
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
    return "\n".join(lines)


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

    return "\n".join(lines)


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
    return "\n".join(lines)


def admin_audit_text(limit=30):
    rows = list(
        audit_log_col.find().sort("created_at", DESCENDING).limit(limit)
    )
    if not rows:
        return "🧾 *Audit Log*\n\nNo administrative audit entries yet."

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
    return "\n".join(lines)


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
        "🎛️ *Control Summary*\n\n"
        f"🟢 Enabled: *{on}*\n"
        f"🔴 Disabled: *{off}*\n"
        f"📦 Bulk max: *{settings.get('bulk_max_channels', 50)}*\n"
        f"🎁 Daily bonus: *{settings.get('daily_bonus', 5)}*\n"
        f"🔥 Streak bonus: *{settings.get('daily_streak_bonus', 2)}*\n"
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
    markup.row(KeyboardButton(ADMIN_SUPPORT_TICKETS))
    markup.row(KeyboardButton(ADMIN_ROLES))
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
        KeyboardButton(USER_WALLET),
        KeyboardButton(USER_HISTORY)
    )
    markup.row(
        KeyboardButton(USER_DAILY),
        KeyboardButton(USER_STATUS)
    )
    markup.row(
        KeyboardButton(USER_NOTIFICATIONS),
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
        f"⚠️ *{feature}* is currently disabled by Admin.\n\n"
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
        "📣 *Announcement Center*\n\n"
        "Send an announcement by using:\n"
        "`/announce your message here`\n\n"
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
        f"📣 Announcement completed.\n\n✅ Sent: {sent}\n❌ Failed: {failed}"
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
            f"📣 Broadcast complete.\n\n✅ Sent: {sent}\n❌ Failed: {failed}"
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
        extra = f"\n📦 Channels: *{details['channels']}*"

    text = (
        "🧾 *Purchase Receipt*\n\n"
        f"🛒 Type: *{source_text}*\n"
        f"💰 Paid: *{amount} {settings['coin_name']}*"
        f"{extra}\n"
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
        "🛒 *New Premium Purchase*\n\n"
        f"👤 User: `{user_id}`\n"
        f"💰 Amount: *{amount} {settings['coin_name']}*\n"
        f"📦 Type: *{source}*\n"
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
# COMBINED ADMIN STATISTICS & REPORTS
# =========================================================

def admin_full_statistics_text():
    """One combined report replacing the separate dashboard/statistics screens."""
    settings = get_settings()
    now = bot_time_now()
    now_ts = now.timestamp()

    total_users = bot_users_col.count_documents({})
    active_premium = users_col.count_documents({"expiry": {"$gt": now_ts}})
    expired_premium = users_col.count_documents({"expiry": {"$lte": now_ts}})
    purchase_count = purchase_history_col.count_documents({})

    total_spent = sum(int(r.get("amount", 0) or 0) for r in purchase_history_col.find({}, {"amount": 1}))
    total_coins = sum(int(r.get("coins", 0) or 0) for r in bot_users_col.find({}, {"coins": 1}))
    referrals = sum(int(r.get("referral_count", 0) or 0) for r in bot_users_col.find({}, {"referral_count": 1}))
    today = now.date().isoformat()
    daily_claims = daily_claims_col.count_documents({"last_claim_date": today})

    top_spenders = list(purchase_history_col.aggregate([
        {"$group": {"_id": "$user_id", "spent": {"$sum": "$amount"}, "orders": {"$sum": 1}}},
        {"$sort": {"spent": -1}},
        {"$limit": 5},
    ]))

    recent_purchases = list(purchase_history_col.find().sort("created_at", DESCENDING).limit(5))
    active_buyers = list(users_col.find({"expiry": {"$gt": now_ts}}).sort("expiry", 1).limit(8))

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
        "📊 *STATISTICS & REPORTS*",
        "",
        "👥 *Users & Premium*",
        f"• Total users: *{total_users}*",
        f"• Active Premium records: *{active_premium}*",
        f"• Expired Premium records: *{expired_premium}*",
        f"• Total referrals: *{referrals}*",
        f"• Today's daily claims: *{daily_claims}*",
        "",
        "💰 *Revenue / Coins*",
        f"• Purchase records: *{purchase_count}*",
        f"• Logged coins spent: *{total_spent}*",
        f"• Current user coin balance: *{total_coins}*",
        "",
        "🏆 *Top Spenders*",
    ]

    if top_spenders:
        for i, row in enumerate(top_spenders, 1):
            lines.append(f"{i}. `{row.get('_id', '-')}` — *{row.get('spent', 0)}* coins ({row.get('orders', 0)} orders)")
    else:
        lines.append("No purchase data yet.")

    lines.extend(["", "🛒 *Recent Purchases*"])
    if recent_purchases:
        for row in recent_purchases:
            lines.append(
                f"• `{row.get('user_id', '-')}` — *{row.get('amount', 0)}* {row.get('coin_name', settings.get('coin_name', 'coins'))} — {str(row.get('source', 'unknown')).replace('_', ' ')}"
            )
    else:
        lines.append("No purchases recorded.")

    lines.extend(["", "👑 *Active Premium Buyers*"])
    if active_buyers:
        for row in active_buyers:
            uid = row.get('user_id', '-')
            channel = premium_channels_col.find_one({"channel_id": row.get("channel_id")})
            cname = channel.get("name", str(row.get("channel_id"))) if channel else str(row.get("channel_id", "-"))
            lines.append(f"• `{uid}` — {cname} — {format_bot_time(row.get('expiry'))}")
    else:
        lines.append("No active Premium buyers.")

    lines.extend(["", "💾 *System Health*"])
    for name, collection in collections.items():
        try:
            lines.append(f"• {name}: {collection.count_documents({})}")
        except Exception:
            lines.append(f"• {name}: unavailable")
    lines.extend([
        f"• Pending payments: *{len(pending_payments)}*",
        f"• Bulk selections: *{len(bulk_redeem_selections)}*",
        f"• Maintenance: *{'ON' if settings.get('maintenance_mode') else 'OFF'}*",
        f"• Timezone: `{settings.get('timezone', 'Asia/Kathmandu')}`",
    ])

    return "\n".join(lines)


def admin_statistics_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("📊 Full Statistics", callback_data="stats:full"),
        InlineKeyboardButton("📈 Analytics", callback_data="stats:analytics"),
    )
    markup.row(
        InlineKeyboardButton("💰 Purchases", callback_data="stats:purchases"),
        InlineKeyboardButton("👑 Premium Buyers", callback_data="stats:buyers"),
    )
    markup.row(
        InlineKeyboardButton("🧾 Audit Log", callback_data="stats:audit"),
        InlineKeyboardButton("💾 System Health", callback_data="stats:health"),
    )
    markup.row(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))
    return markup


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_STATISTICS)
def admin_statistics_handler(message):
    bot.send_message(
        message.chat.id,
        "📊 *Statistics & Reports*\n\nAll admin statistics are grouped here. Choose a report below.",
        reply_markup=admin_statistics_markup(),
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "admin:back")
def admin_back_to_home(call):
    # All final admin inline screens return to the same authoritative Admin
    # Panel. Never route this callback through a legacy admin menu.
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    switch_to_admin_mode()
    final_show_admin_panel(call.message.chat.id) if "final_show_admin_panel" in globals() else show_admin_panel(call.message.chat.id)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("stats:"))
def admin_statistics_callback(call):
    action = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)

    if action == "full":
        text = admin_full_statistics_text()
    elif action == "analytics":
        text = admin_analytics_text()
    elif action == "purchases":
        rows = list(purchase_history_col.find().sort("created_at", DESCENDING).limit(30))
        if not rows:
            text = "💰 *Purchase History*\n\nNo purchase history recorded yet."
        else:
            lines = ["💰 *Purchase History*", ""]
            for r in rows:
                lines.append(
                    f"• `{r.get('user_id', '-')}` | {r.get('amount', 0)} {r.get('coin_name', get_settings().get('coin_name', 'coins'))} | {r.get('source', 'unknown')}"
                )
                lines.append(f"  🕒 {format_bot_time(r.get('created_at'))}")
            text = "\n".join(lines)
    elif action == "buyers":
        now_ts = bot_time_now().timestamp()
        rows = list(users_col.find({"expiry": {"$gt": now_ts}}).sort("expiry", 1).limit(100))
        lines = ["👑 *Active Premium Buyers*", ""]
        if not rows:
            lines.append("No active Premium buyers found.")
        for i, r in enumerate(rows, 1):
            channel = premium_channels_col.find_one({"channel_id": r.get("channel_id")})
            cname = channel.get("name", str(r.get("channel_id"))) if channel else str(r.get("channel_id", "-"))
            lines.append(f"{i}. `{r.get('user_id', '-')}` — {cname} — {format_bot_time(r.get('expiry'))}")
        text = "\n".join(lines)
    elif action == "audit":
        text = admin_audit_text(50)
    elif action == "health":
        text = system_health_text()
    else:
        text = "❌ Unknown report."

    bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=admin_statistics_markup())

# =========================================================
# ADVANCED KEYBOARD PRIORITY ROUTER
# =========================================================
# This router is registered before the generic fallback and is also moved to
# the front of the handler list at startup. It prevents legacy handlers from
# swallowing the newer paginated/advanced keyboard buttons.

def _is_advanced_keyboard_text(message):
    if not getattr(message, "text", None):
        return False
    text = message.text.strip()
    user_labels = {
        globals().get("USER_NEXT"), globals().get("USER_PREVIOUS"),
        globals().get("USER_EARN_EXTRA"), globals().get("USER_DAILY"),
        globals().get("USER_SPIN"), globals().get("USER_VIP"),
        globals().get("USER_DASHBOARD"), globals().get("USER_NOTIFICATIONS"),
        globals().get("USER_DEALS"), globals().get("USER_GIFT"),
        globals().get("USER_RENEW"),
    }
    # Only legacy/pagination admin labels belong here. The approved final
    # Admin Panel labels (including 🎁 Rewards) are handled by final_ui_router.
    # Keeping them out of this matcher prevents this legacy router from
    # swallowing the final panel buttons.
    admin_labels = {
        globals().get("ADMIN_NEXT"), globals().get("ADMIN_PREVIOUS"),
        globals().get("ADMIN_ADVANCED"), globals().get("ADMIN_FEATURES"),
        globals().get("ADMIN_VIP"), globals().get("ADMIN_DEALS"),
        globals().get("ADMIN_GROWTH"), globals().get("ADMIN_SECURITY"),
        globals().get("ADMIN_NOTIFY"), globals().get("ADMIN_RECOVERY"),
        globals().get("ADMIN_CAMPAIGNS"),
        globals().get("ADMIN_BROADCAST_TARGET"), globals().get("ADMIN_GIFTS"),
    }
    return text in (user_labels if message.from_user.id != ADMIN_ID else admin_labels)


@bot.message_handler(func=_is_advanced_keyboard_text)
def advanced_keyboard_priority_router(message):
    text = (message.text or "").strip()
    uid = message.from_user.id

    # USER PAGINATION
    if uid != ADMIN_ID and text == USER_NEXT:
        return user_menu_next(message)
    if uid != ADMIN_ID and text == USER_PREVIOUS:
        return user_menu_previous(message)

    # ADMIN PAGINATION
    if uid == ADMIN_ID and text == ADMIN_NEXT:
        return admin_menu_next(message)
    if uid == ADMIN_ID and text == ADMIN_PREVIOUS:
        return admin_menu_previous(message)

    # Final Admin Panel labels are deliberately NOT handled here. Returning
    # without matching them allows final_ui_router to handle the authoritative
    # panel, including 🎁 Rewards.

    # USER ADVANCED FEATURES
    if uid != ADMIN_ID:
        routes = {
            USER_EARN_EXTRA: user_earn_extra_menu,
            USER_DAILY: advanced_daily_checkin,
            USER_SPIN: advanced_lucky_spin,
            USER_VIP: advanced_vip,
            USER_DASHBOARD: advanced_dashboard,
            USER_NOTIFICATIONS: advanced_notifications,
            USER_DEALS: advanced_flash_deals,
            USER_GIFT: gift_premium_start,
            USER_RENEW: advanced_renew_menu,
        }
        fn = routes.get(text)
        if fn:
            return fn(message)

    # ADMIN ADVANCED FEATURES
    if uid == ADMIN_ID:
        routes = {
            ADMIN_ADVANCED: advanced_admin_hub,
            ADMIN_FEATURES: advanced_feature_menu,
            ADMIN_REWARDS: advanced_rewards_menu,
            ADMIN_VIP: advanced_vip_menu,
            ADMIN_DEALS: advanced_deals_menu,
            ADMIN_GROWTH: advanced_growth_menu,
            ADMIN_SECURITY: advanced_security_menu,
            ADMIN_NOTIFY: advanced_notifications_admin if 'advanced_notifications_admin' in globals() else None,
            ADMIN_RECOVERY: advanced_recovery_menu,
            ADMIN_CAMPAIGNS: advanced_campaign_menu,
            ADMIN_BROADCAST_TARGET: advanced_target_broadcast_menu,
            ADMIN_GIFTS: advanced_gift_manager,
        }
        fn = routes.get(text)
        if fn:
            return fn(message)

    # Not an advanced button: allow normal handlers to process it.
    return

# =========================================================
# UNKNOWN MESSAGE FALLBACK
# =========================================================

@bot.message_handler(
    func=lambda m: (
        bool(m.text)
        and m.content_type == "text"
        and m.text not in {
            USER_DAILY, USER_SPIN, USER_WALLET, USER_VIP, USER_RENEW,
            USER_GIFT, USER_NOTIFICATIONS, USER_DASHBOARD, USER_DEALS, USER_BACK,
            USER_NEXT, USER_PREVIOUS,
            ADMIN_NEXT, ADMIN_PREVIOUS,
            ADMIN_ADVANCED, ADMIN_FEATURES, ADMIN_REWARDS, ADMIN_VIP, ADMIN_DEALS,
            ADMIN_GROWTH, ADMIN_SECURITY, ADMIN_NOTIFY, ADMIN_RECOVERY,
            ADMIN_CAMPAIGNS, ADMIN_BROADCAST_TARGET, ADMIN_GIFTS, ADMIN_STATISTICS,
            ADMIN_CHANNELS, ADMIN_PREMIUM, ADMIN_USERS, ADMIN_COUPONS, ADMIN_SETTINGS,
            ADMIN_MILESTONES, ADMIN_VERIFICATION, ADMIN_USER_SEARCH, ADMIN_COIN_ADD,
            ADMIN_PREMIUM_MANAGE, ADMIN_MAINTENANCE, ADMIN_ANALYTICS, ADMIN_BULK_RULES,
            ADMIN_AUDIT, ADMIN_BACKUP_INFO, ADMIN_ANNOUNCEMENTS, ADMIN_SINGLE_BROADCAST,
            ADMIN_MODE,
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
# ULTIMATE ADVANCED USER GROWTH + ADMIN CONTROL MODULE
# Added without replacing the existing systems.
# =========================================================

# Additional collections (safe because MongoDB creates them lazily)
daily_streak_col = db["daily_streaks"]
lucky_spin_col = db["lucky_spins"]
vip_col = db["vip_levels"]
flash_deals_col = db["flash_deals"]
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
    now = adv_now()
    try:
        user_activity_col.update_one(
            {"user_id": user_id},
            {"$set": {"last_seen": now}, "$inc": {f"actions.{action}": 1}},
            upsert=True,
        )
        # Keep the canonical bot user record synchronized as well.
        bot_users_col.update_one(
            {"user_id": user_id},
            {"$set": {"last_seen": now}},
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
USER_WALLET = "💰 Wallet"  # Legacy handler kept; intentionally hidden from the user keyboard.
USER_VIP = "💎 VIP Status"
USER_RENEW = "🔄 Renew Premium"
USER_GIFT = "🎁 Gift Premium"
USER_EARN_EXTRA = "💰 Earn Extra"
USER_NOTIFICATIONS = "🔔 Notifications"
USER_DASHBOARD = "📊 My Dashboard"
USER_DEALS = "⚡ Flash Deals"
USER_BACK = "🔙 Back"
USER_NEXT = "➡️ Next"
USER_PREVIOUS = "⬅️ Previous"

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
ADMIN_NEXT = "➡️ Admin Next"
ADMIN_PREVIOUS = "⬅️ Admin Previous"

# Keep menu pages in memory. MongoDB remains the source of truth for settings.
_user_menu_pages = {}
_admin_menu_pages = {}


def _paginate_keyboard(buttons, page, per_page=8, next_label=USER_NEXT, previous_label=USER_PREVIOUS):
    """Build a compact 2-column keyboard with exactly six content buttons per page."""
    if not buttons:
        buttons = []

    total_pages = max(1, (len(buttons) + per_page - 1) // per_page)
    page = max(0, min(int(page), total_pages - 1))
    start = page * per_page
    current = buttons[start:start + per_page]

    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for i in range(0, len(current), 2):
        row = [KeyboardButton(x) for x in current[i:i + 2]]
        markup.row(*row)

    navigation = []
    if page > 0:
        navigation.append(KeyboardButton(previous_label))
    if page < total_pages - 1:
        navigation.append(KeyboardButton(next_label))
    if navigation:
        markup.row(*navigation)

    return markup, page, total_pages


def _safe_user_feature_enabled(settings, name, default=True):
    """Read user feature flags without allowing one malformed advanced setting to break /start."""
    try:
        flags = settings.get("feature_flags", {}) or {}
        return bool(flags.get(name, default))
    except Exception:
        return default


def _user_menu_buttons(user_id=None):
    # Final requested USER PANEL. Legacy handlers/features remain in the file,
    # but are intentionally not linked from the main user keyboard.
    return [
        USER_PROFILE, USER_REFER, USER_EXTRA, USER_PREMIUM,
        USER_REFERRALS, USER_LEADERBOARD, USER_CONTACT,
    ]


def ultimate_user_menu_markup(user_id=None, page=None):
    # No pagination on the main User Panel. All requested buttons are visible.
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = _user_menu_buttons(user_id)
    markup.row(KeyboardButton(USER_PROFILE), KeyboardButton(USER_REFER))
    markup.row(KeyboardButton(USER_EXTRA), KeyboardButton(USER_PREMIUM))
    markup.row(KeyboardButton(USER_REFERRALS), KeyboardButton(USER_LEADERBOARD))
    markup.row(KeyboardButton(USER_CONTACT))
    return markup


# Redefinition is intentional: existing handlers call this function at runtime.
def user_menu_markup(user_id=None):
    return ultimate_user_menu_markup(user_id)


def show_user_menu(chat_id):
    """Show the complete requested User Panel on one screen."""
    settings = get_settings()
    markup = ultimate_user_menu_markup(chat_id, 0)
    bot.send_message(
        chat_id,
        settings.get("welcome_text", "Choose an option:"),
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.content_type == "text" and m.from_user.id != ADMIN_ID and m.text == USER_NEXT)
def user_menu_next(message):
    user_id = message.from_user.id
    buttons = _user_menu_buttons(user_id)
    total_pages = max(1, (len(buttons) + 7) // 8)
    current = _user_menu_pages.get(user_id, 0)
    _user_menu_pages[user_id] = min(current + 1, total_pages - 1)
    bot.send_message(
        message.chat.id,
        f"📱 *Menu* — Page {_user_menu_pages[user_id] + 1}/{total_pages}",
        reply_markup=ultimate_user_menu_markup(user_id, _user_menu_pages[user_id]),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.content_type == "text" and m.from_user.id != ADMIN_ID and m.text == USER_PREVIOUS)
def user_menu_previous(message):
    user_id = message.from_user.id
    current = _user_menu_pages.get(user_id, 0)
    _user_menu_pages[user_id] = max(0, current - 1)
    buttons = _user_menu_buttons(user_id)
    total_pages = max(1, (len(buttons) + 7) // 8)
    _user_menu_pages[user_id] = min(_user_menu_pages[user_id], total_pages - 1)
    bot.send_message(
        message.chat.id,
        f"📱 *Menu* — Page {_user_menu_pages[user_id] + 1}/{total_pages}",
        reply_markup=ultimate_user_menu_markup(user_id, _user_menu_pages[user_id]),
        parse_mode="Markdown"
    )


def _admin_menu_buttons():
    return [
        ADMIN_CHANNELS, ADMIN_PREMIUM, ADMIN_USERS, ADMIN_COUPONS, ADMIN_SETTINGS, ADMIN_STATISTICS,
        ADMIN_MILESTONES, ADMIN_VERIFICATION, ADMIN_USER_SEARCH, ADMIN_COIN_ADD, ADMIN_PREMIUM_MANAGE, ADMIN_MAINTENANCE,
        ADMIN_ADVANCED, ADMIN_FEATURES, ADMIN_REWARDS, ADMIN_VIP, ADMIN_DEALS, ADMIN_GROWTH,
        ADMIN_SECURITY, ADMIN_NOTIFY, ADMIN_RECOVERY, ADMIN_CAMPAIGNS, ADMIN_BROADCAST_TARGET, ADMIN_GIFTS,
        ADMIN_ANALYTICS, ADMIN_BULK_RULES, ADMIN_AUDIT, ADMIN_BACKUP_INFO, ADMIN_ANNOUNCEMENTS, ADMIN_SINGLE_BROADCAST, ADMIN_MODE,
    ]


def ultimate_admin_menu_markup(admin_id=None, page=None):
    """Compact admin home with six category buttons per page."""
    if page is None:
        page = _admin_menu_pages.get(admin_id, 0)

    buttons = [
        # Core management
        ADMIN_CHANNELS, ADMIN_PREMIUM, ADMIN_USERS, ADMIN_COUPONS, ADMIN_SETTINGS, ADMIN_STATISTICS,
        # Operations
        ADMIN_MILESTONES, ADMIN_VERIFICATION, ADMIN_USER_SEARCH, ADMIN_COIN_ADD, ADMIN_PREMIUM_MANAGE, ADMIN_MAINTENANCE,
        # Advanced controls
        ADMIN_ADVANCED, ADMIN_FEATURES, ADMIN_REWARDS, ADMIN_VIP, ADMIN_DEALS, ADMIN_GROWTH,
        # Safety / engagement
        ADMIN_SECURITY, ADMIN_NOTIFY, ADMIN_RECOVERY, ADMIN_CAMPAIGNS, ADMIN_BROADCAST_TARGET, ADMIN_GIFTS,
        # Utilities / communication
        ADMIN_ANALYTICS, ADMIN_BULK_RULES, ADMIN_AUDIT, ADMIN_BACKUP_INFO, ADMIN_ANNOUNCEMENTS, ADMIN_SINGLE_BROADCAST, ADMIN_MODE,
    ]

    markup, page, total_pages = _paginate_keyboard(
        buttons,
        page,
        per_page=6,
        next_label=ADMIN_NEXT,
        previous_label=ADMIN_PREVIOUS,
    )
    if admin_id is not None:
        _admin_menu_pages[admin_id] = page
    return markup


def admin_menu_markup():
    return ultimate_admin_menu_markup(ADMIN_ID)


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_NEXT)
def admin_menu_next(message):
    admin_id = message.from_user.id
    current = _admin_menu_pages.get(admin_id, 0)
    total_pages = max(1, (len(_admin_menu_buttons()) + 5) // 6)
    _admin_menu_pages[admin_id] = min(current + 1, total_pages - 1)
    bot.send_message(
        message.chat.id,
        f"👑 *Admin Panel* — Page {_admin_menu_pages[admin_id] + 1}/{total_pages}",
        reply_markup=ultimate_admin_menu_markup(admin_id, _admin_menu_pages[admin_id]),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == ADMIN_PREVIOUS)
def admin_menu_previous(message):
    admin_id = message.from_user.id
    current = _admin_menu_pages.get(admin_id, 0)
    _admin_menu_pages[admin_id] = max(0, current - 1)
    total_pages = max(1, (len(_admin_menu_buttons()) + 5) // 6)
    bot.send_message(
        message.chat.id,
        f"👑 *Admin Panel* — Page {_admin_menu_pages[admin_id] + 1}/{total_pages}",
        reply_markup=ultimate_admin_menu_markup(admin_id, _admin_menu_pages[admin_id]),
        parse_mode="Markdown"
    )


# ------------------------- EARN EXTRA SUBMENU -------------------------
@bot.message_handler(func=lambda m: m.content_type == "text" and m.from_user.id != ADMIN_ID and m.text == USER_EARN_EXTRA)
def user_earn_extra_menu(message):
    settings = get_settings()
    items = []
    if _safe_user_feature_enabled(settings, "daily_checkin", True) and _safe_user_feature_enabled(settings, "daily_bonus", True):
        items.append(USER_DAILY)
    if _safe_user_feature_enabled(settings, "lucky_spin", True):
        items.append(USER_SPIN)
    if _safe_user_feature_enabled(settings, "referrals", True):
        items.append("🔗 Refer & Earn")
    if _safe_user_feature_enabled(settings, "milestones", True):
        items.append("🎯 Milestones")
    if _safe_user_feature_enabled(settings, "coupons", True) or _safe_user_feature_enabled(settings, "personal_coupons", True):
        items.append("🎟️ Claim Coupon")
    if _safe_user_feature_enabled(settings, "flash_deals", True):
        items.append(USER_DEALS)

    markup, _, _ = _paginate_keyboard(items, 0, per_page=8, next_label=USER_NEXT, previous_label=USER_PREVIOUS)
    # Always provide a direct Previous button so the earnings area behaves like
    # a real submenu and users never get trapped here. Avoid duplicates.
    if not items or USER_PREVIOUS not in items:
        markup.row(KeyboardButton(USER_PREVIOUS))
    bot.send_message(message.chat.id, "💰 *Earn Extra*\n\nChoose an earning/reward option:", reply_markup=markup, parse_mode="Markdown")


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
    """Start the real Premium gifting flow (not a coin transfer)."""
    if not final_flag("gift_premium", True):
        bot.send_message(message.chat.id, "🚫 Gift Premium is disabled by Admin.")
        return

    uid = message.from_user.id
    channels = list(premium_channels_col.find().sort("name", 1))
    plans = list(premium_plans_col.find().sort("duration_seconds", 1))
    if not channels or not plans:
        bot.send_message(message.chat.id, "⚠️ Premium gifting is not configured yet.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        markup.add(InlineKeyboardButton(
            f"📢 {ch.get('name', 'Premium Channel')}",
            callback_data=f"giftprem:channel:{ch['channel_id']}"
        ))
    markup.add(InlineKeyboardButton("⬅️ Previous", callback_data="giftprem:back"))
    bot.send_message(message.chat.id, "🎁 *Gift Premium*\n\nChoose the Premium channel you want to gift:", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "giftprem:back")
def gift_premium_back(call):
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    show_user_menu(call.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("giftprem:channel:"))
def gift_premium_channel(call):
    if not final_flag("gift_premium", True):
        bot.answer_callback_query(call.id, "Gift Premium is disabled.", show_alert=True)
        return
    try:
        cid = int(call.data.split(":")[-1])
        plans = list(premium_plans_col.find().sort("duration_seconds", 1))
        if not premium_channels_col.find_one({"channel_id": cid}) or not plans:
            bot.answer_callback_query(call.id, "Premium option unavailable.", show_alert=True)
            return
        markup = InlineKeyboardMarkup(row_width=2)
        for plan in plans:
            markup.add(InlineKeyboardButton(
                f"{format_duration(plan['amount'], plan['unit'])} — {plan['cost']} coins",
                callback_data=f"giftprem:plan:{plan['plan_id']}:{cid}"
            ))
        markup.add(InlineKeyboardButton("⬅️ Back", callback_data="giftprem:back"))
        bot.edit_message_text(
            "🎁 *Gift Premium*\n\nChoose the duration:",
            call.message.chat.id, call.message.message_id,
            reply_markup=markup, parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        print("Gift channel error:", e)
        bot.answer_callback_query(call.id, "Unable to load gift plans.", show_alert=True)


gift_premium_pending = {}


@bot.callback_query_handler(func=lambda c: c.data.startswith("giftprem:plan:"))
def gift_premium_plan(call):
    if not final_flag("gift_premium", True):
        bot.answer_callback_query(call.id, "Gift Premium is disabled.", show_alert=True)
        return
    try:
        _, _, plan_id, cid = call.data.split(":")
        cid = int(cid)
        plan = premium_plans_col.find_one({"plan_id": plan_id})
        channel = premium_channels_col.find_one({"channel_id": cid})
        if not plan or not channel:
            bot.answer_callback_query(call.id, "Premium option unavailable.", show_alert=True)
            return
        gift_premium_pending[call.from_user.id] = {"plan_id": plan_id, "channel_id": cid}
        msg = bot.send_message(
            call.from_user.id,
            "🎁 *Gift Premium*\n\nSend the recipient's Telegram username (example: `@username`).",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, process_premium_gift_recipient)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print("Gift plan error:", e)
        bot.answer_callback_query(call.id, "Unable to start gift.", show_alert=True)


def process_premium_gift_recipient(message):
    sender = message.from_user.id
    state = gift_premium_pending.get(sender)
    if not state:
        bot.send_message(message.chat.id, "❌ Gift session expired. Open 🎁 Gift Premium again.")
        return
    raw_recipient = (message.text or "").strip()
    if not raw_recipient:
        bot.send_message(message.chat.id, "❌ Enter a valid @username or Telegram user ID.")
        return
    recipient = None
    if raw_recipient.lstrip("-").isdigit():
        recipient = bot_users_col.find_one({"user_id": int(raw_recipient)})
    else:
        username = raw_recipient.lstrip("@").strip()
        if username:
            import re
            recipient = bot_users_col.find_one(
                {"username": {"$regex": f"^{re.escape(username)}$", "$options": "i"}}
            )
    if not recipient:
        bot.send_message(message.chat.id, "❌ This user has not started the bot yet. Ask them to start the bot first.")
        gift_premium_pending.pop(sender, None)
        return
    recipient_id = int(recipient["user_id"])
    if recipient_id == sender:
        bot.send_message(message.chat.id, "❌ You cannot gift Premium to yourself.")
        gift_premium_pending.pop(sender, None)
        return
    complete_premium_gift(sender, recipient_id, state["plan_id"], state["channel_id"])
    gift_premium_pending.pop(sender, None)


def complete_premium_gift(sender_id, recipient_id, plan_id, channel_id):
    plan = premium_plans_col.find_one({"plan_id": plan_id})
    channel = premium_channels_col.find_one({"channel_id": channel_id})
    if not plan or not channel:
        bot.send_message(sender_id, "❌ Premium plan/channel is no longer available.")
        return
    cost = int(plan["cost"])
    result = bot_users_col.update_one(
        {"user_id": sender_id, "coins": {"$gte": cost}, "banned": {"$ne": True}},
        {"$inc": {"coins": -cost}}
    )
    if result.modified_count != 1:
        bot.send_message(sender_id, "❌ You don't have enough coins to gift this Premium plan.")
        return
    expiry = bot_time_now() + timedelta(seconds=int(plan["duration_seconds"]))
    try:
        link = bot.create_chat_invite_link(channel_id, member_limit=1, expire_date=int(expiry.timestamp()))
        users_col.update_one(
            {"user_id": recipient_id, "channel_id": channel_id},
            {"$set": {"expiry": expiry.timestamp(), "source": "gift_premium", "plan_id": plan_id, "duration": format_duration(plan["amount"], plan["unit"]) }},
            upsert=True
        )
        log_purchase(sender_id, "gift_premium", cost, get_settings()["coin_name"], {"recipient_id": recipient_id, "channel_id": channel_id, "plan_id": plan_id})
        record_premium_history(
            recipient_id, "gift_received", channel_id,
            channel.get("name", "Premium Channel"),
            plan_id=plan_id,
            duration=format_duration(plan["amount"], plan["unit"]),
            expiry=expiry.timestamp(),
            source="gift_premium",
            details={"gifted_by": sender_id, "cost": cost}
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Join Gifted Premium", url=link.invite_link))
        bot.send_message(sender_id, f"🎁 Premium Gift Sent Successfully!\n\n📢 Channel: {channel.get('name', 'Premium Channel')}\n🎁 Duration: {format_duration(plan['amount'], plan['unit'])}\n💰 Cost: {cost} {get_settings()['coin_name']}\n⏰ Expires: {format_bot_time(expiry)}", reply_markup=markup, disable_web_page_preview=True)

        # Only the recipient's delivery message is auto-deleted. The sender's
        # confirmation is kept as a normal transaction confirmation.
        recipient_message = bot.send_message(recipient_id, f"🎁 You received Premium as a gift!\n\n📢 Channel: {channel.get('name', 'Premium Channel')}\n🎁 Duration: {format_duration(plan['amount'], plan['unit'])}\n⏰ Expires: {format_bot_time(expiry)}\n\n🔗 Join link:\n{link.invite_link}", reply_markup=markup, disable_web_page_preview=True)
        track_premium_delivery_message(recipient_id, recipient_message.message_id, [channel_id])
    except Exception as e:
        add_coins(sender_id, cost)
        log_coin_change(sender_id, cost, "gift_premium_refund")
        print(f"Premium gift error: {e}")
        bot.send_message(sender_id, f"❌ Premium gift could not be completed. Your {cost} coins were refunded.\n\nError: {e}")


# Keep the old coin-gift implementation available in source under a legacy name.
def legacy_process_coin_gift(message, recipient_id):
    try:
        amount = int((message.text or "").strip())
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
    bot.send_message(sender, f"✅ Gift sent!\n\n🪙 {amount} coins were sent successfully.")
    notify_user(recipient_id, f"🎁 You received a gift!\n\n🪙 {amount} coins were sent to you.", "gift")


# ------------------------- SMART RENEWAL MENU -------------------------
@bot.message_handler(func=lambda m: m.content_type == "text" and m.text == USER_RENEW)
def advanced_renew_menu(message):
    """Show active AND recently expired Premium subscriptions available for renewal."""
    if not final_flag("renewal", True):
        bot.send_message(message.chat.id, "🚫 Renewal is disabled by Admin.")
        return
    uid = message.from_user.id
    now_ts = bot_time_now().timestamp()

    # Active subscriptions are stored in users_col. Expired subscriptions are
    # intentionally removed by the expiry worker, so premium_history_col is
    # also used to recover the channels the user previously purchased.
    candidates = {}
    for row in users_col.find({"user_id": uid, "expiry": {"$exists": True}}).sort("expiry", DESCENDING).limit(100):
        cid = row.get("channel_id")
        if cid is not None:
            candidates[int(cid)] = {"channel_id": int(cid), "expiry": float(row.get("expiry", 0) or 0), "source": row.get("source"), "plan_id": row.get("plan_id")}

    for row in premium_history_col.find({"user_id": uid, "event_type": {"$in": ["purchased", "renewed", "gift_received", "expired"]}}).sort("created_at", DESCENDING).limit(200):
        cid = row.get("channel_id")
        if cid is None:
            continue
        cid = int(cid)
        if cid not in candidates:
            candidates[cid] = {
                "channel_id": cid,
                "expiry": float(row.get("expiry", 0) or 0),
                "source": row.get("source"),
                "plan_id": row.get("plan_id"),
            }

    if not candidates:
        bot.send_message(message.chat.id, "🔄 Renew Premium\n\nNo Premium subscription history was found. Open 🎁 Premium → 🎁 Redeem Premium to purchase one first.")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    added = 0
    for cid, row in sorted(candidates.items(), key=lambda x: x[1].get("expiry", 0), reverse=True):
        ch = premium_channels_col.find_one({"channel_id": cid})
        if not ch:
            continue
        exp = float(row.get("expiry", 0) or 0)
        state = "ACTIVE" if exp > now_ts else "EXPIRED"
        markup.add(InlineKeyboardButton(
            f"🔄 {ch.get('name', 'Premium Channel')} — {state}",
            callback_data=f"renewprem:channel:{cid}"
        ))
        added += 1
    markup.add(InlineKeyboardButton("⬅️ Previous", callback_data="renewprem:back"))
    if added == 0:
        bot.send_message(message.chat.id, "⚠️ Your previous Premium channels are no longer configured by Admin.")
        return
    bot.send_message(message.chat.id, "🔄 *Renew Premium*\n\nChoose the Premium channel you want to renew:", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "renewprem:back")
def renew_premium_back(call):
    bot.answer_callback_query(call.id)
    show_user_menu(call.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("renewprem:channel:"))
def renew_premium_channel(call):
    if not final_flag("renewal", True):
        bot.answer_callback_query(call.id, "Renewal is disabled.", show_alert=True)
        return
    try:
        cid = int(call.data.split(":")[-1])
        channel = premium_channels_col.find_one({"channel_id": cid})
        plans = list(premium_plans_col.find().sort("duration_seconds", 1))
        if not channel or not plans:
            bot.answer_callback_query(call.id, "No renewal plans are available.", show_alert=True)
            return
        markup = InlineKeyboardMarkup(row_width=2)
        for plan in plans:
            markup.add(InlineKeyboardButton(
                f"{format_duration(plan['amount'], plan['unit'])} — {plan['cost']} coins",
                callback_data=f"renewprem:plan:{plan['plan_id']}:{cid}"
            ))
        markup.add(InlineKeyboardButton("⬅️ Back", callback_data="renewprem:back"))
        bot.edit_message_text("🔄 *Renew Premium*\n\nChoose how long you want to extend this channel:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    except Exception as e:
        print("Renew channel error:", e)
        bot.answer_callback_query(call.id, "Unable to load renewal plans.", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("renewprem:plan:"))
def renew_premium_plan(call):
    if not final_flag("renewal", True):
        bot.answer_callback_query(call.id, "Renewal is disabled.", show_alert=True)
        return
    uid = call.from_user.id
    cost = 0
    try:
        _, _, plan_id, cid = call.data.split(":")
        cid = int(cid)
        plan = premium_plans_col.find_one({"plan_id": plan_id})
        channel = premium_channels_col.find_one({"channel_id": cid})
        if not plan or not channel:
            bot.answer_callback_query(call.id, "Renewal option unavailable.", show_alert=True)
            return

        cost = int(plan["cost"])
        result = bot_users_col.update_one(
            {"user_id": uid, "coins": {"$gte": cost}, "banned": {"$ne": True}},
            {"$inc": {"coins": -cost}}
        )
        if result.modified_count != 1:
            bot.answer_callback_query(call.id, "❌ You don't have enough coins!", show_alert=True)
            return

        old = users_col.find_one({"user_id": uid, "channel_id": cid}) or {}
        old_exp = float(old.get("expiry", 0) or 0)
        base_ts = max(bot_time_now().timestamp(), old_exp)
        expiry = datetime.fromtimestamp(base_ts, tz=ZoneInfo("UTC")) + timedelta(seconds=int(plan["duration_seconds"]))
        duration_text = format_duration(plan["amount"], plan["unit"])
        already_member = is_user_in_channel(cid, uid)

        users_col.update_one(
            {"user_id": uid, "channel_id": cid},
            {"$set": {
                "expiry": expiry.timestamp(),
                "source": "premium_renewal",
                "plan_id": plan_id,
                "duration": duration_text
            }},
            upsert=True
        )

        settings = get_settings()
        record_premium_history(
            uid, "renewed", cid, channel.get("name", "Premium Channel"),
            plan_id=plan_id, duration=duration_text,
            expiry=expiry.timestamp(), source="premium_renewal",
            details={"cost": cost}
        )
        log_purchase(uid, "premium_renewal", cost, settings["coin_name"], {"channel_id": cid, "plan_id": plan_id})
        bot.answer_callback_query(call.id, "Premium renewed successfully!")

        if already_member:
            bot.send_message(
                uid,
                f"🔄 Premium Renewed Successfully!\n\n"
                f"📢 Channel: {channel.get('name', 'Premium Channel')}\n"
                f"🎁 Added: {duration_text}\n"
                f"⏰ New Expiry: {format_bot_time(expiry)}\n\n"
                "✅ You are already a member, so no new join link is required."
            )
            return

        link = bot.create_chat_invite_link(cid, member_limit=1, expire_date=int(expiry.timestamp()))
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Join Premium Channel", url=link.invite_link))
        delivery_message = bot.send_message(
            uid,
            f"🔄 Premium Renewed Successfully!\n\n"
            f"📢 Channel: {channel.get('name', 'Premium Channel')}\n"
            f"🎁 Added: {duration_text}\n"
            f"⏰ New Expiry: {format_bot_time(expiry)}\n\n"
            f"🔗 New join link:\n{link.invite_link}",
            reply_markup=markup,
            disable_web_page_preview=True
        )
        track_premium_delivery_message(uid, delivery_message.message_id, [cid])

    except Exception as e:
        if cost > 0:
            try:
                add_coins(uid, cost)
                log_coin_change(uid, cost, "renewal_refund")
            except Exception:
                pass
        print(f"Renew plan callback error: {e}")
        bot.answer_callback_query(call.id, "❌ Renewal failed. Coins refunded.", show_alert=True)


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
        # Automatically disable expired referral campaigns.
        referral_campaign_col.update_many({"enabled": True, "end_at": {"$lt": now}}, {"$set": {"enabled": False, "auto_disabled_at": now}})
    except Exception as e:
        print("Advanced maintenance error:", e)


# ------------------------- ACTIVITY TRACKING -------------------------
@bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID, content_types=["text"])
def advanced_activity_tracker(message):
    # This handler is deliberately placed last so existing specific handlers win.
    try:
        register_user(message.from_user)
        track_activity(message.from_user.id, "message")
    except Exception:
        pass

# =========================================================
# SUPPORT TICKETS + DELEGATED ADMIN ROLES
# =========================================================

ADMIN_PERMISSION_LABELS = {
    "users": "👥 Users",
    "premium": "📺 Premium & Channels",
    "coins": "🪙 Coins & Referrals",
    "coupons": "🎟️ Coupons",
    "broadcast": "📢 Broadcast",
    "statistics": "📊 Statistics",
    "support": "🎟️ Support Tickets",
    "announcements": "📣 Announcements",
}

_admin_ticket_waiting = {}
_admin_role_waiting = {}


def get_admin_role(user_id):
    if user_id == ADMIN_ID:
        return {"user_id": user_id, "role_name": "Main Admin", "permissions": list(ADMIN_PERMISSION_LABELS.keys()), "active": True}
    row = admin_roles_col.find_one({"user_id": user_id, "active": True})
    if not row:
        return None
    expires = row.get("expires_at")
    if expires:
        try:
            if isinstance(expires, datetime):
                exp_ts = expires.timestamp()
            else:
                exp_ts = float(expires)
            if exp_ts <= bot_time_now().timestamp():
                admin_roles_col.update_one({"_id": row["_id"]}, {"$set": {"active": False}})
                return None
        except Exception:
            pass
    return row


def is_any_admin(user_id):
    return user_id == ADMIN_ID or get_admin_role(user_id) is not None


def admin_has_permission(user_id, permission):
    if user_id == ADMIN_ID:
        return True
    role = get_admin_role(user_id)
    return bool(role and permission in (role.get("permissions") or []))


def admin_ids_for_permission(permission):
    ids = [ADMIN_ID]
    for row in admin_roles_col.find({"active": True, "permissions": permission}, {"user_id": 1}):
        uid = row.get("user_id")
        if uid and uid not in ids and get_admin_role(uid):
            ids.append(uid)
    return ids


def notify_support_admins(ticket_id, title, source_message=None):
    for aid in admin_ids_for_permission("support"):
        try:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("💬 Reply", callback_data=f"ticket:reply:{ticket_id}"))
            markup.add(InlineKeyboardButton("🔒 Close", callback_data=f"ticket:close:{ticket_id}"))
            if source_message is not None:
                bot.send_message(
                    aid,
                    f"{title}\n\n👤 {source_message.from_user.first_name or 'User'}\\n🆔 `{source_message.from_user.id}`\\n\\nTicket: `#{str(ticket_id)[-6:]}`",
                    parse_mode="Markdown",
                    reply_markup=markup
                )
            else:
                bot.send_message(aid, f"{title}\\n\\nTicket: `#{str(ticket_id)[-6:]}`", parse_mode="Markdown", reply_markup=markup)
        except Exception:
            pass


def _ticket_id_text(ticket):
    return str(ticket.get("_id", ""))[-6:]


@bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID and m.content_type in {"text", "photo", "document", "video", "audio", "voice"})
def support_ticket_user_router(message):
    # Manual task proof takes precedence over support-ticket forwarding.
    if message.from_user.id != ADMIN_ID and message.from_user.id in globals().get("task_submission_states", {}):
        handler = globals().get("task_submission_message_router")
        if handler:
            return handler(message)
    # Do not intercept any current User Panel button. Other messages are sent to the open ticket.
    panel_labels = {USER_PROFILE, USER_REFER, USER_EXTRA, USER_PREMIUM, USER_REFERRALS, USER_LEADERBOARD, USER_CONTACT,
                    USER_DAILY, USER_COUPON, USER_MILESTONES, USER_ANNOUNCEMENTS, USER_FEEDBACK, USER_TASKS,
                    USER_REDEEM, USER_GIFT, USER_RENEW, USER_HISTORY, USER_COLLECTION_STATS, USER_FORWARD_ACCESS, USER_WATCH_AD, USER_BACK}
    if message.content_type == "text" and (message.text or "").strip() in panel_labels:
        return
    ticket = support_tickets_col.find_one({"user_id": message.from_user.id, "status": "open"}, sort=[("created_at", DESCENDING)])
    if not ticket:
        return
    support_ticket_receive(message)


def support_ticket_receive(message):
    uid = message.from_user.id
    ticket = support_tickets_col.find_one({"user_id": uid, "status": "open"}, sort=[("created_at", DESCENDING)])
    if not ticket:
        return False
    entry = {
        "from": "user",
        "user_id": uid,
        "content_type": message.content_type,
        "message_id": message.message_id,
        "created_at": bot_time_now(),
        "text": message.text or message.caption or "",
    }
    support_tickets_col.update_one(
        {"_id": ticket["_id"]},
        {"$push": {"messages": entry}, "$set": {"updated_at": bot_time_now()}}
    )
    for aid in admin_ids_for_permission("support"):
        try:
            bot.send_message(aid, f"🎟️ *Ticket #{_ticket_id_text(ticket)}*\n👤 `{uid}` sent a new {message.content_type}.", parse_mode="Markdown")
            bot.copy_message(aid, message.chat.id, message.message_id)
        except Exception:
            pass
    bot.send_message(uid, "✅ Your message has been sent to the support admin.")
    return True


def support_ticket_admin_reply(message):
    aid = message.from_user.id
    ticket_id = _admin_ticket_waiting.pop(aid, None)
    if not ticket_id or not admin_has_permission(aid, "support"):
        return
    try:
        from bson import ObjectId
        ticket = support_tickets_col.find_one({"_id": ObjectId(ticket_id), "status": "open"})
    except Exception:
        ticket = None
    if not ticket:
        bot.send_message(aid, "❌ Ticket not found or already closed.")
        return
    entry = {"from": "admin", "admin_id": aid, "content_type": message.content_type, "message_id": message.message_id, "created_at": bot_time_now(), "text": message.text or message.caption or ""}
    support_tickets_col.update_one({"_id": ticket["_id"]}, {"$push": {"messages": entry}, "$set": {"updated_at": bot_time_now()}})
    try:
        bot.send_message(ticket["user_id"], "📞 *Admin Support Reply:*", parse_mode="Markdown")
        bot.copy_message(ticket["user_id"], message.chat.id, message.message_id)
        bot.send_message(aid, "✅ Reply sent.")
    except Exception as e:
        bot.send_message(aid, f"❌ Could not send reply: {e}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("ticket:reply:"))
def ticket_reply_callback(call):
    aid = call.from_user.id
    if not admin_has_permission(aid, "support"):
        bot.answer_callback_query(call.id, "You don't have Support Ticket permission.", show_alert=True)
        return
    ticket_id = call.data.split(":", 2)[2]
    _admin_ticket_waiting[aid] = ticket_id
    bot.answer_callback_query(call.id)
    msg = bot.send_message(aid, f"💬 Send your reply for ticket `#{ticket_id[-6:]}`.\nYou may send text, a photo or a document.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, support_ticket_admin_reply)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ticket:close:"))
def ticket_close_callback(call):
    aid = call.from_user.id
    if not admin_has_permission(aid, "support"):
        bot.answer_callback_query(call.id, "No permission.", show_alert=True)
        return
    ticket_id = call.data.split(":", 2)[2]
    try:
        from bson import ObjectId
        result = support_tickets_col.update_one({"_id": ObjectId(ticket_id), "status": "open"}, {"$set": {"status": "closed", "closed_at": bot_time_now(), "closed_by": aid}})
        if result.modified_count:
            ticket = support_tickets_col.find_one({"_id": ObjectId(ticket_id)})
            if ticket:
                bot.send_message(ticket["user_id"], "🔒 Your support ticket has been closed. If you need help again, use 📞 Contact Admin.")
            bot.answer_callback_query(call.id, "Ticket closed.")
        else:
            bot.answer_callback_query(call.id, "Ticket already closed.", show_alert=True)
    except Exception:
        bot.answer_callback_query(call.id, "Invalid ticket.", show_alert=True)


def delegated_admin_keyboard(user_id):
    role = get_admin_role(user_id) or {}
    permissions = role.get("permissions", [])
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    labels = [(p, ADMIN_PERMISSION_LABELS[p]) for p in permissions if p in ADMIN_PERMISSION_LABELS]
    for i in range(0, len(labels), 2):
        markup.row(*[KeyboardButton(label) for _, label in labels[i:i+2]])
    markup.row(KeyboardButton("🔄 Refresh Admin Panel"))
    return markup


def show_delegated_admin_panel(chat_id):
    role = get_admin_role(chat_id)
    if not role:
        return False
    perms = [ADMIN_PERMISSION_LABELS[p] for p in role.get("permissions", []) if p in ADMIN_PERMISSION_LABELS]
    bot.send_message(chat_id, "👮 *Delegated Admin Panel*\n\nRole: *%s*\\n\\nYou can access:\\n%s" % (role.get("role_name", "Admin"), "\n".join("• "+x for x in perms) if perms else "• No permissions assigned."), reply_markup=delegated_admin_keyboard(chat_id), parse_mode="Markdown")
    return True


@bot.message_handler(commands=["admin"] , content_types=["text"])
def delegated_admin_command(message):
    if message.from_user.id == ADMIN_ID:
        return
    show_delegated_admin_panel(message.chat.id)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.from_user.id != ADMIN_ID and m.text == "🔄 Refresh Admin Panel")
def delegated_admin_refresh(message):
    show_delegated_admin_panel(message.chat.id)


@bot.message_handler(func=lambda m: m.content_type == "text" and m.from_user.id != ADMIN_ID and m.text in ADMIN_PERMISSION_LABELS.values())
def delegated_admin_feature(message):
    uid = message.from_user.id
    role = get_admin_role(uid)
    if not role:
        return
    permission = next((p for p, label in ADMIN_PERMISSION_LABELS.items() if label == message.text), None)
    if not permission or not admin_has_permission(uid, permission):
        return
    if permission == "support":
        open_tickets = list(support_tickets_col.find({"status": "open"}).sort("created_at", DESCENDING).limit(20))
        if not open_tickets:
            bot.send_message(uid, "🎟️ No open support tickets.")
            return
        markup = InlineKeyboardMarkup(row_width=1)
        for t in open_tickets:
            markup.add(InlineKeyboardButton(f"🎟️ #{_ticket_id_text(t)} — {t.get('name','User')}", callback_data=f"ticket:reply:{t['_id']}"))
        bot.send_message(uid, "🎟️ *Open Support Tickets*", reply_markup=markup, parse_mode="Markdown")
    elif permission == "statistics":
        bot.send_message(uid, admin_full_statistics_text(), parse_mode="Markdown")
    elif permission == "users":
        count = bot_users_col.count_documents({})
        bot.send_message(uid, f"👥 *Users*\n\nTotal users: *{count}*", parse_mode="Markdown")
    elif permission == "coupons":
        bot.send_message(uid, f"🎟️ Coupons: *{coupons_col.count_documents({})}*", parse_mode="Markdown")
    elif permission == "broadcast":
        msg = bot.send_message(uid, "📢 Send the message to broadcast. This will use your assigned Broadcast permission.")
        bot.register_next_step_handler(msg, delegated_broadcast_receive)
    elif permission == "announcements":
        msg = bot.send_message(uid, "📣 Send the announcement text.")
        bot.register_next_step_handler(msg, delegated_announcement_receive)
    elif permission == "coins":
        msg = bot.send_message(uid, "🪙 Send: `USER_ID AMOUNT`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, delegated_coin_receive)
    elif permission == "premium":
        rows = list(premium_channels_col.find().limit(30))
        text = "📺 *Premium Channels*\\n\\n" + ("\\n".join(f"• {r.get('name','Premium Channel')}" for r in rows) if rows else "No channels configured.")
        bot.send_message(uid, text, parse_mode="Markdown")


def delegated_broadcast_receive(message):
    uid = message.from_user.id
    if not admin_has_permission(uid, "broadcast"):
        return
    sent = failed = 0
    for row in bot_users_col.find({"banned": {"$ne": True}}, {"user_id": 1}):
        try:
            bot.copy_message(row["user_id"], message.chat.id, message.message_id)
            sent += 1
        except Exception:
            failed += 1
    bot.send_message(uid, f"📢 Broadcast complete.\n\n✅ Sent: {sent}\\n❌ Failed: {failed}")


def delegated_announcement_receive(message):
    uid = message.from_user.id
    if not admin_has_permission(uid, "announcements"):
        return
    sent, failed = send_announcement_text(message.text or "")
    bot.send_message(uid, f"📣 Announcement complete.\n\n✅ Sent: {sent}\\n❌ Failed: {failed}")


def delegated_coin_receive(message):
    uid = message.from_user.id
    if not admin_has_permission(uid, "coins"):
        return
    try:
        target, amount = message.text.split()[:2]
        target, amount = int(target), int(amount)
        if amount == 0 or not get_user(target):
            raise ValueError
        bot_users_col.update_one({"user_id": target}, {"$inc": {"coins": amount}})
        log_coin_change(target, amount, "delegated_admin_adjustment", uid)
        bot.send_message(uid, f"✅ Coins updated for `{target}`.", parse_mode="Markdown")
    except Exception:
        bot.send_message(uid, "❌ Invalid format. Use: USER_ID AMOUNT")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_SUPPORT_TICKETS)
def admin_support_tickets_menu(message):
    tickets = list(support_tickets_col.find({"status": "open"}).sort("created_at", DESCENDING).limit(30))
    if not tickets:
        bot.send_message(ADMIN_ID, "🎟️ No open support tickets.")
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for ticket in tickets:
        markup.add(InlineKeyboardButton(
            f"🎟️ #{_ticket_id_text(ticket)} — {ticket.get('name','User')}",
            callback_data=f"ticket:reply:{ticket['_id']}"
        ))
    bot.send_message(ADMIN_ID, "🎟️ *Open Support Tickets*\n\nSelect a ticket to reply.", reply_markup=markup, parse_mode="Markdown")



# Main-admin-only role manager
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == ADMIN_ROLES)
def admin_roles_menu(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("➕ Add Admin", callback_data="roles:add"), InlineKeyboardButton("📋 Admin List", callback_data="roles:list"))
    markup.row(InlineKeyboardButton("🗑️ Remove Admin", callback_data="roles:remove"), InlineKeyboardButton("✏️ Edit Permissions", callback_data="roles:edit"))
    markup.row(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    bot.send_message(ADMIN_ID, "👮 *Admin Roles & Permissions*\\n\\nOnly the Main Admin can add, remove or edit delegated admins.", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "roles:add")
def roles_add(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "➕ Send admin details in 4 lines:\\n\\nUSER_ID\\nROLE NAME\\nPERMISSIONS (comma separated)\\nDAYS (0 = unlimited)\\n\\nAvailable permissions: " + ", ".join(ADMIN_PERMISSION_LABELS.keys()))
    bot.register_next_step_handler(msg, roles_add_receive)


def roles_add_receive(message):
    if message.from_user.id != ADMIN_ID:
        return
    lines = [x.strip() for x in (message.text or "").splitlines() if x.strip()]
    try:
        uid = int(lines[0])
        role_name = lines[1]
        permissions = [x.strip() for x in lines[2].split(",") if x.strip() in ADMIN_PERMISSION_LABELS]
        days = int(lines[3]) if len(lines) > 3 else 0
        if uid == ADMIN_ID or not permissions:
            raise ValueError
        expires_at = None if days <= 0 else bot_time_now() + timedelta(days=days)
        admin_roles_col.update_one({"user_id": uid}, {"$set": {"user_id": uid, "role_name": role_name, "permissions": permissions, "active": True, "expires_at": expires_at, "created_by": ADMIN_ID, "created_at": bot_time_now(), "updated_at": bot_time_now()}}, upsert=True)
        bot.send_message(ADMIN_ID, f"✅ Admin role saved for `{uid}`.\nRole: *{role_name}*\\nPermissions: {', '.join(permissions)}", parse_mode="Markdown")
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid format. Please send the 4 lines exactly as requested.")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "roles:list")
def roles_list(call):
    bot.answer_callback_query(call.id)
    rows = list(admin_roles_col.find().sort("created_at", DESCENDING))
    if not rows:
        bot.send_message(ADMIN_ID, "👮 No delegated admins added yet.")
        return
    lines = ["👮 *Delegated Admin List*", ""]
    for r in rows:
        exp = r.get("expires_at")
        exp_text = "Unlimited" if not exp else format_bot_time(exp)
        lines.append(f"👤 `{r.get('user_id')}` — *{r.get('role_name','Admin')}*")
        lines.append(f"🔐 {', '.join(r.get('permissions', []))}")
        lines.append(f"⏰ {exp_text} | {'ON' if r.get('active') else 'OFF'}")
        lines.append("")
    bot.send_message(ADMIN_ID, "\\n".join(lines), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "roles:remove")
def roles_remove(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "🗑️ Send the delegated admin User ID to remove.")
    bot.register_next_step_handler(msg, roles_remove_receive)


def roles_remove_receive(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(message.text.strip())
        result = admin_roles_col.update_one({"user_id": uid}, {"$set": {"active": False, "removed_at": bot_time_now(), "removed_by": ADMIN_ID}})
        bot.send_message(ADMIN_ID, "✅ Admin access removed." if result.modified_count else "❌ Delegated admin not found.")
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid User ID.")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "roles:edit")
def roles_edit(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "✏️ Send 3 lines:\nUSER_ID\\nPERMISSIONS (comma separated)\\nDAYS (0 = unlimited)")
    bot.register_next_step_handler(msg, roles_edit_receive)


def roles_edit_receive(message):
    if message.from_user.id != ADMIN_ID:
        return
    lines = [x.strip() for x in (message.text or "").splitlines() if x.strip()]
    try:
        uid = int(lines[0])
        permissions = [x.strip() for x in lines[1].split(",") if x.strip() in ADMIN_PERMISSION_LABELS]
        days = int(lines[2]) if len(lines) > 2 else 0
        if not permissions:
            raise ValueError
        expires_at = None if days <= 0 else bot_time_now() + timedelta(days=days)
        result = admin_roles_col.update_one({"user_id": uid}, {"$set": {"permissions": permissions, "expires_at": expires_at, "active": True, "updated_at": bot_time_now()}})
        bot.send_message(ADMIN_ID, "✅ Permissions updated." if result.modified_count else "❌ Delegated admin not found.")
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid format.")


# Capture user ticket media/text before the generic user fallback.
@bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID and m.content_type in ("text", "photo", "document") and support_tickets_col.find_one({"user_id": m.from_user.id, "status": "open"}) is not None)
def support_ticket_user_router(message):
    if message.content_type == "text" and (message.text or "").strip() in {USER_PROFILE, USER_REFER, USER_EXTRA, USER_PREMIUM, USER_REFERRALS, USER_LEADERBOARD, USER_CONTACT, USER_DAILY, USER_COUPON, USER_MILESTONES, USER_ANNOUNCEMENTS, USER_FEEDBACK, USER_REDEEM, USER_GIFT, USER_RENEW, USER_WATCH_AD, USER_HISTORY, USER_BACK}:
        return
    if support_ticket_receive(message):
        return


# =========================================================
# START BOT
# =========================================================


# =========================================================
# FINAL UI / FEATURE-CONTROL PATCH
# =========================================================
# This final layer wires the existing advanced systems into one predictable
# user/admin keyboard architecture.  It intentionally does not replace the
# original payment, referral, coupon, channel, or premium logic.

# Extra user destinations requested in the final layout.
USER_REWARDS = "🎁 Rewards"
USER_ANNOUNCEMENTS = "📢 Announcements"
USER_EXPIRY_INFO = "⏰ Expiry Info"
USER_ACHIEVEMENTS = "🏅 Achievements"
USER_REFERRAL_CAMPAIGNS = "🔗 Referral Campaigns"
USER_MY_REWARDS = "🎁 My Rewards"

# Core features are now also controlled from the same admin Feature Control
# screen. Missing flags default to ON for backwards compatibility.
FINAL_FEATURE_FLAGS = {
    "profile": True,
    "premium_redeem": True,
    "referrals": True,
    "gift_premium": True,
    "daily_checkin": True,
    "earn_extra": True,
    "coupons": True,
    "my_referrals": True,
    "vip_levels": True,
    "rewards": True,
    "milestones": True,
    "leaderboard": True,
    "flash_deals": True,
    "smart_notifications": True,
    "purchase_history": True,
    "announcements": True,
    "renewal": True,
    "expiry_info": True,
    "how_it_works": True,
    "help_rules": True,
    "feedback": True,
    "contact_admin": True,
    "lucky_spin": True,
    "achievements": True,
    "referral_campaigns": True,
    "my_rewards": True,
    "bulk_redeem": True,
    "single_redeem": True,
    "streak_rewards": True,
    "personal_coupons": True,
    "notifications": True,
    "extra_features": True,
    "premium_menu": True,
    "collection_stats": True,
    "rewarded_ads": True,
}


def final_flag(name, default=True):
    try:
        flags = get_settings().get("feature_flags", {}) or {}
        return bool(flags.get(name, FINAL_FEATURE_FLAGS.get(name, default)))
    except Exception:
        return default


def final_set_flag(name, value):
    flags = dict(get_settings().get("feature_flags", {}) or {})
    flags[name] = bool(value)
    update_setting("feature_flags", flags)


# Merge all final flags into the persistent settings once the DB is available.
def ensure_final_feature_flags():
    try:
        flags = dict(get_settings().get("feature_flags", {}) or {})
        changed = False
        for k, v in FINAL_FEATURE_FLAGS.items():
            if k not in flags:
                flags[k] = v
                changed = True
        if changed:
            update_setting("feature_flags", flags)
    except Exception as e:
        print(f"Feature flag initialization warning: {e}")


# Exact final user layout requested by the user. Old handlers/features remain in
# the file, but they are not linked from this new keyboard unless explicitly routed.
def final_user_pages(user_id):
    ensure_final_feature_flags()
    return [[
        USER_PROFILE, USER_REFER,
        USER_EXTRA, USER_PREMIUM, USER_WATCH_AD,
        USER_REFERRALS, USER_LEADERBOARD,
        USER_CONTACT,
    ]]


def final_user_keyboard(user_id, page=0):
    # Feature flags control visibility as well as handler access. With the
    # default settings ON, this is exactly the requested main layout.
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    rows = []
    if final_flag("profile", True):
        rows.append([USER_PROFILE])
    if final_flag("referrals", True):
        rows[-1].append(USER_REFER) if rows and len(rows[-1]) == 1 else rows.append([USER_REFER])
    if final_flag("extra_features", True):
        rows.append([USER_EXTRA])
    rows.append([USER_TASKS])
    if final_flag("premium_menu", True):
        rows[-1].append(USER_PREMIUM) if rows and len(rows[-1]) == 1 else rows.append([USER_PREMIUM])
    if final_flag("rewarded_ads", True) and _feature_setting("rewarded_ads_enabled", False):
        rows.append([USER_WATCH_AD])
    if final_flag("my_referrals", True):
        rows.append([USER_REFERRALS])
    if final_flag("leaderboard", True):
        rows[-1].append(USER_LEADERBOARD) if rows and len(rows[-1]) == 1 else rows.append([USER_LEADERBOARD])
    if final_flag("contact_admin", True):
        rows.append([USER_CONTACT])

    # Only the main configured admin gets the private switch-back button.
    # It is intentionally not exposed to normal users.
    if user_id == ADMIN_ID and not is_admin_mode(ADMIN_ID):
        rows.append([ADMIN_PANEL_BUTTON])

    for row in rows:
        markup.row(*(KeyboardButton(x) for x in row))
    return markup, 0, 1


def final_show_user_menu(chat_id, page=0, text=None):
    ensure_final_feature_flags()
    markup, page, total = final_user_keyboard(chat_id, page)
    _user_menu_pages[chat_id] = page
    bot.send_message(chat_id, text or get_settings().get("welcome_text", "Choose an option:"), reply_markup=markup, parse_mode="Markdown")


def extra_features_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    rows = []
    if final_flag("daily_checkin", True): rows.append([USER_DAILY])
    rows.append([USER_TASKS])
    if final_flag("rewarded_ads", False) and _feature_setting("rewarded_ads_enabled", False):
        rows.append([USER_WATCH_AD])
    if final_flag("coupons", True): rows[-1].append(USER_COUPON) if rows and len(rows[-1]) == 1 else rows.append([USER_COUPON])
    if final_flag("milestones", True): rows.append([USER_MILESTONES])
    if final_flag("announcements", True): rows[-1].append(USER_ANNOUNCEMENTS) if rows and len(rows[-1]) == 1 else rows.append([USER_ANNOUNCEMENTS])
    if final_flag("feedback", True): rows.append([USER_FEEDBACK])
    if final_flag("purchase_history", True): rows.append([USER_HISTORY])
    rows.append([USER_BACK])
    for row in rows: markup.row(*(KeyboardButton(x) for x in row))
    return markup


def premium_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    rows = []
    if final_flag("premium_redeem", True): rows.append([USER_REDEEM])
    if final_flag("gift_premium", True): rows.append([USER_GIFT])
    if final_flag("renewal", True): rows.append([USER_RENEW])
    if _feature_setting("forward_unlock_enabled", True): rows.append([USER_FORWARD_ACCESS])
    rows.append([USER_BACK])
    for row in rows: markup.row(*(KeyboardButton(x) for x in row))
    return markup


def profile_inline_keyboard(user_id=None):
    markup = InlineKeyboardMarkup(row_width=1)

    # Give long-term Premium users a persistent way back to channels from Profile.
    # The callback verifies membership before opening the channel.
    if user_id is not None:
        try:
            purchased_rows = list(users_col.find({
                "user_id": int(user_id),
                "expiry": {"$gt": bot_time_now().timestamp()}
            }).sort("expiry", DESCENDING))
            seen_channels = set()
            for row in purchased_rows:
                cid = row.get("channel_id")
                if cid is None or cid in seen_channels:
                    continue
                seen_channels.add(cid)
                channel = premium_channels_col.find_one({"channel_id": cid}) or {}
                name = channel.get("name") or channel.get("title") or row.get("channel_name") or row.get("channel_title") or "Premium Channel"
                if isinstance(name, str) and (name.strip().isdigit() or name.strip().startswith("@")):
                    name = "Premium Channel"
                markup.add(InlineKeyboardButton(
                    f"🔗 Open {name}",
                    callback_data=f"profile:open:{int(cid)}"
                ))
        except Exception as e:
            print(f"Profile Premium buttons error: {e}")

    markup.row(
        InlineKeyboardButton("📖 How It Works", callback_data="profile:how"),
        InlineKeyboardButton("⏰ Expiry Info", callback_data="profile:expiry")
    )
    markup.row(InlineKeyboardButton(USER_BACK, callback_data="profile:back"))
    return markup


def _profile_purchased_channels(user_id):
    rows = list(users_col.find({"user_id": user_id}).sort("expiry", DESCENDING))
    active = []
    now = bot_time_now().timestamp()
    seen = set()
    for row in rows:
        cid = row.get("channel_id")
        expiry = row.get("expiry")
        if cid is None or not expiry:
            continue
        try:
            if float(expiry) <= now:
                continue
        except Exception:
            continue
        key = (cid, row.get("plan_id"), float(expiry))
        if key in seen:
            continue
        seen.add(key)
        channel = premium_channels_col.find_one({"channel_id": cid}) or {}
        settings = get_settings() or {}

        # Always display the real Premium channel name, never the raw
        # Telegram channel ID/username and never the generic fallback when
        # the name can be resolved from the saved channel or Telegram.
        name = (
            channel.get("name")
            or channel.get("title")
            or row.get("channel_name")
            or row.get("channel_title")
        )
        # Never expose a raw numeric channel ID or @username as the displayed name.
        if isinstance(name, str):
            stripped = name.strip()
            if stripped.isdigit() or stripped.startswith("@"): 
                name = None

        # Older subscriptions may only contain channel_id. Resolve the
        # configured reward channel name for those records.
        if not name and str(settings.get("reward_channel_id")) == str(cid):
            name = settings.get("reward_channel_name")

        # Final fallback: ask Telegram for the channel title when the bot
        # has access to the channel. This keeps IDs/usernames out of Profile.
        if not name:
            try:
                chat = bot.get_chat(int(cid))
                name = getattr(chat, "title", None)
            except Exception:
                name = None

        name = name or "Premium Channel"
        active.append((name, expiry))
    return active


def final_profile_text(message):
    uid = message.from_user.id
    user = get_user(uid) or {}
    s = get_settings()
    joined = format_bot_time(user.get("joined_at"))
    referrer_text = "No one"
    if user.get("referrer_id"):
        referrer = get_user(user["referrer_id"])
        referrer_text = user_display_name(referrer) if referrer else "Unknown User"

    purchased = _profile_purchased_channels(uid)
    if purchased:
        channel_lines = []
        for name, expiry in purchased:
            channel_lines.append(
                f"• *{name}* — ⏰ {format_bot_time(datetime.fromtimestamp(float(expiry), tz=get_bot_timezone()))}"
            )
        purchased_text = "📺 *Purchased Channels*\n" + "\n".join(channel_lines)
    else:
        purchased_text = "📺 *Purchased Channels:* None"

    premium_status = "Active" if purchased else "Not Active"
    latest_expiry = max((x[1] for x in purchased), default=None)
    expiry_text = format_bot_time(datetime.fromtimestamp(float(latest_expiry), tz=get_bot_timezone())) if latest_expiry else "None"

    return (
        "👤 *My Profile*\n\n"
        f"👤 Name: *{message.from_user.first_name or 'User'}*\n"
        f"🆔 Telegram ID: `{uid}`\n"
        f"📅 Joined Date: *{joined}*\n\n"
        f"{s.get('coin_emoji','🪙')} Coins: *{user.get('coins',0)} {s.get('coin_name','Coins')}*\n"
        f"👥 Referral Count: *{user.get('referral_count',0)}*\n"
        f"🔗 Referred By: *{referrer_text}*\n\n"
        f"💎 Premium Status: *{premium_status}*\n"
        f"⏰ Premium Expiry: *{expiry_text}*\n\n"
        f"{purchased_text}"
    )


def show_final_profile(message):
    bot.send_message(
        message.chat.id,
        final_profile_text(message),
        parse_mode="Markdown",
        reply_markup=profile_inline_keyboard(message.from_user.id)
    )


def final_rewards(message):
    uid = message.from_user.id
    row = daily_streak_col.find_one({"user_id": uid}) or {}
    cfg = advanced_settings()
    streak_rewards = cfg.get("streak_rewards", {}) or {}
    text = "🎁 *Rewards*\n\n"
    text += f"🔥 Current streak: *{row.get('streak',0)} days*\n\n"
    text += "🏆 Streak rewards:\n"
    for k,v in sorted(((int(k),v) for k,v in streak_rewards.items()), key=lambda x:x[0]):
        text += f"• {k} days → {v} coins\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


def final_my_rewards(message):
    uid = message.from_user.id
    logs = list(coin_history_col.find({"user_id": uid}).sort("created_at", DESCENDING).limit(10))
    text = "🎁 *My Rewards*\n\n"
    if not logs:
        text += "No reward activity yet. Keep earning!"
    else:
        for r in logs:
            text += f"• {r.get('reason','Reward')}: *{r.get('amount',0)}* coins\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


def final_announcements(message):
    rows = list(announcement_col.find().sort("created_at", DESCENDING).limit(10))
    text = "📢 *Announcements*\n\n"
    if not rows: text += "No announcements right now."
    else:
        for r in rows:
            text += f"• *{r.get('title','Announcement')}*\n{r.get('text', r.get('message',''))}\n\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


def final_expiry_info(message=None, user_id=None):
    uid = int(user_id if user_id is not None else message.from_user.id)
    rows = list(users_col.find({"user_id": uid}).sort("expiry", DESCENDING).limit(10))
    text = "⏰ *Expiry Info*\n\n"
    if not rows: text += "No premium expiry record found."
    else:
        for r in rows:
            exp = r.get("expiry")
            try:
                dt = datetime.fromtimestamp(float(exp), tz=bot_time_now().tzinfo) if exp else None
                text += f"📦 Premium: *{format_bot_time(dt) if dt else 'Not active'}*\n"
            except Exception: text += "📦 Premium: *Not active*\n"
    text += f"\n🕒 Bot timezone: *{get_settings().get('timezone','Asia/Kathmandu')}*"
    bot.send_message(message.chat.id if message is not None else uid, text, parse_mode="Markdown")


def final_achievements(message):
    uid = message.from_user.id
    u = get_user(uid) or {}
    text = ("🏅 *Achievements*\n\n"
            f"👥 Referrals: *{u.get('referral_count',0)}*\n"
            f"🎯 Milestones: *{u.get('milestones_completed',0)}*\n"
            f"💎 VIP: *{(get_vip_level(uid) if 'get_vip_level' in globals() else {'name':'Member'}).get('name','Member')}*\n")
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


def final_referral_campaigns(message):
    rows = list(referral_campaign_col.find({"enabled": True, "start_at": {"$lte": adv_now()}, "end_at": {"$gte": adv_now()}}).sort("created_at", DESCENDING))
    text = "🔗 *Referral Campaigns*\n\n"
    if not rows: text += "No active referral campaigns right now."
    else:
        for r in rows:
            text += f"🚀 *{r.get('title','Campaign')}*\nMultiplier: *x{r.get('multiplier',1)}*\nEnds: *{format_bot_time(r.get('end_at'))}*\n\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


# Final admin feature control includes BOTH advanced and core user-visible flags.
def final_feature_keyboard():
    ensure_final_feature_flags()
    flags = get_settings().get("feature_flags", {}) or {}
    items = list(FINAL_FEATURE_FLAGS.keys())
    markup = InlineKeyboardMarkup(row_width=2)
    for i in range(0, len(items), 2):
        row=[]
        for name in items[i:i+2]:
            state = bool(flags.get(name, FINAL_FEATURE_FLAGS[name]))
            row.append(InlineKeyboardButton(f"{'🟢' if state else '🔴'} {name.replace('_',' ').title()}: {'ON' if state else 'OFF'}", callback_data=f"finalflag:{name}"))
        markup.row(*row)
    markup.row(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin:back"))
    return markup


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("finalflag:"))
def final_feature_toggle(call):
    name = call.data.split(":",1)[1]
    new_state = not final_flag(name, True)
    final_set_flag(name, new_state)
    try: bot.answer_callback_query(call.id, f"{name}: {'ON' if new_state else 'OFF'}")
    except Exception: pass
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=final_feature_keyboard())
    except Exception: pass


# Final router is deliberately registered last and then moved to the front at startup.
def _final_ui_router_match(message):
    if not getattr(message, "text", None) or getattr(message, "content_type", None) != "text":
        return False
    labels = {
        # FINAL USER PANEL
        USER_PROFILE, USER_REFER, USER_EXTRA, USER_PREMIUM,
        USER_REFERRALS, USER_LEADERBOARD, USER_CONTACT,
        USER_DAILY, USER_COUPON, USER_MILESTONES, USER_ANNOUNCEMENTS, USER_FEEDBACK, USER_TASKS,
        USER_REDEEM, USER_GIFT, USER_RENEW, USER_WATCH_AD, USER_BACK,
        # Existing user labels remain routable if reached by old flows.
        USER_EARN_EXTRA, USER_VIP, USER_REWARDS, USER_DEALS, USER_NOTIFICATIONS,
        USER_HISTORY, USER_COLLECTION_STATS, USER_FORWARD_ACCESS, USER_EXPIRY_INFO, USER_HOW, USER_HELP, USER_ACHIEVEMENTS,
        USER_REFERRAL_CAMPAIGNS, USER_MY_REWARDS, USER_SPIN, USER_NEXT, USER_PREVIOUS,
        # FINAL ADMIN PANEL
        FINAL_ADMIN_USERS, FINAL_ADMIN_PREMIUM, FINAL_ADMIN_COINS, FINAL_ADMIN_REWARDS,
        FINAL_ADMIN_TICKETS, FINAL_ADMIN_BROADCAST, FINAL_ADMIN_COUPONS, FINAL_ADMIN_OFFERS,
        FINAL_ADMIN_SETTINGS, FINAL_ADMIN_STATS, FINAL_ADMIN_LOGS, "📺 Ad System", ADMIN_TASKS, ADMIN_MODE, ADMIN_PANEL_BUTTON,
        ADMIN_NEXT, ADMIN_PREVIOUS, ADMIN_ADVANCED, ADMIN_FEATURES, ADMIN_VIP, ADMIN_DEALS,
        ADMIN_GROWTH, ADMIN_SECURITY, ADMIN_NOTIFY, ADMIN_RECOVERY, ADMIN_CAMPAIGNS,
        ADMIN_BROADCAST_TARGET, ADMIN_GIFTS,
    }
    return message.text.strip() in labels


@bot.message_handler(func=_final_ui_router_match)
def final_ui_router(message):
    text = (message.text or '').strip()
    uid = message.from_user.id

    if uid == ADMIN_ID:
        # Admin Panel -> User Mode. The normal user panel becomes fully
        # interactive for the admin while this mode is active.
        if text == ADMIN_MODE:
            switch_to_user_mode()
            return final_show_user_menu(uid, text=get_settings().get("welcome_text", "Choose an option:"))

        # User Mode -> Admin Mode. This button is only present for ADMIN_ID.
        if text == ADMIN_PANEL_BUTTON:
            switch_to_admin_mode()
            return final_show_admin_panel(uid)

        # When the admin is in User Mode, route the exact same user buttons
        # through the normal user handlers. This prevents the old admin-only
        # branch from swallowing those messages.
        if not is_admin_mode(uid) and text in {
            USER_PROFILE, USER_REFER, USER_EXTRA, USER_PREMIUM,
            USER_REFERRALS, USER_LEADERBOARD, USER_CONTACT,
            USER_DAILY, USER_COUPON, USER_MILESTONES, USER_ANNOUNCEMENTS,
            USER_FEEDBACK, USER_TASKS, USER_REDEEM, USER_GIFT, USER_RENEW, USER_WATCH_AD, USER_BACK
        }:
            pass
        elif text in {FINAL_ADMIN_USERS, FINAL_ADMIN_PREMIUM, FINAL_ADMIN_COINS, FINAL_ADMIN_REWARDS,
                      FINAL_ADMIN_TICKETS, FINAL_ADMIN_BROADCAST, FINAL_ADMIN_COUPONS, FINAL_ADMIN_OFFERS,
                      FINAL_ADMIN_SETTINGS, FINAL_ADMIN_STATS, FINAL_ADMIN_LOGS, "📺 Ad System", ADMIN_TASKS}:
            return final_requested_admin_router(message)
        elif text == ADMIN_NEXT:
            return admin_menu_next(message)
        elif text == ADMIN_PREVIOUS:
            return admin_menu_previous(message)
        else:
            return

    if text == USER_PROFILE:
        if not final_flag("profile", True): return bot.send_message(uid, "⚠️ This feature is currently disabled.")
        return show_final_profile(message)
    if text == USER_REFER:
        if not final_flag("referrals", True): return bot.send_message(uid, "⚠️ This feature is currently disabled.")
        return refer_and_earn(message)
    if text == USER_EXTRA:
        if not final_flag("extra_features", True): return bot.send_message(uid, "⚠️ This feature is currently disabled.")
        return bot.send_message(uid, "🪄 *Extra Features*", reply_markup=extra_features_keyboard(), parse_mode="Markdown")
    if text == USER_PREMIUM:
        if not final_flag("premium_menu", True): return bot.send_message(uid, "⚠️ This feature is currently disabled.")
        return bot.send_message(uid, "🎁 *Premium*", reply_markup=premium_menu_keyboard(), parse_mode="Markdown")
    if text == USER_TASKS:
        return show_user_tasks(uid)
    if text == USER_BACK:
        return show_user_menu(uid)
    if text == USER_REFERRALS:
        if not final_flag("my_referrals", True): return bot.send_message(uid, "⚠️ This feature is currently disabled.")
        return my_referrals(message)
    if text == USER_LEADERBOARD:
        if not final_flag("leaderboard", True): return bot.send_message(uid, "⚠️ This feature is currently disabled.")
        return leaderboard(message)
    if text == USER_CONTACT:
        if not final_flag("contact_admin", True): return bot.send_message(uid, "⚠️ Contact Admin is currently disabled.")
        return contact_admin(message)
    if text == USER_DAILY:
        return advanced_daily_checkin(message)
    if text == USER_COUPON:
        return claim_coupon_prompt(message)
    if text == USER_MILESTONES:
        return show_milestones(message)
    if text == USER_ANNOUNCEMENTS:
        return final_announcements(message)
    if text == USER_FEEDBACK:
        return feedback_start(message)
    if text == USER_COLLECTION_STATS:
        return show_user_collection_stats(message)
    if text == USER_WATCH_AD:
        return watch_ad_from_bot(message)
    if text == USER_REDEEM:
        return redeem_premium_menu(message)
    if text == USER_GIFT:
        return gift_premium_start(message)
    if text == USER_RENEW:
        return advanced_renew_menu(message)
    if text == USER_FORWARD_ACCESS:
        return forward_access_channel_menu(message)


@bot.callback_query_handler(func=lambda c: c.data.startswith("profile:open:"))
def profile_open_premium_callback(call):
    uid = call.from_user.id
    try:
        cid = int(call.data.split(":")[-1])
        row = users_col.find_one({
            "user_id": uid,
            "channel_id": cid,
            "expiry": {"$gt": bot_time_now().timestamp()}
        })
        if not row:
            bot.answer_callback_query(call.id, "❌ This Premium access has expired.", show_alert=True)
            return

        channel = premium_channels_col.find_one({"channel_id": cid}) or {}
        name = channel.get("name") or channel.get("title") or row.get("channel_name") or row.get("channel_title") or "Premium Channel"

        # Confirm that the user actually joined before opening it from Profile.
        if not is_user_in_channel(cid, uid):
            bot.answer_callback_query(
                call.id,
                "⚠️ You have not joined this Premium channel yet. Use your Premium join message/link first.",
                show_alert=True
            )
            return

        bot.answer_callback_query(call.id, "Opening Premium…")

        # Public channels/groups can be opened directly. Private ones get a fresh
        # one-time invite; because the user is already a member, Telegram opens it.
        username = None
        try:
            chat = bot.get_chat(cid)
            username = getattr(chat, "username", None)
        except Exception:
            pass

        markup = InlineKeyboardMarkup()
        if username:
            url = f"https://t.me/{username}"
        else:
            try:
                fresh = bot.create_chat_invite_link(cid, member_limit=1)
                url = fresh.invite_link
            except Exception:
                bot.send_message(uid, f"📺 *{name}* is active in your Premium Profile, but Telegram could not create an access link right now.", parse_mode="Markdown")
                return

        markup.add(InlineKeyboardButton(f"📺 Open {name}", url=url))
        bot.send_message(uid, f"💎 *{name}*\n\nYour Premium access is active until *{format_bot_time(datetime.fromtimestamp(float(row['expiry']), tz=get_bot_timezone()))}*.", reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Profile Premium open error: {e}")
        bot.answer_callback_query(call.id, "❌ Unable to open Premium channel.", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "profile:how")
def profile_how_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.from_user.id, get_settings().get("how_it_works_text", "Follow the instructions."), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "profile:expiry")
def profile_expiry_callback(call):
    bot.answer_callback_query(call.id)
    final_expiry_info(None, call.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data == "profile:back")
def profile_back_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    show_user_menu(call.from_user.id)


# Override the runtime menu functions used by /start and by all existing core flows.
def user_menu_markup(user_id=None):
    uid = user_id
    page = 0
    markup, page, _ = final_user_keyboard(uid, page)
    if uid is not None:
        _user_menu_pages[uid] = page
    return markup


def show_user_menu(chat_id):
    # FINAL USER PANEL — always use the authoritative keyboard builder.
    # This is important for the main admin: while in User Mode, the private
    # "👑 Admin Panel" button must remain available so the admin can switch
    # back without restarting the bot.
    ensure_final_feature_flags()
    _user_menu_pages[chat_id] = 0
    markup, page, _ = final_user_keyboard(chat_id, 0)
    _user_menu_pages[chat_id] = page
    bot.send_message(
        chat_id,
        get_settings().get("welcome_text", "Choose an option:"),
        reply_markup=markup,
        parse_mode="Markdown"
    )

def _prioritize_advanced_handlers():
    """Put the final advanced keyboard router first.

    pyTelegramBotAPI checks message handlers in registration order. The source
    contains legacy handlers for some of the same labels, so the router must
    be first to guarantee that the current paginated menu is authoritative.
    """
    handlers = getattr(bot, "message_handlers", [])

    def name_of(h):
        fn = h.get("function") if isinstance(h, dict) else None
        return getattr(fn, "__name__", "")

    priority = {
        # /start must be authoritative for normal users and must not be
        # swallowed by any legacy text/fallback handler.
        "start_handler": -250,
        "advanced_keyboard_priority_router": -240,
        # Keep core navigation ahead of generic legacy handlers.
        "admin_panel_shortcut": 2,
        "user_menu_next": 3,
        "user_menu_previous": 4,
        "admin_menu_next": 5,
        "admin_menu_previous": 6,
        # The final UI router MUST run before support/legacy routers because
        # support_ticket_user_router intentionally matches many user messages.
        # If it runs first, it can swallow the panel buttons.
        "watch_ad_button_handler": -262,
        "final_ui_router": -260,
        "final_requested_admin_router": -259,
        "support_ticket_user_router": -200,
        "support_ticket_receive": -199,
        "delegated_admin_command": -198,
        "delegated_admin_refresh": -197,
        "delegated_admin_feature": -196,
    }

    indexed = list(enumerate(handlers))
    indexed.sort(key=lambda item: (priority.get(name_of(item[1]), 50), item[0]))
    bot.message_handlers = [h for _, h in indexed]


# =========================================================
# FINAL ADMIN BROADCAST + OFFERS CONTROLS
# =========================================================

def _broadcast_target_users(target):
    """Return eligible user IDs for the requested broadcast audience."""
    banned_filter = {"banned": {"$ne": True}}
    if target == "all":
        return [int(r["user_id"]) for r in bot_users_col.find(banned_filter, {"user_id": 1}) if r.get("user_id")]
    if target == "coins":
        q = {**banned_filter, "coins": {"$gt": 0}}
        return [int(r["user_id"]) for r in bot_users_col.find(q, {"user_id": 1}) if r.get("user_id")]
    if target == "coins_no_premium":
        # Users who have coins but do NOT currently have active Premium.
        coin_ids = {
            int(r["user_id"]) for r in bot_users_col.find(
                {**banned_filter, "coins": {"$gt": 0}}, {"user_id": 1}
            ) if r.get("user_id")
        }
        if not coin_ids:
            return []
        now_ts = bot_time_now().timestamp()
        premium_ids = {
            int(r["user_id"]) for r in users_col.find(
                {"user_id": {"$in": list(coin_ids)}, "expiry": {"$gt": now_ts}},
                {"user_id": 1}
            ) if r.get("user_id")
        }
        return sorted(coin_ids - premium_ids)
    if target == "zero_coins":
        q = {**banned_filter, "$or": [{"coins": {"$lte": 0}}, {"coins": {"$exists": False}}]}
        return [int(r["user_id"]) for r in bot_users_col.find(q, {"user_id": 1}) if r.get("user_id")]
    if target == "premium":
        now_ts = bot_time_now().timestamp()
        ids = set()
        for r in users_col.find({"expiry": {"$gt": now_ts}}, {"user_id": 1}):
            if r.get("user_id"):
                ids.add(int(r["user_id"]))
        if not ids:
            return []
        banned = {int(r["user_id"]) for r in bot_users_col.find({"user_id": {"$in": list(ids)}, "banned": True}, {"user_id": 1})}
        return sorted(ids - banned)
    return []


def _broadcast_target_label(target):
    return {
        "all": "All Users",
        "premium": "Premium Users",
        "coins": "Users With Coins",
        "coins_no_premium": "Coins But No Premium",
        "zero_coins": "Users With 0 Coins",
    }.get(target, target)


def final_broadcast_menu(chat_id=ADMIN_ID):
    if chat_id != ADMIN_ID:
        return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("📢 All Users", callback_data="finalbroadcast:target:all"),
        InlineKeyboardButton("💎 Premium Users", callback_data="finalbroadcast:target:premium"),
    )
    markup.row(
        InlineKeyboardButton("🪙 Users With Coins", callback_data="finalbroadcast:target:coins"),
        InlineKeyboardButton("⚪ 0 Coins", callback_data="finalbroadcast:target:zero_coins"),
    )
    markup.row(
        InlineKeyboardButton("🪙💎 Coins + No Premium", callback_data="finalbroadcast:target:coins_no_premium"),
    )
    markup.row(
        InlineKeyboardButton("📨 Single User", callback_data="finalbroadcast:single"),
        InlineKeyboardButton("👥 View User Lists", callback_data="finalbroadcast:lists"),
    )
    markup.row(
        InlineKeyboardButton("📜 Announcement History", callback_data="finalbroadcast:history"),
        InlineKeyboardButton("🧪 Test Broadcast", callback_data="finalbroadcast:test"),
    )
    markup.row(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    bot.send_message(
        chat_id,
        "📢 *Broadcast & Announcements*\n\nChoose the audience for your message. Each audience can receive a different message.",
        reply_markup=markup,
        parse_mode="Markdown"
    )


def _start_targeted_broadcast(admin_id, target):
    if not feature_enabled("broadcast", True):
        bot.send_message(admin_id, "⚠️ Broadcast is disabled in Feature Control.")
        return
    users = _broadcast_target_users(target)
    label = _broadcast_target_label(target)
    msg = bot.send_message(
        admin_id,
        f"📢 *{label}*\n\nCurrent eligible users: *{len(users)}*\n\nSend the message now. You can send text, photo, video, document, etc.",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, lambda m: final_targeted_broadcast_receive(m, target))


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("finalbroadcast:target:"))
def final_broadcast_target_callback(call):
    bot.answer_callback_query(call.id)
    target = call.data.split(":")[-1]
    if target not in {"all", "premium", "coins", "zero_coins", "coins_no_premium"}:
        bot.send_message(ADMIN_ID, "❌ Invalid broadcast audience.")
        return
    _start_targeted_broadcast(ADMIN_ID, target)


def final_targeted_broadcast_receive(message, target):
    if message.from_user.id != ADMIN_ID:
        return
    users = _broadcast_target_users(target)
    sent = failed = 0
    for uid in users:
        try:
            bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    label = _broadcast_target_label(target)
    announcement_col.insert_one({
        "admin_id": ADMIN_ID,
        "target": target,
        "target_label": label,
        "text": message.text or message.caption or f"[{message.content_type}]",
        "content_type": message.content_type,
        "sent": sent,
        "failed": failed,
        "created_at": bot_time_now(),
        "source": "final_admin_targeted_broadcast",
    })
    write_audit(ADMIN_ID, "targeted_broadcast", {"target": target, "sent": sent, "failed": failed, "content_type": message.content_type})
    bot.send_message(ADMIN_ID, f"📢 *{label} broadcast complete*\n\n👥 Targeted: {len(users)}\n✅ Sent: {sent}\n❌ Failed: {failed}", parse_mode="Markdown")
    final_broadcast_menu(ADMIN_ID)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finalbroadcast:lists")
def final_broadcast_lists_callback(call):
    bot.answer_callback_query(call.id)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("👥 All Users", callback_data="finalbroadcast:list:all"),
        InlineKeyboardButton("💎 Premium", callback_data="finalbroadcast:list:premium"),
    )
    markup.row(
        InlineKeyboardButton("🪙 With Coins", callback_data="finalbroadcast:list:coins"),
        InlineKeyboardButton("⚪ 0 Coins", callback_data="finalbroadcast:list:zero_coins"),
    )
    markup.row(
        InlineKeyboardButton("🪙💎 Coins + No Premium", callback_data="finalbroadcast:list:coins_no_premium"),
    )
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="finalbroadcast:back"))
    bot.send_message(ADMIN_ID, "👥 *User Lists*\n\nChoose which audience list you want to view.", reply_markup=markup, parse_mode="Markdown")


def _send_broadcast_user_list(target):
    user_ids = _broadcast_target_users(target)
    label = _broadcast_target_label(target)
    if not user_ids:
        bot.send_message(ADMIN_ID, f"👥 *{label}*\n\nNo eligible users found.", parse_mode="Markdown")
        return
    # Build details in chunks so large lists remain within Telegram's message limit.
    lines = [f"👥 *{label}*", f"Total: *{len(user_ids)}*", ""]
    now_ts = bot_time_now().timestamp()
    for i, uid in enumerate(user_ids, 1):
        u = bot_users_col.find_one({"user_id": uid}) or {}
        name = (u.get("first_name") or "User").replace("\n", " ")
        username = u.get("username") or ""
        uname = f" (@{username})" if username else ""
        coins = int(u.get("coins", 0) or 0)
        premium = users_col.find_one({"user_id": uid, "expiry": {"$gt": now_ts}}, {"expiry": 1})
        ptxt = f" | 💎 {format_bot_time(premium.get('expiry'))}" if premium else ""
        lines.append(f"{i}. {name}{uname}\n   🆔 `{uid}` | 🪙 {coins}{ptxt}")
        if len("\n".join(lines)) > 3200:
            bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")
            lines = [f"👥 *{label}* — continued", ""]
    if len(lines) > 2:
        bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("finalbroadcast:list:"))
def final_broadcast_list_callback(call):
    bot.answer_callback_query(call.id)
    target = call.data.split(":")[-1]
    if target not in {"all", "premium", "coins", "zero_coins", "coins_no_premium"}:
        bot.send_message(ADMIN_ID, "❌ Invalid list.")
        return
    _send_broadcast_user_list(target)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finalbroadcast:back")
def final_broadcast_back_callback(call):
    bot.answer_callback_query(call.id)
    final_broadcast_menu(ADMIN_ID)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finalbroadcast:all")
def final_broadcast_all_callback(call):
    bot.answer_callback_query(call.id)
    _start_targeted_broadcast(ADMIN_ID, "all")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finalbroadcast:test")
def final_broadcast_test_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "🧪 Send the exact test message.")
    bot.register_next_step_handler(msg, final_broadcast_test_receive)


def final_broadcast_test_receive(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        bot.copy_message(ADMIN_ID, message.chat.id, message.message_id)
        bot.send_message(ADMIN_ID, "🧪 Test message sent successfully.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Test failed: {e}")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finalbroadcast:history")
def final_broadcast_history_callback(call):
    bot.answer_callback_query(call.id)
    rows = list(announcement_col.find().sort("created_at", DESCENDING).limit(30))
    if not rows:
        bot.send_message(ADMIN_ID, "📜 *Announcement History*\n\nNo broadcasts recorded yet.", parse_mode="Markdown")
        return
    lines = ["📜 *Announcement History*", ""]
    for row in rows:
        target = row.get("target_label") or ("All Users" if row.get("source") == "final_admin_broadcast" else "Broadcast")
        lines.append(
            f"• {format_bot_time(row.get('created_at'))} — *{target}* — {row.get('content_type', 'text')} — "
            f"✅ {row.get('sent', 0)} / ❌ {row.get('failed', 0)}"
        )
        preview = str(row.get("text", "")).replace("\n", " ")[:90]
        if preview:
            lines.append(f"  {preview}")
    bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finalbroadcast:single")
def final_broadcast_single_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "📨 Send: `USER_ID` first. Then the bot will ask for the message.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, final_broadcast_single_user_receive)


def final_broadcast_single_user_receive(message):
    if message.from_user.id != ADMIN_ID:
        return
    raw = (message.text or "").strip()
    try:
        uid = int(raw)
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Invalid User ID. Please send only the numeric Telegram User ID.")
        return
    user = bot_users_col.find_one({"user_id": uid})
    if not user:
        bot.send_message(ADMIN_ID, "❌ This user is not registered in the bot.")
        return
    msg = bot.send_message(ADMIN_ID, f"📨 Send the message for *{user.get('first_name') or uid}* (`{uid}`).", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: final_broadcast_single_message_receive(m, uid))


def final_broadcast_single_message_receive(message, uid):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        bot.copy_message(uid, message.chat.id, message.message_id)
        announcement_col.insert_one({
            "admin_id": ADMIN_ID,
            "target": "single",
            "target_label": f"Single User {uid}",
            "target_user_id": uid,
            "text": message.text or message.caption or f"[{message.content_type}]",
            "content_type": message.content_type,
            "sent": 1,
            "failed": 0,
            "created_at": bot_time_now(),
            "source": "final_admin_single_broadcast",
        })
        write_audit(ADMIN_ID, "single_broadcast", {"target_user_id": uid, "content_type": message.content_type})
        bot.send_message(ADMIN_ID, f"✅ Message sent successfully to `{uid}`.", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Failed to send to `{uid}`: {e}", parse_mode="Markdown")
    final_broadcast_menu(ADMIN_ID)


def final_offers_menu(chat_id=ADMIN_ID):
    if chat_id != ADMIN_ID:
        return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("⚡ Flash Deals", callback_data="finaloffers:list"),
        InlineKeyboardButton("➕ Add Flash Deal", callback_data="finaloffers:add"),
    )
    markup.row(
        InlineKeyboardButton("🗑️ Remove Flash Deal", callback_data="finaloffers:remove"),
        InlineKeyboardButton("📦 Bulk Discounts", callback_data="finaloffers:bulk"),
    )
    markup.row(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    bot.send_message(ADMIN_ID, "🏷️ *Offers & Discounts*\n\nManage the existing Flash Deals and Bulk Discount Rules.", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finaloffers:list")
def final_offers_list_callback(call):
    bot.answer_callback_query(call.id)
    rows = list(flash_deals_col.find().sort("created_at", DESCENDING).limit(30))
    if not rows:
        bot.send_message(ADMIN_ID, "⚡ *Flash Deals*\n\nNo flash deals created yet.", parse_mode="Markdown")
        return
    lines = ["⚡ *Flash Deals*", ""]
    for d in rows:
        status = "🟢 ON" if d.get("enabled") else "🔴 OFF"
        lines.append(f"• *{d.get('title', 'Special Deal')}* — {d.get('discount', 0)}% — {status}")
        lines.append(f"  ⏰ {format_bot_time(d.get('start_at'))} → {format_bot_time(d.get('end_at'))}")
    bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finaloffers:add")
def final_offers_add_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "➕ *Add Flash Deal*\n\nSend: `TITLE | DISCOUNT_PERCENT | HOURS`\nExample: `Weekend Offer | 20 | 24`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, final_offers_add_receive)


def final_offers_add_receive(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = [x.strip() for x in message.text.split("|", 2)]
        if len(parts) != 3:
            raise ValueError("Use TITLE | DISCOUNT_PERCENT | HOURS")
        title = parts[0]
        discount = int(parts[1])
        hours = float(parts[2])
        if not title or discount < 1 or discount > 100 or hours <= 0:
            raise ValueError("Invalid title, discount or duration")
        now = adv_now()
        end = now + timedelta(hours=hours)
        flash_deals_col.insert_one({
            "title": title,
            "discount": discount,
            "start_at": now,
            "end_at": end,
            "enabled": True,
            "created_at": now,
            "created_by": ADMIN_ID,
        })
        write_audit(ADMIN_ID, "flash_deal_add", {"title": title, "discount": discount, "hours": hours})
        bot.send_message(ADMIN_ID, f"✅ Flash Deal created.\n\n🔥 {title}\n🏷️ {discount}%\n⏰ Ends: {format_bot_time(end)}")
        final_offers_menu(ADMIN_ID)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Invalid format: {e}\n\nUse: `TITLE | DISCOUNT_PERCENT | HOURS`", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finaloffers:remove")
def final_offers_remove_callback(call):
    bot.answer_callback_query(call.id)
    rows = list(flash_deals_col.find().sort("created_at", DESCENDING).limit(30))
    markup = InlineKeyboardMarkup(row_width=1)
    for d in rows:
        markup.add(InlineKeyboardButton(
            f"🗑️ {d.get('title', 'Special Deal')}",
            callback_data=f"finaloffers:delete:{d['_id']}"
        ))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    bot.send_message(ADMIN_ID, "🗑️ *Remove Flash Deal*\n\nChoose a deal:", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("finaloffers:delete:"))
def final_offers_delete_callback(call):
    bot.answer_callback_query(call.id)
    try:
        oid = ObjectId(call.data.split(":")[-1])
        flash_deals_col.delete_one({"_id": oid})
        bot.send_message(ADMIN_ID, "✅ Flash Deal removed.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Unable to remove deal: {e}")
    final_offers_menu(ADMIN_ID)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "finaloffers:bulk")
def final_offers_bulk_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, bulk_rules_text(), parse_mode="Markdown")


def advanced_target_broadcast_info(chat_id=ADMIN_ID):
    # Compatibility entry point for the approved final Admin Panel button.
    # The final panel should use the working broadcast center, not the old
    # targeted-broadcast menu that previously caused a NameError.
    return final_broadcast_menu(chat_id)


def advanced_deals_control(chat_id=ADMIN_ID):
    # Compatibility entry point for the approved final Admin Panel button.
    return final_offers_menu(chat_id)



# =========================================================
# NEW CHANNEL/USER OPERATIONS
# =========================================================

def _feature_setting(name, default=True):
    try:
        return bool(get_settings().get(name, default))
    except Exception:
        return default


def _configured_notification_channels(kind):
    try:
        return list(notification_channels_col.find({"kind": kind, "enabled": True}).sort("created_at", 1))
    except Exception:
        return []


def _send_separate_notification(kind, text):
    sent = 0
    for row in _configured_notification_channels(kind):
        try:
            bot.send_message(int(row["channel_id"]), text, parse_mode="Markdown")
            sent += 1
        except Exception as exc:
            _record_safety_event("notification_channel_error", {"kind": kind, "channel_id": row.get("channel_id"), "error": str(exc)[:300]}, "warning")
    return sent


def _save_notification_channel(kind, chat):
    notification_channels_col.update_one(
        {"kind": kind, "channel_id": int(chat.id)},
        {"$set": {"name": getattr(chat, "title", None) or str(chat.id), "enabled": True, "updated_at": bot_time_now()},
         "$setOnInsert": {"created_at": bot_time_now()}},
        upsert=True,
    )


def separate_notification_channels_text():
    labels = {"referral":"👤 Referral / New User", "milestone":"🎯 Milestones", "ad_watch":"🎬 Ad Watchers", "coin_report":"📊 3-Hour Coin Report"}
    lines = ["📢 *Separate Notification Channels*", ""]
    for kind, label in labels.items():
        rows = _configured_notification_channels(kind)
        lines.append(f"{label}: *{len(rows)} channel(s)*")
        for row in rows:
            lines.append(f"  • {row.get('name', row.get('channel_id'))} — `{row.get('channel_id')}`")
        lines.append("")
    return "\n".join(lines)


def notification_channels_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for kind, label in (("referral","👤 Referral"),("milestone","🎯 Milestone"),("ad_watch","🎬 Ad Watch"),("coin_report","📊 Coin Report")):
        markup.add(InlineKeyboardButton(f"➕ {label}", callback_data=f"notifych:add:{kind}"))
    markup.add(InlineKeyboardButton("🔄 Refresh", callback_data="notifych:menu"), InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    return markup


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "notifych:menu")
def separate_notification_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, separate_notification_channels_text(), reply_markup=notification_channels_keyboard(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("notifych:add:"))
def separate_notification_add_callback(call):
    kind = call.data.split(":", 2)[2]
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, f"Forward a message from the channel for *{kind}* notifications.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m, k=kind: save_separate_notification_channel(m, k))


def save_separate_notification_channel(message, kind):
    if message.from_user.id != ADMIN_ID:
        return
    chat = getattr(message, "forward_from_chat", None)
    if chat is None:
        origin = getattr(message, "forward_origin", None)
        chat = getattr(origin, "chat", None) if origin else None
    if chat is None:
        bot.send_message(ADMIN_ID, "❌ Please forward a message from the target channel/group.")
        return
    _save_notification_channel(kind, chat)
    bot.send_message(ADMIN_ID, f"✅ {getattr(chat, 'title', str(chat.id))} added for *{kind}* notifications.", parse_mode="Markdown")
    bot.send_message(ADMIN_ID, separate_notification_channels_text(), reply_markup=notification_channels_keyboard(), parse_mode="Markdown")


def invite_db_users_to_channel(channel_id, limit=None):
    """Send one-use invitations to DB users. Bot API cannot forcibly add arbitrary users."""
    if not _feature_setting("member_invites_enabled", True):
        return {"sent":0,"failed":0,"skipped":0,"reason":"disabled"}
    sent = failed = skipped = 0
    users = bot_users_col.find({"banned":{"$ne":True}}, {"user_id":1,"first_name":1,"username":1})
    if limit:
        users = users.limit(int(limit))
    for user in users:
        uid = user.get("user_id")
        if not uid:
            skipped += 1
            continue
        try:
            invite = bot.create_chat_invite_link(channel_id, name=f"DB user {uid}", member_limit=1)
            bot.send_message(int(uid), f"📢 *Channel Invitation*\n\nJoin here:\n{invite.invite_link}", parse_mode="Markdown")
            member_invite_jobs_col.insert_one({"user_id":int(uid),"channel_id":int(channel_id),"invite_link":invite.invite_link,"created_at":bot_time_now(),"status":"sent"})
            sent += 1
            time.sleep(0.35)
        except Exception as exc:
            failed += 1
            _record_safety_event("db_member_invite_failed", {"user_id":uid,"channel_id":channel_id,"error":str(exc)[:300]}, "warning")
    return {"sent":sent,"failed":failed,"skipped":skipped,"reason":None}


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "members:invite")
def db_member_invite_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "Send the Premium channel ID or @username. The bot must be an administrator there.")
    bot.register_next_step_handler(msg, process_db_member_invite)


def process_db_member_invite(message):
    if message.from_user.id != ADMIN_ID:
        return
    raw = (message.text or "").strip()
    try:
        channel_id = int(raw)
    except Exception:
        channel_id = raw
    result = invite_db_users_to_channel(channel_id)
    bot.send_message(ADMIN_ID, f"👥 *DB User Invitation Complete*\n\n📨 Sent: *{result['sent']}*\n❌ Failed: *{result['failed']}*\n⏭️ Skipped: *{result['skipped']}*\n\nUsers receive an invite and choose whether to join; they are not forcibly added.", parse_mode="Markdown")


def _content_type_for_message(message):
    ctype = getattr(message, "content_type", "")
    if ctype in ("video","video_note","animation"):
        return "videos"
    if ctype == "photo":
        return "photos"
    if ctype == "document":
        return "documents"
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    if "http://" in text or "https://" in text or "t.me/" in text:
        return "links"
    return "other"


def _update_channel_content_stats(message):
    chat = getattr(message, "chat", None)
    if not chat or getattr(chat, "type", None) != "channel":
        return None
    kind = _content_type_for_message(message)
    channel_id = int(chat.id)
    now = bot_time_now()
    channel_content_stats_col.update_one(
        {"channel_id":channel_id},
        {"$set":{"channel_name":getattr(chat,"title",None) or str(channel_id),"updated_at":now}, "$inc":{kind:1,"total":1}, "$setOnInsert":{"created_at":now}},
        upsert=True,
    )
    return kind


def _channel_content_stats_text():
    docs = list(channel_content_stats_col.find().sort("channel_name", 1))
    if not docs:
        return "📚 *Collection Stats*\n\nNo tracked channel posts yet. The Bot API cannot enumerate old channel history, so counts start when the bot receives new posts."
    lines = ["📚 *Premium Collection Stats*", ""]
    for d in docs:
        lines += [f"📺 *{d.get('channel_name', d.get('channel_id'))}*", f"🎬 Videos: *{d.get('videos',0)}*", f"🖼️ Photos: *{d.get('photos',0)}*", f"📄 Documents: *{d.get('documents',0)}*", f"🔗 Links: *{d.get('links',0)}*", f"📦 Total: *{d.get('total',0)}*", ""]
    return "\n".join(lines)


def show_user_collection_stats(message):
    if not _feature_setting("content_stats_enabled", True):
        bot.send_message(message.chat.id, "⚠️ Collection statistics are currently disabled.")
        return
    bot.send_message(message.chat.id, _channel_content_stats_text(), parse_mode="Markdown")


def _active_user_has_premium_channel(user_id, channel_id):
    return premium_history_col.find_one({"user_id":int(user_id),"channel_id":int(channel_id),"expiry":{"$gt":time.time()}}) is not None


@bot.channel_post_handler(content_types=["video","video_note","animation","photo","document","text"])
def premium_channel_content_tracker(message):
    try:
        kind = _update_channel_content_stats(message) if _feature_setting("content_stats_enabled", True) else _content_type_for_message(message)
        if not _feature_setting("content_notifications_enabled", True):
            return
        channel_id = int(message.chat.id)
        if not premium_channels_col.find_one({"channel_id":channel_id}):
            return
        link = f"https://t.me/c/{str(channel_id).replace('-100','')}/{message.message_id}"
        for row in bot_users_col.find({"banned":{"$ne":True}}, {"user_id":1}):
            uid = row.get("user_id")
            if not uid or not _active_user_has_premium_channel(uid, channel_id):
                continue
            try:
                bot.send_message(uid, f"📚 *New Collection Uploaded*\n\n📺 Channel: *{message.chat.title}*\n📦 New item: *{kind}*\n\n🔗 {link}", parse_mode="Markdown")
                channel_upload_notifications_col.insert_one({"user_id":int(uid),"channel_id":channel_id,"message_id":int(message.message_id),"content_type":kind,"created_at":bot_time_now()})
            except Exception:
                pass
    except Exception as exc:
        _record_safety_event("channel_content_tracker_error", {"error":str(exc)[:500]}, "warning")



def _active_purchased_premium_channels(user_id):
    """Return only Premium channels the user currently owns/accesses."""
    now_ts = bot_time_now().timestamp()
    rows = list(users_col.find({
        "user_id": int(user_id),
        "expiry": {"$gt": now_ts},
    }).sort("expiry", DESCENDING))
    result = []
    seen = set()
    for row in rows:
        try:
            cid = int(row.get("channel_id"))
        except Exception:
            continue
        if cid in seen:
            continue
        channel = premium_channels_col.find_one({"channel_id": cid}) or {}
        if not channel:
            continue
        seen.add(cid)
        result.append((channel, float(row.get("expiry", 0) or 0)))
    return result


def forward_access_channel_menu(message):
    if not _feature_setting("forward_unlock_enabled", True):
        bot.send_message(message.chat.id, "⚠️ Forward access is currently disabled.")
        return

    purchased = _active_purchased_premium_channels(message.from_user.id)
    if not purchased:
        bot.send_message(
            message.chat.id,
            "🔓 *Forward Access*\n\n❌ You haven't purchased any Premium channel yet.\n\nPlease buy Premium first, then return here to unlock Forward Access for that channel.",
            parse_mode="Markdown",
        )
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for ch, expiry in purchased:
        name = ch.get("name") or ch.get("title") or "Premium Channel"
        markup.add(InlineKeyboardButton(f"📺 {name}", callback_data=f"fwdch:{int(ch['channel_id'])}"))
    markup.add(InlineKeyboardButton("⬅️ Previous", callback_data="final:premium_back"))
    bot.send_message(
        message.chat.id,
        f"🔓 *Forward Access*\n\nOnly your currently purchased Premium channels are shown here.\n\n💰 One-time unlock: *{forward_unlock_cost()} {get_settings().get('coin_name','KP')} per channel*",
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("fwdch:"))
def forward_access_channel_callback(call):
    uid = call.from_user.id
    cid = int(call.data.split(":",1)[1])
    if not user_forward_unlock_status(uid, cid):
        cost = forward_unlock_cost()
        if get_coin_balance(uid) < cost:
            bot.answer_callback_query(call.id, "❌ Not enough coins.", show_alert=True)
            return
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton(f"✅ Pay {cost} {get_settings().get('coin_name','KP')}", callback_data=f"fwdpay:{cid}"), InlineKeyboardButton("❌ Cancel", callback_data="fwdcancel"))
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔓 *Confirm Forward Access*\n\nThis is a one-time payment for this channel.", reply_markup=markup, parse_mode="Markdown")
        return
    bot.answer_callback_query(call.id)
    _request_forward_message_link(call.message.chat.id, uid, cid)


@bot.callback_query_handler(func=lambda c: c.data.startswith("fwdpay:"))
def forward_access_pay_callback(call):
    uid = call.from_user.id
    cid = int(call.data.split(":",1)[1])
    if not grant_forward_unlock(uid, cid):
        bot.answer_callback_query(call.id, "❌ Payment could not be completed.", show_alert=True)
        return
    bot.answer_callback_query(call.id, "✅ Forward access unlocked")
    _request_forward_message_link(call.message.chat.id, uid, cid)


@bot.callback_query_handler(func=lambda c: c.data == "fwdcancel")
def forward_access_cancel_callback(call):
    bot.answer_callback_query(call.id, "Cancelled")


def _request_forward_message_link(chat_id, user_id, channel_id):
    msg = bot.send_message(chat_id, "🔗 Send the Telegram message link of the video/photo/document you want the bot to copy to you.\n\nExample: `https://t.me/c/1234567890/123`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m, u=user_id, c=channel_id: process_forward_message_link(m, u, c))


def _normalize_channel_id(value):
    """Normalize Telegram supergroup/channel IDs to the canonical -100... form."""
    try:
        n = int(value)
    except Exception:
        return None
    if n < 0:
        return n
    # Database migrations/older records may contain the numeric part only.
    return int(f"-100{n}")


def process_forward_message_link(message, user_id, unlocked_channel_id):
    raw = (message.text or "").strip()
    import re

    # Supports both private channel links (t.me/c/1234567890/123) and
    # public channel links (t.me/channelname/123). Query strings such as
    # ?single and ?thread are intentionally ignored.
    m = re.search(r"https?://t\.me/(?:c/(\d+)|([A-Za-z0-9_]+))/(\d+)(?:\?[^\s]*)?", raw)
    if not m:
        bot.send_message(message.chat.id, "❌ Invalid Telegram message link.")
        return

    private_part, public_part, msg_id = m.groups()
    unlocked_norm = _normalize_channel_id(unlocked_channel_id)
    source_chat = None

    if private_part:
        source_chat = _normalize_channel_id(private_part)
        # Do not compare the raw strings: Telegram private post URLs contain
        # only the numeric portion while channel records normally contain -100...
        if source_chat is None or unlocked_norm is None or source_chat != unlocked_norm:
            bot.send_message(
                message.chat.id,
                "❌ This link is from a different channel than the one you unlocked.",
            )
            return
    else:
        # Resolve the public username through Telegram and compare the actual
        # chat ID. This is safer than trusting a username saved in MongoDB.
        try:
            resolved = bot.get_chat(f"@{public_part}")
            resolved_id = _normalize_channel_id(getattr(resolved, "id", None))
        except Exception as exc:
            bot.send_message(message.chat.id, f"❌ I couldn't access that channel. Make sure the bot is an administrator there.\n\n`{str(exc)[:250]}`", parse_mode="Markdown")
            return

        if resolved_id is None or unlocked_norm is None or resolved_id != unlocked_norm:
            bot.send_message(message.chat.id, "❌ This link is from a different channel than the one you unlocked.")
            return
        source_chat = getattr(resolved, "id", f"@{public_part}")

    try:
        bot.copy_message(int(user_id), source_chat, int(msg_id))
        bot.send_message(message.chat.id, "✅ Content copied to your chat.")
    except Exception as exc:
        bot.send_message(
            message.chat.id,
            "❌ Telegram could not copy that message. It may be protected, deleted, or inaccessible.\n\n"
            f"`{str(exc)[:300]}`",
            parse_mode="Markdown",
        )


def forward_unlock_cost():
    return int(get_settings().get("forward_unlock_cost",50) or 50)


def user_forward_unlock_status(user_id, channel_id):
    row = forward_unlocks_col.find_one({"user_id":int(user_id),"channel_id":int(channel_id)})
    return bool(row and row.get("active"))


def grant_forward_unlock(user_id, channel_id):
    if user_forward_unlock_status(user_id, channel_id):
        return True
    cost = forward_unlock_cost()
    if get_coin_balance(user_id) < cost:
        return False
    add_coins(user_id, -cost)
    forward_unlocks_col.update_one({"user_id":int(user_id),"channel_id":int(channel_id)}, {"$set":{"active":True,"cost":cost,"granted_at":bot_time_now()}}, upsert=True)
    record_user_history(user_id,"forward_unlock","Forward unlock",{"channel_id":int(channel_id),"cost":cost},amount=-cost)
    return True


def forward_unlock_info(chat_id, user_id):
    settings=get_settings()
    bot.send_message(chat_id, f"🔓 *Forward Unlock*\n\nOne-time cost: *{forward_unlock_cost()} {settings.get('coin_name','KP')} per channel*.\n\nThis is a bot-controlled unlock for copy/forward requests. Telegram's Bot API cannot turn native forwarding on for one individual user in a protected channel.", parse_mode="Markdown")


def send_periodic_coin_report():
    if not _feature_setting("user_coin_report_enabled", True):
        return
    rows=list(bot_users_col.find({"banned":{"$ne":True}}, {"user_id":1,"first_name":1,"last_name":1,"username":1,"coins":1}).sort("user_id",1))
    settings=get_settings(); emoji=settings.get('coin_emoji','🌽')
    chunks=[]; current=f"📊 *User Coin Report*\n\n👥 Total Users: *{len(rows)}*\n🕒 {format_bot_time(bot_time_now())}\n\n"
    for i,u in enumerate(rows,1):
        name=(u.get('first_name') or 'User') + (f" {u.get('last_name')}" if u.get('last_name') else '')
        username=f"@{u.get('username')}" if u.get('username') else '-'
        line=f"{i}. {name} | {username} | `{u.get('user_id')}` | {emoji} *{int(u.get('coins',0) or 0)}*\n"
        if len(current)+len(line)>3800:
            chunks.append(current); current="📊 *User Coin Report — continued*\n\n"+line
        else: current+=line
    if current.strip(): chunks.append(current)
    for row in _configured_notification_channels("coin_report"):
        for chunk in chunks:
            try: bot.send_message(int(row['channel_id']),chunk,parse_mode="Markdown")
            except Exception as exc: _record_safety_event("coin_report_error",{"channel_id":row.get('channel_id'),"error":str(exc)[:300]},"warning")


def run_coin_report_job():
    try: send_periodic_coin_report()
    except Exception as exc: _record_safety_event("coin_report_job_error",{"error":str(exc)[:500]},"warning")


# =========================================================
# REWARDED ADS / GIGAPUB MINI APP
# =========================================================
# GigaPub Rewarded Ads are launched from the Mini App through the
# GigaPub SDK function `showGiga()`. The provider promise resolves
# after the rewarded experience, then the backend validates Telegram initData,
# the short-lived one-time session, cooldown, daily limit, requirements, and
# atomically marks the session rewarded. This prevents replay/double claims.
# Note: the supplied GigaPub SDK integration exposes completion to the WebView;
# there is no separate Telegram Bot API ad-view callback.

AD_SESSION_TTL_DEFAULT = 600


def _ad_settings():
    """Normalize rewarded-ad settings and select the active enabled provider."""
    s=get_settings() or {}
    def _int(v,d,m=0):
        try:return max(m,int(v))
        except (TypeError,ValueError):return max(m,int(d))
    def _bool(v,d=False):
        if isinstance(v,bool):return v
        if isinstance(v,str):return v.strip().lower() in {"1","true","yes","on","enabled"}
        return bool(d if v is None else v)
    default_url="https://channel-subscription-bot-p85l.onrender.com/ad-app?v=gp8548"
    miniapp_url=str(s.get("ad_miniapp_url") or default_url).strip()
    if not miniapp_url.lower().startswith("https://"): miniapp_url=default_url
    legacy_ref=1 if _bool(s.get("ad_require_referral",False)) else 0
    rr=_int(s.get("ad_required_referrals",legacy_ref),legacy_ref)
    gp_enabled=_bool(s.get("gigapub_enabled",True),True); ax_enabled=_bool(s.get("adexora_enabled",True),True)
    gp_id=str(s.get("gigapub_app_id") or (s.get("ad_block_id") if str(s.get("ad_provider","GigaPub")).lower()=="gigapub" else "") or "8548").strip()
    ax_id=str(s.get("adexora_app_id") or "2210").strip()
    preferred=str(s.get("ad_provider","GigaPub") or "GigaPub").strip().lower()
    if preferred=="adexora" and ax_enabled and ax_id: provider,block_id="Adexora",ax_id
    elif gp_enabled and gp_id: provider,block_id="GigaPub",gp_id
    elif ax_enabled and ax_id: provider,block_id="Adexora",ax_id
    else: provider,block_id=("Adexora" if preferred=="adexora" else "GigaPub"),""
    return {"enabled":_bool(s.get("rewarded_ads_enabled",False)),"provider":provider,"block_id":block_id,
            "gigapub_enabled":gp_enabled,"gigapub_app_id":gp_id,"adexora_enabled":ax_enabled,"adexora_app_id":ax_id,
            "miniapp_url":miniapp_url,"reward_coins":_int(s.get("ad_reward_coins",10),10),"cooldown_seconds":_int(s.get("ad_cooldown_seconds",60),60),
            "daily_limit":_int(s.get("ad_daily_limit",10),10),"required_referrals":rr,"require_force_join":_bool(s.get("ad_require_force_join",True),True),
            "session_ttl_seconds":_int(s.get("ad_session_ttl_seconds",AD_SESSION_TTL_DEFAULT),AD_SESSION_TTL_DEFAULT,60)}


def _ad_day_start():
    now = bot_time_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _ad_recent_reward(user_id):
    return ad_watch_history_col.find_one(
        {"user_id": int(user_id), "rewarded": True},
        sort=[("rewarded_at", DESCENDING)]
    )


def _ad_daily_count(user_id):
    start = _ad_day_start()
    return int(ad_watch_history_col.count_documents({
        "user_id": int(user_id),
        "rewarded": True,
        "rewarded_at": {"$gte": start},
    }))


def _ad_requirements_error(user_id, cfg=None):
    """Check ad eligibility without allowing a bad force-join record to crash the UI."""
    cfg = cfg or _ad_settings()
    uid = int(user_id)
    try:
        user = get_user(uid) or {}
    except Exception as exc:
        print(f"Ad user lookup error for {uid}: {exc}")
        return "⚠️ Unable to check your ad eligibility right now. Please try again in a moment."

    if user.get("banned"):
        return "🚫 Your account is not eligible for rewarded ads."

    required_referrals = int(cfg.get("required_referrals", 0) or 0)
    if required_referrals > 0:
        try:
            referral_count = int(user.get("referral_count", 0) or 0)
        except (TypeError, ValueError):
            referral_count = 0
        if referral_count < required_referrals:
            return (
                f"🔗 You need at least {required_referrals} successful "
                f"referral{'s' if required_referrals != 1 else ''} before watching rewarded ads."
            )

    if cfg.get("require_force_join", True):
        try:
            channels = list(force_channels_col.find())
            if channels and not check_all_force_channels(uid):
                return "📣 Please join all required channels first, then try again."
        except Exception as exc:
            # Do not turn a Telegram/Mongo force-join problem into the generic
            # 'temporarily unavailable' message. The user gets a retryable error
            # and the exact exception is visible in the server log.
            print(f"Ad force-join check error for {uid}: {exc}")
            return "⚠️ I couldn't verify the required channels right now. Please try again in a moment."
    return None


def _ad_cooldown_remaining(user_id, cfg=None):
    cfg = cfg or _ad_settings()
    if cfg["cooldown_seconds"] <= 0:
        return 0
    last = _ad_recent_reward(int(user_id))
    if not last or not last.get("rewarded_at"):
        return 0
    try:
        elapsed = (bot_time_now() - last["rewarded_at"]).total_seconds()
    except Exception:
        return 0
    return max(0, int(cfg["cooldown_seconds"] - elapsed))


def _ad_start_session(user_id):
    cfg = _ad_settings()
    if not cfg["enabled"]:
        return False, "📺 Rewarded ads are currently disabled."
    if not cfg["block_id"]:
        return False, "⚠️ Rewarded ads are not configured yet. Please ask the admin to configure the GigaPub App ID."
    req_error = _ad_requirements_error(user_id, cfg)
    if req_error:
        return False, req_error
    remaining = _ad_cooldown_remaining(user_id, cfg)
    if remaining > 0:
        return False, f"⏳ Please wait {remaining} seconds before watching another ad."
    daily = _ad_daily_count(user_id)
    if cfg["daily_limit"] and daily >= cfg["daily_limit"]:
        return False, f"📅 You have reached today's ad limit ({cfg['daily_limit']}). Try again tomorrow."

    now = bot_time_now()
    session_id = secrets.token_urlsafe(32)
    ad_sessions_col.insert_one({
        "session_id": session_id,
        "user_id": int(user_id),
        "provider": cfg["provider"],
        "block_id": cfg["block_id"],
        "created_at": now,
        "expires_at": now + timedelta(seconds=cfg["session_ttl_seconds"]),
        "rewarded": False,
        "reward_coins": cfg["reward_coins"],
    })
    return True, session_id


def _telegram_webapp_user(init_data):
    """Validate Telegram.WebApp.initData using the bot token and return the user dict."""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        auth_date = int(pairs.get("auth_date", "0"))
        if auth_date <= 0 or abs(time.time() - auth_date) > 86400:
            return None
        user_raw = pairs.get("user")
        if not user_raw:
            return None
        import json as _json
        user = _json.loads(user_raw)
        return user if user.get("id") else None
    except Exception as exc:
        print(f"Mini App initData validation error: {exc}")
        return None


def _ad_reward_session(user_id, session_id):
    cfg = _ad_settings()
    if not cfg["enabled"]:
        return False, "Rewarded ads are disabled."
    if not session_id:
        return False, "Invalid ad session."

    now = bot_time_now()
    session = ad_sessions_col.find_one({"session_id": session_id, "user_id": int(user_id)})
    if not session:
        return False, "Invalid or expired ad session."
    if session.get("rewarded"):
        return True, 0
    if session.get("expires_at") and session["expires_at"] < now:
        return False, "This ad session has expired. Please start a new ad."

    req_error = _ad_requirements_error(user_id, cfg)
    if req_error:
        return False, req_error
    remaining = _ad_cooldown_remaining(user_id, cfg)
    if remaining > 0:
        return False, f"Cooldown active for {remaining} seconds."
    if cfg["daily_limit"] and _ad_daily_count(user_id) >= cfg["daily_limit"]:
        return False, "Today's ad limit has been reached."

    # One-time atomic claim. Only the first valid request can change rewarded=false.
    claim = ad_sessions_col.update_one(
        {"_id": session["_id"], "rewarded": False},
        {"$set": {"rewarded": True, "rewarded_at": now}},
    )
    if claim.modified_count != 1:
        return False, "This ad session was already processed."

    reward = int(session.get("reward_coins", cfg["reward_coins"]))
    add_coins(int(user_id), reward)
    ad_watch_history_col.insert_one({
        "user_id": int(user_id),
        "session_id": session_id,
        "provider": session.get("provider", cfg["provider"]),
        "block_id": session.get("block_id", cfg["block_id"]),
        "reward": reward,
        "rewarded": True,
        "rewarded_at": now,
    })
    try:
        bot_users_col.update_one({"user_id": int(user_id)}, {"$set": {"last_ad_rewarded_at": now}, "$inc": {"ad_watch_count": 1}}, upsert=True)
    except Exception:
        pass

    text = f"""🎉 *Ad completed!*

💰 You earned *{reward} {get_settings().get('coin_name', 'Coins')}*.
{get_settings().get('coin_emoji', '🪙')} Balance: *{get_coin_balance(user_id)}*"""
    try:
        bot.send_message(int(user_id), text, parse_mode="Markdown")
    except Exception:
        pass
    try:
        _send_separate_notification("ad_watch", f"📺 *Ad Reward*\n\n👤 User: `{int(user_id)}`\n💰 Reward: *{reward}*\n🕒 {format_bot_time(now)}")
    except Exception:
        pass
    try:
        user_history_col.insert_one({
            "user_id": int(user_id),
            "type": "ad_reward",
            "title": "Rewarded Ad",
            "description": f"Earned {reward} coins from a rewarded ad",
            "amount": reward,
            "created_at": now,
        })
    except Exception:
        pass
    return True, reward


AD_UI_ASSET_LABELS = {
    "hero": "🎁 Main Reward / Gift",
    "preparing": "🎬 Preparing Ad",
    "completed": "✅ Ad Completed",
    "requirements": "🔒 Requirements Locked",
    "cooldown": "⏳ Cooldown / Limit",
    "channels": "📣 Required Channels",
}

def _ad_ui_assets():
    assets=(get_settings() or {}).get("ad_ui_assets") or {}
    return {k:str(assets.get(k) or "").strip() for k in AD_UI_ASSET_LABELS}

@app.route("/ad-assets/<asset_key>", methods=["GET"])
def ad_ui_asset(asset_key):
    if asset_key not in AD_UI_ASSET_LABELS: return "",404
    fid=_ad_ui_assets().get(asset_key)
    if not fid: return "",404
    try:
        tg_file=bot.get_file(fid)
        raw=bot.download_file(tg_file.file_path)
        mime=mimetypes.guess_type(tg_file.file_path or "")[0] or "image/jpeg"
        return send_file(BytesIO(raw),mimetype=mime,max_age=300)
    except Exception as exc:
        print(f"Ad UI asset error ({asset_key}): {exc}")
        return "",404

def ads_assets_keyboard():
    m=InlineKeyboardMarkup(row_width=2)
    assets=_ad_ui_assets()
    for key,label in AD_UI_ASSET_LABELS.items():
        state="🟢 Set" if assets.get(key) else "⚪ Default"
        m.row(InlineKeyboardButton(f"{label} · {state}",callback_data=f"ads:asset:{key}"))
    m.row(InlineKeyboardButton("🔙 Back to Ad System",callback_data="ads:menu"))
    return m

def ads_assets_menu():
    bot.send_message(ADMIN_ID,"🖼️ *Ad Mini App Images*\n\nUpload or replace the illustrations used by the burgundy rewarded-ad UI.\n\nSend an image after selecting an item. Send `remove` to restore the built-in fallback.",reply_markup=ads_assets_keyboard(),parse_mode="Markdown")

def save_ads_asset(message,asset_key):
    if message.from_user.id!=ADMIN_ID or asset_key not in AD_UI_ASSET_LABELS: return
    text=(message.text or "").strip().lower() if message.content_type=="text" else ""
    if text=="remove":
        update_setting(f"ad_ui_assets.{asset_key}","")
        bot.send_message(ADMIN_ID,f"✅ {AD_UI_ASSET_LABELS[asset_key]} restored to the built-in fallback.")
        return ads_assets_menu()
    file_id=""
    if message.content_type=="photo" and message.photo: file_id=message.photo[-1].file_id
    elif message.content_type=="document" and message.document and (message.document.mime_type or "").lower().startswith("image/"): file_id=message.document.file_id
    if not file_id:
        msg=bot.send_message(ADMIN_ID,f"❌ Please send an image for *{AD_UI_ASSET_LABELS[asset_key]}*, or send `remove`.",parse_mode="Markdown")
        return bot.register_next_step_handler(msg,lambda m,k=asset_key: save_ads_asset(m,k))
    update_setting(f"ad_ui_assets.{asset_key}",file_id)
    bot.send_message(ADMIN_ID,f"✅ {AD_UI_ASSET_LABELS[asset_key]} updated.")
    ads_assets_menu()


def watch_ad_from_bot(message):
    """Open the rewarded-ad Mini App from the user keyboard.

    Every editable setting is normalized before Telegram markup is built. This
    is important because one malformed MongoDB setting used to make the whole
    button fall into the generic 'temporarily unavailable' handler.
    """
    uid = int(message.from_user.id)
    cfg = _ad_settings()

    if not cfg["enabled"]:
        bot.send_message(uid, "📺 Rewarded ads are currently disabled. The Watch Ad option is hidden while ads are off.")
        try:
            show_user_menu(uid)
        except Exception as refresh_error:
            print(f"Could not refresh disabled-ad user menu for {uid}: {refresh_error}")
        return

    if not cfg["block_id"]:
        return bot.send_message(uid, "⚠️ Rewarded ads are not configured yet. Please ask the admin to configure the GigaPub App ID.")

    # Telegram.WebApp.initData is supplied only when the page is opened as a
    # Telegram Web App, so this MUST remain a WebAppInfo button rather than a
    # normal URL button.
    webapp_url = cfg["miniapp_url"]
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("📺 Watch Ad", web_app=WebAppInfo(url=webapp_url)))
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="ads:user_cancel"))

    required_referrals = int(cfg.get("required_referrals", 0) or 0)
    referral_line = (
        f"🔗 Referral requirement: *{required_referrals}* successful referral"
        f"{'s' if required_referrals != 1 else ''}.\n"
        if required_referrals > 0
        else "🔗 Referral requirement: *None*.\n"
    )

    try:
        coin_name = str(get_settings().get("coin_name", "KP") or "KP")
    except Exception:
        coin_name = "KP"

    # Do not interpolate an arbitrary admin-edited coin name into Markdown.
    # This prevents Telegram parse errors from breaking Watch Ad.
    safe_coin_name = coin_name.replace("\\", "").replace("*", "").replace("_", "\\_").replace("[", "\\[").replace("]", "\\]")

    return bot.send_message(
        uid,
        "📺 *Watch Ad & Earn*\n\n"
        f"💰 Reward: *{cfg['reward_coins']} {safe_coin_name}* per completed ad.\n"
        f"📅 Daily limit: *{cfg['daily_limit'] or 'Unlimited'}*.\n"
        f"⏱️ Cooldown: *{cfg['cooldown_seconds']} seconds*.\n"
        f"{referral_line}"
        + (f"⚠️ Current requirement: {req_error}\n\n" if req_error else "")
        + "📣 The Mini App will show your exact join/referral status and let you check again.\n\n"
        + "Tap *Watch Ad* below to open the Mini App and start the rewarded ad.",
        reply_markup=markup,
        parse_mode="Markdown",
    )


# Dedicated user-panel route for Watch Ad. The final UI router is registered
# late in this large legacy file, so this explicit handler guarantees that the
# current main-panel button cannot be swallowed by an older generic handler.
@bot.message_handler(
    func=lambda m: (
        m.content_type == "text"
        and m.from_user.id != ADMIN_ID
        and (m.text or "").strip() == USER_WATCH_AD
    )
)
def watch_ad_button_handler(message):
    try:
        return watch_ad_from_bot(message)
    except Exception as exc:
        # Keep the exact exception in Render logs and tell the user what to do.
        # The old generic message hid the real configuration/Telegram error.
        print(f"Watch Ad button error for {message.from_user.id}: {type(exc).__name__}: {exc}")
        try:
            bot.send_message(
                message.chat.id,
                "⚠️ I couldn't open the rewarded-ad panel right now. Please try again in a moment."
            )
        except Exception:
            pass


@app.route("/ad-app", methods=["GET"])
def rewarded_ad_app():
    cfg=_ad_settings()
    assets=_ad_ui_assets()
    asset_urls={k:(f"/ad-assets/{k}" if v else "") for k,v in assets.items()}
    html=r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>Watch & Earn</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
{{ ad_script|safe }}
<style>
:root{--bg:#09070b;--panel:#171017;--panel2:#21131e;--line:#4d2940;--red:#8f2945;--red2:#b33b5c;--gold:#f2b642;--text:#f8f2f6;--muted:#b9adb6;--ok:#45dc8c;--bad:#ea6078}*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:radial-gradient(circle at 50% -10%,#3a142b 0,#170b16 34%,#09070b 74%);color:var(--text);font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body{padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}main{min-height:100vh;display:flex;justify-content:center;padding:16px 13px 28px}.wrap{width:min(460px,100%)}.top{display:flex;justify-content:space-between;align-items:center;margin:2px 4px 12px}.brand{font-weight:850}.provider{font-size:10px;color:#d9becb;background:#241420;border:1px solid #583149;border-radius:999px;padding:7px 10px}.card{background:linear-gradient(145deg,rgba(35,19,32,.96),rgba(16,11,18,.98));border:1px solid rgba(173,61,101,.43);box-shadow:0 18px 50px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.03);border-radius:23px;padding:19px;margin-bottom:11px}.hero{text-align:center;padding:18px}.hero img,.art{width:112px;height:112px;object-fit:contain;display:block;margin:0 auto 10px;filter:drop-shadow(0 12px 22px rgba(190,45,88,.25))}.fallback{font-size:68px;line-height:1;margin:5px auto 12px}.title{font-size:25px;font-weight:850}.sub{color:var(--muted);font-size:13px;line-height:1.55;margin:8px auto 16px;max-width:370px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.stat{background:#120d13;border:1px solid #3b2233;border-radius:14px;padding:10px 5px;text-align:center}.stat b{display:block;font-size:15px}.stat span{display:block;color:var(--muted);font-size:10px;margin-top:3px}.section-title{font-size:13px;font-weight:850;margin:1px 0 8px}.req{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid rgba(110,52,77,.28)}.req:last-child{border-bottom:0}.req-icon{width:34px;height:34px;border-radius:11px;background:#271522;display:grid;place-items:center}.req-main{flex:1}.req-main b{display:block;font-size:12px}.req-main span{display:block;color:var(--muted);font-size:10px;margin-top:2px}.check{color:var(--ok);font-size:18px}.cross{color:var(--bad);font-size:18px}.btn{width:100%;border:0;border-radius:15px;padding:14px 16px;font-size:15px;font-weight:850;color:white;background:linear-gradient(135deg,#8c2947,#b23b5d);box-shadow:0 9px 24px rgba(142,35,70,.28);cursor:pointer}.btn:disabled{opacity:.48;cursor:not-allowed}.btn.secondary{margin-top:8px;background:#19111a;border:1px solid #3b2435;box-shadow:none;color:#e7dce2}.tiny{font-size:10px;color:#8f808a;text-align:center;line-height:1.5;margin-top:11px}.state{text-align:center;padding:22px 12px}.state img{width:105px;height:105px;object-fit:contain;display:block;margin:0 auto 10px}.state .emoji{font-size:64px;margin:4px 0 12px}.state h2{font-size:22px;margin:0 0 7px}.state p{color:var(--muted);font-size:13px;line-height:1.55;margin:0 auto 16px;max-width:350px}.reward-pill{display:inline-flex;align-items:center;gap:8px;border:1px solid #70415a;background:#21131e;border-radius:999px;padding:10px 16px;color:#ffd36e;font-weight:850;margin-bottom:14px}.channel{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid rgba(110,52,77,.28)}.channel:last-child{border-bottom:0}.channel .name{flex:1;font-size:12px;font-weight:700;text-align:left}.join{border:1px solid #7f3653;background:#2a1522;color:#ffd9e5;border-radius:11px;padding:8px 12px;font-weight:850}.hidden{display:none!important}.provider-note{font-size:10px;color:#a58f9b;text-align:center;margin-top:4px}.spinner{width:45px;height:45px;border:4px solid #3b2434;border-top-color:#d04b70;border-right-color:#812946;border-radius:50%;animation:spin .9s linear infinite;margin:18px auto}@keyframes spin{to{transform:rotate(360deg)}}
</style></head><body><main><div class="wrap">
<div class="top"><div class="brand">🌹 Watch & Earn</div><div class="provider">Rewarded Ad · {{ provider_name }}</div></div>
<section id="main-card" class="card hero"><div id="hero-art">{{ hero_markup|safe }}</div><div class="title">Watch Ad & Earn KP</div><div class="sub">Complete a short rewarded ad and receive your KP reward after the provider confirms completion.</div><div class="stats"><div class="stat"><b id="reward">+{{ reward }}</b><span>KP / ad</span></div><div class="stat"><b id="limit">{{ daily_limit or '∞' }}</b><span>daily limit</span></div><div class="stat"><b id="cooldown">{{ cooldown }}s</b><span>cooldown</span></div></div></section>
<section id="req-card" class="card"><div class="section-title">Requirements</div><div id="reqs"></div></section>
<section id="actions"><button class="btn" id="watch">▶ Watch Ad</button><button class="btn secondary" id="close">Back to Bot</button><div class="tiny">Rewarded ads are optional. Your normal bot features do not depend on watching ads.</div></section>
<section id="state" class="card state hidden"></section>
<div class="provider-note">Powered by {{ provider_name }} · Rewarded Ad</div>
</div></main>
<script>
(()=>{const tg=window.Telegram&&window.Telegram.WebApp,watch=document.getElementById('watch'),actions=document.getElementById('actions'),mainCard=document.getElementById('main-card'),reqCard=document.getElementById('req-card'),reqs=document.getElementById('reqs'),state=document.getElementById('state');const assets={{ assets|tojson }};let cfg=null,rewarding=false;function closeApp(){try{if(tg&&typeof tg.close==='function'){tg.close();setTimeout(()=>{try{if(document.visibilityState!=='hidden'&&window.history.length>1)window.history.back()}catch(e){}},450);return}}catch(e){}try{if(window.history.length>1)window.history.back()}catch(e){}}function art(url,emoji){return url?`<img class="art" src="${url}" alt="">`:`<div class="fallback">${emoji}</div>`}function showState(t,p,url,emoji){state.classList.remove('hidden');mainCard.classList.add('hidden');reqCard.classList.add('hidden');actions.classList.add('hidden');state.innerHTML=`${art(url,emoji)}<h2>${t}</h2><p>${p}</p>`}function showMain(){state.classList.add('hidden');mainCard.classList.remove('hidden');reqCard.classList.remove('hidden');actions.classList.remove('hidden')}async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(j.error||'Request failed');e.data=j;throw e}return j}function renderReq(d){let h=`<div class="req"><div class="req-icon">📣</div><div class="req-main"><b>Join required channels</b><span>${d.force_join_count||0} channel(s)</span></div><div class="${d.force_join_ok?'check':'cross'}">${d.force_join_ok?'✓':'×'}</div></div>`;const rr=Number(d.required_referrals||0),rc=Number(d.referral_count||0);if(rr>0)h+=`<div class="req"><div class="req-icon">🔗</div><div class="req-main"><b>Referral requirement</b><span>${rc}/${rr} successful referrals</span></div><div class="${rc>=rr?'check':'cross'}">${rc>=rr?'✓':'×'}</div></div>`;reqs.innerHTML=h}function showRequirements(d){showState('Requirements Not Met','Complete the requirements below before watching rewarded ads.',(!d.force_join_ok?assets.channels:assets.requirements),'🔒');let h='';if(!d.force_join_ok&&(d.force_channels||[]).length){h+='<div style="text-align:left;margin:8px 0 12px">'+d.force_channels.map(c=>`<div class="channel"><div class="req-icon">📣</div><div class="name">${c.name||'Required Channel'}</div>${c.join_url?`<button class="join" data-url="${c.join_url}">Join</button>`:''}</div>`).join('')+'</div>'}if(Number(d.required_referrals||0)>0&&Number(d.referral_count||0)<Number(d.required_referrals||0))h+=`<div class="tiny">🔗 Referrals: ${d.referral_count||0}/${d.required_referrals}</div>`;state.innerHTML+=h+'<button class="btn secondary" id="again">Check Again</button><button class="btn secondary" id="back">Close</button>';document.querySelectorAll('[data-url]').forEach(b=>b.onclick=()=>{try{tg.openTelegramLink(b.dataset.url)}catch(e){window.open(b.dataset.url,'_blank')}});document.getElementById('again').onclick=load;document.getElementById('back').onclick=closeApp}function showCooldown(d){showState('Please Wait',`Your next rewarded ad will be available in ${d.remaining_text||d.remaining+' seconds'}.`,assets.cooldown,'⏳');state.innerHTML+='<button class="btn" id="back">Back to Bot</button>';document.getElementById('back').onclick=closeApp}function showDaily(d){showState('Daily Limit Reached',`You have completed the maximum of ${d.daily_limit} rewarded ads today.`,assets.cooldown,'⏳');state.innerHTML+='<button class="btn" id="back">Back to Bot</button>';document.getElementById('back').onclick=closeApp}async function load(){if(!tg||!tg.initData){showState('Open inside Telegram','This rewarded-ad Mini App must be opened from the Telegram bot.',assets.requirements,'🔒');return}tg.ready();tg.expand();try{cfg=await post('/api/ad/session',{initData:tg.initData});renderReq(cfg);watch.disabled=false;watch.textContent='▶ Watch Ad';watch.onclick=null;document.getElementById('reward').textContent='+'+cfg.reward;document.getElementById('limit').textContent=cfg.daily_limit||'∞';document.getElementById('cooldown').textContent=(cfg.cooldown_remaining||0)+'s'}catch(e){const d=e.data||{};cfg=d;renderReq(d);if(d.code==='requirements'){watch.disabled=false;watch.textContent='🔒 Requirements Not Met';watch.onclick=()=>showRequirements(d);return}if(d.code==='cooldown'){showCooldown(d);return}if(d.code==='daily_limit'){showDaily(d);return}showState('Unable to Prepare','Please return to the bot and try again.',assets.preparing,'⏳')}}async function reward(){if(rewarding||!cfg||!cfg.session_id)return;rewarding=true;showState('Verifying Reward','The provider confirmed the ad. Securing your KP reward…',assets.preparing,'⏳');try{const j=await post('/api/ad/reward',{initData:tg.initData,session_id:cfg.session_id});showState('Ad Completed',`You earned +${j.reward} KP. Your balance is now ${j.balance} KP.`,assets.completed,'✓');state.innerHTML+=`<div class="reward-pill">🌽 +${j.reward} KP</div><button class="btn" id="back">✈ Back to Bot</button><div class="tiny">This window will close automatically.</div>`;document.getElementById('back').onclick=closeApp;setTimeout(closeApp,2600)}catch(e){rewarding=false;showState('Reward Not Confirmed',e.message||'The reward could not be confirmed. Please try again.',assets.requirements,'⚠️');state.innerHTML+='<button class="btn" id="retry">Try Again</button><button class="btn secondary" id="back">Back to Bot</button>';document.getElementById('retry').onclick=load;document.getElementById('back').onclick=closeApp}}async function getProviderShow(){const started=Date.now();const fnName={{ show_function|tojson }};while(Date.now()-started<12000){const fn=window[fnName];if(typeof fn==='function')return fn;await new Promise(r=>setTimeout(r,250))}return null}watch.addEventListener('click',async()=>{if(!cfg||!cfg.eligible){showRequirements(cfg||{});return}if(rewarding)return;showState('Preparing Your Ad','We are preparing your '+(cfg.provider||'rewarded')+' experience.',assets.preparing,'⏳');const showAd=await getProviderShow();if(typeof showAd!=='function'){showState('Ad Service Unavailable',(cfg.provider||'Ad provider')+' could not finish loading. Please close this window and try again.',assets.preparing,'⚠️');state.innerHTML+='<button class="btn" id="retry">Try Again</button><button class="btn secondary" id="back">Back to Bot</button>';document.getElementById('retry').onclick=load;document.getElementById('back').onclick=closeApp;return}try{await showAd();await reward();return}catch(e){showState('Ad Not Completed','The rewarded ad was closed or not completed.',assets.hero,'⚠️');state.innerHTML+='<button class="btn" id="retry">Try Again</button><button class="btn secondary" id="back">Back to Bot</button>';document.getElementById('retry').onclick=load;document.getElementById('back').onclick=closeApp;return}});document.getElementById('close').onclick=closeApp;load()})();
</script></body></html>"""
    hero_markup=f'<img src="/ad-assets/hero" alt="Reward" class="art">' if assets.get("hero") else '<div class="fallback">🎁</div>'
    if cfg["provider"]=="GigaPub" and cfg["block_id"]:
        gp_id=cfg["gigapub_app_id"]
        ad_script=(f'<script data-project-id="{gp_id}">!function(){{var s=document.currentScript,p=s.getAttribute("data-project-id")||"default",d=["https://ad.gigapub.tech","https://ru-ad.gigapub.tech"],i=0,t,sc;function l(){{sc=document.createElement("script");sc.async=true;sc.src=d[i]+"/script?id="+encodeURIComponent(p);clearTimeout(t);t=setTimeout(function(){{sc.onload=sc.onerror=null;sc.src="";if(++i<d.length)l()}},15000);sc.onload=function(){{clearTimeout(t)}};sc.onerror=function(){{clearTimeout(t);if(++i<d.length)l()}};document.head.appendChild(sc)}}l()}}();</script>')
    elif cfg["provider"]=="Adexora" and cfg["block_id"]:
        ad_script=f'<script src="https://adexora.com/cdn/ads.js?id={cfg["adexora_app_id"]}"></script>'
    else:
        ad_script=""
    show_function="showGiga" if cfg["provider"]=="GigaPub" else "showAdexora"
    return render_template_string(html,block_id=cfg["block_id"],reward=cfg["reward_coins"],daily_limit=cfg["daily_limit"],cooldown=cfg["cooldown_seconds"],assets=asset_urls,hero_markup=hero_markup,provider_name=cfg["provider"],ad_script=ad_script,show_function=show_function)


@app.route("/api/ad/session", methods=["POST"])
def ad_session_api():
    data=request.get_json(silent=True) or {}
    tg_user=_telegram_webapp_user(data.get("initData", ""))
    if not tg_user:
        return jsonify({"error":"Invalid Telegram Mini App authentication."}), 401
    uid=int(tg_user["id"]); cfg=_ad_settings(); user=get_user(uid) or {}
    req_error=_ad_requirements_error(uid,cfg)
    force_count=force_channels_col.count_documents({}) if cfg["require_force_join"] else 0
    force_ok=(force_count==0) or check_all_force_channels(uid)
    ref_count=int(user.get("referral_count",0) or 0); rr=int(cfg.get("required_referrals",0) or 0)
    force_rows=[]
    if cfg["require_force_join"]:
        for ch in force_channels_col.find({}).limit(20):
            force_rows.append({"name": ch.get("name") or "Required Channel", "join_url": ch.get("join_url") or ""})
    common={"reward":cfg["reward_coins"],"daily_limit":cfg["daily_limit"],"cooldown":cfg["cooldown_seconds"],"cooldown_remaining":_ad_cooldown_remaining(uid,cfg),"required_referrals":rr,"referral_count":ref_count,"force_join_count":force_count,"force_join_ok":force_ok,"force_channels":force_rows,"block_id":cfg["block_id"],"provider":cfg["provider"],"eligible":False}
    if not cfg["enabled"]: common.update({"code":"disabled","error":"Rewarded ads are currently disabled."}); return jsonify(common),403
    if not cfg["block_id"]: common.update({"code":"not_configured","error":"Rewarded ads are not configured yet."}); return jsonify(common),403
    if req_error: common.update({"code":"requirements","error":req_error}); return jsonify(common),403
    remaining=common["cooldown_remaining"]
    if remaining>0: common.update({"code":"cooldown","error":f"Please wait {remaining} seconds before watching another ad.","remaining":remaining,"remaining_text":f"{remaining} seconds"}); return jsonify(common),403
    daily=_ad_daily_count(uid)
    if cfg["daily_limit"] and daily>=cfg["daily_limit"]: common.update({"code":"daily_limit","error":f"Today's ad limit ({cfg['daily_limit']}) has been reached.","daily_count":daily}); return jsonify(common),403
    ok,result=_ad_start_session(uid)
    if not ok: common["error"]=str(result); return jsonify(common),403
    common.update({"session_id":result,"eligible":True,"daily_count":daily})
    return jsonify(common)


@app.route("/api/ad/reward", methods=["POST"])
def ad_reward_api():
    data=request.get_json(silent=True) or {}
    tg_user=_telegram_webapp_user(data.get("initData", ""))
    if not tg_user:
        return jsonify({"error":"Invalid Telegram Mini App authentication."}), 401
    ok,result=_ad_reward_session(int(tg_user["id"]), data.get("session_id"))
    if not ok:
        return jsonify({"error":str(result)}), 403
    return jsonify({"ok":True,"reward":int(result),"already_rewarded":int(result)==0,"balance":get_coin_balance(int(tg_user["id"]))})


def ads_admin_text():
    cfg=_ad_settings(); s=get_settings()
    total=int(ad_watch_history_col.count_documents({"rewarded":True})); unique=int(len(ad_watch_history_col.distinct("user_id",{"rewarded":True})))
    coins=int(sum((r.get("reward",0) or 0) for r in ad_watch_history_col.find({"rewarded":True},{"reward":1}))) if total else 0
    return ("📺 *Rewarded Ad System*\n\n"
            f"🟢 Rewarded Ads: *{'ON' if cfg['enabled'] else 'OFF'}*\n"
            f"🎯 Active Provider: *{cfg['provider']}*\n"
            f"🟢 GigaPub: *{'ON' if s.get('gigapub_enabled',True) else 'OFF'}* · ID `{s.get('gigapub_app_id','8548')}`\n"
            f"🟣 Adexora: *{'ON' if s.get('adexora_enabled',True) else 'OFF'}* · ID `{s.get('adexora_app_id','2210')}`\n"
            f"🌐 Mini App: `{cfg['miniapp_url']}`\n"
            f"💰 Ad Reward: *{cfg['reward_coins']} coins / ad*\n"
            f"⏱️ Cooldown: *{cfg['cooldown_seconds']}s*\n"
            f"📅 Daily Limit: *{cfg['daily_limit'] or 'Unlimited'}*\n"
            f"🔗 Required Referrals: *{cfg.get('required_referrals',0)}* (0 = none)\n"
            f"📣 Force Join Required: *{'Yes' if cfg['require_force_join'] else 'No'}*\n\n"
            f"📊 Completed Ads: *{total}*\n👥 Unique Watchers: *{unique}*\n🪙 Coins Issued: *{coins}*")

def ads_admin_keyboard():
    cfg=_ad_settings(); s=get_settings(); gp=bool(s.get('gigapub_enabled',True)); ax=bool(s.get('adexora_enabled',True))
    m=InlineKeyboardMarkup(row_width=2)
    m.row(InlineKeyboardButton("🔴 Disable Ads" if cfg['enabled'] else "🟢 Enable Ads",callback_data="ads:toggle"),InlineKeyboardButton("⚙️ Settings",callback_data="ads:settings"))
    m.row(InlineKeyboardButton(("🔘 " if cfg['provider']=="GigaPub" else "⚪ ")+"Use GigaPub",callback_data="ads:provider:gigapub"),InlineKeyboardButton(("🔘 " if cfg['provider']=="Adexora" else "⚪ ")+"Use Adexora",callback_data="ads:provider:adexora"))
    m.row(InlineKeyboardButton("🟢 GigaPub ON" if gp else "⚫ GigaPub OFF",callback_data="ads:toggle:gigapub"),InlineKeyboardButton("🟢 Adexora ON" if ax else "⚫ Adexora OFF",callback_data="ads:toggle:adexora"))
    m.row(InlineKeyboardButton("🔑 GigaPub ID",callback_data="ads:id:gigapub"),InlineKeyboardButton("🔑 Adexora ID",callback_data="ads:id:adexora"))
    m.row(InlineKeyboardButton("🌐 Mini App URL",callback_data="ads:url"),InlineKeyboardButton("💰 Ad Reward",callback_data="ads:reward"))
    m.row(InlineKeyboardButton("⏱️ Cooldown",callback_data="ads:cooldown"),InlineKeyboardButton("📅 Daily Limit",callback_data="ads:limit"))
    m.row(InlineKeyboardButton("🖼️ UI Images",callback_data="ads:assets"),InlineKeyboardButton("🔗 Referral Req.",callback_data="ads:ref"))
    m.row(InlineKeyboardButton("📣 Force Join Req.",callback_data="ads:force"),InlineKeyboardButton("📢 Ad Notifications",callback_data="ads:notify"))
    m.row(InlineKeyboardButton("📊 Statistics",callback_data="ads:stats"),InlineKeyboardButton("👤 Watchers",callback_data="ads:watchers"))
    m.row(InlineKeyboardButton("🧪 Test Ad",callback_data="ads:test"),InlineKeyboardButton("🔄 Reset User",callback_data="ads:reset"))
    m.row(InlineKeyboardButton("🔙 Back",callback_data="admin:back"))
    return m


def ads_admin_menu():
    bot.send_message(ADMIN_ID, ads_admin_text(), reply_markup=ads_admin_keyboard(), parse_mode="Markdown")


def _ads_prompt(text, key, parser=None):
    msg=bot.send_message(ADMIN_ID, text)
    bot.register_next_step_handler(msg, lambda m, k=key, p=parser: save_ads_setting_step(m,k,p))


def save_ads_setting_step(message,key,parser=None):
    if message.from_user.id!=ADMIN_ID:return
    raw=(message.text or "").strip()
    try:
        value=parser(raw) if parser else raw
        if key in {"ad_reward_coins","ad_cooldown_seconds","ad_daily_limit","ad_session_ttl_seconds","ad_required_referrals"} and int(value)<0: raise ValueError
        if key == "ad_required_referrals":
            update_setting("ad_required_referrals", int(value))
            # Keep the legacy switch in sync for old code/settings readers.
            update_setting("ad_require_referral", int(value) > 0)
        else:
            update_setting(key,value)
            if key == "gigapub_app_id": update_setting("ad_block_id", str(value))
        bot.send_message(ADMIN_ID,"✅ Setting updated.")
        ads_admin_menu()
    except Exception:
        bot.send_message(ADMIN_ID,"❌ Invalid value. Please try again from Ad System.")


def ads_callback(call):
    bot.answer_callback_query(call.id)
    d=call.data
    if d=="ads:menu": return ads_admin_menu()
    if d=="ads:assets": return ads_assets_menu()
    if d.startswith("ads:asset:"):
        key=d.split(":",2)[2]
        if key not in AD_UI_ASSET_LABELS: return
        msg=bot.send_message(ADMIN_ID,f"🖼️ Upload image for *{AD_UI_ASSET_LABELS[key]}*.\n\nSend a photo/image document, or send `remove` to restore the fallback.",parse_mode="Markdown")
        bot.register_next_step_handler(msg,lambda m,k=key: save_ads_asset(m,k))
        return
    if d=="ads:toggle":
        new_value = not _ad_settings()["enabled"]
        update_setting("rewarded_ads_enabled", new_value)
        final_set_flag("rewarded_ads", new_value)
        return ads_admin_menu()
    if d=="ads:provider:gigapub": update_setting("ad_provider","GigaPub"); return ads_admin_menu()
    if d=="ads:provider:adexora": update_setting("ad_provider","Adexora"); return ads_admin_menu()
    if d=="ads:toggle:gigapub":
        new=not bool(get_settings().get("gigapub_enabled",True)); update_setting("gigapub_enabled",new)
        if not new and str(get_settings().get("ad_provider","GigaPub")).lower()=="gigapub" and bool(get_settings().get("adexora_enabled",True)): update_setting("ad_provider","Adexora")
        return ads_admin_menu()
    if d=="ads:toggle:adexora":
        new=not bool(get_settings().get("adexora_enabled",True)); update_setting("adexora_enabled",new)
        if not new and str(get_settings().get("ad_provider","GigaPub")).lower()=="adexora" and bool(get_settings().get("gigapub_enabled",True)): update_setting("ad_provider","GigaPub")
        return ads_admin_menu()
    if d=="ads:id:gigapub": return _ads_prompt("🔑 Send the GigaPub App ID.","gigapub_app_id")
    if d=="ads:id:adexora": return _ads_prompt("🔑 Send the Adexora App ID.","adexora_app_id")
    if d=="ads:block": return _ads_prompt("🔑 Send the GigaPub App ID.","gigapub_app_id")
    if d=="ads:url": return _ads_prompt("🌐 Send the full HTTPS Mini App URL.","ad_miniapp_url")
    if d=="ads:reward": return _ads_prompt("💰 Send coins awarded per completed ad.","ad_reward_coins",int)
    if d=="ads:cooldown": return _ads_prompt("⏱️ Send cooldown in seconds.","ad_cooldown_seconds",int)
    if d=="ads:limit": return _ads_prompt("📅 Send maximum completed ads per user per day. Use 0 for unlimited.","ad_daily_limit",int)
    if d=="ads:ref":
        return _ads_prompt(
            "🔗 Send the minimum successful referral count required before a user can watch an ad.\n\n"
            "Send `0` for no referral requirement.",
            "ad_required_referrals",
            int,
        )
    if d=="ads:force":
        update_setting("ad_require_force_join", not bool(get_settings().get("ad_require_force_join",True)))
        return ads_admin_menu()
    if d=="ads:notify":
        return bot.send_message(ADMIN_ID,"📢 Use *Ad Notifications* in the Separate Notifications menu to add/remove the ad-watch notification channel.",parse_mode="Markdown")
    if d=="ads:stats": return bot.send_message(ADMIN_ID,ads_admin_text(),parse_mode="Markdown")
    if d=="ads:watchers":
        rows=list(ad_watch_history_col.find({"rewarded":True}).sort("rewarded_at",DESCENDING).limit(30))
        if not rows:return bot.send_message(ADMIN_ID,"👤 No rewarded-ad watchers yet.")
        lines=["👤 *Recent Ad Watchers*",""]
        for r in rows:
            u=get_user(r.get("user_id")) or {}
            lines.append(f"• {user_display_name(u)} — `{r.get('user_id')}` — +{r.get('reward',0)} — {format_bot_time(r.get('rewarded_at'))}")
        return bot.send_message(ADMIN_ID,"\n".join(lines),parse_mode="Markdown")
    if d=="ads:reset": return _ads_prompt("🔄 Send the Telegram user ID whose daily ad limit/cooldown should be reset.","__ad_reset_user__",int)
    if d=="ads:test":
        cfg=_ad_settings()
        if not cfg["block_id"]: return bot.send_message(ADMIN_ID,"⚠️ Enable/configure at least one ad provider first.")
        test_markup=InlineKeyboardMarkup(row_width=1)
        test_markup.add(InlineKeyboardButton(f"🧪 Open {cfg['provider']} Test",web_app=WebAppInfo(url=cfg["miniapp_url"])))
        return bot.send_message(ADMIN_ID,f"🧪 *Rewarded Ad Test*\n\nProvider: *{cfg['provider']}*\nApp ID: `{cfg['block_id']}`\n\nOpen this from Telegram to test the real Mini App flow and reward session.",reply_markup=test_markup,parse_mode="Markdown")
    if d=="ads:settings": return ads_admin_menu()


def _handle_ads_reset_setting(message,key,value):
    if key=="__ad_reset_user__":
        uid=int(value)
        now=bot_time_now()
        ad_sessions_col.update_many({"user_id":uid,"rewarded":False},{"$set":{"expires_at":now}})
        ad_watch_history_col.delete_many({"user_id":uid,"rewarded_at":{"$gte":_ad_day_start()}})
        bot_users_col.update_one({"user_id":uid},{"$unset":{"last_ad_rewarded_at":""},"$set":{"ad_watch_count":0}})
        bot.send_message(ADMIN_ID,f"✅ Ad limit/cooldown data reset for `{uid}`.",parse_mode="Markdown")
        return ads_admin_menu()
    return None

# Re-wrap the generic setting saver so reset-user can be handled without
# disturbing any existing next-step handlers.
_old_save_ads_setting_step = save_ads_setting_step
def save_ads_setting_step(message,key,parser=None):
    if key=="__ad_reset_user__":
        if message.from_user.id!=ADMIN_ID:return
        try:return _handle_ads_reset_setting(message,key,int((message.text or '').strip()))
        except Exception:return bot.send_message(ADMIN_ID,"❌ Invalid Telegram user ID.")
    return _old_save_ads_setting_step(message,key,parser)



# =========================================================
# ADMIN MONGODB DATA MANAGER
# =========================================================
# This manager is intentionally admin-only and uses predefined operations rather
# than arbitrary MongoDB queries. That makes destructive actions much harder to
# trigger accidentally while still allowing very granular cleanup.
MONGO_DELETE_COLLECTIONS={
    "settings":settings_col,"users":users_col,"bot_users":bot_users_col,"channels":channels_col,"force_channels":force_channels_col,
    "coupons":coupons_col,"coupon_uses":coupon_uses_col,"feedback":feedback_col,"premium_plans":premium_plans_col,
    "premium_channels":premium_channels_col,"milestones":milestones_col,"milestone_claims":milestone_claims_col,
    "purchase_history":purchase_history_col,"coin_history":coin_history_col,"daily_claims":daily_claims_col,
    "audit_logs":audit_log_col,"notifications":notification_col,"feature_logs":feature_log_col,"admin_actions":admin_action_col,
    "user_history":user_history_col,"premium_history":premium_history_col,"announcements":announcement_col,"admin_roles":admin_roles_col,
    "support_tickets":support_tickets_col,"premium_delivery_messages":premium_delivery_col,
    "referral_notification_channels":referral_notification_channels_col,"safety_events":safety_events_col,
    "channel_monitor":channel_monitor_col,"notification_channels":notification_channels_col,"member_invite_jobs":member_invite_jobs_col,
    "forward_unlocks":forward_unlocks_col,"channel_content_stats":channel_content_stats_col,
    "channel_upload_notifications":channel_upload_notifications_col,"ad_sessions":ad_sessions_col,"ad_watch_history":ad_watch_history_col,
    "earning_tasks":tasks_col,"task_submissions":task_submissions_col,
    "daily_streaks":daily_streak_col,"lucky_spins":lucky_spin_col,"vip_levels":vip_col,"flash_deals":flash_deals_col,
    "premium_gifts":gift_col,"recovery_notifications":recovery_col,"referral_campaigns":referral_campaign_col,
    "security_events":security_col,"notification_preferences":notification_pref_col,"personal_coupons":user_coupon_col,
    "advanced_config":admin_config_col,"user_activity":user_activity_col,"spin_prizes":spin_prize_col,
}

# User-specific cleanup groups. Each group may touch several collections, but
# never affects another Telegram user.
MONGO_USER_GROUPS={
    "profile":("👤 Profile / Account", [
        (bot_users_col,"delete_user_doc"),(users_col,"delete_user_docs"),(notification_pref_col,"delete_user_docs"),
    ]),
    "coins":("🪙 Coin Balance & Coin Data", [
        (bot_users_col,"reset_coins"),(coin_history_col,"delete_user_docs"),(daily_claims_col,"delete_user_docs"),
        (daily_streak_col,"delete_user_docs"),(lucky_spin_col,"delete_user_docs"),(spin_prize_col,"delete_user_docs"),
    ]),
    "premium":("💎 Premium / Subscriptions", [
        (users_col,"delete_user_docs"),(premium_history_col,"delete_user_docs"),(purchase_history_col,"delete_user_docs"),
        (premium_delivery_col,"delete_user_docs"),(forward_unlocks_col,"delete_user_docs"),
    ]),
    "referrals":("👥 Referrals", [
        (bot_users_col,"unset_referral_fields"),(user_history_col,"delete_referral_history"),(referral_campaign_col,"delete_user_docs"),
    ]),
    "coupons":("🎟️ Coupon Usage", [
        (coupon_uses_col,"delete_user_docs"),(user_coupon_col,"delete_user_docs"),
    ]),
    "ads":("📺 Rewarded Ads", [
        (ad_sessions_col,"delete_user_docs"),(ad_watch_history_col,"delete_user_docs"),
    ]),
    "activity":("📜 User Activity / History", [
        (user_history_col,"delete_user_docs"),(user_activity_col,"delete_user_docs"),(feedback_col,"delete_user_docs"),
        (support_tickets_col,"delete_user_docs"),(recovery_col,"delete_user_docs"),
    ]),
    "security":("🛡️ Security / Notifications", [
        (security_col,"delete_user_docs"),(notification_col,"delete_user_docs"),(notification_pref_col,"delete_user_docs"),
    ]),
}

def mongo_data_menu(edit_message=None):
    m=InlineKeyboardMarkup(row_width=1)
    m.add(InlineKeyboardButton("👤 Specific User Data",callback_data="mongo:user"))
    m.add(InlineKeyboardButton("🔎 Users by Condition",callback_data="mongo:filter"))
    m.add(InlineKeyboardButton("🧾 Specific Document by _id",callback_data="mongo:doc"))
    m.add(InlineKeyboardButton("📦 Delete/Empty One Collection",callback_data="mongo:collection"))
    m.add(InlineKeyboardButton("☢️ DELETE ALL DATABASE DATA",callback_data="mongo:all"))
    m.add(InlineKeyboardButton("🔙 Back to Bot Settings",callback_data="mongo:settingsback"))
    text="🗑️ *MongoDB Data Manager*\n\nChoose exactly what you want to remove. User cleanup is separated into profile, coins, Premium, referrals, coupons, ads, activity, and security data. Every destructive operation requires confirmation."
    if edit_message:
        try: return bot.edit_message_text(text,edit_message.chat.id,edit_message.message_id,reply_markup=m,parse_mode="Markdown")
        except Exception: pass
    return bot.send_message(ADMIN_ID,text,reply_markup=m,parse_mode="Markdown")

def _mongo_collection_keyboard(prefix):
    m=InlineKeyboardMarkup(row_width=2)
    for name in MONGO_DELETE_COLLECTIONS:
        m.add(InlineKeyboardButton(name,callback_data=f"mongo:{prefix}:{name}"))
    m.add(InlineKeyboardButton("🔙 Back",callback_data="mongo:menu")); return m

def mongo_delete_document_prompt(collection_name):
    msg=bot.send_message(ADMIN_ID,f"🧾 Send the exact MongoDB `_id` for `{collection_name}`. ObjectId or string IDs are supported.",parse_mode="Markdown")
    bot.register_next_step_handler(msg,lambda m,c=collection_name:mongo_delete_document(m,c))

def mongo_delete_document(message,collection_name):
    if message.from_user.id!=ADMIN_ID or collection_name not in MONGO_DELETE_COLLECTIONS:return
    raw=(message.text or '').strip()
    col=MONGO_DELETE_COLLECTIONS[collection_name]
    q={"_id":ObjectId(raw)} if ObjectId.is_valid(raw) else {"_id":raw}
    doc=col.find_one(q)
    if not doc:return bot.send_message(ADMIN_ID,"❌ No document found with that exact `_id`.",parse_mode="Markdown")
    oid=str(doc.get('_id')); m=InlineKeyboardMarkup(row_width=2)
    m.row(InlineKeyboardButton("✅ DELETE",callback_data=f"mongo:confirmdoc:{collection_name}:{oid}"),InlineKeyboardButton("❌ Cancel",callback_data="mongo:menu"))
    bot.send_message(ADMIN_ID,f"⚠️ *Confirm deletion*\n\nCollection: `{collection_name}`\n_ID: `{oid}`\nUser ID: `{doc.get('user_id','-')}`\n\nThis deletes only this exact document.",reply_markup=m,parse_mode="Markdown")

def mongo_delete_user_prompt():
    msg=bot.send_message(ADMIN_ID,"👤 Send the Telegram user ID you want to manage.\n\nExample: `6284765303`",parse_mode="Markdown")
    bot.register_next_step_handler(msg,mongo_user_data_menu_for_message)

def _mongo_user_counts(uid):
    counts={}
    for name,col in MONGO_DELETE_COLLECTIONS.items():
        try:
            n=col.count_documents({"user_id":int(uid)})
            if n: counts[name]=n
        except Exception: pass
    return counts

def mongo_user_data_menu(uid,chat_id=ADMIN_ID):
    counts=_mongo_user_counts(uid); total=sum(counts.values())
    m=InlineKeyboardMarkup(row_width=2)
    for key,(label,ops) in MONGO_USER_GROUPS.items():
        n=0
        for col,mode in ops:
            try:
                if mode in {"reset_coins","unset_referral_fields"}: n += 1 if col.find_one({"user_id":int(uid)}) else 0
                elif mode=="delete_user_doc": n += 1 if col.find_one({"user_id":int(uid)}) else 0
                else: n += col.count_documents({"user_id":int(uid)})
            except Exception: pass
        m.add(InlineKeyboardButton(f"{label} · {n}",callback_data=f"mongo:ugroup:{key}:{int(uid)}"))
    m.add(InlineKeyboardButton(f"☢️ DELETE ALL DATA FOR USER · {total}",callback_data=f"mongo:confirmuser:{int(uid)}"))
    m.add(InlineKeyboardButton("🔙 MongoDB Manager",callback_data="mongo:menu"))
    summary="\n".join(f"• {k}: {v}" for k,v in counts.items()) or "No documents currently contain this user_id."
    return bot.send_message(chat_id,f"👤 *User Data Manager*\n\nTelegram ID: `{int(uid)}`\nTotal linked documents: *{total}*\n\n{summary}\n\nChoose a specific category below, or delete everything linked to this user.",reply_markup=m,parse_mode="Markdown")

def mongo_user_data_menu_for_message(message):
    if message.from_user.id!=ADMIN_ID:return
    try: uid=int((message.text or '').strip())
    except Exception:return bot.send_message(ADMIN_ID,"❌ Invalid Telegram user ID.")
    return mongo_user_data_menu(uid)

def _mongo_user_group_counts(uid,key):
    label,ops=MONGO_USER_GROUPS[key]; out=[]
    for col,mode in ops:
        try:
            if mode in {"reset_coins","unset_referral_fields","delete_user_doc"}:
                n=1 if col.find_one({"user_id":int(uid)}) else 0
            elif mode=="delete_referral_history":
                n=col.count_documents({"user_id":int(uid),"action":{"$regex":"referr","$options":"i"}})
            else: n=col.count_documents({"user_id":int(uid)})
            if n: out.append((col.name,n,mode))
        except Exception: pass
    return label,out

def mongo_confirm_user_group(uid,key):
    if key not in MONGO_USER_GROUPS:return
    label,rows=_mongo_user_group_counts(uid,key)
    if not rows:return bot.send_message(ADMIN_ID,f"ℹ️ No `{label}` data found for `{uid}`.",parse_mode="Markdown")
    lines=[f"⚠️ *Confirm: {label}*",f"User: `{uid}`",""]+[f"• {n}: {c}" for n,c,_ in rows]
    m=InlineKeyboardMarkup(row_width=2)
    m.row(InlineKeyboardButton("✅ DELETE THIS CATEGORY",callback_data=f"mongo:confirmugroup:{key}:{uid}"),InlineKeyboardButton("❌ Cancel",callback_data=f"mongo:usermenu:{uid}"))
    bot.send_message(ADMIN_ID,"\n".join(lines)+"\n\nOnly this category for this user will be affected.",reply_markup=m,parse_mode="Markdown")

def mongo_apply_user_group(uid,key):
    label,ops=MONGO_USER_GROUPS[key]; changed=0
    for col,mode in ops:
        try:
            if mode=="delete_user_doc": changed += int(col.delete_one({"user_id":int(uid)}).deleted_count)
            elif mode=="delete_user_docs": changed += int(col.delete_many({"user_id":int(uid)}).deleted_count)
            elif mode=="reset_coins":
                changed += int(col.update_many({"user_id":int(uid)}, {"$set":{"coins":0}}).modified_count)
            elif mode=="unset_referral_fields":
                changed += int(col.update_many({"user_id":int(uid)}, {"$unset":{"referral_count":"","valid_referrals":"","referred_by":"","referrals":"","referral_users":""}}).modified_count)
            elif mode=="delete_referral_history": changed += int(col.delete_many({"user_id":int(uid),"action":{"$regex":"referr","$options":"i"}}).deleted_count)
        except Exception: pass
    bot.send_message(ADMIN_ID,f"✅ *{label} cleanup complete.*\n\nUser: `{uid}`\nAffected records/fields: *{changed}*",parse_mode="Markdown")
    return mongo_user_data_menu(uid)

def mongo_user_filter_menu():
    m=InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton("🪙 With Coins",callback_data="mongo:filter:with_coins"),InlineKeyboardButton("⚪ Without Coins",callback_data="mongo:filter:without_coins"))
    m.add(InlineKeyboardButton("💎 With Premium",callback_data="mongo:filter:with_premium"),InlineKeyboardButton("⚪ Without Premium",callback_data="mongo:filter:without_premium"))
    m.add(InlineKeyboardButton("🚫 Banned",callback_data="mongo:filter:banned"),InlineKeyboardButton("🟢 Not Banned",callback_data="mongo:filter:not_banned"))
    m.add(InlineKeyboardButton("🔙 MongoDB Manager",callback_data="mongo:menu"))
    return bot.send_message(ADMIN_ID,"🔎 *User Conditions*\n\nChoose a condition to preview matching Telegram users. The next screen shows the exact count before any deletion.",reply_markup=m,parse_mode="Markdown")

def _mongo_matching_user_ids(key):
    if key=="with_coins":
        return [int(r["user_id"]) for r in bot_users_col.find({"coins":{"$gt":0}}, {"user_id":1}) if r.get("user_id") is not None]
    if key=="without_coins":
        return [int(r["user_id"]) for r in bot_users_col.find({"$or":[{"coins":{"$lte":0}},{"coins":{"$exists":False}}]}, {"user_id":1}) if r.get("user_id") is not None]
    if key=="banned":
        return [int(r["user_id"]) for r in bot_users_col.find({"banned":True}, {"user_id":1}) if r.get("user_id") is not None]
    if key=="not_banned":
        return [int(r["user_id"]) for r in bot_users_col.find({"banned":{"$ne":True}}, {"user_id":1}) if r.get("user_id") is not None]
    now=time.time()
    premium_ids={int(r["user_id"]) for r in users_col.find({"expiry":{"$gt":now}}, {"user_id":1}) if r.get("user_id") is not None}
    all_ids={int(r["user_id"]) for r in bot_users_col.find({}, {"user_id":1}) if r.get("user_id") is not None}
    if key=="with_premium": return sorted(premium_ids)
    if key=="without_premium": return sorted(all_ids-premium_ids)
    return []

def mongo_filter_preview(key):
    labels={"with_coins":"🪙 Users With Coins","without_coins":"⚪ Users Without Coins","with_premium":"💎 Users With Active Premium","without_premium":"⚪ Users Without Active Premium","banned":"🚫 Banned Users","not_banned":"🟢 Not Banned Users"}
    if key not in labels:return mongo_user_filter_menu()
    ids=_mongo_matching_user_ids(key)
    m=InlineKeyboardMarkup(row_width=2)
    m.row(InlineKeyboardButton("☢️ DELETE ALL MATCHING USERS",callback_data=f"mongo:confirmfilter:{key}"),InlineKeyboardButton("❌ Cancel",callback_data="mongo:filter"))
    bot.send_message(ADMIN_ID,f"⚠️ *{labels[key]}*\n\nMatching users: *{len(ids)}*\n\nDeletion removes all managed documents linked by `user_id` for every matching user. This is not reversible.",reply_markup=m,parse_mode="Markdown")

def mongo_delete_filter(key):
    ids=_mongo_matching_user_ids(key); deleted=0
    if not ids:
        return bot.send_message(ADMIN_ID,"ℹ️ No users match this condition.")
    for uid in ids:
        for col in MONGO_DELETE_COLLECTIONS.values():
            try: deleted += int(col.delete_many({"user_id":int(uid)}).deleted_count)
            except Exception: pass
    bot.send_message(ADMIN_ID,f"✅ Deleted linked data for *{len(ids)}* matching users.\n\nDocuments deleted: *{deleted}*.",parse_mode="Markdown")
    return mongo_data_menu()

def mongo_confirm_all():
    total=0; names=[]
    try:
        collection_names=db.list_collection_names()
    except Exception as e:
        return bot.send_message(ADMIN_ID,f"❌ Cannot list MongoDB collections: {type(e).__name__}: {str(e)[:200]}")
    for name in collection_names:
        try:
            n=db[name].count_documents({}); total+=n
            if n:names.append(f"• {name}: {n}")
        except Exception as e:
            names.append(f"• {name}: count failed ({type(e).__name__})")
    m=InlineKeyboardMarkup(row_width=2)
    m.row(InlineKeyboardButton("☢️ YES, DELETE EVERYTHING",callback_data="mongo:confirmall"),InlineKeyboardButton("❌ Cancel",callback_data="mongo:menu"))
    bot.send_message(ADMIN_ID,f"☢️ *FINAL DATABASE CONFIRMATION*\n\nYou are about to delete *{total} documents* from *all {len(collection_names)} collections* in database `{db.name}`.\n\n{chr(10).join(names[:60]) or 'No documents found.'}\n\nThis clears every collection in this bot database, including unknown/new collections. Collections remain but their documents are deleted. Settings/defaults may be recreated after the bot next runs.",reply_markup=m,parse_mode="Markdown")

def mongo_delete_all():
    deleted=0; errors=[]; cleared=[]
    try:
        client.admin.command("ping")
        collection_names=db.list_collection_names()
    except Exception as e:
        return bot.send_message(ADMIN_ID,f"❌ MongoDB collection listing failed: {type(e).__name__}: {str(e)[:200]}")
    for name in collection_names:
        try:
            result=db[name].delete_many({})
            deleted += int(result.deleted_count)
            cleared.append(name)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:160]}")
            print(f"MongoDB delete-all failed for {name}: {e}")
    status = "⚠️ *PARTIAL DATABASE CLEANUP*" if errors else "☢️ *MongoDB cleanup complete*"
    lines=[status, "", f"Deleted documents: *{deleted}*", f"Collections emptied: *{len(cleared)}/{len(collection_names)}*"]
    if errors:
        lines += ["", "*Collections with errors:*"] + [f"• `{e}`" for e in errors[:20]]
        lines += ["", "Check Render logs and MongoDB permissions/network access. Errors are reported rather than hidden."]
    else:
        lines += ["", "All collections in database `sub_management` were emptied. Default settings may be recreated by the bot."]
    bot.send_message(ADMIN_ID,"\n".join(lines),parse_mode="Markdown")
    return mongo_data_menu()

def mongo_callback(call):
    bot.answer_callback_query(call.id); d=call.data
    if d=="mongo:menu":return mongo_data_menu()
    if d=="mongo:settingsback":
        return bot.send_message(ADMIN_ID,"⚙️ *Bot Settings*",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ MongoDB Data Manager",callback_data="mongo:menu")]]),parse_mode="Markdown")
    if d=="mongo:doc":return bot.send_message(ADMIN_ID,"🧾 Select the collection:",reply_markup=_mongo_collection_keyboard("doc"))
    if d=="mongo:user":return mongo_delete_user_prompt()
    if d=="mongo:filter":return mongo_user_filter_menu()
    if d.startswith("mongo:filter:"):return mongo_filter_preview(d.split(":",2)[2])
    if d.startswith("mongo:confirmfilter:"):return mongo_delete_filter(d.split(":",2)[2])
    if d=="mongo:collection":return bot.send_message(ADMIN_ID,"📦 Select the collection to empty:",reply_markup=_mongo_collection_keyboard("collection"))
    if d=="mongo:all":return mongo_confirm_all()
    if d.startswith("mongo:doc:"):return mongo_delete_document_prompt(d.split(":",2)[2])
    if d.startswith("mongo:collection:"):return mongo_delete_collection_prompt(d.split(":",2)[2])
    if d.startswith("mongo:usermenu:"):return mongo_user_data_menu(int(d.split(":",2)[2]))
    if d.startswith("mongo:ugroup:"):
        _,_,key,uid=d.split(":",3); return mongo_confirm_user_group(int(uid),key)
    if d.startswith("mongo:confirmugroup:"):
        _,_,key,uid=d.split(":",3); return mongo_apply_user_group(int(uid),key)
    if d.startswith("mongo:confirmdoc:"):
        _,_,name,oid=d.split(":",3); col=MONGO_DELETE_COLLECTIONS.get(name)
        if not col:return
        q={"_id":ObjectId(oid)} if ObjectId.is_valid(oid) else {"_id":oid}; n=col.delete_one(q).deleted_count
        bot.send_message(ADMIN_ID,"✅ Document deleted." if n else "❌ Document no longer exists."); return mongo_data_menu()
    if d.startswith("mongo:confirmuser:"):
        uid=int(d.split(":",2)[2]); total=0
        for col in MONGO_DELETE_COLLECTIONS.values():
            try:total+=int(col.delete_many({"user_id":uid}).deleted_count)
            except Exception:pass
        bot.send_message(ADMIN_ID,f"✅ Deleted *{total}* user-linked documents for `{uid}`.",parse_mode="Markdown"); return mongo_data_menu()
    if d.startswith("mongo:confirmcol:"):
        name=d.split(":",2)[2]; col=MONGO_DELETE_COLLECTIONS.get(name)
        if not col:return
        n=col.delete_many({}).deleted_count; bot.send_message(ADMIN_ID,f"✅ Deleted *{n}* documents from `{name}`.",parse_mode="Markdown"); return mongo_data_menu()
    if d=="mongo:confirmall":return mongo_delete_all()

@bot.callback_query_handler(func=lambda c:c.from_user.id==ADMIN_ID and c.data.startswith("mongo:"))
def mongo_callback_router(call):return mongo_callback(call)

@bot.callback_query_handler(func=lambda c: c.data == "ads:user_cancel")
def ads_user_cancel_callback(call):
    bot.answer_callback_query(call.id, "Cancelled.")
    try:
        bot.edit_message_text("📺 Ad cancelled. You can watch one later using the 📺 Watch Ad button.", call.message.chat.id, call.message.message_id)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data.startswith("ads:"))
def ads_callback_router(call):
    return ads_callback(call)


# =========================================================
# FINAL REQUESTED ADMIN PANEL LINK LAYER
# =========================================================
FINAL_ADMIN_USERS = "👥 Users"
FINAL_ADMIN_PREMIUM = "📺 Premium & Channels"
FINAL_ADMIN_COINS = "🪙 Coins & Referrals"
FINAL_ADMIN_REWARDS = "🎁 Rewards"
FINAL_ADMIN_TICKETS = "🎟️ Support Tickets"
FINAL_ADMIN_BROADCAST = "📢 Broadcast & Announcements"
FINAL_ADMIN_COUPONS = "🎟️ Coupons"
FINAL_ADMIN_OFFERS = "🏷️ Offers & Discounts"
@bot.callback_query_handler(func=lambda c:c.from_user.id==ADMIN_ID and c.data=="welcome_coupon:amount")
def welcome_coupon_amount_prompt(call):
    bot.answer_callback_query(call.id)
    current=int(get_settings().get("welcome_coupon_discount",0) or 0)
    msg=bot.send_message(ADMIN_ID,f"🎁 *Welcome Premium Coin Reward*\n\nCurrent reward: *{current} {get_settings().get('coin_name', 'KP')}*\n\nSend the number of coins to credit to a new user after they join all force-join channels and verify. These are normal coins usable in Redeem Premium, NOT a price discount. Send `0` to disable.",parse_mode="Markdown")
    bot.register_next_step_handler(msg,save_welcome_coupon_amount)


def save_welcome_coupon_amount(message):
    if message.from_user.id!=ADMIN_ID:return
    try: amount=int((message.text or "").strip())
    except Exception: amount=-1
    if amount<0 or amount>100000000:
        msg=bot.send_message(ADMIN_ID,"Enter a whole number from 0 to 100000000 KP.")
        return bot.register_next_step_handler(msg,save_welcome_coupon_amount)
    update_setting("welcome_coupon_discount",amount)
    bot.send_message(ADMIN_ID,f"✅ Welcome Premium coin reward set to *{amount} {get_settings().get('coin_name', 'KP')}*. {'New verified users will receive this amount as normal coins for Premium redemption.' if amount else 'Automatic welcome coin rewards are now disabled.'}",parse_mode="Markdown")


# =========================================================
# ADMIN-CREATED EARNING TASKS
# =========================================================

def admin_tasks_menu():
    m=InlineKeyboardMarkup(row_width=1)
    m.add(InlineKeyboardButton("➕ Create Join Task (auto verify)", callback_data="taskadmin:create:join"))
    m.add(InlineKeyboardButton("➕ Create Manual Task (admin verifies)", callback_data="taskadmin:create:manual"))
    m.add(InlineKeyboardButton("📋 Manage Tasks", callback_data="taskadmin:list"))
    m.add(InlineKeyboardButton("🧾 Pending Submissions", callback_data="taskadmin:pending"))
    m.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="taskadmin:back"))
    return bot.send_message(ADMIN_ID,"🧩 *Earning Tasks*\n\nJoin tasks are checked through Telegram membership. Other tasks require admin approval of the user's submitted proof. The bot must be an admin in the target channel/group for reliable join verification.",reply_markup=m,parse_mode="Markdown")


def _task_admin_state(message, state):
    if message.from_user.id != ADMIN_ID: return
    task_admin_states[ADMIN_ID]=state


task_admin_states = {}


def _task_create_step_title(message, kind):
    if message.from_user.id != ADMIN_ID: return
    title=(message.text or "").strip()
    if len(title)<3 or title.startswith("/"):
        msg=bot.send_message(ADMIN_ID,"Please send a task title (at least 3 characters).")
        bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_title(m,k)); return
    state={"kind":kind,"title":title}
    task_admin_states[ADMIN_ID]=state
    prompt="Send the public channel/group username or numeric chat ID (example: @mychannel or -1001234567890)." if kind=="join" else "Send the task instructions and what proof users must submit."
    msg=bot.send_message(ADMIN_ID,prompt)
    bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_target(m,k))


def _task_create_step_target(message, kind):
    if message.from_user.id != ADMIN_ID: return
    state=task_admin_states.get(ADMIN_ID,{})
    if kind=="join":
        target=(message.text or "").strip()
        if not target:
            msg=bot.send_message(ADMIN_ID,"Invalid target. Send @username or numeric chat ID.")
            bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_target(m,k)); return
        state["chat_id"]=target
        state["instructions"]=f"Join {target}, then tap Verify Join."
        task_admin_states[ADMIN_ID]=state
        msg=bot.send_message(ADMIN_ID,"Send the join URL (for example https://t.me/channelname or a private invite link). For public @usernames, send - to use the username automatically.")
        return bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_join_url(m,k))
    else:
        state["instructions"]=(message.text or "").strip()
        if not state["instructions"]:
            msg=bot.send_message(ADMIN_ID,"Instructions cannot be empty. Send them again.")
            bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_target(m,k)); return
    task_admin_states[ADMIN_ID]=state
    msg=bot.send_message(ADMIN_ID,"How many coins should the user earn after completing this task? Send a positive whole number.")
    bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_reward(m,k))


def _task_create_step_join_url(message, kind):
    if message.from_user.id != ADMIN_ID:return
    state=task_admin_states.get(ADMIN_ID,{})
    raw=(message.text or "").strip()
    if raw != "-" and not raw.startswith(("https://t.me/","http://t.me/")):
        msg=bot.send_message(ADMIN_ID,"Send a Telegram invite URL starting with https://t.me/ or send - for a public @username.")
        return bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_join_url(m,k))
    if raw != "-":state["join_url"]=raw
    task_admin_states[ADMIN_ID]=state
    msg=bot.send_message(ADMIN_ID,"How many coins should the user earn after completing this task? Send a positive whole number.")
    return bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_reward(m,k))


def _task_create_step_reward(message, kind):
    if message.from_user.id != ADMIN_ID:return
    try: reward=int((message.text or "").strip())
    except Exception: reward=0
    if reward<=0 or reward>100000000:
        msg=bot.send_message(ADMIN_ID,"Reward must be a positive whole number (max 100,000,000). Send it again.")
        bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_reward(m,k)); return
    state=task_admin_states.pop(ADMIN_ID,{})
    state.update({"task_id":secrets.token_hex(5),"reward":reward,"kind":kind,"active":True,"created_at":datetime.now(),"created_by":ADMIN_ID,"completed_count":0})
    try:
        tasks_col.insert_one(state)
        bot.send_message(ADMIN_ID,f"✅ Task created.\n\nID: `{state['task_id']}`\nType: *{'Join (auto verify)' if kind=='join' else 'Manual approval'}*\nTitle: {state['title']}\nReward: {reward} KP",parse_mode="Markdown")
    except Exception as e:
        print(f"Task creation error: {e}"); bot.send_message(ADMIN_ID,"❌ Could not save task to MongoDB. Check Render logs and database permissions.")
    return admin_tasks_menu()


def show_user_tasks(user_id, chat_id=None):
    chat_id=chat_id or user_id
    rows=list(tasks_col.find({"active":True}).sort("created_at",-1).limit(50))
    if not rows:
        return bot.send_message(chat_id,"🧩 No earning tasks are available right now.")
    m=InlineKeyboardMarkup(row_width=1); lines=["🧩 *Available Tasks*",""]
    for task in rows:
        tid=task.get("task_id")
        done=task_submissions_col.find_one({"task_id":tid,"user_id":int(user_id),"status":{"$in":["approved","completed"]}})
        pending=task_submissions_col.find_one({"task_id":tid,"user_id":int(user_id),"status":"pending"})
        if done:
            status="✅ Completed"
        elif pending:
            status="⏳ Pending review"
        else:
            status=f"🪙 {int(task.get('reward',0))} KP"
            m.add(InlineKeyboardButton(f"{task.get('title','Task')} — {status}",callback_data=f"task:user:{tid}"))
        lines.append(f"• *{task.get('title','Task')}* — {status}")
    m.add(InlineKeyboardButton("🔄 Refresh",callback_data="task:userlist"))
    bot.send_message(chat_id,"\n".join(lines),reply_markup=m,parse_mode="Markdown")


def task_user_callback(call):
    data=call.data
    if data=="task:userlist":
        bot.answer_callback_query(call.id); return show_user_tasks(call.from_user.id,call.message.chat.id)
    tid=data.split(":",2)[2]
    task=tasks_col.find_one({"task_id":tid,"active":True})
    if not task:
        bot.answer_callback_query(call.id,"Task unavailable",show_alert=True); return
    uid=call.from_user.id
    existing=task_submissions_col.find_one({"task_id":tid,"user_id":uid,"status":{"$in":["approved","completed","pending"]}})
    if existing:
        bot.answer_callback_query(call.id,"Already completed or awaiting review.",show_alert=True); return
    m=InlineKeyboardMarkup(row_width=1)
    if task.get("kind")=="join":
        join_url=task.get("join_url") or ("https://t.me/"+str(task.get("chat_id","")).lstrip("@") if str(task.get("chat_id","")).startswith("@") else None)
        if join_url:m.add(InlineKeyboardButton("📢 Join Channel / Group",url=join_url))
        m.add(InlineKeyboardButton("✅ Verify Join",callback_data=f"task:verify:{tid}"))
        bot.answer_callback_query(call.id)
        return bot.send_message(uid,f"🧩 *{task.get('title')}*\n\n{task.get('instructions','Join the target chat, then verify.')}\n\nReward: *{task.get('reward',0)} KP*",reply_markup=m,parse_mode="Markdown")
    task_submission_states[uid]={"task_id":tid,"created_at":time.time()}
    bot.answer_callback_query(call.id)
    msg=bot.send_message(uid,f"🧩 *{task.get('title')}*\n\n{task.get('instructions','Complete this task and send proof.')}\n\nSend your proof now as a text message or photo caption. Admin will review it.",parse_mode="Markdown")


def task_verify_join(call):
    tid=call.data.split(":",2)[2]; uid=call.from_user.id
    task=tasks_col.find_one({"task_id":tid,"active":True,"kind":"join"})
    if not task:
        bot.answer_callback_query(call.id,"Task is unavailable.",show_alert=True); return
    try:
        member=bot.get_chat_member(task.get("chat_id"),uid)
        joined=member.status in ("creator","administrator","member") or (member.status=="restricted" and getattr(member,"is_member",False))
    except Exception as e:
        print(f"Task join verify error for {tid}/{uid}: {e}")
        bot.answer_callback_query(call.id,"Can't verify membership. Ensure the bot is an admin in that channel/group.",show_alert=True); return
    if not joined:
        bot.answer_callback_query(call.id,"Please join first, then verify again.",show_alert=True); return
    result=task_submissions_col.update_one({"task_id":tid,"user_id":uid},{"$setOnInsert":{"task_id":tid,"user_id":uid,"status":"completed","submitted_at":datetime.now(),"reviewed_at":datetime.now(),"kind":"join"}},upsert=True)
    if result.upserted_id:
        add_coins(uid,int(task.get("reward",0)))
        tasks_col.update_one({"task_id":tid},{"$inc":{"completed_count":1}})
        try: bot.send_message(uid,f"✅ Task completed! You earned {int(task.get('reward',0))} KP.")
        except Exception: pass
        bot.answer_callback_query(call.id,"Completed! Reward added.")
    else:
        bot.answer_callback_query(call.id,"This task was already claimed.",show_alert=True)


task_submission_states={}


@bot.message_handler(content_types=["text","photo"], func=lambda m:m.from_user.id != ADMIN_ID and m.from_user.id in task_submission_states)
def task_submission_message_router(message):
    uid=message.from_user.id
    if uid==ADMIN_ID or uid not in task_submission_states:return
    state=task_submission_states.pop(uid,None)
    if not state:return
    tid=state["task_id"]
    task=tasks_col.find_one({"task_id":tid,"active":True,"kind":"manual"})
    if not task:
        return bot.send_message(uid,"This task is no longer available. Open Earn by Tasks again.")
    proof=(message.caption or message.text or "").strip()
    file_id=message.photo[-1].file_id if message.content_type=="photo" and message.photo else None
    try:
        task_submissions_col.update_one({"task_id":tid,"user_id":uid},{"$setOnInsert":{"task_id":tid,"user_id":uid,"status":"pending","proof":proof,"photo_file_id":file_id,"submitted_at":datetime.now(),"kind":"manual"}},upsert=True)
        bot.send_message(uid,"📨 Proof submitted. Your task will be rewarded after admin approval.")
        admin=InlineKeyboardMarkup(row_width=2)
        admin.row(InlineKeyboardButton("✅ Approve",callback_data=f"taskadmin:approve:{tid}:{uid}"),InlineKeyboardButton("❌ Reject",callback_data=f"taskadmin:reject:{tid}:{uid}"))
        note=f"🧾 *Task submission*\nTask: {task.get('title')} (`{tid}`)\nUser: `{uid}`\nProof: {proof or '(photo attached)'}"
        bot.send_message(ADMIN_ID,note,reply_markup=admin,parse_mode="Markdown")
        if file_id: bot.send_photo(ADMIN_ID,file_id,caption=f"Task proof from {uid}")
    except Exception as e:
        print(f"Task submission save error: {e}"); bot.send_message(uid,"❌ Could not submit proof. Please try again.")


def task_admin_callback(call):
    d=call.data; bot.answer_callback_query(call.id)
    if d=="taskadmin:back":return final_show_admin_panel(ADMIN_ID)
    if d=="taskadmin:list":
        rows=list(tasks_col.find().sort("created_at",-1).limit(50))
        if not rows:return bot.send_message(ADMIN_ID,"No tasks found.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="taskadmin:back")]]))
        m=InlineKeyboardMarkup(row_width=1)
        for t in rows:
            m.add(InlineKeyboardButton(f"{'🟢' if t.get('active') else '🔴'} {t.get('title','Task')} · {t.get('reward',0)} KP",callback_data=f"taskadmin:toggle:{t.get('task_id')}"))
            m.add(InlineKeyboardButton(f"🗑️ Delete {t.get('task_id')}",callback_data=f"taskadmin:delete:{t.get('task_id')}"))
        m.add(InlineKeyboardButton("🔙 Back",callback_data="taskadmin:back"))
        return bot.send_message(ADMIN_ID,"📋 *Tasks — tap a task to enable/disable, or delete it below.*",reply_markup=m,parse_mode="Markdown")
    if d=="taskadmin:pending":
        rows=list(task_submissions_col.find({"status":"pending"}).sort("submitted_at",1).limit(30))
        if not rows:return bot.send_message(ADMIN_ID,"No pending submissions.")
        for sub in rows:
            task=tasks_col.find_one({"task_id":sub.get("task_id")}) or {}
            m=InlineKeyboardMarkup(row_width=2)
            m.row(InlineKeyboardButton("✅ Approve",callback_data=f"taskadmin:approve:{sub.get('task_id')}:{sub.get('user_id')}"),InlineKeyboardButton("❌ Reject",callback_data=f"taskadmin:reject:{sub.get('task_id')}:{sub.get('user_id')}"))
            bot.send_message(ADMIN_ID,f"🧾 Pending task: {task.get('title','Deleted task')}\nUser: `{sub.get('user_id')}`\nProof: {sub.get('proof') or '(photo attached)'}",reply_markup=m,parse_mode="Markdown")
            if sub.get("photo_file_id"):bot.send_photo(ADMIN_ID,sub["photo_file_id"])
        return
    if d.startswith("taskadmin:create:"):
        kind=d.split(":",2)[2]
        msg=bot.send_message(ADMIN_ID,"Send a short title for the new task.")
        return bot.register_next_step_handler(msg,lambda m,k=kind:_task_create_step_title(m,k))
    if d.startswith("taskadmin:approve:") or d.startswith("taskadmin:reject:"):
        parts=d.split(":")
        action=parts[1]; tid=parts[2]; uid=int(parts[3])
        sub=task_submissions_col.find_one({"task_id":tid,"user_id":uid,"status":"pending"})
        if not sub:return bot.send_message(ADMIN_ID,"Submission is no longer pending.")
        if action=="approve":
            task=tasks_col.find_one({"task_id":tid}) or {}
            changed=task_submissions_col.update_one({"_id":sub["_id"],"status":"pending"},{"$set":{"status":"approved","reviewed_at":datetime.now(),"reviewed_by":ADMIN_ID}}).modified_count
            if changed:
                add_coins(uid,int(task.get("reward",0))); tasks_col.update_one({"task_id":tid},{"$inc":{"completed_count":1}})
                bot.send_message(uid,f"✅ Your task was approved. You earned {int(task.get('reward',0))} KP.")
                return bot.send_message(ADMIN_ID,"Approved and reward credited.")
        else:
            task_submissions_col.update_one({"_id":sub["_id"],"status":"pending"},{"$set":{"status":"rejected","reviewed_at":datetime.now(),"reviewed_by":ADMIN_ID}})
            bot.send_message(uid,"❌ Your task submission was rejected. You may retry if the task is still available.")
            return bot.send_message(ADMIN_ID,"Submission rejected.")
    if d.startswith("taskadmin:toggle:"):
        tid=d.split(":",2)[2]; task=tasks_col.find_one({"task_id":tid})
        if task:tasks_col.update_one({"task_id":tid},{"$set":{"active":not bool(task.get('active',True))}})
        return admin_tasks_menu()
    if d.startswith("taskadmin:delete:"):
        tid=d.split(":",2)[2]; tasks_col.delete_one({"task_id":tid}); task_submissions_col.delete_many({"task_id":tid})
        return bot.send_message(ADMIN_ID,"Task and its submissions deleted.")


@bot.callback_query_handler(func=lambda c:c.from_user.id==ADMIN_ID and c.data.startswith("taskadmin:"))
def task_admin_router(call):return task_admin_callback(call)

@bot.callback_query_handler(func=lambda c:c.data == "task:userlist" or c.data.startswith("task:user:"))
def task_user_router(call):return task_user_callback(call)

@bot.callback_query_handler(func=lambda c:c.data.startswith("task:verify:"))
def task_join_verify_router(call):return task_verify_join(call)


FINAL_ADMIN_SETTINGS = "⚙️ Bot Settings"
FINAL_ADMIN_STATS = "📊 Statistics"
FINAL_ADMIN_LOGS = "📜 Activity Logs"

def final_admin_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.row(KeyboardButton(FINAL_ADMIN_USERS), KeyboardButton(FINAL_ADMIN_PREMIUM))
    m.row(KeyboardButton(FINAL_ADMIN_COINS), KeyboardButton(FINAL_ADMIN_REWARDS))
    m.row(KeyboardButton(FINAL_ADMIN_TICKETS), KeyboardButton(FINAL_ADMIN_BROADCAST))
    m.row(KeyboardButton(FINAL_ADMIN_COUPONS), KeyboardButton(FINAL_ADMIN_OFFERS))
    m.row(KeyboardButton(FINAL_ADMIN_SETTINGS), KeyboardButton(FINAL_ADMIN_STATS))
    m.row(KeyboardButton(ADMIN_TASKS), KeyboardButton("📺 Ad System"))
    m.row(KeyboardButton(FINAL_ADMIN_LOGS))
    m.row(KeyboardButton(ADMIN_MODE))
    return m


def final_show_admin_panel(chat_id):
    if chat_id != ADMIN_ID:
        return
    settings = get_settings()
    bot.send_message(
        chat_id,
        f"👑 *ADMIN PANEL*\n\n🌽 Currency: *{settings.get('coin_name','Coins')}*\n\n👇 Choose a section:",
        reply_markup=final_admin_keyboard(),
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text == FINAL_ADMIN_REWARDS)
def final_rewards_button_router(message):
    # Explicit final route for the new Admin Panel Rewards button.
    # This avoids collisions with older reward-menu handlers.
    return advanced_rewards_control(message.chat.id)


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.content_type == "text" and m.text in {
    FINAL_ADMIN_USERS, FINAL_ADMIN_PREMIUM, FINAL_ADMIN_COINS, FINAL_ADMIN_REWARDS,
    FINAL_ADMIN_TICKETS, FINAL_ADMIN_BROADCAST, FINAL_ADMIN_COUPONS, FINAL_ADMIN_OFFERS,
    FINAL_ADMIN_SETTINGS, FINAL_ADMIN_STATS, FINAL_ADMIN_LOGS
})
def final_requested_admin_router(message):
    t = message.text.strip()
    if message.from_user.id != ADMIN_ID:
        return
    if t == FINAL_ADMIN_USERS:
        return admin_users_menu(message)
    if t == FINAL_ADMIN_PREMIUM:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("➕ Add Paid Channel", callback_data="admin:add_paid_channel"), InlineKeyboardButton("📋 Paid Channels", callback_data="admin:list_paid_channels"))
        markup.row(InlineKeyboardButton("🎁 Premium Plans & Channels", callback_data="final:premium_menu"))
        markup.row(InlineKeyboardButton("📣 Force Join Channels", callback_data="safety:force_join"), InlineKeyboardButton("🛡️ Channel Monitor", callback_data="safety:monitor"))
        markup.row(InlineKeyboardButton("👥 Invite DB Users", callback_data="members:invite"), InlineKeyboardButton("🔓 Forward Unlock", callback_data="forward:info"))
        markup.row(InlineKeyboardButton("💰 Forward Cost", callback_data="forward:cost"))
        markup.row(InlineKeyboardButton("📦 Bulk Pricing", callback_data="premium:set_bulk_price"), InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
        return bot.send_message(ADMIN_ID, "📺 *Premium & Channels*\n\nManage both the original paid-channel system and the referral Premium system.\n\n🛡️ Force-join management and channel health monitoring are also available here.", reply_markup=markup, parse_mode="Markdown")
    if t == FINAL_ADMIN_COINS:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("🪙 Coin Settings", callback_data="settings:coins"), InlineKeyboardButton("🎯 Milestones", callback_data="milestone:manage"))
        markup.row(InlineKeyboardButton("📢 Notification Channels", callback_data="refnotify:menu"), InlineKeyboardButton("📊 Referral Stats", callback_data="users:stats"))
        markup.row(InlineKeyboardButton("📢 Separate Notifications", callback_data="notifych:menu"))
        markup.row(InlineKeyboardButton("📺 Ad System", callback_data="ads:menu"))
        markup.row(InlineKeyboardButton("🔗 Legacy Referral Log", callback_data="referral:set_log"))
        markup.row(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
        return bot.send_message(ADMIN_ID, "🪙 *Coins & Referrals*\n\nManage the existing coin, referral and milestone systems.", reply_markup=markup, parse_mode="Markdown")
    if t == FINAL_ADMIN_REWARDS:
        return advanced_rewards_control(ADMIN_ID)
    if t == FINAL_ADMIN_TICKETS:
        return admin_support_tickets_menu(message)
    if t == FINAL_ADMIN_BROADCAST:
        return advanced_target_broadcast_info(ADMIN_ID)
    if t == FINAL_ADMIN_COUPONS:
        return admin_coupons_menu(message)
    if t == FINAL_ADMIN_OFFERS:
        return advanced_deals_control(ADMIN_ID)
    if t == FINAL_ADMIN_SETTINGS:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.row(InlineKeyboardButton("🎛️ Feature Controls", callback_data="final:features"), InlineKeyboardButton("🛡️ Safety Controls", callback_data="safety:menu"))
        markup.row(InlineKeyboardButton("🕒 Timezone", callback_data="settings:timezone"), InlineKeyboardButton("🪙 Coin & Referral", callback_data="settings:coins"))
        markup.row(InlineKeyboardButton("✏️ Bot Texts", callback_data="settings:texts"))
        markup.row(InlineKeyboardButton("🔘 User Buttons", callback_data="settings:buttons"), InlineKeyboardButton("👮 Admin Roles", callback_data="roles:menu"))
        markup.row(InlineKeyboardButton("💬 Feedback", callback_data="settings:feedback"), InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
        markup.row(InlineKeyboardButton("🎁 Welcome Premium Coin Reward", callback_data="welcome_coupon:amount"))
        markup.row(InlineKeyboardButton("🗑️ MongoDB Data Manager", callback_data="mongo:menu"))
        return bot.send_message(ADMIN_ID, "⚙️ *Bot Settings*", reply_markup=markup, parse_mode="Markdown")
    if t == FINAL_ADMIN_STATS:
        return admin_statistics_handler(message)
    if t == ADMIN_TASKS:
        return admin_tasks_menu()
    if t == "📺 Ad System":
        return ads_admin_menu()
    if t == FINAL_ADMIN_LOGS:
        rows = list(audit_log_col.find().sort("created_at", DESCENDING).limit(30))
        if not rows:
            return bot.send_message(ADMIN_ID, "📜 *Activity Logs*\n\nNo activity logs yet.", parse_mode="Markdown")
        lines = ["📜 *Activity Logs*", ""]
        for r in rows:
            lines.append(f"• `{r.get('actor_id','-')}` — *{r.get('action','unknown')}* — {format_bot_time(r.get('created_at'))}")
        return bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="Markdown")



@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "final:premium_menu")
def final_premium_menu_callback(call):
    bot.answer_callback_query(call.id)
    return admin_premium_menu(call.message)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "forward:info")
def forward_unlock_admin_callback(call):
    bot.answer_callback_query(call.id)
    forward_unlock_info(ADMIN_ID, ADMIN_ID)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "forward:cost")
def forward_cost_admin_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, f"💰 Current forward unlock cost: *{forward_unlock_cost()} {get_settings().get('coin_name','KP')}*\n\nSend the new coin cost.", parse_mode="Markdown")
    bot.register_next_step_handler(msg, save_forward_unlock_cost)


def save_forward_unlock_cost(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        cost=int((message.text or '').strip())
        if cost < 0: raise ValueError
    except Exception:
        bot.send_message(ADMIN_ID, "❌ Send a valid non-negative coin amount.")
        return
    update_setting("forward_unlock_cost", cost)
    bot.send_message(ADMIN_ID, f"✅ Forward unlock cost set to *{cost} {get_settings().get('coin_name','KP')}*.", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "content:stats")
def content_stats_admin_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, _channel_content_stats_text(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "final:features")
def final_features_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, "🎛️ *Feature Controls*\n\nTurn user-visible features ON/OFF. Changes apply immediately.", reply_markup=final_feature_keyboard(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "roles:menu")
def roles_menu_callback(call):
    bot.answer_callback_query(call.id)
    return admin_roles_menu(call.message)


# =========================================================
# TELEGRAM SAFETY + CHANNEL MONITORING LAYER
# =========================================================
# This layer is intentionally conservative. It slows broadcasts, handles
# Telegram flood-wait responses, stops on repeated failures, records events,
# and monitors channels using information exposed by the Bot API. It does NOT
# attempt to bypass Telegram moderation, bans, or rate limits.


def _safety_settings():
    settings = get_settings() or {}
    defaults = DEFAULT_SETTINGS.get("safety", {}) or {}
    current = settings.get("safety", {}) or {}
    merged = dict(defaults)
    merged.update(current)
    return merged


def _record_safety_event(event_type, details=None, severity="info"):
    try:
        safety_events_col.insert_one({
            "event_type": str(event_type),
            "severity": str(severity),
            "details": details or {},
            "created_at": bot_time_now(),
        })
    except Exception as e:
        print(f"Safety event log error: {e}")


def _telegram_retry_after(exc):
    """Best-effort extraction of Telegram's RetryAfter value."""
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        try:
            return max(1, int(retry_after))
        except Exception:
            pass
    result_json = getattr(exc, "result_json", None) or {}
    try:
        return max(1, int((result_json.get("parameters") or {}).get("retry_after")))
    except Exception:
        return None


def _is_blocked_or_unreachable_error(exc):
    text = str(exc).lower()
    return any(x in text for x in (
        "bot was blocked by the user",
        "user is deactivated",
        "chat not found",
        "user not found",
        "forbidden: bot was blocked",
        "forbidden: user is deactivated",
    ))


def _mark_broadcast_unreachable(user_id, reason):
    try:
        bot_users_col.update_one(
            {"user_id": int(user_id)},
            {"$set": {
                "broadcast_unreachable": True,
                "broadcast_unreachable_reason": str(reason)[:300],
                "broadcast_unreachable_at": bot_time_now(),
            }}
        )
    except Exception:
        pass


def _broadcast_safety_notice(admin_id, target, total):
    cfg = _safety_settings()
    if not cfg.get("enabled", True):
        bot.send_message(admin_id, "⚠️ Safety layer is disabled. Broadcast was not started.")
        return False
    if total <= 0:
        bot.send_message(admin_id, "ℹ️ No eligible users in this audience.")
        return False
    bot.send_message(
        admin_id,
        f"🛡️ *Safety Check Passed*\n\n"
        f"Audience: *{_broadcast_target_label(target)}*\n"
        f"Eligible users: *{total}*\n"
        f"Delay: *{cfg.get('broadcast_delay_seconds', 0.35)}s/user*\n"
        f"Batch size: *{cfg.get('broadcast_batch_size', 25)}*\n\n"
        "The broadcast will automatically pause on Telegram FloodWait and stop if repeated failures indicate a problem.",
        parse_mode="Markdown",
    )
    return True


def _safe_broadcast_users(target):
    """Return eligible IDs while excluding banned/unreachable users."""
    users = _broadcast_target_users(target)
    if not users:
        return []
    rows = bot_users_col.find(
        {"user_id": {"$in": [int(x) for x in users]},
         "banned": {"$ne": True},
         "broadcast_unreachable": {"$ne": True}},
        {"user_id": 1},
    )
    return [int(r["user_id"]) for r in rows if r.get("user_id")]


def _run_safe_targeted_broadcast(message, target):
    if message.from_user.id != ADMIN_ID:
        return
    if not feature_enabled("broadcast", True):
        bot.send_message(ADMIN_ID, "⚠️ Broadcast is disabled in Feature Control.")
        return

    cfg = _safety_settings()
    if not cfg.get("enabled", True):
        bot.send_message(ADMIN_ID, "⚠️ Telegram Safety is disabled. Broadcast cancelled.")
        return

    users = _safe_broadcast_users(target)
    label = _broadcast_target_label(target)
    if not _broadcast_safety_notice(ADMIN_ID, target, len(users)):
        return

    sent = 0
    failed = 0
    unreachable = 0
    consecutive_failures = 0
    paused_for = 0
    batch_size = max(1, int(cfg.get("broadcast_batch_size", 25) or 25))
    delay = max(0.05, float(cfg.get("broadcast_delay_seconds", 0.35) or 0.35))
    batch_pause = max(0.0, float(cfg.get("broadcast_batch_pause_seconds", 2.0) or 2.0))
    max_failures = max(1, int(cfg.get("max_consecutive_failures", 20) or 20))

    _record_safety_event("broadcast_started", {
        "target": target, "target_label": label, "eligible": len(users)
    })

    for index, uid in enumerate(users, 1):
        try:
            bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
            consecutive_failures = 0
        except Exception as exc:
            failed += 1
            consecutive_failures += 1
            if _is_blocked_or_unreachable_error(exc):
                unreachable += 1
                _mark_broadcast_unreachable(uid, exc)
            retry_after = _telegram_retry_after(exc)
            if retry_after and cfg.get("auto_pause_on_floodwait", True):
                paused_for = retry_after
                _record_safety_event("flood_wait", {
                    "target": target, "user_id": uid, "retry_after": retry_after
                }, "warning")
                bot.send_message(
                    ADMIN_ID,
                    f"⏸️ *Broadcast paused by Telegram FloodWait*\n\nWaiting *{retry_after} seconds* before continuing.",
                    parse_mode="Markdown",
                )
                time.sleep(retry_after + 1)
            if consecutive_failures >= max_failures:
                _record_safety_event("broadcast_auto_paused", {
                    "target": target,
                    "consecutive_failures": consecutive_failures,
                }, "critical")
                bot.send_message(
                    ADMIN_ID,
                    f"🛑 *Broadcast automatically stopped*\n\n"
                    f"Reason: *{consecutive_failures} consecutive failures*.\n"
                    f"Sent: *{sent}* | Failed: *{failed}*\n\n"
                    "Check Telegram/API status and the Activity Logs before restarting.",
                    parse_mode="Markdown",
                )
                break

        if index % batch_size == 0 and index < len(users):
            time.sleep(batch_pause)
        else:
            time.sleep(delay)

    announcement_col.insert_one({
        "admin_id": ADMIN_ID,
        "target": target,
        "target_label": label,
        "text": message.text or message.caption or f"[{message.content_type}]",
        "content_type": message.content_type,
        "sent": sent,
        "failed": failed,
        "unreachable": unreachable,
        "paused_for": paused_for,
        "eligible": len(users),
        "safety_layer": True,
        "created_at": bot_time_now(),
        "source": "safe_final_admin_targeted_broadcast",
    })
    write_audit(ADMIN_ID, "safe_targeted_broadcast", {
        "target": target,
        "sent": sent,
        "failed": failed,
        "unreachable": unreachable,
        "eligible": len(users),
    })
    _record_safety_event("broadcast_finished", {
        "target": target, "sent": sent, "failed": failed,
        "unreachable": unreachable, "eligible": len(users),
    })
    bot.send_message(
        ADMIN_ID,
        f"📢 *{label} broadcast finished*\n\n"
        f"👥 Eligible: *{len(users)}*\n"
        f"✅ Sent: *{sent}*\n"
        f"❌ Failed: *{failed}*\n"
        f"🚫 Unreachable/blocked: *{unreachable}*",
        parse_mode="Markdown",
    )
    final_broadcast_menu(ADMIN_ID)


# Override the final broadcast next-step target without deleting the original
# implementation. The existing button flow calls this global at execution time.
def final_targeted_broadcast_receive(message, target):
    return _run_safe_targeted_broadcast(message, target)


def broadcast_message(message):
    """Safety-wrapped compatibility handler for the legacy broadcast button."""
    return _run_safe_targeted_broadcast(message, "all")


def _channel_display_name(row):
    return row.get("name") or row.get("title") or str(row.get("channel_id"))


def _check_managed_channel(row):
    """Check channel health using Bot API-visible state only."""
    cid = row.get("channel_id")
    result = {
        "channel_id": cid,
        "name": _channel_display_name(row),
        "ok": False,
        "chat_type": None,
        "member_count": None,
        "bot_status": None,
        "bot_can_manage_chat": False,
        "bot_can_invite": False,
        "error": None,
    }
    try:
        chat = bot.get_chat(cid)
        result["chat_type"] = getattr(chat, "type", None)
        try:
            result["member_count"] = bot.get_chat_member_count(cid)
        except Exception:
            pass
        me = bot.get_me()
        member = bot.get_chat_member(cid, me.id)
        result["bot_status"] = getattr(member, "status", None)
        privileges = getattr(member, "privileges", None)
        result["bot_can_manage_chat"] = bool(getattr(privileges, "can_manage_chat", False))
        result["bot_can_invite"] = bool(
            getattr(privileges, "can_invite_users", False)
            or getattr(privileges, "can_post_messages", False)
            or result["bot_status"] in ("creator", "administrator")
        )
        result["ok"] = result["bot_status"] in ("creator", "administrator")
        if row.get("join_url"):
            result["join_url"] = row.get("join_url")
    except Exception as exc:
        result["error"] = str(exc)[:500]
    return result


def channel_monitor_snapshot(notify=True):
    """Monitor configured Force-Join and Premium channels.

    Telegram's Bot API does not expose a generic counter for reports against a
    channel/bot. We therefore monitor observable operational signals instead:
    accessibility, bot admin status/rights, member count, and API errors.
    """
    if not _safety_settings().get("monitor_channels", True):
        return []

    rows = []
    seen = set()
    for collection_name, collection in (("force_join", force_channels_col), ("premium", premium_channels_col)):
        try:
            docs = list(collection.find())
        except Exception:
            docs = []
        for row in docs:
            cid = row.get("channel_id")
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            checked = _check_managed_channel(row)
            checked["source"] = collection_name
            rows.append(checked)

    now = bot_time_now()
    for item in rows:
        previous = channel_monitor_col.find_one({"channel_id": item["channel_id"]})
        changed = bool(previous and (
            previous.get("ok") != item.get("ok")
            or previous.get("bot_status") != item.get("bot_status")
            or previous.get("bot_can_manage_chat") != item.get("bot_can_manage_chat")
            or previous.get("error") != item.get("error")
        ))
        channel_monitor_col.update_one(
            {"channel_id": item["channel_id"]},
            {"$set": {**item, "checked_at": now, "status_changed": changed},
             "$setOnInsert": {"first_seen": now}},
            upsert=True,
        )
        if item.get("ok"):
            _record_safety_event("channel_health_check", {
                "channel_id": item["channel_id"], "name": item["name"],
                "member_count": item.get("member_count"),
                "bot_status": item.get("bot_status"),
            })
        else:
            _record_safety_event("channel_health_problem", item, "warning")

        if notify and (not previous or changed) and _safety_settings().get("notify_on_status_change", True):
            if item.get("ok"):
                text = (
                    f"🟢 *Channel Monitor — Healthy*\n\n"
                    f"📺 {item['name']}\n"
                    f"🆔 `{item['channel_id']}`\n"
                    f"👤 Members: *{item.get('member_count', 'Unknown')}*\n"
                    f"🤖 Bot status: *{item.get('bot_status', 'Unknown')}*"
                )
            else:
                text = (
                    f"🔴 *Channel Monitor — Attention Required*\n\n"
                    f"📺 {item['name']}\n"
                    f"🆔 `{item['channel_id']}`\n"
                    f"🤖 Bot status: *{item.get('bot_status', 'Unknown')}*\n"
                    f"🛡️ Can manage chat: *{item.get('bot_can_manage_chat', False)}*\n"
                    f"❌ Error: `{str(item.get('error') or 'Bot may no longer be an administrator/access may be restricted')[:300]}`"
                )
            try:
                bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
            except Exception:
                pass
    return rows


def channel_monitor_text():
    rows = list(channel_monitor_col.find().sort("name", 1))
    if not rows:
        rows = channel_monitor_snapshot(notify=False)
    if not rows:
        return "🛡️ *Channel Monitor*\n\nNo Force-Join or Premium channels are configured."
    lines = ["🛡️ *Channel Monitor*", ""]
    for row in rows:
        icon = "🟢" if row.get("ok") else "🔴"
        lines.extend([
            f"{icon} *{row.get('name', row.get('channel_id'))}*",
            f"🆔 `{row.get('channel_id')}`",
            f"👥 Members: *{row.get('member_count', 'Unknown')}*",
            f"🤖 Bot: *{row.get('bot_status', 'Unknown')}*",
            f"🛡️ Manage: *{'YES' if row.get('bot_can_manage_chat') else 'NO'}*",
            "",
        ])
    return "\n".join(lines)


def force_join_admin_text():
    rows = list(force_channels_col.find().sort("name", 1))
    if not rows:
        return "📣 *Force-Join Channels*\n\nNo required channels configured yet."
    lines = ["📣 *Force-Join Channels*", ""]
    for row in rows:
        lines.append(f"• *{row.get('name', 'Channel')}* — `{row.get('channel_id')}`")
        if row.get("join_url"):
            lines.append(f"  🔗 {row.get('join_url')}")
    return "\n".join(lines)


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "safety:force_join")
def safety_force_join_menu_callback(call):
    bot.answer_callback_query(call.id)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("➕ Add Required Channel", callback_data="verify:add"),
        InlineKeyboardButton("🗑️ Remove / Manage", callback_data="verify:manage"),
    )
    markup.row(InlineKeyboardButton("🔄 Check Now", callback_data="safety:monitor:refresh"))
    markup.row(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    bot.send_message(
        ADMIN_ID,
        force_join_admin_text(),
        reply_markup=markup,
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "safety:monitor")
def safety_monitor_callback(call):
    bot.answer_callback_query(call.id)
    channel_monitor_snapshot(notify=False)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(InlineKeyboardButton("🔄 Refresh", callback_data="safety:monitor:refresh"))
    markup.row(InlineKeyboardButton("📣 Force-Join Channels", callback_data="safety:force_join"))
    markup.row(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    bot.send_message(ADMIN_ID, channel_monitor_text(), reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "safety:monitor:refresh")
def safety_monitor_refresh_callback(call):
    bot.answer_callback_query(call.id, "Checking channels…")
    channel_monitor_snapshot(notify=True)
    bot.send_message(ADMIN_ID, channel_monitor_text(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.from_user.id == ADMIN_ID and c.data == "safety:menu")
def safety_menu_callback(call):
    bot.answer_callback_query(call.id)
    cfg = _safety_settings()
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton("📣 Force-Join", callback_data="safety:force_join"),
        InlineKeyboardButton("🛡️ Channel Monitor", callback_data="safety:monitor"),
    )
    markup.row(InlineKeyboardButton("🔄 Run Monitor Now", callback_data="safety:monitor:refresh"))
    markup.row(InlineKeyboardButton("🔙 Back", callback_data="admin:back"))
    bot.send_message(
        ADMIN_ID,
        "🛡️ *Telegram Safety Controls*\n\n"
        f"Safety layer: *{'ON' if cfg.get('enabled', True) else 'OFF'}*\n"
        f"Broadcast delay: *{cfg.get('broadcast_delay_seconds', 0.35)}s*\n"
        f"Batch size: *{cfg.get('broadcast_batch_size', 25)}*\n"
        f"FloodWait auto-pause: *{'ON' if cfg.get('auto_pause_on_floodwait', True) else 'OFF'}*\n"
        f"Channel monitoring: *{'ON' if cfg.get('monitor_channels', True) else 'OFF'}*\n\n"
        "The safety layer does not bypass Telegram limits or moderation.",
        reply_markup=markup,
        parse_mode="Markdown",
    )


def run_channel_monitoring_job():
    try:
        channel_monitor_snapshot(notify=True)
    except Exception as e:
        _record_safety_event("channel_monitor_job_error", {"error": str(e)}, "critical")
        try:
            bot.send_message(ADMIN_ID, f"🔴 Channel monitor job error: `{str(e)[:500]}`", parse_mode="Markdown")
        except Exception:
            pass


if __name__ == "__main__":

    keep_alive()

    get_settings()
    setup_database()
    initialize_advanced_defaults()
    ensure_final_feature_flags()

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
        cleanup_premium_delivery_messages,
        "interval",
        seconds=10,
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

    scheduler.add_job(
        run_advanced_maintenance,
        "interval",
        minutes=5,
        id="advanced_maintenance",
        max_instances=1,
        replace_existing=True
    )

    scheduler.add_job(
        run_channel_monitoring_job,
        "interval",
        minutes=15,
        id="channel_monitoring",
        max_instances=1,
        replace_existing=True
    )

    scheduler.add_job(
        run_coin_report_job,
        "interval",
        hours=3,
        id="user_coin_report",
        max_instances=1,
        replace_existing=True
    )

    scheduler.start()

    _prioritize_advanced_handlers()

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


