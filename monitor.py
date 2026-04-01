import yfinance as yf
import requests
import os
import json
import base64
import pandas as pd
from datetime import datetime

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GITHUB_TOKEN = os.environ.get("GH_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GAS_URL = os.environ.get("GAS_WEBAPP_URL")

def send_discord(text):
    if WEBHOOK_URL: requests.post(WEBHOOK_URL, json={"content": text})

def send_to_spreadsheet(log_data):
    if GAS_URL: requests.post(GAS_URL, json=log_data)

def update_config_status(config, sha):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    payload = {"message": "Update status", "content": base64.b64encode(json.dumps(config, indent=2).encode()).decode(), "sha": sha}
    requests.put(url, headers=headers, json=payload)

def check_price():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    res = requests.get(url, headers=headers).json()
    if "content" not in res: return
    sha = res["sha"]
    config = json.loads(base64.b64decode(res["content"]).decode('utf-8'))
    if not config.get("is_active"): return

    side, status = config.get("side", "buy"), config.get("status", "waiting_entry")
    entry, tp, sl, lots = config["entry"], config["tp"], config["sl"], config.get("lots", 0.0)

    try:
        data = yf.Ticker("JPY=X").history(period="1d", interval="1m")
        current_p = float(data['Close'].iloc[-1])
    except: return

    if status == "waiting_entry":
        if (side == "buy" and current_p <= entry + 0.02) or (side == "sell" and current_p >= entry - 0.02):
            send_discord(f"🔔 【エントリー】方向:{side}/ロット:{lots}/現在:{current_p:.3f}")
            config["status"] = "holding"
            update_config_status(config, sha)
    elif status == "holding":
        is_win = (side == "buy" and current_p >= tp) or (side == "sell" and current_p <= tp)
        is_lose = (side == "buy" and current_p <= sl) or (side == "sell" and current_p >= sl)
        if is_win or is_lose:
            exit_p = tp if is_win else sl
            pnl = int((exit_p - entry) * lots * 10000) if side == "buy" else int((entry - exit_p) * lots * 10000)
            send_discord(f"{'💰 利確' if is_win else '⚠️ 損切'}\n損益:{pnl:,}円")
            send_to_spreadsheet({"date": datetime.now().strftime('%Y-%m-%d %H:%M'), "side": side, "entry": entry, "exit": exit_p, "result": "WIN" if is_win else "LOSE", "pnl": pnl, "lots": lots})
            config["is_active"], config["status"] = False, "done"
            update_config_status(config, sha)

if __name__ == "__main__": check_price()
