#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import uuid
import random
import asyncio
import threading
from datetime import datetime

import psutil
from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    ClientForbiddenError,
    LoginRequired,
    PleaseWaitFewMinutes,
    RateLimitError,
    TwoFactorRequired,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ======================== CONFIG ========================

BOT_TOKEN = os.environ.get("TG_TOKEN", "").strip()
RAW_ADMINS = os.environ.get("ADMIN_IDS", "").strip()
ADMIN_IDS = {int(x.strip()) for x in RAW_ADMINS.split(",") if x.strip().isdigit()}

DATA_DIR = os.environ.get("DATA_DIR", "/data" if os.path.isdir("/data") else "./data")
os.makedirs(DATA_DIR, exist_ok=True)
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
TEMPLATE_FILE = os.path.join(DATA_DIR, "template.json")

BASE_TEMPLATE = """<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -⚡-





<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -🌀-





<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -🪷-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -🌱-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -😂-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -🤣-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -🥳-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -❄️-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -☔-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -🌈-






<{TARGET}> Kɪ Mᴀᴀ Mᴏᴛɪ !< Gᴀɴᴅ Wᴀʟɪ> Rᴀɴᴅ!> -🌒-"""

MAX_RETRIES = 5

IG_APP_PROFILES = [
    {
        "app_version": "312.0.0.29.111",
        "version_code": "538748192",
        "android_version": 33,
        "android_release": "13",
        "dpi": "420dpi",
        "resolution": "1080x2400",
        "manufacturer": "Samsung",
        "device": "SM-S918B",
        "model": "SM-S918B",
        "cpu": "qcom",
    },
    {
        "app_version": "315.0.0.25.109",
        "version_code": "544912830",
        "android_version": 34,
        "android_release": "14",
        "dpi": "440dpi",
        "resolution": "1080x2400",
        "manufacturer": "Google",
        "device": "husky",
        "model": "Pixel 8 Pro",
        "cpu": "tensor",
    },
    {
        "app_version": "310.0.0.32.104",
        "version_code": "534119022",
        "android_version": 33,
        "android_release": "13",
        "dpi": "480dpi",
        "resolution": "1080x2340",
        "manufacturer": "OnePlus",
        "device": "CPH2451",
        "model": "CPH2451",
        "cpu": "qcom",
    },
]

# Conversation states
(
    STATE_USERNAME,
    STATE_PASSWORD,
    STATE_2FA,
    STATE_SESSION_ID,
    STATE_MANUAL_THREADS,
    STATE_TARGET,
    STATE_EDIT_TEMPLATE,
) = range(7)

active_tasks = {}
tasks_lock = threading.Lock()
store_lock = threading.Lock()
pending_logins = {}
GLOBAL_MESSAGES_SENT = 0
BOT_START_TIME = datetime.now()


# ======================== PERSISTENCE ========================

def load_saved_accounts() -> dict:
    with store_lock:
        if not os.path.exists(ACCOUNTS_FILE):
            return {}
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def register_saved_account(username: str, ig_user_id=None, auth_method: str = "password"):
    with store_lock:
        accounts = {}
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        accounts = loaded
            except Exception:
                accounts = {}

        prev = accounts.get(username, {})
        accounts[username] = {
            "username": username,
            "ig_user_id": ig_user_id or prev.get("ig_user_id"),
            "auth_method": auth_method,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)


def remove_saved_account(username: str):
    with store_lock:
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    accounts = json.load(f)
                if isinstance(accounts, dict) and username in accounts:
                    del accounts[username]
                    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                        json.dump(accounts, f, indent=2)
            except Exception:
                pass
        session_path = os.path.join(DATA_DIR, f"ig_{username}.json")
        if os.path.exists(session_path):
            try:
                os.remove(session_path)
            except Exception:
                pass


def get_active_template() -> str:
    with store_lock:
        if os.path.exists(TEMPLATE_FILE):
            try:
                with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                tpl = payload.get("template")
                if isinstance(tpl, str) and tpl.strip():
                    return tpl
            except Exception:
                pass
        return BASE_TEMPLATE


def set_active_template(tpl: str):
    with store_lock:
        with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"template": tpl, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)


def reset_active_template():
    with store_lock:
        if os.path.exists(TEMPLATE_FILE):
            try:
                os.remove(TEMPLATE_FILE)
            except Exception:
                pass


# ======================== IG VERSION & SESSION HELPERS ========================

def is_outdated_app_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        phrase in msg
        for phrase in (
            "out of date",
            "outdated",
            "update your app",
            "upgrade your app",
            "client is too old",
            "app version",
        )
    )


def apply_fresh_ig_headers(client: Client, profile_idx: int | None = None):
    prof = (
        IG_APP_PROFILES[profile_idx % len(IG_APP_PROFILES)]
        if profile_idx is not None
        else random.choice(IG_APP_PROFILES)
    )
    client.delay_range = [0, 0]

    if hasattr(client, "app_version"):
        client.app_version = prof["app_version"]
    if hasattr(client, "version_code"):
        client.version_code = prof["version_code"]
    if hasattr(client, "android_version"):
        client.android_version = prof["android_version"]
    if hasattr(client, "android_release"):
        client.android_release = prof["android_release"]
    if hasattr(client, "phone_dpi"):
        client.phone_dpi = prof["dpi"]
    if hasattr(client, "phone_resolution"):
        client.phone_resolution = prof["resolution"]
    if hasattr(client, "phone_manufacturer"):
        client.phone_manufacturer = prof["manufacturer"]
    if hasattr(client, "phone_device"):
        client.phone_device = prof["device"]
    if hasattr(client, "phone_model"):
        client.phone_model = prof["model"]
    if hasattr(client, "cpu"):
        client.cpu = prof["cpu"]

    ua = (
        f"Instagram {prof['app_version']} Android "
        f"({prof['android_version']}/{prof['android_release']}; "
        f"{prof['dpi']}; {prof['resolution']}; {prof['manufacturer']}; "
        f"{prof['device']}; {prof['model']}; {prof['cpu']}; en_US; {prof['version_code']})"
    )
    try:
        client.set_user_agent(ua)
    except Exception:
        pass
    try:
        if hasattr(client, "private") and hasattr(client.private, "headers"):
            client.private.headers["User-Agent"] = ua
            client.private.headers["X-IG-App-ID"] = "936619743392459"
    except Exception:
        pass


def clean_session_id_input(raw: str) -> str:
    val = raw.strip().strip('"').strip("'")
    if "sessionid=" in val:
        part = val.split("sessionid=", 1)[1]
        val = part.split(";", 1)[0].strip()
    return val


def resolve_username_from_client(client: Client, fallback: str = "") -> str:
    if fallback:
        return fallback.lstrip("@")
    u = getattr(client, "username", None)
    if isinstance(u, str) and u.strip():
        return u.strip().lstrip("@")
    try:
        info = client.account_info()
        u = getattr(info, "username", None)
        if u:
            return str(u).strip().lstrip("@")
    except Exception:
        pass
    try:
        if getattr(client, "user_id", None):
            uinfo = client.user_info(client.user_id)
            u = getattr(uinfo, "username", None)
            if u:
                return str(u).strip().lstrip("@")
    except Exception:
        pass
    return f"user_{getattr(client, 'user_id', 'session')}"


def build_client_with_session(username: str | None = None, profile_idx: int | None = None) -> Client:
    client = Client()
    apply_fresh_ig_headers(client, profile_idx=profile_idx)
    if username:
        session_path = os.path.join(DATA_DIR, f"ig_{username}.json")
        if os.path.exists(session_path):
            try:
                client.load_settings(session_path)
                apply_fresh_ig_headers(client, profile_idx=profile_idx)
            except Exception:
                pass
    return client


def save_client_session(client: Client, username: str, auth_method: str = "password"):
    session_path = os.path.join(DATA_DIR, f"ig_{username}.json")
    try:
        client.dump_settings(session_path)
        register_saved_account(username, getattr(client, "user_id", None), auth_method=auth_method)
    except Exception:
        pass


def login_with_password_and_retry(client: Client, username: str, password: str, code: str | None = None):
    last_exc = None
    for idx in range(len(IG_APP_PROFILES)):
        if idx > 0:
            apply_fresh_ig_headers(client, profile_idx=idx)
        try:
            if code:
                client.login(username, password, verification_code=code)
            else:
                client.login(username, password)
            return client
        except TwoFactorRequired:
            raise
        except BadPassword:
            raise
        except Exception as exc:
            last_exc = exc
            if is_outdated_app_error(exc) or isinstance(exc, ClientForbiddenError):
                continue
            raise
    raise last_exc


def login_with_session_id_sync(session_id: str) -> tuple[Client, str]:
    cleaned = clean_session_id_input(session_id)
    if not cleaned:
        raise ValueError("Session ID cannot be empty.")

    last_exc = None
    for idx in range(len(IG_APP_PROFILES)):
        client = Client()
        apply_fresh_ig_headers(client, profile_idx=idx)
        try:
            client.login_by_sessionid(cleaned)
            if not getattr(client, "user_id", None):
                profile = client.account_info()
                if getattr(profile, "pk", None):
                    client.user_id = int(profile.pk)
            if not getattr(client, "user_id", None):
                raise RuntimeError("Session ID did not authenticate a valid user account.")
            uname = resolve_username_from_client(client)
            return client, uname
        except Exception as exc:
            last_exc = exc
            if is_outdated_app_error(exc) or isinstance(exc, ClientForbiddenError):
                continue
            raise
    raise last_exc


def resume_saved_account_sync(username: str) -> Client:
    session_path = os.path.join(DATA_DIR, f"ig_{username}.json")
    if not os.path.exists(session_path):
        raise RuntimeError(f"Saved session file for @{username} not found.")

    last_exc = None
    for idx in range(len(IG_APP_PROFILES)):
        client = Client()
        apply_fresh_ig_headers(client, profile_idx=idx)
        try:
            client.load_settings(session_path)
            apply_fresh_ig_headers(client, profile_idx=idx)
            profile = client.account_info()
            if not getattr(profile, "pk", None) and not getattr(client, "user_id", None):
                raise RuntimeError("Saved session is no longer valid.")
            client.dump_settings(session_path)
            return client
        except Exception as exc:
            last_exc = exc
            if is_outdated_app_error(exc) or isinstance(exc, ClientForbiddenError):
                continue
            raise
    raise last_exc


def fetch_threads_sync(client: Client):
    threads = client.direct_threads(amount=20)
    items = []
    for t in threads:
        if getattr(t, "thread_title", None):
            title = t.thread_title
        elif getattr(t, "users", None):
            usernames = [u.username for u in t.users if getattr(u, "username", None)]
            title = ", ".join(usernames) if usernames else "Direct Chat"
        else:
            title = "Unnamed Thread"
        tag = "GC" if getattr(t, "is_group", False) else "DM"
        items.append({"id": str(t.id), "label": f"[{tag}] {title[:26]}"})
    return items


# ======================== TASK & WORKER HELPERS ========================

def is_authorized(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def get_bot_uptime() -> str:
    return str(datetime.now() - BOT_START_TIME).split(".")[0]


def make_bar(percent: float, length: int = 10) -> str:
    pct = max(0.0, min(100.0, float(percent)))
    filled = int(round(length * pct / 100))
    return "█" * filled + "░" * (length - filled)


def update_task_log(task_id: str, event_text: str):
    with tasks_lock:
        task = active_tasks.get(task_id)
        if not task:
            return
        task["last_event"] = event_text
        task["last_update"] = datetime.now().strftime("%H:%M:%S")
        sent = task.get("msg_count", 0)
        status = "RUNNING" if task.get("running", False) else "STOPPED"
        target = task["target_name"]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[{ts}] ⚙️ {task_id} | {status} | 🎯 {target} | 📨 Sent: {sent} | {event_text}",
        flush=True,
    )


def generate_random_band():
    min_delay = random.uniform(25, 45)
    spread = random.uniform(5, 15)
    return (min_delay, min(min_delay + spread, 60))


def is_task_running(task_id: str) -> bool:
    with tasks_lock:
        return bool(active_tasks.get(task_id, {}).get("running", False))


def set_task_running(task_id: str, value: bool):
    with tasks_lock:
        if task_id in active_tasks:
            active_tasks[task_id]["running"] = value


def send_message_with_retry(client: Client, thread_id: int, message: str, task_id: str) -> bool:
    global GLOBAL_MESSAGES_SENT

    for attempt in range(1, MAX_RETRIES + 1):
        if not is_task_running(task_id):
            return False

        try:
            client.direct_send(message, thread_ids=[int(thread_id)])
            with tasks_lock:
                GLOBAL_MESSAGES_SENT += 1
                if task_id in active_tasks:
                    active_tasks[task_id]["msg_count"] += 1
            update_task_log(task_id, f"✅ Sent message to {thread_id}")
            return True
        except RateLimitError:
            wait = 120 * attempt
            update_task_log(task_id, f"⚠️ Rate Limit: Pausing {wait}s ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)
        except PleaseWaitFewMinutes:
            wait = 300
            update_task_log(task_id, f"⏳ 'Please Wait' API Block: Pausing {wait}s")
            time.sleep(wait)
        except ChallengeRequired:
            update_task_log(task_id, "🔒 Challenge Required! Pausing for 1 hour.")
            time.sleep(3600)
        except (ClientForbiddenError, LoginRequired):
            set_task_running(task_id, False)
            update_task_log(task_id, "🔐 Session Expired/Forbidden! Task killed.")
            return False
        except Exception as exc:
            wait = 30 * attempt
            update_task_log(task_id, f"❌ Err: {str(exc)[:40]}... Retrying in {wait}s")
            time.sleep(wait)

    update_task_log(task_id, f"❌ Failed after {MAX_RETRIES} attempts. Skipping thread.")
    return False


def worker_thread(task_id: str):
    with tasks_lock:
        task = active_tasks.get(task_id)
        if not task:
            return
        cl = task["client"]
        thread_ids = list(task["thread_ids"])
        target_name = task["target_name"]

    raw_template = get_active_template()
    msg_template = raw_template.replace("{TARGET}", target_name)
    current_band = generate_random_band()
    last_band_change = time.time()
    band_interval = random.uniform(3600, 7200)
    round_num = 0

    while is_task_running(task_id):
        try:
            round_num += 1
            update_task_log(task_id, f"🔄 Starting Round {round_num}...")

            for thread_id in thread_ids:
                if not is_task_running(task_id):
                    break

                num = random.randint(1, 10**10)
                full_msg = (
                    f"{num}\n\n{msg_template}"
                    if random.choice([True, False])
                    else f"{msg_template}\n\n{num}"
                )

                send_message_with_retry(cl, thread_id, full_msg, task_id)

                delay = random.uniform(current_band[0], current_band[1])
                update_task_log(task_id, f"⏱️ Cooldown... Waiting {delay:.1f}s")

                slept = 0.0
                while slept < delay and is_task_running(task_id):
                    step = min(1.0, delay - slept)
                    time.sleep(step)
                    slept += step

                if time.time() - last_band_change >= band_interval:
                    current_band = generate_random_band()
                    last_band_change = time.time()
                    band_interval = random.uniform(3600, 7200)

        except Exception as exc:
            update_task_log(task_id, f"💥 Loop crash: {str(exc)[:40]}... Resting 60s.")
            time.sleep(60)

    update_task_log(task_id, "🛑 Task has been safely stopped.")


# ======================== KEYBOARDS & UI ========================

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Login / Start Task", callback_data="menu_login_choice")],
        [
            InlineKeyboardButton("💾 Saved Accounts", callback_data="menu_accounts"),
            InlineKeyboardButton("✏️ Edit Template", callback_data="menu_template"),
        ],
        [
            InlineKeyboardButton("📋 Active Tasks", callback_data="menu_tasks"),
            InlineKeyboardButton("📊 System Stats", callback_data="menu_stats"),
        ],
        [InlineKeyboardButton("🛑 Stop All Tasks", callback_data="menu_stop_all")],
    ])


def login_choice_keyboard() -> InlineKeyboardMarkup:
    accounts = load_saved_accounts()
    rows = []
    for uname in sorted(accounts.keys()):
        rows.append([
            InlineKeyboardButton(f"⚡ Use Saved: @{uname}", callback_data=f"use_saved:{uname}")
        ])
    rows.append([InlineKeyboardButton("🔑 Username & Password (with 2FA)", callback_data="start_new_login")])
    rows.append([InlineKeyboardButton("🍪 Login via Session ID", callback_data="start_sid_login")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def accounts_menu_keyboard() -> InlineKeyboardMarkup:
    accounts = load_saved_accounts()
    rows = []
    for uname in sorted(accounts.keys()):
        rows.append([
            InlineKeyboardButton(f"⚡ Use @{uname}", callback_data=f"use_saved:{uname}"),
            InlineKeyboardButton(f"🗑️ Remove @{uname}", callback_data=f"del_acc:{uname}"),
        ])
    rows.append([InlineKeyboardButton("🔑 Login Username/Password", callback_data="start_new_login")])
    rows.append([InlineKeyboardButton("🍪 Login via Session ID", callback_data="start_sid_login")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def template_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set Custom Template", callback_data="tpl_edit_start")],
        [InlineKeyboardButton("🔄 Reset to Default Template", callback_data="tpl_reset")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_home")],
    ])


def thread_picker_keyboard(items, selected_ids) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        tid = item["id"]
        mark = "✅" if tid in selected_ids else "⬜"
        rows.append([
            InlineKeyboardButton(f"{mark} {item['label']}", callback_data=f"pick_tid:{tid}")
        ])
    rows.append([
        InlineKeyboardButton(f"🚀 Confirm ({len(selected_ids)})", callback_data="pick_confirm"),
        InlineKeyboardButton("✍️ Manual IDs", callback_data="pick_manual"),
    ])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="wiz_cancel")])
    return InlineKeyboardMarkup(rows)


def build_main_menu_text() -> str:
    with tasks_lock:
        total = len(active_tasks)
        running = sum(1 for t in active_tasks.values() if t.get("running"))
        sent_total = sum(t.get("msg_count", 0) for t in active_tasks.values())

    saved_count = len(load_saved_accounts())
    is_custom_tpl = os.path.exists(TEMPLATE_FILE)

    return (
        "🎛️ <b>Instagram Controller Panel</b>\n\n"
        f"▶️ Running Tasks: <b>{running}</b> / {total}\n"
        f"💾 Saved Accounts: <b>{saved_count}</b>\n"
        f"📝 Template Mode: <b>{'Custom' if is_custom_tpl else 'Default'}</b>\n"
        f"📨 Task Messages Sent: <b>{sent_total}</b>\n"
        f"🌐 Global Counter: <b>{GLOBAL_MESSAGES_SENT}</b>\n"
        f"⏱️ Bot Uptime: <code>{get_bot_uptime()}</code>\n\n"
        "Choose an action below:"
    )


def build_template_view_text() -> str:
    tpl = get_active_template()
    preview = tpl if len(tpl) <= 1200 else tpl[:1200] + "\n... (truncated)"
    return (
        "✏️ <b>Message Template</b>\n\n"
        "Use <code>{TARGET}</code> anywhere you want the task's Target Name inserted.\n\n"
        f"<pre>{preview}</pre>"
    )


def build_tasks_summary() -> tuple[str, InlineKeyboardMarkup]:
    with tasks_lock:
        snapshot = [
            (tid, dict(info))
            for tid, info in active_tasks.items()
        ]

    if not snapshot:
        return (
            "📋 <b>Active Tasks</b>\n\nNo tasks created yet.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_home")]]),
        )

    lines = ["📋 <b>Tasks Overview</b>\n"]
    buttons = []
    for tid, info in snapshot:
        state = "🟢 RUNNING" if info.get("running") else "🔴 STOPPED"
        lines.append(
            f"• <code>{tid}</code> ({state}) — 👤 <code>@{info.get('username', '?')}</code> | "
            f"🎯 <b>{info['target_name']}</b> | 📨 <b>{info.get('msg_count', 0)}</b> | "
            f"{info.get('last_event', 'Idle')[:32]}"
        )
        if info.get("running"):
            buttons.append([InlineKeyboardButton(f"🛑 Stop {tid}", callback_data=f"stop_task:{tid}")])

    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="menu_tasks"),
        InlineKeyboardButton("⬅️ Back", callback_data="menu_home"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_stats_text() -> str:
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    proc = psutil.Process(os.getpid())
    proc_mb = proc.memory_info().rss / (1024 * 1024)

    with tasks_lock:
        running = sum(1 for t in active_tasks.values() if t.get("running"))

    return (
        "📊 <b>Railway Runtime Stats</b>\n\n"
        f"⚙️ CPU: <code>{cpu:.1f}%</code> [{make_bar(cpu)}]\n"
        f"🧠 RAM: <code>{ram.percent:.1f}%</code> [{make_bar(ram.percent)}] "
        f"({ram.used / (1024**3):.2f}/{ram.total / (1024**3):.2f} GB)\n"
        f"🐍 Bot RSS: <code>{proc_mb:.1f} MB</code>\n"
        f"▶️ Running Tasks: <b>{running}</b>\n"
        f"⏱️ Bot Uptime: <code>{get_bot_uptime()}</code>"
    )


# ======================== HANDLERS ========================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        build_main_menu_text(),
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pending_logins.pop(uid, None)
    context.user_data.clear()
    msg = update.callback_query.message if update.callback_query else update.message
    await msg.reply_text("❌ Flow cancelled.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def show_login_choices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END

    await query.edit_message_text(
        "🔐 <b>Select Login Method</b>\n\n"
        "Reuse a saved account, log in with username/password (with 2FA), or authenticate via Session ID:",
        reply_markup=login_choice_keyboard(),
        parse_mode="HTML",
    )
    return STATE_USERNAME


async def start_new_login_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END

    context.user_data["login_flow"] = {"auth_method": "password"}
    await query.edit_message_text(
        "👤 <b>Step 1/4: Instagram Username</b>\n\n"
        "Send your Instagram username (or /cancel to abort):",
        parse_mode="HTML",
    )
    return STATE_USERNAME


async def start_sid_login_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END

    context.user_data["login_flow"] = {"auth_method": "sessionid"}
    await query.edit_message_text(
        "🍪 <b>Login via Session ID</b>\n\n"
        "Paste your Instagram <code>sessionid</code> cookie value (or full <code>sessionid=...</code> string).\n"
        "Your message will be deleted right after reading.",
        parse_mode="HTML",
    )
    return STATE_SESSION_ID


async def receive_session_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END

    raw_sid = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    if not raw_sid:
        await update.message.reply_text("❌ Session ID cannot be empty. Paste it again or /cancel:")
        return STATE_SESSION_ID

    status_msg = await update.message.reply_text(
        "🔄 Authenticating with Session ID (with updated IG app headers)..."
    )

    try:
        client, username = await asyncio.to_thread(login_with_session_id_sync, raw_sid)
    except Exception as exc:
        await status_msg.edit_text(
            f"❌ Session ID login failed: <code>{type(exc).__name__}: {str(exc)[:180]}</code>",
            reply_markup=login_choice_keyboard(),
            parse_mode="HTML",
        )
        return STATE_USERNAME

    return await finish_auth_and_show_threads(
        status_msg, context, client, username, auth_method="sessionid"
    )


async def use_saved_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END

    username = query.data.split(":", 1)[1]
    meta = load_saved_accounts().get(username, {})
    auth_method = meta.get("auth_method", "password")

    status_msg = await query.edit_message_text(
        f"⚡ Resuming saved session for <code>@{username}</code>...",
        parse_mode="HTML",
    )

    try:
        client = await asyncio.to_thread(resume_saved_account_sync, username)
    except Exception as exc:
        await status_msg.edit_text(
            f"⚠️ Saved session for <code>@{username}</code> could not be resumed "
            f"(<code>{str(exc)[:140]}</code>).\n"
            "Try logging in again using Username/Password or Session ID.",
            reply_markup=login_choice_keyboard(),
            parse_mode="HTML",
        )
        return STATE_USERNAME

    return await finish_auth_and_show_threads(
        status_msg, context, client, username, auth_method=auth_method
    )


async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END

    username = update.message.text.strip().lstrip("@")
    if not username:
        await update.message.reply_text("❌ Username cannot be empty. Send again:")
        return STATE_USERNAME

    flow = context.user_data.setdefault("login_flow", {"auth_method": "password"})
    flow["username"] = username

    try:
        await update.message.delete()
    except Exception:
        pass

    await update.message.reply_text(
        f"🔑 <b>Step 2/4: Instagram Password</b> for <code>@{username}</code>\n\n"
        "Send the password in your next message:",
        parse_mode="HTML",
    )
    return STATE_PASSWORD


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return ConversationHandler.END

    password = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    if not password:
        await update.message.reply_text("❌ Password cannot be empty. Send again:")
        return STATE_PASSWORD

    flow = context.user_data.setdefault("login_flow", {"auth_method": "password"})
    username = flow.get("username", "")
    status_msg = await update.message.reply_text(
        f"🔄 Logging into <code>@{username}</code>...",
        parse_mode="HTML",
    )

    client = build_client_with_session(username, profile_idx=0)

    def _attempt_login():
        return login_with_password_and_retry(client, username, password, code=None)

    try:
        logged_client = await asyncio.to_thread(_attempt_login)
    except TwoFactorRequired as exc:
        pending_logins[uid] = {
            "client": client,
            "username": username,
            "password": password,
            "error": str(exc),
        }
        await status_msg.edit_text(
            "📲 <b>2FA Code Required</b>\n\n"
            f"Instagram asked for two-factor verification for <code>@{username}</code>.\n"
            "Reply with your <b>6-digit 2FA code</b>:",
            parse_mode="HTML",
        )
        return STATE_2FA
    except BadPassword:
        await status_msg.edit_text(
            "❌ Incorrect Instagram password.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END
    except Exception as exc:
        await status_msg.edit_text(
            f"❌ Login failed: <code>{type(exc).__name__}: {str(exc)[:180]}</code>",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    return await finish_auth_and_show_threads(
        status_msg, context, logged_client, username, auth_method="password"
    )


async def receive_2fa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return ConversationHandler.END

    code = update.message.text.strip().replace(" ", "")
    try:
        await update.message.delete()
    except Exception:
        pass

    pending = pending_logins.get(uid)
    if not pending:
        await update.message.reply_text(
            "⚠️ Login session expired. Start again with /start.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    status_msg = await update.message.reply_text("🔐 Verifying 2FA code...")
    client = pending["client"]
    username = pending["username"]
    password = pending["password"]

    def _verify_2fa():
        return login_with_password_and_retry(client, username, password, code=code)

    try:
        logged_client = await asyncio.to_thread(_verify_2fa)
    except Exception as exc:
        await status_msg.edit_text(
            f"❌ 2FA verification failed: <code>{type(exc).__name__}: {str(exc)[:160]}</code>\n"
            "Send another 6-digit code or /cancel:",
            parse_mode="HTML",
        )
        return STATE_2FA

    pending_logins.pop(uid, None)
    return await finish_auth_and_show_threads(
        status_msg, context, logged_client, username, auth_method="password+2fa"
    )


async def finish_auth_and_show_threads(
    status_msg, context, client: Client, username: str, auth_method: str = "password"
):
    if not getattr(client, "user_id", None):
        await status_msg.edit_text(
            "❌ Login did not return an Instagram user ID.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    await asyncio.to_thread(save_client_session, client, username, auth_method)

    flow = context.user_data.setdefault("login_flow", {})
    flow["client"] = client
    flow["username"] = username
    flow["selected_threads"] = []

    await status_msg.edit_text(
        f"✅ Ready with <code>@{username}</code> (ID: <code>{client.user_id}</code>)\n"
        "📥 Fetching recent chats & group chats...",
        parse_mode="HTML",
    )

    try:
        items = await asyncio.to_thread(fetch_threads_sync, client)
    except Exception as exc:
        items = []
        await status_msg.edit_text(
            f"⚠️ Could not load threads automatically (<code>{str(exc)[:120]}</code>).\n"
            "Send Thread ID(s) separated by commas (e.g. <code>178412345, 178998877</code>):",
            parse_mode="HTML",
        )
        return STATE_MANUAL_THREADS

    flow["thread_items"] = items

    if not items:
        await status_msg.edit_text(
            "📭 No recent threads found.\n"
            "Send Thread ID(s) separated by commas:",
            parse_mode="HTML",
        )
        return STATE_MANUAL_THREADS

    await status_msg.edit_text(
        "💬 <b>Step 3/4: Select Target Chat(s)</b>\n\n"
        "Tap one or more chats below to toggle selection, then tap <b>Confirm</b>:",
        reply_markup=thread_picker_keyboard(items, []),
        parse_mode="HTML",
    )
    return STATE_MANUAL_THREADS


async def on_thread_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "wiz_cancel":
        pending_logins.pop(query.from_user.id, None)
        context.user_data.pop("login_flow", None)
        await query.edit_message_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    flow = context.user_data.setdefault("login_flow", {})
    selected = list(flow.get("selected_threads", []))
    items = flow.get("thread_items", [])

    if data.startswith("pick_tid:"):
        tid = data.split(":", 1)[1]
        if tid in selected:
            selected.remove(tid)
        else:
            selected.append(tid)
        flow["selected_threads"] = selected
        await query.edit_message_reply_markup(
            reply_markup=thread_picker_keyboard(items, selected)
        )
        return STATE_MANUAL_THREADS

    if data == "pick_manual":
        await query.edit_message_text(
            "✍️ Send Thread ID(s) separated by commas (e.g. <code>178412345, 178998877</code>):",
            parse_mode="HTML",
        )
        return STATE_MANUAL_THREADS

    if data == "pick_confirm":
        if not selected:
            await query.answer("Select at least 1 chat first.", show_alert=True)
            return STATE_MANUAL_THREADS
        flow["thread_ids"] = [int(x) for x in selected]
        await query.edit_message_text(
            "🎯 <b>Step 4/4: Target Name</b>\n\n"
            "Send the Target Name to inject into the template:",
            parse_mode="HTML",
        )
        return STATE_TARGET

    return STATE_MANUAL_THREADS


async def receive_manual_threads_or_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END

    text = update.message.text.strip()
    flow = context.user_data.setdefault("login_flow", {})

    if "thread_ids" not in flow:
        parsed = [int(p.strip()) for p in text.split(",") if p.strip().isdigit()]
        if not parsed:
            await update.message.reply_text("❌ No valid numeric Thread IDs found. Send again:")
            return STATE_MANUAL_THREADS
        flow["thread_ids"] = parsed
        await update.message.reply_text(
            "🎯 <b>Step 4/4: Target Name</b>\n\n"
            "Send the Target Name to inject into the template:",
            parse_mode="HTML",
        )
        return STATE_TARGET

    if not text:
        await update.message.reply_text("❌ Target Name cannot be empty. Send again:")
        return STATE_TARGET

    client = flow.get("client")
    thread_ids = flow.get("thread_ids", [])
    username = flow.get("username", "unknown")

    if client is None or not thread_ids:
        await update.message.reply_text(
            "⚠️ Missing session or thread selection. Use /start to begin again.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    task_id = f"T{uuid.uuid4().hex[:6].upper()}"
    with tasks_lock:
        active_tasks[task_id] = {
            "client": client,
            "username": username,
            "thread_ids": thread_ids,
            "target_name": text,
            "running": True,
            "msg_count": 0,
            "last_event": "Queued",
            "last_update": datetime.now().strftime("%H:%M:%S"),
        }

    t = threading.Thread(target=worker_thread, args=(task_id,), daemon=True)
    t.start()

    context.user_data.pop("login_flow", None)
    await update.message.reply_text(
        f"🚀 <b>Task Started:</b> <code>{task_id}</code>\n"
        f"👤 Account: <code>@{username}</code>\n"
        f"🎯 Target: <b>{text}</b>\n"
        f"💬 Threads: <code>{', '.join(str(x) for x in thread_ids)}</code>",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def start_template_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return ConversationHandler.END

    await query.edit_message_text(
        "✏️ <b>Send New Message Template</b>\n\n"
        "Include <code>{TARGET}</code> where the Target Name should appear.\n"
        "Send /cancel to keep the current template.",
        parse_mode="HTML",
    )
    return STATE_EDIT_TEMPLATE


async receive_new_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return ConversationHandler.END

    new_tpl = update.message.text
    if not new_tpl or not new_tpl.strip():
        await update.message.reply_text("❌ Template cannot be empty. Send again or /cancel:")
        return STATE_EDIT_TEMPLATE

    set_active_template(new_tpl)
    await update.message.reply_text(
        "✅ <b>Template updated!</b> New and restarted tasks will use this template.",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    data = query.data

    if data == "menu_home":
        await query.edit_message_text(
            build_main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
    elif data == "menu_accounts":
        accounts = load_saved_accounts()
        if not accounts:
            txt = "💾 <b>Saved Accounts</b>\n\nNo saved accounts yet. Log in once to save a session."
        else:
            lines = ["💾 <b>Saved Accounts</b>\n"]
            for uname, meta in sorted(accounts.items()):
                lines.append(
                    f"• <code>@{uname}</code> (IG ID: <code>{meta.get('ig_user_id') or 'N/A'}</code>, "
                    f"via <code>{meta.get('auth_method', 'session')}</code>) — <i>{meta.get('updated_at', '')}</i>"
                )
            txt = "\n".join(lines)
        await query.edit_message_text(txt, reply_markup=accounts_menu_keyboard(), parse_mode="HTML")
    elif data.startswith("del_acc:"):
        uname = data.split(":", 1)[1]
        remove_saved_account(uname)
        await query.edit_message_text(
            f"🗑️ Removed saved account <code>@{uname}</code>.",
            reply_markup=accounts_menu_keyboard(),
            parse_mode="HTML",
        )
    elif data == "menu_template":
        await query.edit_message_text(
            build_template_view_text(),
            reply_markup=template_menu_keyboard(),
            parse_mode="HTML",
        )
    elif data == "tpl_reset":
        reset_active_template()
        await query.edit_message_text(
            "🔄 Reset template back to default.\n\n" + build_template_view_text(),
            reply_markup=template_menu_keyboard(),
            parse_mode="HTML",
        )
    elif data == "menu_tasks":
        txt, kb = build_tasks_summary()
        await query.edit_message_text(txt, reply_markup=kb, parse_mode="HTML")
    elif data == "menu_stats":
        await query.edit_message_text(
            build_stats_text(),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="menu_stats")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_home")],
            ]),
            parse_mode="HTML",
        )
    elif data.startswith("stop_task:"):
        tid = data.split(":", 1)[1]
        set_task_running(tid, False)
        txt, kb = build_tasks_summary()
        await query.edit_message_text(txt, reply_markup=kb, parse_mode="HTML")
    elif data == "menu_stop_all":
        with tasks_lock:
            for info in active_tasks.values():
                info["running"] = False
        await query.edit_message_text(
            "🛑 Stop signal sent to all active tasks.",
            reply_markup=main_menu_keyboard(),
        )


def main():
    if not BOT_TOKEN:
        print("❌ Missing TG_TOKEN environment variable.", flush=True)
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_login_choices, pattern="^menu_login_choice$"),
            CallbackQueryHandler(start_new_login_from_callback, pattern="^start_new_login$"),
            CallbackQueryHandler(start_sid_login_from_callback, pattern="^start_sid_login$"),
            CallbackQueryHandler(use_saved_account_callback, pattern="^use_saved:"),
            CallbackQueryHandler(start_template_edit, pattern="^tpl_edit_start$"),
        ],
        states={
            STATE_USERNAME: [
                CallbackQueryHandler(start_new_login_from_callback, pattern="^start_new_login$"),
                CallbackQueryHandler(start_sid_login_from_callback, pattern="^start_sid_login$"),
                CallbackQueryHandler(use_saved_account_callback, pattern="^use_saved:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username),
            ],
            STATE_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
            STATE_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_2fa_code)],
            STATE_SESSION_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_session_id)],
            STATE_MANUAL_THREADS: [
                CallbackQueryHandler(on_thread_picker_callback, pattern="^(pick_tid:|pick_confirm|pick_manual|wiz_cancel)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_manual_threads_or_target),
            ],
            STATE_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_manual_threads_or_target)],
            STATE_EDIT_TEMPLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_template)],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CallbackQueryHandler(on_menu_callback, pattern="^menu_home$"),
        ],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("panel", cmd_start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(on_menu_callback))

    print("🤖 Telegram controller running on Railway...", flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
