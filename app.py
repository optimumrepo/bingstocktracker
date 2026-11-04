"""
Bing Rewards 24/7 Restock Monitor (Hugging Face Spaces Edition)
==============================================================
Runs continuously in the cloud every 60 seconds (no laptop needed).
Includes a lightweight built-in HTTP server on port 7860 to satisfy
Hugging Face health checks and provide a live web status dashboard.
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
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
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

# Check interval in seconds (default: 60 seconds)
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL", "60"))

# IST Timezone (UTC +5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Environment Secrets
MS_COOKIE = os.environ.get("MS_COOKIE", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip()
CALLMEBOT_PHONE = os.environ.get("CALLMEBOT_PHONE", "").strip()
CALLMEBOT_API_KEY = os.environ.get("CALLMEBOT_API_KEY", "").strip()

# Global in-memory state
app_state = {
    "start_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    "last_check_time": "Never",
    "check_count": 0,
    "cookie_status": "Loaded" if MS_COOKIE else "Not configured",
    "cookie_expired_alerted": False,
    "items": {},
    "logs": [],
}
state_lock = threading.Lock()

def log(msg: str):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    with state_lock:
        app_state["logs"].append(line)
        if len(app_state["logs"]) > 50:
            app_state["logs"].pop(0)

# ---------------------------------------------------------------------------
# Core Checking Logic
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> tuple[str, str]:
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
        log(f"HTTP Error {e.code} for {url}")
        return "", ""
    except Exception as e:
        log(f"Error fetching {url}: {e}")
        return "", ""


def is_login_required(html: str, final_url: str) -> bool:
    if "login.live.com" in final_url.lower():
        return True
    html_lower = html.lower()
    for ind in LOGIN_INDICATORS:
        if ind in html_lower:
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

    html, final_url = fetch_page(url)
    if not html:
        return {
            "name": name, "url": url, "in_stock": False,
            "status": "ERROR: Could not fetch page",
        }, False

    if is_login_required(html, final_url):
        return {
            "name": name, "url": url, "in_stock": False,
            "status": "⚠️ SIGN-IN REQUIRED (Cookie expired)",
        }, True

    out_of_stock = is_out_of_stock(html)
    redeem_available = has_redeem_button(html)

    if out_of_stock:
        status = "OUT OF STOCK"
        in_stock = False
    elif redeem_available:
        status = "🟢 IN STOCK! Redeem button detected!"
        in_stock = True
    else:
        status = "OUT OF STOCK"
        in_stock = False

    return {
        "name": name, "url": url, "in_stock": in_stock,
        "status": status,
    }, False

# ---------------------------------------------------------------------------
# Notification Senders
# ---------------------------------------------------------------------------

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
            return result.get("ok", False)
    except Exception as e:
        log(f"Error sending Telegram: {e}")
        return False


def send_ntfy(title: str, message: str, url: str = "") -> bool:
    if not NTFY_TOPIC:
        return False
    ntfy_url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    headers = {"Title": title, "Priority": "urgent", "Tags": "gift,moneybag"}
    if url:
        headers["Click"] = url
        headers["Actions"] = f"view, Open Rewards Page, {url}"

    req = urllib.request.Request(ntfy_url, data=message.encode("utf-8"),
                                 method="POST", headers=headers)
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        log(f"Error sending ntfy: {e}")
        return False


def send_whatsapp_callmebot(title: str, message: str) -> bool:
    if not CALLMEBOT_PHONE or not CALLMEBOT_API_KEY:
        return False
    encoded_msg = urllib.parse.quote_plus(message)
    phone = CALLMEBOT_PHONE.replace("+", "").strip()
    url = (f"https://api.callmebot.com/whatsapp.php"
           f"?phone={phone}&text={encoded_msg}&apikey={CALLMEBOT_API_KEY}")
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        log(f"Error sending CallMeBot: {e}")
        return False


def send_cookie_expired_alert():
    tg_msg = (
        "⚠️ *Microsoft Rewards Session Expired*\n\n"
        "Your `MS_COOKIE` has expired and Microsoft is prompting to sign in.\n\n"
        "Please update the `MS_COOKIE` secret in your Hugging Face Space settings."
    )
    ntfy_msg = "Your MS_COOKIE has expired. Please update it in Hugging Face Space secrets."
    wa_msg = "⚠️ Microsoft Rewards session expired! Please refresh your MS_COOKIE in Space settings."

    log("⚠️ Sending session expiration alert...")
    send_telegram("⚠️ Rewards Session Expired", tg_msg)
    send_ntfy("⚠️ Rewards Cookie Expired", ntfy_msg)
    send_whatsapp_callmebot("⚠️ Rewards Cookie Expired", wa_msg)


def send_restock_alert(item: dict):
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

    log(f"🚀 SENDING RESTOCK ALERT FOR {name}!")
    send_telegram(f"🎁 {name} Restocked!", tg_msg)
    send_ntfy(f"🎁 {name} Restocked!", ntfy_msg, url)
    send_whatsapp_callmebot(f"🎁 {name} Restocked!", wa_msg)

# ---------------------------------------------------------------------------
# Background Monitoring Loop
# ---------------------------------------------------------------------------

def monitor_loop():
    log(f"🚀 Monitor worker started. Checking every {CHECK_INTERVAL_SECONDS} seconds...")
    while True:
        try:
            any_login_failed = False
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

            for item in ITEMS:
                result, login_required = check_item(item)
                name = item["name"]

                if login_required:
                    any_login_failed = True

                with state_lock:
                    prev_status = app_state["items"].get(name, {}).get("in_stock", False)

                    if result["in_stock"]:
                        if not prev_status:
                            send_restock_alert(result)
                        app_state["items"][name] = {"in_stock": True, "status": result["status"]}
                    else:
                        app_state["items"][name] = {"in_stock": False, "status": result["status"]}

            with state_lock:
                app_state["last_check_time"] = now_str
                app_state["check_count"] += 1

                if MS_COOKIE and any_login_failed:
                    app_state["cookie_status"] = "❌ Expired / Sign-in required"
                    if not app_state.get("cookie_expired_alerted", False):
                        send_cookie_expired_alert()
                        app_state["cookie_expired_alerted"] = True
                elif MS_COOKIE and not any_login_failed:
                    app_state["cookie_status"] = "✅ Active & Valid"
                    app_state["cookie_expired_alerted"] = False

            log(f"Check #{app_state['check_count']} finished. Sleeping {CHECK_INTERVAL_SECONDS}s...")

        except Exception as e:
            log(f"Unexpected loop error: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)

# ---------------------------------------------------------------------------
# Lightweight Web Dashboard (Port 7860)
# ---------------------------------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        with state_lock:
            items_html = ""
            for name, data in app_state["items"].items():
                in_stock = data.get("in_stock", False)
                status_color = "#10b981" if in_stock else "#ef4444"
                badge = "🟢 IN STOCK" if in_stock else "🔴 OUT OF STOCK"
                items_html += f"""
                <div style="background:#1e293b; padding:15px; border-radius:8px; margin-bottom:12px; border-left: 4px solid {status_color};">
                    <h3 style="margin:0 0 5px 0; color:#f8fafc;">{name}</h3>
                    <span style="background:{status_color}; color:#fff; padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold;">{badge}</span>
                    <p style="margin:8px 0 0 0; color:#94a3b8; font-size:13px;">{data.get('status', 'Checking...')}</p>
                </div>
                """

            logs_text = "\n".join(reversed(app_state["logs"][-20:]))

            html = f"""<!DOCTYPE html>
            <html>
            <head>
                <title>Bing Rewards 24/7 Monitor</title>
                <meta http-equiv="refresh" content="30">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
                    .container {{ max-width: 700px; margin: 0 auto; }}
                    .card {{ background: #1e293b; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }}
                    .stat-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }}
                    .stat-box {{ background: #0f172a; padding: 12px; border-radius: 6px; }}
                    .stat-label {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
                    .stat-value {{ font-size: 18px; font-weight: bold; margin-top: 4px; color: #38bdf8; }}
                    pre {{ background: #000; color: #a3e635; padding: 12px; border-radius: 6px; font-size: 11px; overflow-x: auto; max-height: 250px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1 style="display:flex; align-items:center; gap:10px; font-size:24px; margin-bottom:5px;">
                        🎁 Bing Rewards 24/7 Restock Monitor
                    </h1>
                    <p style="color:#94a3b8; font-size:14px; margin-top:0;">Checking automatically every {CHECK_INTERVAL_SECONDS} seconds • No laptop needed</p>

                    <div class="stat-grid">
                        <div class="stat-box">
                            <div class="stat-label">System Status</div>
                            <div class="stat-value" style="color:#10b981;">🟢 Running 24/7</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">Cookie Status</div>
                            <div class="stat-value">{app_state['cookie_status']}</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">Checks Completed</div>
                            <div class="stat-value">{app_state['check_count']} times</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">Last Check Time</div>
                            <div class="stat-value" style="font-size:14px;">{app_state['last_check_time']}</div>
                        </div>
                    </div>

                    <h2>Tracked Items</h2>
                    {items_html if items_html else "<p style='color:#94a3b8;'>First check running, please wait a moment...</p>"}

                    <h2>Live Logs (Auto-refreshes)</h2>
                    <pre>{logs_text}</pre>
                </div>
            </body>
            </html>"""

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # suppress standard HTTP server request clutter

def main():
    # Start monitor thread
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

    # Start HTTP server on port 7860
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    log(f"Web status dashboard running on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
