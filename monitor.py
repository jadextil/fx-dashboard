import yfinance as yf
import requests
import os

# GitHubの「Secrets」から設定を読み込む
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
TARGET_PRICE = 150.50  # ここをAIに書き換えさせるか、固定値にする

def send_discord(text):
    requests.post(WEBHOOK_URL, json={"content": text})

def check_price():
    data = yf.Ticker("JPY=X").history(period="1d", interval="1m")
    current_p = data['Close'].iloc[-1]
    
    # 到達判定（例：150.50円を超えたら）
    if current_p >= TARGET_PRICE:
        send_discord(f"🔔 【全自動監視】目標の{TARGET_PRICE}円に到達しました！ 現在：{current_p:.3f}円")

if __name__ == "__main__":
    check_price()