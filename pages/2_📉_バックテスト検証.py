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
    df['RSI'] = 100 - (100 / (1 + (delta.clip(lower=0).rolling(14).mean() / -delta.clip(upper=0).rolling(14).mean())))
    return df.dropna()

def run_ai_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    price_data = ""
    for idx, row in df.iterrows():
        price_data += f"{idx.strftime('%m/%d %H:%M')},終:{row['Close']:.2f},BB上:{row['Upper2']:.2f},BB下:{row['Lower2']:.2f},RSI:{row['RSI']:.1f}\n"

    prompt = f"以下のルールをデータに適用し、全トレードをJSONリスト [{{'side':'buy','entry_price':0,'exit_price':0,'entry_time':'...','exit_time':'...','reason':'...'}}] で出力せよ。解説不要。\n\n【ルール】\n{rule_text}\n\n【データ】\n{price_data}"
    try:
        res = model.generate_content(prompt).text
        match = re.search(r'\[.*\]', res, re.DOTALL)
        return json.loads(match.group()) if match else []
    except: return []

st.title("📉 バックテスト検証 ＆ AI自動改善")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    target_pair = st.selectbox("テストペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    
    if st.button("🚀 精密バックテストを実行", type="primary", use_container_width=True):
        with st.spinner("AIが全トレードを計算中..."):
            trades = run_ai_backtest(target_pair, st.session_state.saved_rule_text)
            if trades:
                initial_balance = 1000000
                balance = initial_balance
                history = []
                win_count = 0
                
                for t in trades:
                    e, ex = float(t['entry_price']), float(t['exit_price'])
                    # 損益率計算
                    pnl_rate = (ex - e)/e if t.get('side')=='buy' else (e - ex)/e
                    # 円建て損益（現在の残高に対して計算）
                    profit_yen = int(balance * pnl_rate)
                    balance += profit_yen
                    
                    win_loss = "✅ 勝ち" if profit_yen > 0 else "❌ 負け"
                    if profit_yen > 0: win_count += 1
                    
                    history.append({
                        "結果": win_loss,
                        "売買": t.get('side'),
                        "損益(円)": f"{profit_yen:+,}円",
                        "利率": f"{pnl_rate*100:.2f}%",
                        "エントリー価格": e,
                        "決済価格": ex,
                        "入った時間": t.get('entry_time'),
                        "出た時間": t.get('exit_time'),
                        "残高": f"{int(balance):,}円",
                        "理由": t.get('reason')
                    })
                
                st.session_state.backtest_results = history
                st.session_state.backtest_summary = {
                    "final_balance": balance,
                    "net_profit": balance - initial_balance,
                    "win_rate": (win_count / len(trades)) * 100,
                    "count": len(trades)
                }

    if "backtest_results" in st.session_state:
        summary = st.session_state.backtest_summary
        
        # 概要をメトリックで表示
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最終資産", f"{int(summary['final_balance']):,} 円")
        c2.metric("純損益", f"{int(summary['net_profit']):+,} 円")
        c3.metric("勝率", f"{summary['win_rate']:.1f} %")
        c4.metric("取引回数", f"{summary['count']} 回")
        
        st.write("### 📜 詳細トレード履歴")
        st.table(pd.DataFrame(st.session_state.backtest_results))
        
        if st.button("💡 この結果からルールを改善する"):
            # 改善ロジック（省略せず維持）
            prompt = f"以下の結果を分析し、改善案を出せ。新ルールを <NEW_RULE>...</NEW_RULE> で囲め。\n\n{pd.DataFrame(st.session_state.backtest_results).to_string()}"
            res = model.generate_content(prompt).text
            st.info(res)
            match = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', res, re.DOTALL)
            if match:
                st.session_state.saved_rule_text = match.group(1).strip()
                st.success("新ルールを保存しました。再テスト可能です。")
else:
    st.info("分析室ページでルールを作成してください。")
