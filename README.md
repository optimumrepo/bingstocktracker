# Bing Rewards Gift Card Restock Monitor 🎁

Automatically monitors Microsoft Rewards gift card pages and sends you a **Telegram** and/or **WhatsApp** notification the moment they get restocked — running **for free on GitHub Actions** (no laptop needed).

## Currently Tracking

| Item | URL |
|------|-----|
| Flipkart Gift Card | https://rewards.bing.com/redeem/sku/000885000034 |
| Overwatch Coins Digital Code | https://rewards.bing.com/redeem/sku/000485000005 |

---

## 🚀 Setup Guide

### Step 1: Set Up Telegram Bot (Recommended — 2 min)

The Telegram Bot API is completely free, ultra-reliable, and takes just 2 minutes.

1. **Create a bot** — Open Telegram, search for `@BotFather`, and send:
   ```
   /newbot
   ```
   - Choose a name (e.g., `Rewards Alert`)
   - Choose a username (e.g., `my_rewards_alert_bot`)
   - BotFather will give you a **Bot Token** like `123456789:ABCdefGhIJKlmNoPQRs`

2. **Get your Chat ID** — Search for `@userinfobot` on Telegram and send it any message. It will reply with your **Chat ID** (a number like `987654321`).

3. **Start your bot** — Open a chat with your new bot (search its username) and press **Start** or send `/start`. This is required for the bot to be able to message you.

4. **Test it** — Open this URL in your browser (replace the values):
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/sendMessage?chat_id=<YOUR_CHAT_ID>&text=Hello!
   ```
   You should get a message from your bot on Telegram!

### Step 1b: Set Up CallMeBot WhatsApp (Optional)

If you also want WhatsApp notifications:

1. Save **+34 623 78 64 49** in your contacts as "CallMeBot"  
   *(If this doesn't work, try alternate number: **+34 684 72 39 62**)*
2. Send this exact message to CallMeBot on WhatsApp:
   ```
   I allow callmebot to send me messages
   ```
3. Wait 1-2 minutes — you'll get a reply with your API key

### Step 2: Create a GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Create a **private** repository (e.g., `bing-rewards-tracker`)
3. Push this code to it:

```bash
cd bing-rewards-tracker
git init
git add .
git commit -m "Initial commit — restock monitor"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/bing-rewards-tracker.git
git push -u origin main
```

### Step 3: Add Secrets to GitHub

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add:

**Telegram (recommended):**

| Secret Name | Value | Example |
|-------------|-------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | `123456789:ABCdefGhIJKlmNoPQRs` |
| `TELEGRAM_CHAT_ID` | Your chat ID from @userinfobot | `987654321` |

**CallMeBot WhatsApp (optional):**

| Secret Name | Value | Example |
|-------------|-------|---------|
| `CALLMEBOT_PHONE` | Your WhatsApp number | `+919876543210` |
| `CALLMEBOT_API_KEY` | API key from CallMeBot | `1234567` |

### Step 4: Enable GitHub Actions

1. Go to your repo → **Actions** tab
2. You should see the "Bing Rewards Restock Monitor" workflow
3. Click **Enable workflow** if prompted
4. Click **Run workflow** → **Run workflow** to test it manually

That's it! ✅ The monitor will now check every **10 minutes**, 24/7, for free.

---

## 📂 Project Structure

```
bing-rewards-tracker/
├── monitor.py                          # Main monitoring script
├── .github/
│   └── workflows/
│       └── restock-monitor.yml         # GitHub Actions cron workflow
├── .gitignore
└── README.md                           # This file
```

## ⚙️ Configuration

### Add More Items to Track

Edit `monitor.py` and add entries to the `ITEMS` list:

```python
ITEMS = [
    {
        "name": "Flipkart Gift Card",
        "url": "https://rewards.bing.com/redeem/sku/000885000034",
    },
    {
        "name": "Overwatch Coins Digital Code",
        "url": "https://rewards.bing.com/redeem/sku/000485000005",
    },
    # Add more:
    {
        "name": "Another Gift Card",
        "url": "https://rewards.bing.com/redeem/sku/XXXXXXXXXX",
    },
]
```

### Change Check Frequency

Edit `.github/workflows/restock-monitor.yml` and change the cron schedule:

| Schedule | Cron Expression | Monthly Minutes Used |
|----------|----------------|---------------------|
| Every 10 min (default) | `*/10 * * * *` | ~1,080 min |
| Every 5 min | `*/5 * * * *` | ~2,160 min |
| Every 30 min | `*/30 * * * *` | ~360 min |
| Every hour | `0 * * * *` | ~180 min |

> ⚠️ GitHub Actions free tier: **2,000 min/month** (private repos) or **unlimited** (public repos).

### Run Locally (optional)

```bash
# Set credentials (PowerShell)
$env:TELEGRAM_BOT_TOKEN="123456789:ABCdef..."
$env:TELEGRAM_CHAT_ID="987654321"

# Single check
python monitor.py --once

# Continuous monitoring (every 5 min)
python monitor.py
```

---

## 🛠 Troubleshooting

| Issue | Fix |
|-------|-----|
| No Telegram message | Make sure you pressed "Start" in the chat with your bot |
| No WhatsApp message | Verify you sent the activation message to the correct CallMeBot number |
| GitHub Actions not running | Check Actions tab → enable the workflow |
| "HTTP Error 403" in logs | Microsoft may be blocking — the script uses browser-like headers to avoid this |
| Getting false positives | The script alerts if no out-of-stock message is found — check the page manually |

---

## 📜 License

Personal use. Not affiliated with Microsoft, Bing Rewards, Telegram, or CallMeBot.
