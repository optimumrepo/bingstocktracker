"""
Bing Rewards Gift Card Restock Monitor (Playwright Edition)
============================================================
Uses a real headless browser (Playwright/Chromium) to check stock.
The browser automatically handles Microsoft's token rotation,
so the session NEVER expires on its own.

After each check, the refreshed browser state is saved back,
keeping the session alive indefinitely.
"""

import os
import sys
import json
import asyncio
import re
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BROWSER_STATE_FILE = os.path.join(SCRIPT_DIR, "browser_state.json")
MONITOR_STATE_FILE = os.path.join(SCRIPT_DIR, "state.json")

# Notification credentials
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip()

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"[{now}] {msg}", flush=True)


def load_monitor_state() -> dict:
    if os.path.exists(MONITOR_STATE_FILE):
        try:
            with open(MONITOR_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"session_expired_alerted": False, "items": {}}


def save_monitor_state(state: dict):
    try:
        with open(MONITOR_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log(f"Warning: Could not save state.json: {e}")


# ---------------------------------------------------------------------------
# Notification Senders (using stdlib only — no extra deps)
# ---------------------------------------------------------------------------

import urllib.request
import urllib.parse
import ssl

def send_telegram(title: str, message: str) -> bool:
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
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                log("  ✅ Telegram sent!")
                return True
            log(f"  ❌ Telegram error: {result}")
    except Exception as e:
        log(f"  Error sending Telegram: {e}")
    return False


def send_ntfy(title: str, message: str, url: str = "", tags: str = "gift,moneybag") -> bool:
    if not NTFY_TOPIC:
        return False
    ntfy_url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    clean_title = title.encode("ascii", "ignore").decode("ascii").strip() or "Bing Rewards Alert"
    headers = {"Title": clean_title, "Priority": "urgent", "Tags": tags}
    if url:
        headers["Click"] = url
        headers["Actions"] = f"view, Open Rewards Page, {url}"
    req = urllib.request.Request(ntfy_url, data=message.encode("utf-8"),
                                 method="POST", headers=headers)
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            if resp.status == 200:
                log("  ✅ ntfy sent!")
                return True
    except Exception as e:
        log(f"  Error sending ntfy: {e}")
    return False


def send_session_expired_alert():
    log("⚠️ Sending session expiration alert...")
    tg_msg = (
        "⚠️ *Microsoft Rewards Session Expired*\n\n"
        "Your browser session has expired.\n\n"
        "Please run `python setup_login.py` on your laptop, "
        "log in again, then push the updated `browser_state.json` to GitHub."
    )
    ntfy_msg = "Your Rewards browser session expired. Run setup_login.py on your laptop to re-login."
    send_telegram("Session Expired", tg_msg)
    send_ntfy("Rewards Session Expired", ntfy_msg, tags="warning,lock")


def send_restock_alert(item: dict):
    name = item["name"]
    url = item["url"]
    status = item["status"]

    log(f"🚀 SENDING RESTOCK ALERT FOR {name}!")
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
    send_telegram(f"{name} Restocked!", tg_msg)
    send_ntfy(f"{name} Restocked!", ntfy_msg, url=url, tags="gift,moneybag")


# ---------------------------------------------------------------------------
# Page Checking Logic
# ---------------------------------------------------------------------------

def is_login_page(page_url: str, page_content: str) -> bool:
    if "login.live.com" in page_url.lower():
        return True
    content_lower = page_content.lower()
    for ind in LOGIN_INDICATORS:
        if ind in content_lower:
            return True
    return False


def is_out_of_stock(html: str) -> bool:
    html_lower = html.lower()
    for phrase in OUT_OF_STOCK_PHRASES:
        if phrase in html_lower:
            return True
    return False


def has_redeem_button(html: str) -> bool:
    html_lower = html.lower()
    patterns = [
        r'class="[^"]*redeem[^"]*"', r'id="[^"]*redeem[^"]*"',
        r'>redeem<', r'>confirm<',
        r'data-bi-id="[^"]*redeem[^"]*"', r'redeemsku',
    ]
    for pattern in patterns:
        if re.search(pattern, html_lower):
            return True
    return False


async def check_item(page, item: dict) -> tuple[dict, bool]:
    name = item["name"]
    url = item["url"]
    log(f"Checking: {name}")

    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Wait a bit for dynamic content to render
        await page.wait_for_timeout(3000)

        final_url = page.url
        html = await page.content()

        if is_login_page(final_url, html):
            log(f"  ⚠️ Session expired — Microsoft redirected to login.")
            return {"name": name, "url": url, "in_stock": False,
                    "status": "SESSION EXPIRED"}, True

        out_of_stock = is_out_of_stock(html)
        redeem_available = has_redeem_button(html)

        if out_of_stock:
            status = "OUT OF STOCK (restocking message found)"
            in_stock = False
        elif redeem_available:
            status = "🟢 IN STOCK! Redeem button detected!"
            in_stock = True
        else:
            status = "OUT OF STOCK"
            in_stock = False

        log(f"  Status: {status} (page size: {len(html)} bytes)")
        return {"name": name, "url": url, "in_stock": in_stock,
                "status": status}, False

    except Exception as e:
        log(f"  Error checking {name}: {e}")
        return {"name": name, "url": url, "in_stock": False,
                "status": f"ERROR: {e}"}, False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_monitor():
    log("=" * 60)
    log("Bing Rewards Restock Monitor (Playwright Edition)")
    log(f"Tracking {len(ITEMS)} item(s)")
    log("=" * 60)

    if not os.path.exists(BROWSER_STATE_FILE):
        log("❌ browser_state.json not found!")
        log("   Run 'python setup_login.py' on your laptop first.")
        sys.exit(1)

    monitor_state = load_monitor_state()
    items_state = monitor_state.setdefault("items", {})
    any_login_failed = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=BROWSER_STATE_FILE,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        )
        page = await context.new_page()

        for item in ITEMS:
            result, login_required = await check_item(page, item)
            name = item["name"]

            if login_required:
                any_login_failed = True

            prev_in_stock = items_state.get(name, {}).get("in_stock", False)

            if result["in_stock"]:
                if not prev_in_stock:
                    send_restock_alert(result)
                else:
                    log(f"  ℹ️ {name} still in stock (already alerted).")
                items_state[name] = {"in_stock": True}
            else:
                if prev_in_stock:
                    log(f"  ℹ️ {name} is now out of stock again.")
                items_state[name] = {"in_stock": False}

        # Save the REFRESHED browser state back (this is the key!)
        # The browser auto-renewed any rotated tokens during page visits
        if not any_login_failed:
            state = await context.storage_state()
            with open(BROWSER_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            log("✅ Browser state refreshed and saved.")
        else:
            log("⚠️ Login failed — NOT overwriting browser_state.json.")

        await browser.close()

    # Handle session expiration alerts
    if any_login_failed:
        if not monitor_state.get("session_expired_alerted", False):
            send_session_expired_alert()
            monitor_state["session_expired_alerted"] = True
        else:
            log("ℹ️ Session expiry alert already sent. Skipping repeat.")
    else:
        if monitor_state.get("session_expired_alerted", False):
            log("✅ Session is valid again. Resetting alert flag.")
            monitor_state["session_expired_alerted"] = False

    save_monitor_state(monitor_state)
    log("=" * 60)
    log("Check complete.\n")


def main():
    asyncio.run(run_monitor())


if __name__ == "__main__":
    main()
