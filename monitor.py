import yfinance as yf
import requests
import os
import json
import base64
from datetime import datetime

# GitHub Secrets から環境変数を取得
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GITHUB_TOKEN = os.environ.get("GH_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GAS_URL = os.environ.get("GAS_WEBAPP_URL")

def send_discord(text):
    """Discordへ通知を送信"""
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

def update_config_status(config, sha):
    """GitHub上のconfig.jsonの状態を更新"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    content_json = json.dumps(config, indent=2)
    content_base64 = base64.b64encode(content_json.encode()).decode()
    
    payload = {
        "message": "Update status by Monitor",
        "content": content_base64,
        "sha": sha
    }
    requests.put(url, headers=headers, json=payload)

def check_price():
    """価格をチェックし、エントリー・決済の判定を行うメインロジック"""
    # 1. GitHubから現在の設定を取得
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        res = requests.get(url, headers=headers).json()
        if "content" not in res:
            print("config.json not found.")
            return
        
        sha = res["sha"]
        config = json.loads(base64.b64decode(res["content"]).decode('utf-8'))
    except Exception as e:
        print(f"GitHub fetch error: {e}")
        return

    # 監視が無効なら終了
    if not config.get("is_active"):
        print("Monitoring is currently inactive.")
        return

    # 設定値の抽出
    rule_full_name = config.get("rule_name", "Rule 1") # "Rule 1" or "Rule 2"
    # スプレッドシート用に "1" か "2" だけを抽出
    rule_id = "1" if "1" in rule_full_name else "2"
    
    side = config.get("side", "buy")
    status = config.get("status", "waiting_entry")
    entry = config["entry"]
    tp = config["tp"]
    sl = config["sl"]
    lots = config.get("lots", 0.0)

    # 2. 現在価格の取得 (JPY=X)
    try:
        data = yf.Ticker("JPY=X").history(period="1d", interval="1m")
        if data.empty:
            print("Price data is empty.")
            return
        current_p = float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"Price fetch error: {e}")
        return

    print(f"Checking {rule_full_name}: Current={current_p:.3f}, Target={entry:.3f}, Status={status}")

    # --- A. エントリー待ちフェーズ ---
    if status == "waiting_entry":
        # 買いの場合: エントリー価格以下にタッチ
        is_entry_buy = (side == "buy" and current_p <= entry + 0.02)
        # 売りの場合: エントリー価格以上にタッチ
        is_entry_sell = (side == "sell" and current_p >= entry - 0.02)

        if is_entry_buy or is_entry_sell:
            # 入口通知
            msg = (f"🔔 【{rule_full_name} エントリー到達】\n"
                   f"方向: {side} / ロット: {lots}\n"
                   f"設定価格: {entry:.3f}円 / 現在価格: {current_p:.3f}円\n"
                   f"※DMM FX等で注文を確認してください。自動で決済監視に移行します。")
            send_discord(msg)
            
            # ステータスを「保持(holding)」に変更してGitHub更新
            config["status"] = "holding"
            update_config_status(config, sha)

    # --- B. 決済待ちフェーズ (利確・損切り) ---
    elif status == "holding":
        is_win = (side == "buy" and current_p >= tp) or (side == "sell" and current_p <= tp)
        is_lose = (side == "buy" and current_p <= sl) or (side == "sell" and current_p >= sl)

        if is_win or is_lose:
            exit_price = tp if is_win else sl
            result_text = "利確 🎉" if is_win else "損切り 😢"
            
            # 損益（円）の計算 (1ロット = 10,000通貨)
            if side == "buy":
                pnl = (exit_price - entry) * lots * 10000
            else:
                pnl = (entry - exit_price) * lots * 10000
            pnl = int(pnl)

            # 出口通知
            icon = "💰" if is_win else "⚠️"
            msg = (f"{icon} 【{rule_full_name} 決済完了】\n"
                   f"結果: {result_text}\n"
                   f"決済価格: {exit_price:.3f}円\n"
                   f"推定損益: {pnl:,}円\n"
                   f"本日の監視を終了します。")
            send_discord(msg)
            
            # 🌟 スプレッドシートに記帳 (ルール列と売買列を分離)
            log_data = {
                "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
                "rule": rule_id,
                "side": "買い" if side == "buy" else "売り",
                "entry": entry,
                "exit": exit_price,
                "result": result_text,
                "pnl": pnl,
                "lots": lots
            }
            send_to_spreadsheet(log_data)

            # 監視をオフにして終了状態へ
            config["is_active"] = False
            config["status"] = "done"
            update_config_status(config, sha)

if __name__ == "__main__":
    check_price()
