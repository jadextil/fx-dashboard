import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
import re

st.set_page_config(page_title="釘田式・バックテスト PRO", layout="wide")

MODEL_NAME = 'gemini-2.5-flash' 

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
except Exception as e:
    st.error(f"APIエラー: {e}")
    st.stop()

def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    # SMA & BB
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['StdDev'] = df['Close'].rolling(window=20).std()
    df['Upper2'] = df['SMA20'] + (df['StdDev'] * 2)
    df['Lower2'] = df['SMA20'] - (df['StdDev'] * 2)
    # RSI
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    # ATR
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    return df.dropna()

def run_ai_interpretive_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    price_data = ""
    for index, row in df.iterrows():
        price_data += (f"{index.strftime('%m/%d %H:%M')},終:{row['Close']:.3f},BB上:{row['Upper2']:.3f},BB下:{row['Lower2']:.3f},"
                       f"SMA20:{row['SMA20']:.3f},RSI:{row['RSI14']:.1f},ATR:{row['ATR']:.3f}\n")

    ai_prompt = f"""
    あなたは凄腕のバックテスト・エージェントです。以下の【ルール】を【価格データ】に厳密に適用してください。
    
    【ルール】
    {rule_text}
    【価格データ】
    {price_data}

    【判定のルール】
    - 未来予知は禁止。その瞬間のデータのみで判断すること。
    - BBのバンドウォークや、RSIの過熱感、ATRによる値幅を考慮したルール実行を徹底してください。
    - 条件に合致しない期間は「ノーエントリー」を維持してください。
    
    【出力形式】
    JSONリストのみ出力。
    [
      {{"side": "buy", "entry_time": "MM/DD HH:MM", "exit_time": "MM/DD HH:MM", "entry_price": 0.0, "exit_price": 0.0, "reason": "根拠"}}
    ]
    """
    
    try:
        response = model.generate_content(ai_prompt)
        json_str = re.search(r'\[.*\]', response.text, re.DOTALL).group()
        return json.loads(json_str)
    except:
        return []

st.title("📉 バックテスト検証 PRO")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    target_pair = st.selectbox("テストペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    
    if st.button("🚀 精密バックテストを実行", type="primary", use_container_width=True):
        with st.spinner("AIがBBとローソク足を1本ずつ照合中..."):
            trades = run_ai_interpretive_backtest(target_pair, st.session_state.saved_rule_text)
            
            if trades:
                balance = 1000000
                history = []
                win_count = 0
                for t in trades:
                    e, ex = float(t['entry_price']), float(t['exit_price'])
                    pnl = (ex - e) / e if t.get('side') == 'buy' else (e - ex) / e
                    balance *= (1 + pnl)
                    t['pnl_rate'] = pnl * 100
                    t['balance'] = int(balance)
                    if pnl > 0: win_count += 1
                    history.append(t)
                
                st.metric("最終資産", f"{balance:,.0f} 円", f"{(balance-1000000):,.0f}")
                st.dataframe(pd.DataFrame(history), use_container_width=True)
            else:
                st.warning("トレードは発生しませんでした。")
else:
    st.info("分析室ページでルールを作成してください。")
