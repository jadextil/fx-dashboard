import yfinance as yf
import requests
import os
import json
import base64
import pandas as pd
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
        "message": "Update status by Indicator Monitor",
        "content": content_base64,
        "sha": sha
    }
    requests.put(url, headers=headers, json=payload)

def calculate_indicators(df):
    """監視に必要なインジケーターを計算"""
    df = df.copy()
    close = df['Close']
    # SMA
    df['SMA20'] = close.rolling(window=20).mean()
    df['SMA50'] = close.rolling(window=50).mean()
    # Bollinger Bands
    std = close.rolling(window=20).std()
    df['Upper2'] = df['SMA20'] + (std * 2)
    df['Lower2'] = df['SMA20'] - (std * 2)
    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    return df.dropna()

def check_price():
    """インジケーター条件を判定するメインロジック"""
    # 1. GitHubから現在の設定を取得
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/config.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    try:
        res = requests.get(url, headers=headers).json()
        if "content" not in res: return
        sha = res["sha"]
        config = json.loads(base64.b64decode(res["content"]).decode('utf-8'))
    except: return

    if not config.get("is_active"): return

    rule_name = config.get("rule_name", "Rule 1")
    rule_id = "1" if "1" in rule_name else "2"
    status = config.get("status", "waiting_entry")
    lots = config.get("lots", 0.0)

    # 2. 最新データの取得とインジケーター計算
    try:
        # 1時間足の直近データを取得
        df = yf.download("JPY=X", period="5d", interval="1h", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = [col[0] for col in df.columns]
        df = calculate_indicators(df)
        
        curr = df.iloc[-1]  # 現在の足
        prev = df.iloc[-2]  # 1本前の足
    except: return

    # --- A. エントリー判定 (waiting_entry) ---
    if status == "waiting_entry":
        # 買い条件判定
        buy_trend = curr['SMA20'] > curr['SMA50']
        buy_push  = prev['Close'] < prev['SMA20'] and curr['Close'] > curr['SMA20']
        buy_rsi   = 40 <= curr['RSI'] < 70
        
        # 売り条件判定
        sell_trend = curr['SMA20'] < curr['SMA50']
        sell_push  = prev['Close'] > prev['SMA20'] and curr['Close'] < curr['SMA20']
        sell_rsi   = 30 < curr['RSI'] <= 60

        if buy_trend and buy_push and buy_rsi:
            send_discord(f"🔔 【{rule_name} 買いエントリー】\n条件合致: SMAゴールデンクロス中 + 押し目上抜け\nロット: {lots}\n現在値: {curr['Close']:.3f}\n※決済監視に移行します。")
            config.update({"status": "holding", "side": "buy", "entry": float(curr['Close'])})
            update_config_status(config, sha)
            
        elif sell_trend and sell_push and sell_rsi:
            send_discord(f"🔔 【{rule_name} 売りエントリー】\n条件合致: SMAデッドクロス中 + 戻り下抜け\nロット: {lots}\n現在値: {curr['Close']:.3f}\n※決済監視に移行します。")
            config.update({"status": "holding", "side": "sell", "entry": float(curr['Close'])})
            update_config_status(config, sha)

    # --- B. 決済判定 (holding) ---
    elif status == "holding":
        side = config.get("side")
        entry_price = config.get("entry")
        
        is_exit = False
        res_txt = ""
        
        if side == "buy":
            # 利確: BB上タッチ or RSI > 70
            if curr['Close'] >= curr['Upper2'] or curr['RSI'] > 70:
                is_exit, res_txt = True, "利確 🎉"
            # 損切: デッドクロス発生
            elif curr['SMA20'] < curr['SMA50']:
                is_exit, res_txt = True, "損切り 😢"
        
        elif side == "sell":
            # 利確: BB下タッチ or RSI < 30
            if curr['Close'] <= curr['Lower2'] or curr['RSI'] < 30:
                is_exit, res_txt = True, "利確 🎉"
            # 損切: ゴールデンクロス発生
            elif curr['SMA20'] > curr['SMA50']:
                is_exit, res_txt = True, "損切り 😢"

        if is_exit:
            exit_p = float(curr['Close'])
            pnl = int((exit_p - entry_price) * lots * 10000) if side == "buy" else int((entry_price - exit_p) * lots * 10000)
            
            send_discord(f"🏁 【{rule_name} 決済完了】\n結果: {res_txt}\n決済価格: {exit_p:.3f}円\n損益: {pnl:,}円\n次の方針を待機します。")
            send_to_spreadsheet({"date": datetime.now().strftime('%Y-%m-%d %H:%M'), "rule": rule_id, "side": "買い" if side=="buy" else "売り", "entry": entry_price, "exit": exit_p, "result": res_txt, "pnl": pnl, "lots": lots})
            
            # 🌟 サイクルを回す: 決済が終わったら再度「エントリー待ち」に戻す
            config.update({"status": "waiting_entry", "is_active": True}) 
            update_config_status(config, sha)

if __name__ == "__main__":
    check_price()
