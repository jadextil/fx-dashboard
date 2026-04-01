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

st.title("📉 バックテスト検証 ＆ AI改善 (Rule 2)")

if "saved_rule_text" in st.session_state:
    target_pair = st.selectbox("テストペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    if st.button("🚀 精密バックテスト ＆ 改善実行", type="primary", use_container_width=True):
        with st.spinner("AIが計算中..."):
            df = yf.download(target_pair, period="1mo", interval="1h", progress=False)
            df = add_indicators(df)
            price_data = "\n".join([f"{idx.strftime('%m/%d %H:%M')},終:{row['Close']:.2f},BB上:{row['Upper2']:.2f},BB下:{row['Lower2']:.2f}" for idx, row in df.iterrows()])
            res = model.generate_content(f"以下のルールをデータに適用しJSONリストで出力せよ。\nルール:\n{st.session_state.saved_rule_text}\nデータ:\n{price_data}").text
            match = re.search(r'\[.*\]', res, re.DOTALL)
            trades = json.loads(match.group()) if match else []
            
            if trades:
                initial_balance, balance, win_count, history = 1000000, 1000000, 0, []
                for t in trades:
                    e, ex = float(t['entry_price']), float(t['exit_price'])
                    pnl_rate = (ex - e)/e if t.get('side')=='buy' else (e - ex)/e
                    profit_yen = int(balance * pnl_rate)
                    balance += profit_yen
                    win_loss = "✅ 勝ち" if profit_yen > 0 else "❌ 負け"
                    if profit_yen > 0: win_count += 1
                    history.append({"結果": win_loss, "損益(円)": f"{profit_yen:+,}円", "エントリー": e, "決済": ex, "時間": t.get('entry_time'), "理由": t.get('reason')})
                
                st.metric("最終資産", f"{int(balance):,} 円", f"{int(balance-initial_balance):+,} 円")
                st.table(pd.DataFrame(history))
                
                # 改善提案
                improve_res = model.generate_content(f"以下の結果から改善案を出し、新ルールを <NEW_RULE>...</NEW_RULE> で囲め。\n{pd.DataFrame(history).to_string()}").text
                st.info(improve_res)
                rule2_match = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', improve_res, re.DOTALL)
                if rule2_match: st.session_state.improved_rule = rule2_match.group(1).strip()

    if "improved_rule" in st.session_state:
        st.write("---")
        st.subheader("🛡️ Rule 2 (改善ルール) の監視予約")
        colA, colB = st.columns(2)
        with colA:
            risk2 = st.number_input("許容損失(円)", value=10000, key="r2")
            side2 = st.selectbox("売買方向", ["buy", "sell"], key="s2")
        with colB:
            ent2 = st.number_input("Entry", value=150.0, step=0.01, key="e2")
            tp2 = st.number_input("TP", value=151.0, step=0.01, key="t2")
            sl2 = st.number_input("SL", value=149.0, step=0.01, key="sl2")
        
        lots2 = round(risk2 / (abs(ent2 - sl2) * 10000), 2) if abs(ent2 - sl2) > 0 else 0.0
        st.metric("推奨ロット (Rule 2)", f"{lots2} lot")
        
        if st.button("🚀 Rule 2 で監視予約", type="primary", use_container_width=True):
            if update_github_config(side2, ent2, tp2, sl2, lots2, "Rule 2"):
                requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": f"🔥 【Rule 2 予約確定】\n改善ルールによる監視を開始しました。\nロット: {lots2}\nEntry: {ent2} / TP: {tp2} / SL: {sl2}"})
                requests.post(st.secrets["GAS_WEBAPP_URL"], json={"date": datetime.now().strftime('%m/%d %H:%M'), "side": f"Rule 2({side2})", "entry": ent2, "lots": lots2, "result": "待機中"})
                st.success("Rule 2 予約完了！")
