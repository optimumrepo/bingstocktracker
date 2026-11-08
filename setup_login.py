"""
One-Time Login Setup Script
============================
Run this once. A browser window opens.
Log into your burner Microsoft account.
Come back to the terminal and press Enter.
The script saves the session and closes the browser.
"""

import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_state.json")

async def main():
    print("=" * 60, flush=True)
    print("  Bing Rewards — One-Time Login Setup", flush=True)
    print("=" * 60, flush=True)
    print("\nOpening browser window now...\n", flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        )
        page = await context.new_page()
        await page.goto("https://rewards.bing.com/", wait_until="domcontentloaded")

        print("------------------------------------------------------------", flush=True)
        print("  1. In the browser window, log into your BURNER account.", flush=True)
        print("  2. Check 'Stay signed in: Yes' when prompted.", flush=True)
        print("  3. Make sure you see the Rewards dashboard.", flush=True)
        print("------------------------------------------------------------\n", flush=True)

        # Wait for user confirmation in terminal
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, "👉 Once you are logged in, press ENTER here in this window: ")

        print("\nSaving browser session...", flush=True)
        state = await context.storage_state()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        await browser.close()

    print(f"\n✅ Session successfully saved to: {STATE_FILE}")
    print(f"   Size: {os.path.getsize(STATE_FILE)} bytes\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
