"""
Bing Rewards Gift Card Restock Monitor (Hardened Production Edition)
=====================================================================
Built-in Defenses & Hardening:
1. Anti-Bloat: Strips Microsoft telemetry from localStorage to prevent QuotaExceededError.
2. Safety Guard: Never overwrites browser_state.json unless valid auth cookies exist.
3. Network Resilience: Automatic retry on flaky page loads.
4. Alert Guarantee: Automatic retry on Telegram/ntfy delivery to prevent missed alerts.
5. Parallel Checks: Checks all items concurrently in separate tabs for maximum speed.
6. Resource Blocking: Aborts heavy images, media, fonts, and tracking scripts.
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


def sanitize_storage_state(state: dict) -> dict:
    """Filter out Microsoft's massive telemetry logs from localStorage to prevent quota crashes."""
    clean_origins = []
    for origin in state.get("origins", []):
        clean_ls = [
            item for item in origin.get("localStorage", [])
            if not any(k in item.get("name", "").lower() for k in ["vnext", "telemetry", "1ds", "akey", "aria", "perf"])
            and len(item.get("value", "")) < 1000
        ]
        clean_origins.append({"origin": origin.get("origin"), "localStorage": clean_ls})

    return {
        "cookies": state.get("cookies", []),
        "origins": clean_origins
    }


# ---------------------------------------------------------------------------
# Resilient Notification Senders (With Automatic Retry)
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

    # Retry up to 2 times on network blips
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=payload, method="POST",
                                         headers={"Content-Type": "application/json"})
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                if result.get("ok"):
                    log("  ✅ Telegram sent!")
                    return True
                log(f"  ❌ Telegram API returned error: {result}")
        except Exception as e:
            log(f"  Attempt {attempt + 1} error sending Telegram: {e}")
            if attempt == 0:
                import time
                time.sleep(1)
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

    for attempt in range(2):
        try:
            req = urllib.request.Request(ntfy_url, data=message.encode("utf-8"),
                                         method="POST", headers=headers)
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                if resp.status == 200:
                    log("  ✅ ntfy sent!")
                    return True
        except Exception as e:
            log(f"  Attempt {attempt + 1} error sending ntfy: {e}")
            if attempt == 0:
                import time
                time.sleep(1)
    return False


def send_session_expired_alert():
    log("⚠️ Sending session expiration alert...")
    tg_msg = (
        "⚠️ *Microsoft Rewards Session Expired*\n\n"
        "Your browser session has expired.\n\n"
        "Please run `login.bat` on your laptop to refresh it."
    )
    ntfy_msg = "Your Rewards browser session expired. Run login.bat to re-login."
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

def is_login_page(page_url: str, body_text: str) -> bool:
    if "login.live.com" in page_url.lower():
        return True
    text_lower = body_text.lower()
    for ind in LOGIN_INDICATORS:
        if ind in text_lower:
            return True
    return False


async def check_single_item(context, item: dict) -> tuple[dict, bool]:
    """Check a single item in its own tab with robust element inspection and anti-fluke verification."""
    name = item["name"]
    url = item["url"]
    log(f"Checking: {name}")

    page = await context.new_page()
    try:
        # Retry up to 2 times if page fails to load
        for attempt in range(2):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                # Wait for SKU card hydration (either action button or restocking text)
                try:
                    await page.wait_for_selector(
                        'button:has-text("Redeem now"), button:has-text("Redeem"), text="restocking"',
                        timeout=8000
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(1000)
                break
            except Exception as e:
                if attempt == 0:
                    log(f"  Retrying {name} due to page load delay...")
                    await asyncio.sleep(1)
                else:
                    raise e

        final_url = page.url
        body_text = (await page.inner_text("body")).lower()

        if is_login_page(final_url, body_text):
            log(f"  ⚠️ Session expired — Microsoft redirected to login.")
            return {"name": name, "url": url, "in_stock": False,
                    "status": "SESSION EXPIRED"}, True

        # Check for explicit out-of-stock messages
        has_oos_text = any(phrase in body_text for phrase in OUT_OF_STOCK_PHRASES)

        # Inspect the actual SKU action button (specifically the button, not nav bar)
        btn = page.locator('main button:has-text("Redeem"), button:has-text("Redeem now"), button:has-text("Claim")').first
        btn_exists = await btn.count() > 0
        btn_is_enabled = False
        btn_text = ""

        if btn_exists:
            btn_text = (await btn.inner_text()).strip()
            is_prop_disabled = await btn.is_disabled()
            has_data_disabled = await btn.get_attribute("data-disabled") is not None
            has_aria_disabled = await btn.get_attribute("aria-disabled") == "true"
            btn_is_enabled = not (is_prop_disabled or has_data_disabled or has_aria_disabled)

        # If SKU card failed to render at all
        if not btn_exists and not has_oos_text:
            log(f"  ⚠️ {name} page did not render SKU card. Treating as unverified.")
            return {"name": name, "url": url, "in_stock": False, "status": "ERROR: SKU card not loaded"}, False

        # Preliminary stock status
        preliminary_in_stock = btn_exists and btn_is_enabled and (not has_oos_text)

        # Anti-Fluke Guard: If in stock, re-confirm after 1.5 seconds to eliminate React hydration blips
        if preliminary_in_stock:
            log(f"  ⚡ {name} appears in stock! Performing 1.5s re-confirmation check...")
            await page.wait_for_timeout(1500)
            re_body = (await page.inner_text("body")).lower()
            re_has_oos = any(p in re_body for p in OUT_OF_STOCK_PHRASES)
            re_btn = page.locator('main button:has-text("Redeem"), button:has-text("Redeem now"), button:has-text("Claim")').first
            re_btn_exists = await re_btn.count() > 0
            re_btn_enabled = False
            if re_btn_exists:
                re_disabled = await re_btn.is_disabled()
                re_data_disabled = await re_btn.get_attribute("data-disabled") is not None
                re_aria_disabled = await re_btn.get_attribute("aria-disabled") == "true"
                re_btn_enabled = not (re_disabled or re_data_disabled or re_aria_disabled)

            if re_btn_exists and re_btn_enabled and (not re_has_oos):
                in_stock = True
                status = f"🟢 IN STOCK! Active '{btn_text}' button verified!"
            else:
                log(f"  ⚠️ Re-confirmation rejected initial in_stock reading for {name}.")
                in_stock = False
                status = "OUT OF STOCK (restocking message found on re-check)"
        else:
            in_stock = False
            if has_oos_text:
                status = "OUT OF STOCK (restocking message found)"
            elif btn_exists and not btn_is_enabled:
                status = f"OUT OF STOCK ('{btn_text}' button is disabled)"
            else:
                status = "OUT OF STOCK"

        log(f"  Status: {name} -> {status} (btn_found={btn_exists}, btn_enabled={btn_is_enabled}, oos_text={has_oos_text})")
        return {"name": name, "url": url, "in_stock": in_stock, "status": status}, False

    except Exception as e:
        log(f"  Error checking {name}: {e}")
        return {"name": name, "url": url, "in_stock": False, "status": f"ERROR: {e}"}, False
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_monitor():
    log("=" * 60)
    log("Bing Rewards Restock Monitor (Hardened Production Edition)")
    log(f"Tracking {len(ITEMS)} items in parallel")
    log("=" * 60)

    if not os.path.exists(BROWSER_STATE_FILE):
        log("❌ browser_state.json not found!")
        sys.exit(1)

    monitor_state = load_monitor_state()
    items_state = monitor_state.setdefault("items", {})

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
        )
        context = await browser.new_context(
            storage_state=BROWSER_STATE_FILE,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        )

        # Optimization: Abort heavy media, fonts, and telemetry bloat
        async def block_media_and_trackers(route):
            url = route.request.url.lower()
            if route.request.resource_type in ["image", "media", "font"]:
                await route.abort()
            elif any(tracker in url for tracker in [
                "telemetry", "clarity.ms", "bat.bing.com", "vortex.data.microsoft.com",
                "browser.events.data.msn.com", "1ds.microsoft.com"
            ]):
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", block_media_and_trackers)

        # Check all items in parallel tabs
        tasks = [check_single_item(context, item) for item in ITEMS]
        results = await asyncio.gather(*tasks)

        any_login_failed = False
        for result, login_required in results:
            name = result["name"]
            if login_required:
                any_login_failed = True

            # Don't update in_stock state on transient network errors
            if result.get("status", "").startswith("ERROR:"):
                log(f"  ⚠️ Skipping state update for {name} due to transient network error.")
                continue

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

        # Save refreshed session (with safety checks and telemetry stripped)
        if not any_login_failed:
            raw_state = await context.storage_state()
            clean_state = sanitize_storage_state(raw_state)
            # Safety Guard: Ensure we never overwrite with an empty cookie list
            if clean_state.get("cookies"):
                with open(BROWSER_STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(clean_state, f, indent=2)
                log("✅ Clean browser state refreshed and saved.")
            else:
                log("⚠️ Warning: Refreshed state had no cookies. Preserving existing browser_state.json.")

        await browser.close()

    # Session alert handling
    if any_login_failed:
        if not monitor_state.get("session_expired_alerted", False):
            send_session_expired_alert()
            monitor_state["session_expired_alerted"] = True
    else:
        if monitor_state.get("session_expired_alerted", False):
            log("✅ Session valid. Resetting alert flag.")
            monitor_state["session_expired_alerted"] = False

    save_monitor_state(monitor_state)
    log("=" * 60)
    log("Check complete.\n")


def main():
    asyncio.run(run_monitor())


if __name__ == "__main__":
    main()
