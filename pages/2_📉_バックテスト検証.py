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
except: st.stop()

def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    std = df['Close'].rolling(window=20).std()
    df['Upper2'] = df['SMA20'] + (std * 2)
    df['Lower2'] = df['SMA20'] - (std * 2)
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -1 * delta.clip(upper=0).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + gain/loss))
    return df.dropna()

def run_ai_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    price_data = ""
    for idx, row in df.iterrows():
        price_data += f"{idx.strftime('%m/%d %H:%M')},終:{row['Close']:.2f},BB上:{row['Upper2']:.2f},BB下:{row['Lower2']:.2f},RSI:{row['RSI']:.1f}\n"

    prompt = f"以下のルールを価格データに適用し、全トレードをJSONリスト形式 [{{'side':'buy','entry_price':0,'exit_price':0,'entry_time':'...','exit_time':'...','reason':'...'}}] のみで出力せよ。\n\n【ルール】\n{rule_text}\n\n【データ】\n{price_data}"
    try:
        res = model.generate_content(prompt).text
        match = re.search(r'\[.*\]', res, re.DOTALL)
        return json.loads(match.group()) if match else []
    except: return []

def evaluate_and_improve(rule_text, trades_df):
    prompt = f"以下のルールと結果を分析し、改善案を提示せよ。新ルールを <NEW_RULE>...</NEW_RULE> で囲むこと。\n\n【ルール】\n{rule_text}\n\n【結果】\n{trades_df.to_string()}"
    res = model.generate_content(prompt).text
    eval_text = re.sub(r'<NEW_RULE>.*?</NEW_RULE>', '', res, flags=re.DOTALL).strip()
    match = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', res, re.DOTALL)
    new_rule = match.group(1).strip() if match else rule_text
    return eval_text, new_rule

st.title("📉 バックテスト検証 ＆ AI自動改善 PRO")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    with st.expander("現在の検証ルール"): st.write(st.session_state.saved_rule_text)
    target_pair = st.selectbox("テストペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    
    if st.button("🚀 精密バックテストを実行", type="primary", use_container_width=True):
        with st.spinner("解析中..."):
            trades = run_ai_backtest(target_pair, st.session_state.saved_rule_text)
            if trades:
                balance = 1000000
                history = []
                for t in trades:
                    e, ex = float(t['entry_price']), float(t['exit_price'])
                    pnl = (ex - e)/e if t.get('side')=='buy' else (e - ex)/e
                    balance *= (1 + pnl)
                    t['pnl_rate'] = pnl * 100
                    t['balance'] = int(balance)
                    history.append(t)
                st.session_state.test_results_df = pd.DataFrame(history)
                st.session_state.final_balance = balance

    if "test_results_df" in st.session_state:
        st.metric("最終資産", f"{st.session_state.final_balance:,.0f} 円")
        st.dataframe(st.session_state.test_results_df, use_container_width=True)
        if st.button("💡 敗因を分析して改善する"):
            eval_text, new_r = evaluate_and_improve(st.session_state.saved_rule_text, st.session_state.test_results_df)
            st.info(eval_text)
            st.session_state.improved_rule = new_r
            if st.button("新ルールを上書き適用"):
                st.session_state.saved_rule_text = new_r
                st.rerun()
else:
    st.info("分析室ページでルールを作成してください。")
