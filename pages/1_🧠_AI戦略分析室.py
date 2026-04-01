import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai

st.set_page_config(page_title="釘田式・AI戦略分析室 PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except: st.stop()

if "saved_rule_text" not in st.session_state:
    st.session_state.saved_rule_text = ""

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
    df['RSI14'] = 100 - (100 / (1 + (gain / loss)))
    df['ATR'] = (df['High'] - df['Low']).rolling(14).mean()
    return df.dropna()

def find_optimal_rule(ticker):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df).tail(300)
    data_summary = ""
    for idx, row in df.iterrows():
        data_summary += f"{idx.strftime('%m/%d %H:%M')}|終:{row['Close']:.3f}|BB上:{row['Upper2']:.3f}|BB下:{row['Lower2']:.3f}|RSI:{row['RSI14']:.1f}\n"

    prompt = f"あなたはプロクオンツです。以下の{ticker}の直近300時間データを分析し、ボリンジャーバンドを用いた高期待値ルールを立案してください。\n\n{data_summary}"
    return model.generate_content(prompt).text

st.title("🧠 釘田式・AI戦略分析室 PRO")
target_pair = st.selectbox("分析対象", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("🚀 300時間のデータとBBから最適ルールを逆算", type="primary", use_container_width=True):
    with st.spinner("300時間分のデータを解析中..."):
        st.session_state.temp_result = find_optimal_rule(target_pair)

if "temp_result" in st.session_state:
    st.markdown(st.session_state.temp_result)
    if st.button("📥 このルールをバックテストに適用", use_container_width=True):
        st.session_state.saved_rule_text = st.session_state.temp_result
        st.toast("バックテスト側にルールを保存しました。")
