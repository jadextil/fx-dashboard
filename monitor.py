import yfinance as yf
import requests
import os
import json
import base64
import pandas as pd

# GitHub Secretsから読み込み
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GITHUB_TOKEN = os.environ.get("GH_TOKEN")  # ★注意：GitHubのSecretsにPATを「GH_TOKEN」という名前で登録してください
GITHUB_REPO = os.environ.get("GITHUB_REPO")

def send_discord(text):
    if WEBHOOK_URL:
        requests.post(WEBHOOK_URL, json={"content": text})

def update_config_status(config, sha):
    """状態が変わったらGitHubのconfig.jsonを上書きして記憶させる"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    content_json = json.dumps(config, indent=2)
    content_base64 = base64.b64encode(content_json.encode()).decode()
    data = {"message": "State auto-update by monitor", "content": content_base64, "sha": sha}
    requests.put(url, headers=headers, json=data)

def check_price():
    # 1. GitHub上の指令ファイルを読み込む
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    res = requests.get(url, headers=headers).json()
    
    if "content" not in res:
        return
        
    sha = res["sha"]
    content_decoded = base64.b64decode(res["content"]).decode('utf-8')
    config = json.loads(content_decoded)

    if not config.get("is_active"):
        return # 監視がオフなら終了

    # 🌟 「売り(sell)」「買い(buy)」の方向と「ロット数」を取得
    side = config.get("side", "buy")
    status = config.get("status", "waiting_entry")
    entry = config["entry"]
    tp = config["tp"]
    sl = config["sl"]
    lots = config.get("lots", 0.0) # ロット数を追加（古い設定用に対策済み）

    # 2. 現在価格を取得（エラーが起きにくい download方式）
    try:
        data = yf.download("JPY=X", period="1d", interval="1m", progress=False)
        if data is None or data.empty:
            return
            
        # yfinanceのバージョンによるデータ構造の違いを吸収
        close_data = data['Close']
        if isinstance(close_data, pd.DataFrame):
            close_data = close_data.iloc[:, 0]
        current_p = float(close_data.iloc[-1])
    except Exception as e:
        print(f"Error fetching price: {e}")
        return

    # 3. 状態(フェーズ)に応じた監視ロジック
    if status == "waiting_entry":
        if abs(current_p - entry) <= 0.03:
            # 🌟 通知にDMM FX用のロット数を追加！
            send_discord(f"🔔 【クラウド・エントリー到達】\n方向: {side}\n推奨ロット: {lots} ロット\n設定: {entry}円\n現在: {current_p:.3f}円\n※DMM FXで注文を実行してください。自動で決済監視に移行します。")
            config["status"] = "holding" # 状態を「保有中」に変更
            update_config_status(config, sha)

    elif status == "holding":
        # 🌟 売り・買いで利確/損切りの判定を逆転させる
        is_win = (side == "buy" and current_p >= tp) or (side == "sell" and current_p <= tp)
        is_lose = (side == "buy" and current_p <= sl) or (side == "sell" and current_p >= sl)

        if is_win:
            send_discord(f"💰 【クラウド・利確達成】\n方向: {side} / 目標の{tp}円に到達！\n現在: {current_p:.3f}円\n本日の監視を完全終了します。")
            config["is_active"] = False
            config["status"] = "done"
            update_config_status(config, sha)
            
        elif is_lose:
            send_discord(f"⚠️ 【クラウド・損切り到達】\n方向: {side} / 撤退ラインの{sl}円に到達。\n現在: {current_p:.3f}円\n本日の監視を完全終了します。")
            config["is_active"] = False
            config["status"] = "done"
            update_config_status(config, sha)

if __name__ == "__main__":
    check_price()
