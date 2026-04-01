import streamlit as st
import yfinance as yf
import pandas as pd
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime
from PIL import Image
import requests
import time
import json
import re
import base64

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーが設定されていません。")
    st.stop()

# セッション状態
if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

# --- 1. 共通関数群 ---
def get_fx_data(ticker):
    try:
        data = yf.download(ticker, period="5d", interval="1d", progress=False)
        if not data.empty:
            current = float(data['Close'].iloc[-1])
            diff = current - float(data['Close'].iloc[-2])
            return current, diff
    except: pass
    return 0, 0

def get_current_price(ticker):
    try:
        data = yf.download(ticker, period="1d", interval="1m", progress=False)
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except: pass
    return 0

def send_discord_message(text):
    try:
        requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": text})
    except: pass

def update_github_config(side, entry, tp, sl):
    """GitHubに『売買方向』を含めて送信"""
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        sha = res["sha"]
        
        # 🌟 side (buy/sell) を追加
        content_dict = {
            "side": side, "entry": entry, "tp": tp, "sl": sl, 
            "status": "waiting_entry", "is_active": True
        }
        content_json = json.dumps(content_dict, indent=2)
        content_base64 = base64.b64encode(content_json.encode()).decode()
        data = {"message": "Update strategy", "content": content_base64, "sha": sha}
        requests.put(url, headers=headers, json=data)
        return True
    except: return False

# ==========================================
# メイン画面
# ==========================================
st.title("🎯 リアルタイム AI相場解析 ＆ 売り買い両対応監視")

col1, col2, col3 = st.columns([1.2, 2, 2])

with col1:
    usd_p, usd_d = get_fx_data("JPY=X")
    st.metric("🇺🇸 ドル/円", f"{usd_p:.3f} 円", f"{usd_d:.3f}")

with col2:
    if st.button("✨ 総合解析 ＆ 戦略算出", use_container_width=True, type="primary"):
        with st.spinner("AI解析中..."):
            # 戦略立案
            st.session_state.strategy_result = model.generate_content(f"現在{usd_p:.3f}円。今後の方向性とエントリー、利確、損切の目安を教えて。").text
            # 🌟 売買方向(side)を含むJSON抽出
            json_prompt = f"現在{usd_p:.3f}円。以下のJSONのみで回答して。{{\"side\": \"buy\"または\"sell\", \"entry\": 150.10, \"tp\": 150.50, \"sl\": 149.80}}"
            json_res = model.generate_content(json_prompt).text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match:
                st.session_state.target_prices = json.loads(match.group())

with col3:
    if st.session_state.strategy_result:
        st.success(st.session_state.strategy_result)
        if st.session_state.target_prices:
            tp_data = st.session_state.target_prices
            # 画面上で売買方向を表示・変更可能に
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_data['side']=="buy" else 1)
            t_entry = st.number_input("エントリー", value=float(tp_data['entry']), step=0.01)
            t_tp = st.number_input("利確(TP)", value=float(tp_data['tp']), step=0.01)
            t_sl = st.number_input("損切(SL)", value=float(tp_data['sl']), step=0.01)

            if st.button("🌐 24時間クラウド監視を予約", use_container_width=True, type="primary"):
                if update_github_config(side, t_entry, t_tp, t_sl):
                    st.success(f"予約完了！ {'買い' if side=='buy' else '売り'}で監視します。")
                    send_discord_message(f"✅ 【監視開始】方向: {side} / 目標: {t_entry}円")

            # --- ローカル監視ロジック ---
            if st.button("💻 ブラウザで監視スタート"):
                st.info("監視中...")
                status = "entry"
                while True:
                    curr = get_current_price("JPY=X")
                    if status == "entry":
                        if abs(curr - t_entry) <= 0.02:
                            send_discord_message(f"🔔 到着！{side}でエントリーしてください。")
                            status = "exit"
                    else:
                        # 🌟 売り買いによる判定の逆転
                        if side == "buy":
                            if curr >= t_tp: send_discord_message("💰 利確！"); break
                            if curr <= t_sl: send_discord_message("⚠️ 損切"); break
                        else: # sellの場合
                            if curr <= t_tp: send_discord_message("💰 利確！"); break
                            if curr >= t_sl: send_discord_message("⚠️ 損切"); break
                    time.sleep(300)
