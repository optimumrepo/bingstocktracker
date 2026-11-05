"""
Bing Rewards Gift Card Restock Monitor
=======================================
Monitors Microsoft Rewards SKU pages and sends Telegram, ntfy.sh,
and/or WhatsApp (CallMeBot) notifications when restocked.

Features:
- Authenticated checks via MS_COOKIE to track localized stock banners
- Automatic notification when MS_COOKIE expires (without spamming)
- Smart state tracking to prevent duplicate alerts
"""

import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import json
import re
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ITEMS = [
    {
        "name": "Flipkart Gift Card",
        "url": "https://rewards.bing.com/redeem/sku/000885000034",
    },
    {
        "name": "Overwatch Coins Digital Code",
        "url": "https://rewards.bing.com/redeem/sku/000485000005",
    },
]

OUT_OF_STOCK_PHRASES = [
    "so popular we're restocking",
    "back soon",
    "out of stock",
    "currently unavailable",
    "sold out",
]

LOGIN_INDICATORS = [
    "sign in to earn and redeem",
    "sign in with your microsoft account",
    "login.live.com",
    "join microsoft rewards",
    "sign in to redeem",
]

# --- State File ---
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# --- Microsoft Rewards Session Cookie ---
MS_COOKIE = os.environ.get("MS_COOKIE", "").strip()

# --- Telegram Bot API ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# --- ntfy.sh Push Notifications ---
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip()

# --- CallMeBot WhatsApp ---
CALLMEBOT_PHONE = os.environ.get("CALLMEBOT_PHONE", "").strip()
CALLMEBOT_API_KEY = os.environ.get("CALLMEBOT_API_KEY", "").strip()

# Loop mode interval
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL", "300"))

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load persistent state from state.json."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"Warning: Could not read state.json ({e}). Starting fresh.")
    return {"cookie_expired_alerted": False, "items": {}}


def save_state(state: dict):
    """Save persistent state to state.json."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log(f"Warning: Could not save state.json: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"[{now}] {msg}")


def fetch_page(url: str) -> tuple[str, str]:
    """Fetch HTML content and final resolved URL."""
    ctx = ssl.create_default_context()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    if MS_COOKIE:
        headers["Cookie"] = MS_COOKIE

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            final_url = resp.geturl()
            html = resp.read().decode("utf-8", errors="replace")
            return html, final_url
    except urllib.error.HTTPError as e:
        log(f"  HTTP Error {e.code} for {url}")
        return "", ""
    except Exception as e:
        log(f"  Error fetching {url}: {e}")
        return "", ""


def is_login_required(html: str, final_url: str) -> bool:
    """Check if Microsoft redirected to login or is prompting sign in."""
    if "login.live.com" in final_url.lower():
        return True
    html_lower = html.lower()
    for ind in LOGIN_INDICATORS:
        if ind in html_lower:
            return True
    return False


def is_out_of_stock(html: str) -> bool:
    """Check if the page contains out-of-stock indicators."""
    html_lower = html.lower()
    for phrase in OUT_OF_STOCK_PHRASES:
        if phrase in html_lower:
            return True
    return False


def has_redeem_button(html: str) -> bool:
    """Check if the page has an active redeem/confirm button."""
    html_lower = html.lower()
    redeem_patterns = [
        r'class="[^"]*redeem[^"]*"',
        r'id="[^"]*redeem[^"]*"',
        r'>redeem<',
        r'>confirm<',
        r'data-bi-id="[^"]*redeem[^"]*"',
        r'redeemsku',
    ]
    for pattern in redeem_patterns:
        if re.search(pattern, html_lower):
            return True
    return False


def check_item(item: dict) -> tuple[dict, bool]:
    name = item["name"]
    url = item["url"]
    log(f"Checking: {name}")

    html, final_url = fetch_page(url)
    if not html:
        return {
            "name": name, "url": url, "in_stock": False,
            "status": "ERROR: Could not fetch page", "html_length": 0,
        }, False

    if is_login_required(html, final_url):
        log("  ⚠️ Page requires login! Microsoft redirected or prompt visible.")
        return {
            "name": name, "url": url, "in_stock": False,
            "status": "⚠️ SIGN-IN REQUIRED",
            "html_length": len(html),
        }, True

    out_of_stock = is_out_of_stock(html)
    redeem_available = has_redeem_button(html)

    if out_of_stock:
        status = "OUT OF STOCK (restocking message found)"
        in_stock = False
    elif redeem_available:
        status = "🟢 IN STOCK! Redeem button detected!"
        in_stock = True
    else:
        status = "OUT OF STOCK (restock banner or unknown state)"
        in_stock = False

    log(f"  Status: {status} (page size: {len(html)} bytes)")
    return {
        "name": name, "url": url, "in_stock": in_stock,
        "status": status, "html_length": len(html),
    }, False


# ---------------------------------------------------------------------------
# Notification Senders
# ---------------------------------------------------------------------------

def send_telegram(title: str, message: str) -> bool:
    """Send via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    log("  Sending Telegram notification...")
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                log("  ✅ Telegram sent!")
                return True
            log(f"  ❌ Telegram error: {result}")
            return False
    except Exception as e:
        log(f"  Error sending Telegram: {e}")
        return False


def send_ntfy(title: str, message: str, url: str = "", tags: str = "gift,moneybag") -> bool:
    """Send via ntfy.sh push notification (with clean ASCII headers)."""
    if not NTFY_TOPIC:
        log("  ℹ️ NTFY_TOPIC not configured — skipping ntfy.")
        return False

    ntfy_url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    
    # Strip non-ASCII characters from headers to prevent Python HTTP header encode errors
    clean_title = title.encode("ascii", "ignore").decode("ascii").strip()
    if not clean_title:
        clean_title = "Bing Rewards Alert"

    headers = {
        "Title": clean_title,
        "Priority": "urgent",
        "Tags": tags,
    }
    if url:
        headers["Click"] = url
        headers["Actions"] = f"view, Open Rewards Page, {url}"

    req = urllib.request.Request(
        ntfy_url,
        data=message.encode("utf-8"),
        method="POST",
        headers=headers,
    )

    log(f"  Sending ntfy.sh notification to topic '{NTFY_TOPIC}'...")
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            if resp.status == 200:
                log("  ✅ ntfy.sh sent successfully!")
                return True
            log(f"  ❌ ntfy.sh response: {resp.status}")
            return False
    except Exception as e:
        log(f"  ❌ Error sending ntfy: {e}")
        return False


def send_whatsapp_callmebot(title: str, message: str) -> bool:
    """Send via CallMeBot WhatsApp API."""
    if not CALLMEBOT_PHONE or not CALLMEBOT_API_KEY:
        return False

    encoded_msg = urllib.parse.quote_plus(message)
    phone = CALLMEBOT_PHONE.replace("+", "").strip()
    url = (f"https://api.callmebot.com/whatsapp.php"
           f"?phone={phone}&text={encoded_msg}&apikey={CALLMEBOT_API_KEY}")

    log(f"  Sending CallMeBot WhatsApp to +{phone}...")
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            log(f"  CallMeBot: {resp.status} — {body[:200]}")
            return resp.status == 200
    except Exception as e:
        log(f"  Error sending CallMeBot: {e}")
        return False


def send_cookie_expired_alert():
    """Notify the user once that their MS_COOKIE session has expired."""
    tg_msg = (
        "⚠️ *Microsoft Rewards Session Expired*\n\n"
        "Your `MS_COOKIE` has expired and Microsoft is prompting to sign in.\n\n"
        "To keep tracking gift card stock accurately, please refresh your "
        "*MS_COOKIE* secret in your GitHub repository settings."
    )
    ntfy_msg = (
        "Your MS_COOKIE session has expired. Please update MS_COOKIE in GitHub Secrets to keep monitoring."
    )
    wa_msg = (
        "⚠️ Microsoft Rewards session expired! Please refresh your MS_COOKIE secret in GitHub to continue monitoring."
    )

    log("⚠️ Sending cookie expiration alert to user...")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram("⚠️ Rewards Session Expired", tg_msg)
    if NTFY_TOPIC:
        send_ntfy("Rewards Session Expired", ntfy_msg, tags="warning,lock")
    if CALLMEBOT_PHONE and CALLMEBOT_API_KEY:
        send_whatsapp_callmebot("⚠️ Rewards Cookie Expired", wa_msg)


def send_restock_alert(item: dict):
    """Send restock alert when an item becomes available."""
    name = item["name"]
    url = item["url"]
    status = item["status"]

    tg_msg = (
        f"🎁 *RESTOCK ALERT!*\n\n"
        f"*{name}* is back in stock on Microsoft Rewards!\n\n"
        f"Status: {status}\n"
        f"🔗 [Redeem Now]({url})\n\n"
        f"Hurry and redeem before it runs out again!"
    )
    ntfy_msg = (
        f"{name} is back in stock on Microsoft Rewards!\n\n"
        f"Status: {status}\n\n"
        f"Hurry and redeem before it runs out again!"
    )
    wa_msg = (
        f"🎁 RESTOCK ALERT!\n\n"
        f"{name} is back in stock on Microsoft Rewards!\n\n"
        f"Status: {status}\n"
        f"🔗 {url}\n\n"
        f"Hurry and redeem before it runs out again!"
    )

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram(f"🎁 {name} Restocked!", tg_msg)
    if NTFY_TOPIC:
        send_ntfy(f"{name} Restocked!", ntfy_msg, url=url, tags="gift,moneybag")
    if CALLMEBOT_PHONE and CALLMEBOT_API_KEY:
        send_whatsapp_callmebot(f"🎁 {name} Restocked!", wa_msg)


# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------

def run_check():
    log("=" * 60)
    log("Starting restock check...")
    if MS_COOKIE:
        log("🔑 Running with MS_COOKIE session")
    else:
        log("ℹ️ Running in guest mode (no MS_COOKIE set)")
    log("=" * 60)

    state = load_state()
    items_state = state.setdefault("items", {})

    any_login_failed = False

    for item in ITEMS:
        result, login_required = check_item(item)
        name = item["name"]

        if login_required:
            any_login_failed = True

        # Check for state transition (out of stock -> in stock)
        item_prev = items_state.get(name, {}).get("in_stock", False)
        
        if result["in_stock"]:
            if not item_prev:
                log(f"🎉 NEW RESTOCK DETECTED: {name}! Sending alerts...")
                send_restock_alert(result)
            else:
                log(f"ℹ️ {name} is still in stock (already alerted).")
            items_state[name] = {"in_stock": True}
        else:
            if item_prev:
                log(f"ℹ️ {name} is now out of stock again.")
            items_state[name] = {"in_stock": False}

    # Handle cookie expiration alerting (send once when expired)
    if MS_COOKIE and any_login_failed:
        if not state.get("cookie_expired_alerted", False):
            send_cookie_expired_alert()
            state["cookie_expired_alerted"] = True
        else:
            log("ℹ️ Cookie expired notification was already sent. Skipping repeat.")
    elif MS_COOKIE and not any_login_failed:
        # If login was successful, reset the alert flag
        if state.get("cookie_expired_alerted", False):
            log("✅ Cookie is valid again. Resetting expiration alert flag.")
            state["cookie_expired_alerted"] = False

    save_state(state)
    log("=" * 60)
    log("Check complete.\n")


def main():
    log("Bing Rewards Gift Card Restock Monitor")
    log(f"Tracking {len(ITEMS)} item(s):")
    for item in ITEMS:
        log(f"  • {item['name']} — {item['url']}")
    log("")

    channels = []
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        channels.append("Telegram")
    if NTFY_TOPIC:
        channels.append(f"ntfy.sh ({NTFY_TOPIC})")
    if CALLMEBOT_PHONE and CALLMEBOT_API_KEY:
        channels.append("CallMeBot WhatsApp")

    if channels:
        log(f"Notification channels: {', '.join(channels)}\n")
    else:
        log("⚠️  WARNING: No notification channel configured!\n")

    is_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    single_run = "--once" in sys.argv or is_ci

    if single_run:
        log("Running in single-check mode.\n")
        run_check()
        sys.exit(0)
    else:
        log(f"Running in loop mode — checking every {CHECK_INTERVAL_SECONDS}s\n")
        while True:
            try:
                run_check()
            except KeyboardInterrupt:
                log("Interrupted. Exiting.")
                break
            except Exception as e:
                log(f"Unexpected error: {e}")
            log(f"Sleeping {CHECK_INTERVAL_SECONDS}s...\n")
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
