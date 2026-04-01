import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
import re

st.set_page_config(page_title="釘田式・バックテスト PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except:
    st.stop()

def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    df['SMA20'] = df['Close'].rolling(20).mean()
    std = df['Close'].rolling(20).std()
    df['Upper2'] = df['SMA20'] + (std * 2)
    df['Lower2'] = df['SMA20'] - (std * 2)
    delta = df['Close'].diff()
    df['RSI'] = 100 - (100 / (1 + (delta.clip(lower=0).rolling(14).mean() / -delta.clip(upper=0).rolling(14).mean())))
    return df.dropna()

def run_ai_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    price_data = ""
    for idx, row in df.iterrows():
        price_data += f"{idx.strftime('%m/%d %H:%M')},終:{row['Close']:.2f},BB上:{row['Upper2']:.2f},BB下:{row['Lower2']:.2f},RSI:{row['RSI']:.1f}\n"

    prompt = f"以下のルールをデータに適用し、全トレードをJSONリストで出力せよ。\n\n【ルール】\n{rule_text}\n\n【データ】\n{price_data}"
    try:
        res = model.generate_content(prompt).text
        match = re.search(r'\[.*\]', res, re.DOTALL)
        return json.loads(match.group()) if match else []
    except: return []

def evaluate_and_improve(rule_text, trades_df):
    prompt = f"結果を分析し改善案を出せ。新ルールを <NEW_RULE>...</NEW_RULE> で囲め。\n\n{trades_df.to_string()}"
    res = model.generate_content(prompt).text
    eval_txt = re.sub(r'<NEW_RULE>.*?</NEW_RULE>', '', res, flags=re.DOTALL).strip()
    match = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', res, re.DOTALL)
    new_rule = match.group(1).strip() if match else rule_text
    return eval_txt, new_rule

st.title("📉 バックテスト検証 ＆ AI自動改善")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    target_pair = st.selectbox("テストペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    if st.button("🚀 精密バックテストを実行", type="primary", use_container_width=True):
        with st.spinner("AI解析中..."):
            trades = run_ai_backtest(target_pair, st.session_state.saved_rule_text)
            if trades:
                initial_balance = 1000000
                balance = initial_balance
                win_count, history = 0, []
                for t in trades:
                    e, ex = float(t['entry_price']), float(t['exit_price'])
                    pnl_rate = (ex - e)/e if t.get('side')=='buy' else (e - ex)/e
                    profit_yen = int(balance * pnl_rate)
                    balance += profit_yen
                    win_loss = "✅ 勝ち" if profit_yen > 0 else "❌ 負け"
                    if profit_yen > 0: win_count += 1
                    history.append({"結果": win_loss, "損益(円)": f"{profit_yen:+,}円", "エントリー": e, "決済": ex, "残高": f"{int(balance):,}円", "理由": t.get('reason')})
                
                st.write("### 📊 結果サマリー")
                c1, c2, c3 = st.columns(3)
                c1.metric("最終資産", f"{int(balance):,} 円")
                c2.metric("純利益", f"{int(balance - initial_balance):+,} 円")
                c3.metric("勝率", f"{(win_count/len(trades)*100):.1f} %")
                st.session_state.history_df = pd.DataFrame(history)
                st.table(st.session_state.history_df)

    if "history_df" in st.session_state:
        if st.button("💡 敗因を分析して改善する"):
            eval_txt, new_r = evaluate_and_improve(st.session_state.saved_rule_text, st.session_state.history_df)
            st.info(eval_txt)
            if st.button("新ルールを上書き保存"):
                st.session_state.saved_rule_text = new_r
                st.rerun()
else:
    st.info("分析室ページでルールを作成してください。")
