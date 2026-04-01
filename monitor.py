import yfinance as yf
import requests
import os
import json
import base64
import pandas as pd
from datetime import datetime

# GitHub Secretsから読み込み
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GITHUB_TOKEN = os.environ.get("GH_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GAS_URL = os.environ.get("GAS_WEBAPP_URL") # 🌟 GASのURL

def send_discord(text):
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={"content": text})
        except Exception as e:
            print(f"Discord error: {e}")

def send_to_spreadsheet(log_data):
    """GAS経由でスプレッドシートに結果を記帳"""
    if GAS_URL:
        try:
            requests.post(GAS_URL, json=log_data)
        except Exception as e:
            print(f"GAS error: {e}")
    else:
        print("Error: GAS_WEBAPP_URL is not set in GitHub Secrets.")

def update_config_status(config, sha):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    content_json = json.dumps(config, indent=2)
    content_base64 = base64.b64encode(content_json.encode()).decode()
    requests.put(url, headers=headers, json={"message": "Update status", "content": content_base64, "sha": sha})

def check_price():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    res = requests.get(url, headers=headers).json()
    
    if "content" not in res: return
    sha = res["sha"]
    config = json.loads(base64.b64decode(res["content"]).decode('utf-8'))

    if not config.get("is_active"): return

    side = config.get("side", "buy")
    status = config.get("status", "waiting_entry")
    entry, tp, sl, lots = config["entry"], config["tp"], config["sl"], config.get("lots", 0.0)

    # 価格の取得（より安定した Ticker.history 方式に変更）
    try:
        data = yf.Ticker("JPY=X").history(period="1d", interval="1m")
        if data is None or data.empty: return
        current_p = float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"Price fetch error: {e}")
        return

    # --- 🚪 エントリー待ち（すり抜け防止ロジックに強化！） ---
    if status == "waiting_entry":
        # 買い(buy)の場合：現在価格がエントリー価格「以下」に落ちてきたら発動
        is_entry_buy = (side == "buy" and current_p <= entry + 0.02)
        # 売り(sell)の場合：現在価格がエントリー価格「以上」に上がってきたら発動
        is_entry_sell = (side == "sell" and current_p >= entry - 0.02)

        if is_entry_buy or is_entry_sell:
            send_discord(f"🔔 【クラウド・エントリー到達】\n方向: {side} / ロット: {lots}\n設定: {entry}円 / 現在: {current_p:.3f}円\n※DMM FXで注文を実行してください。自動で決済監視に移行します。")
            config["status"] = "holding"
            update_config_status(config, sha)

    # --- 🏁 決済待ち（利確・損切り） ---
    elif status == "holding":
        is_win = (side == "buy" and current_p >= tp) or (side == "sell" and current_p <= tp)
        is_lose = (side == "buy" and current_p <= sl) or (side == "sell" and current_p >= sl)

        if is_win or is_lose:
            exit_price = tp if is_win else sl
            result_text = "勝ち🎉" if is_win else "負け😢"
            
            # 損益（円）の自動計算 (DMM FX: 1ロット = 10,000通貨)
            if side == "buy":
                pnl = (exit_price - entry) * lots * 10000
            else:
                pnl = (entry - exit_price) * lots * 10000
            pnl = int(pnl) # 整数に変換
            
            # Discord通知
            icon = "💰 【利確達成】" if is_win else "⚠️ 【損切り】"
            send_discord(f"{icon}\n結果: {result_text}\n決済価格: {exit_price}円\n推定損益: {pnl:,}円\n本日の監視を終了します。")
            
            # 🌟 スプレッドシートに記帳
            log_data = {
                "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
                "side": "買い" if side == "buy" else "売り",
                "entry": entry,
                "exit": exit_price,
                "result": result_text,
                "pnl": pnl,
                "lots": lots
            }
            send_to_spreadsheet(log_data)

            # 監視をオフにして終了
            config["is_active"] = False
            config["status"] = "done"
            update_config_status(config, sha)

if __name__ == "__main__":
    check_price()
