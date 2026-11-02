"""
Bing Rewards Gift Card Restock Monitor
=======================================
Monitors Microsoft Rewards SKU pages and sends Telegram, ntfy.sh,
and/or WhatsApp (CallMeBot) notifications when restocked.

Usage:
  Local:  python monitor.py
  CI/CD:  Set secrets as environment variables in GitHub Actions.
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

# --- Telegram Bot API ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- ntfy.sh Push Notifications ---
# Topic name acts as your private channel (use something unique/unguessable)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # e.g. bing-rewards-arya-xk92m
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")  # default public server

# --- CallMeBot WhatsApp ---
CALLMEBOT_PHONE = os.environ.get("CALLMEBOT_PHONE", "")
CALLMEBOT_API_KEY = os.environ.get("CALLMEBOT_API_KEY", "")

# Loop mode interval
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL", "300"))

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"[{now}] {msg}")


def fetch_page(url: str) -> str:
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
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        log(f"  HTTP Error {e.code} for {url}")
        return ""
    except Exception as e:
        log(f"  Error fetching {url}: {e}")
        return ""


def is_out_of_stock(html: str) -> bool:
    html_lower = html.lower()
    for phrase in OUT_OF_STOCK_PHRASES:
        if phrase in html_lower:
            return True
    return False


def has_redeem_button(html: str) -> bool:
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


def check_item(item: dict) -> dict:
    name = item["name"]
    url = item["url"]
    log(f"Checking: {name}")

    html = fetch_page(url)
    if not html:
        return {
            "name": name, "url": url, "in_stock": False,
            "status": "ERROR: Could not fetch page", "html_length": 0,
        }

    out_of_stock = is_out_of_stock(html)
    redeem_available = has_redeem_button(html)

    if out_of_stock:
        status = "OUT OF STOCK (restocking message found)"
        in_stock = False
    elif redeem_available:
        status = "🟢 IN STOCK! Redeem button detected!"
        in_stock = True
    else:
        status = "⚠️ POSSIBLY IN STOCK (no out-of-stock message found)"
        in_stock = True

    log(f"  Status: {status} (page size: {len(html)} bytes)")
    return {"name": name, "url": url, "in_stock": in_stock, "status": status, "html_length": len(html)}


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
    log(f"  Sending Telegram notification...")
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


def send_ntfy(title: str, message: str, url: str = "") -> bool:
    """Send via ntfy.sh push notification."""
    if not NTFY_TOPIC:
        return False

    ntfy_url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": "urgent",
        "Tags": "gift,moneybag",
    }
    if url:
        headers["Click"] = url  # tapping the notification opens this URL
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
                log("  ✅ ntfy.sh sent!")
                return True
            log(f"  ❌ ntfy.sh response: {resp.status}")
            return False
    except Exception as e:
        log(f"  Error sending ntfy.sh: {e}")
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


def send_all_notifications(item: dict):
    """Send restock alert via all configured channels."""
    name = item["name"]
    url = item["url"]
    status = item["status"]
    sent = False

    # Telegram (Markdown)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        msg = (f"🎁 *RESTOCK ALERT!*\n\n"
               f"*{name}* is back in stock on Microsoft Rewards!\n\n"
               f"Status: {status}\n"
               f"🔗 [Redeem Now]({url})\n\n"
               f"Hurry and redeem before it runs out again!")
        sent = send_telegram(f"🎁 {name} Restocked!", msg) or sent

    # ntfy.sh (plain text + clickable link)
    if NTFY_TOPIC:
        msg = (f"{name} is back in stock on Microsoft Rewards!\n\n"
               f"Status: {status}\n\n"
               f"Hurry and redeem before it runs out again!")
        sent = send_ntfy(f"🎁 {name} Restocked!", msg, url) or sent

    # CallMeBot WhatsApp (plain text)
    if CALLMEBOT_PHONE and CALLMEBOT_API_KEY:
        msg = (f"🎁 RESTOCK ALERT!\n\n"
               f"{name} is back in stock on Microsoft Rewards!\n\n"
               f"Status: {status}\n"
               f"🔗 {url}\n\n"
               f"Hurry and redeem before it runs out again!")
        sent = send_whatsapp_callmebot(f"🎁 {name} Restocked!", msg) or sent

    if not sent:
        log("⚠️  No notification channel configured or all failed!")
        log("   Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
        log("   and/or NTFY_TOPIC")

    return sent


# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------

def run_check() -> list:
    log("=" * 60)
    log("Starting restock check...")
    log("=" * 60)

    in_stock_items = []
    for item in ITEMS:
        result = check_item(item)
        if result["in_stock"]:
            in_stock_items.append(result)

    if in_stock_items:
        log(f"\n🎉 {len(in_stock_items)} item(s) appear to be IN STOCK!")
        for item in in_stock_items:
            send_all_notifications(item)
    else:
        log("\n😴 All items are still out of stock. Will check again later.")

    log("=" * 60)
    log("Check complete.\n")
    return in_stock_items


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
