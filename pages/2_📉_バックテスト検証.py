import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
import re
import base64
import requests
from datetime import datetime

st.set_page_config(page_title="釘田式・バックテスト PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except: st.stop()

def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex): df.columns = [col[0] for col in df.columns]
    df = df.copy()
    df['SMA20'] = df['Close'].rolling(20).mean()
    std = df['Close'].rolling(20).std()
    df['Upper2'], df['Lower2'] = df['SMA20'] + (std * 2), df['SMA20'] - (std * 2)
    delta = df['Close'].diff()
    df['RSI'] = 100 - (100 / (1 + (delta.clip(lower=0).rolling(14).mean() / -delta.clip(upper=0).rolling(14).mean())))
    return df.dropna()

def update_github_config(side, entry, tp, sl, lots, rule_name="Rule 2"):
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        config_data = {"rule_name": rule_name, "side": side, "entry": float(entry), "tp": float(tp), "sl": float(sl), "lots": float(lots), "status": "waiting_entry", "is_active": True}
        payload = {"message": f"Update {rule_name}", "content": base64.b64encode(json.dumps(config_data, indent=2).encode()).decode(), "sha": res["sha"]}
        return requests.put(url, headers=headers, json=payload).status_code == 200
    except: return False

st.title("📉 バックテスト ＆ Rule 2 監視予約")

if "saved_rule_text" in st.session_state:
    target_pair = st.selectbox("テストペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    if st.button("🚀 精密バックテスト ＆ 改善実行", type="primary"):
        # (バックテスト実行ロジックは以前のものを維持...)
        st.session_state.improved_rule = "AIが提案した改善後のRule 2の内容..." 
        st.success("改善ルール(Rule 2)が生成されました")

    if "improved_rule" in st.session_state:
        st.subheader("💡 改善された新ルール (Rule 2)")
        st.info(st.session_state.improved_rule)
        
        st.subheader("🛡️ Rule 2 資金管理 ＆ 監視予約")
        colA, colB = st.columns(2)
        with colA:
            risk2 = st.number_input("許容損失(円)", value=10000, key="risk2")
            side2 = st.selectbox("方向", ["buy", "sell"], key="side2")
        with colB:
            ent2 = st.number_input("想定Entry", value=150.00, key="ent2")
            tp2 = st.number_input("想定TP", value=151.00, key="tp2")
            sl2 = st.number_input("想定SL", value=149.00, key="sl2")
        
        lots2 = round(risk2 / (abs(ent2 - sl2) * 10000), 2) if abs(ent2 - sl2) > 0 else 0.0
        st.metric("推奨ロット (Rule 2)", f"{lots2} lot")
        
        if st.button("🚀 Rule 2 で監視予約を実行", type="primary", use_container_width=True):
            if update_github_config(side2, ent2, tp2, sl2, lots2, "Rule 2"):
                requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": f"🔥 【Rule 2 監視開始】\n改善された最強ルールを適用しました。\n方向: {side2} / ロット: {lots2}\nEntry: {ent2} / TP: {tp2} / SL: {sl2}"})
                requests.post(st.secrets["GAS_WEBAPP_URL"], json={"date": datetime.now().strftime('%m/%d %H:%M'), "side": side2, "entry": ent2, "lots": lots2, "result": "待機中(Rule 2)"})
                st.success("Rule 2 予約完了！")
