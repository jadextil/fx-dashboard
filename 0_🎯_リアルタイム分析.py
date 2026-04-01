import streamlit as st
import yfinance as yf
import pandas as pd
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime, timedelta
from PIL import Image
import requests
import json
import re
import base64

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except:
    st.error("API設定を確認してください。")
    st.stop()

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

def check_economic_calendar():
    """Yahooファイナンス等のRSSから指標情報を簡易チェック（重要度が高いものを抽出）"""
    url = "https://news.yahoo.co.jp/rss/categories/business.xml" # 簡易的にビジネスニュースから
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            root = ET.fromstring(response.read())
        news = [item.find('title').text for item in root.findall('./channel/item')]
        # 危険キーワード（雇用統計、CPI、金利、発言など）
        danger_keywords = ["雇用統計", "CPI", "消費者物価", "政策金利", "FOMC", "日銀"]
        found = [n for n in news if any(k in n for k in danger_keywords)]
        return found
    except: return []

def send_to_spreadsheet(data):
    """Google Apps Script (GAS) 経由でスプレッドシートに記帳"""
    try:
        gas_url = st.secrets["GAS_WEBAPP_URL"]
        requests.post(gas_url, json=data)
    except: pass

def update_github_config(side, entry, tp, sl, lots):
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}"}
        res = requests.get(url, headers=headers).json()
        
        content_dict = {
            "side": side, "entry": entry, "tp": tp, "sl": sl, "lots": lots,
            "status": "waiting_entry", "is_active": True
        }
        content_json = json.dumps(content_dict, indent=2)
        content_base64 = base64.b64encode(content_json.encode()).decode()
        data = {"message": "Update strategy", "content": content_base64, "sha": res["sha"]}
        requests.put(url, headers=headers, json=data)
        return True
    except: return False

# ==========================================
# メイン画面
# ==========================================
st.title("🎯 釘田式・プロ仕様 AI指令室")

col1, col2, col3 = st.columns([1.2, 2, 2])

with col1:
    usd_p, usd_d = get_fx_data("JPY=X")
    st.metric("🇺🇸 ドル/円", f"{usd_p:.3f} 円", f"{usd_d:.3f}")
    
    st.write("---")
    st.subheader("⚠️ 指標アラート")
    danger_news = check_economic_calendar()
    if danger_news:
        for n in danger_news[:3]:
            st.warning(f"注目指標: {n}")
    else:
        st.success("現在、大きな指標ニュースはありません。")

with col2:
    if st.button("✨ 総合解析 ＆ 戦略算出", use_container_width=True, type="primary"):
        with st.spinner("AI解析中..."):
            st.session_state.strategy_result = model.generate_content(f"現在{usd_p:.3f}円。デイトレ戦略を提案して。").text
            json_res = model.generate_content(f"現在{usd_p:.3f}円。以下をJSONのみで。{{\"side\": \"buy\"/\"sell\", \"entry\": 150.1, \"tp\": 150.5, \"sl\": 149.8}}").text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match:
                st.session_state.target_prices = json.loads(match.group())

with col3:
    if "strategy_result" in st.session_state and st.session_state.strategy_result:
        st.success(st.session_state.strategy_result)
        
        if st.session_state.target_prices:
            tp_data = st.session_state.target_prices
            
            # --- 🛡️ 資金管理セクション ---
            st.subheader("🛡️ リスク管理設定")
            risk_cash = st.number_input("今回の損失許容額 (円)", value=10000, step=1000)
            
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_data['side']=="buy" else 1)
            t_entry = st.number_input("エントリー", value=float(tp_data['entry']), step=0.01)
            t_sl = st.number_input("損切(SL)", value=float(tp_data['sl']), step=0.01)
            t_tp = st.number_input("利確(TP)", value=float(tp_data['tp']), step=0.01)
            
            # ロット計算 (DMM FX: 1ロット=10,000通貨)
            pips_risk = abs(t_entry - t_sl)
            if pips_risk > 0:
                # 計算式: 許容損失 / (損切幅 * 10,000)
                calc_lots = risk_cash / (pips_risk * 10000)
                calc_lots = round(calc_lots, 2)
            else:
                calc_lots = 0.0
            
            st.info(f"💡 推奨ロット数: **{calc_lots} ロット** (DMM FX基準)")

            if st.button("🚀 この条件で予約 ＆ スプレッドシート記録", use_container_width=True, type="primary"):
                # 1. GitHub予約
                if update_github_config(side, t_entry, t_tp, t_sl, calc_lots):
                    # 2. スプレッドシート記帳 (GAS連携)
                    log_data = {
                        "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
                        "side": side, "entry": t_entry, "tp": t_tp, "sl": t_sl, "lots": calc_lots
                    }
                    send_to_spreadsheet(log_data)
                    
                    st.success(f"予約完了！ DMM FXで **{calc_lots}ロット** を発注準備してください。")
                    requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": f"🎯 【予約確定】\n方向: {side}\nロット: {calc_lots}\nエントリー: {t_entry}円\n※損切り時は約{risk_cash}円の損失に抑えます。"})
