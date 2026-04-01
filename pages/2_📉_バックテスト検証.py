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
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error("APIキーの設定を確認してください。")
    st.stop()

def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    close = df['Close']
    df['SMA20'] = close.rolling(window=20).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    return df.dropna()

def run_ai_interpretive_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    price_data = ""
    for index, row in df.iterrows():
        price_data += (f"{index.strftime('%m/%d %H:%M')},"
                       f"始:{row['Open']:.3f},高:{row['High']:.3f},安:{row['Low']:.3f},終:{row['Close']:.3f},"
                       f"SMA20:{row['SMA20']:.3f},RSI:{row['RSI14']:.1f},ATR:{row['ATR']:.3f}\n")

    ai_prompt = f"""
    あなたは非常に厳格なバックテスト・エージェントです。提供された【トレードルール】を【価格データ】に適用してください。
    
    【ルール】
    {rule_text}

    【価格データ】
    {price_data}

    【実行指示（最重要）】
    1. **厳格な判定**: エントリー条件を完全に満たしていない場合はトレードを行わないでください。
    2. **現実的なシミュレーション**: 1時間足の高値・安値を考慮し、その時間内に損切り価格にタッチしている場合は、必ず「損切り」として処理してください。
    3. **後出しジャンケンの禁止**: 未来の価格を知っているかのような利益の出し方はせず、あくまでその時点のデータのみで判定してください。

    【出力形式】
    JSON形式のリストのみを出力してください。
    [
      {{"side": "buy"または"sell", "entry_time": "MM/DD HH:MM", "exit_time": "MM/DD HH:MM", "entry_price": 0.0, "exit_price": 0.0, "reason": "根拠"}}
    ]
    """
    
    try:
        response = model.generate_content(ai_prompt).text
        json_str = re.search(r'\[.*\]', response, re.DOTALL).group()
        return json.loads(json_str)
    except:
        return []

st.title("📉 バックテスト検証 PRO")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    with st.expander("現在の検証ルール"):
        st.write(st.session_state.saved_rule_text)
    
    target_pair = st.selectbox("テスト通貨ペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    
    if st.button("🚀 精密バックテストを実行", type="primary", use_container_width=True):
        with st.spinner("AIが1ヶ月分のデータを厳格にシミュレーション中..."):
            trades = run_ai_interpretive_backtest(target_pair, st.session_state.saved_rule_text)
            
            if trades:
                balance = 1000000
                history = []
                win_count = 0
                for t in trades:
                    entry = float(t['entry_price'])
                    exit = float(t['exit_price'])
                    side = t.get('side', 'buy').lower()
                    
                    if side == "buy":
                        pnl = (exit - entry) / entry
                    else:
                        pnl = (entry - exit) / entry # ショートの損益
                    
                    balance *= (1 + pnl)
                    t['pnl_rate'] = pnl * 100
                    t['balance'] = int(balance)
                    if pnl > 0: win_count += 1
                    history.append(t)
                
                st.session_state.test_results = history
                st.session_state.final_balance = balance
                st.session_state.win_rate = (win_count / len(history)) * 100

    if "test_results" in st.session_state:
        st.metric("最終資産", f"{st.session_state.final_balance:,.0f} 円")
        st.dataframe(pd.DataFrame(st.session_state.test_results), use_container_width=True)
else:
    st.info("分析室ページでルールを生成してください。")
