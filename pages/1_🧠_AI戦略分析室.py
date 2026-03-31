import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
from datetime import datetime

st.set_page_config(page_title="釘田式・AI戦略分析室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーの設定を確認してください。")
    st.stop()

# メモリの初期化
if "saved_rule_text" not in st.session_state:
    st.session_state.saved_rule_text = ""

def find_optimal_rule(ticker):
    df = yf.download(ticker, period="1mo", interval="1h")
    price_history = ""
    for index, row in df.iterrows():
        date_str = index.strftime('%m/%d %H:%M')
        try:
            price_val = float(row['Close'].iloc[0])
        except:
            price_val = float(row['Close'])
        price_history += f"{date_str}: {price_val:.3f}\n"
        
    prompt = f"""
    あなたはデイトレード専門のクオンツです。以下の{ticker}の過去1ヶ月・1時間足データを分析し、
    最も利益が出るルールを逆算してください。
    【データ】\n{price_history}
    【指示】
    1. 相場環境の総括
    2. 推奨ルール（エントリー・決済の具体的な条件）
    3. 機能した理由と注意点
    """
    return model.generate_content(prompt).text

st.title("🧠 AI戦略分析室")
target_pair = st.selectbox("分析対象の通貨ペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("💡 過去1ヶ月の最適ルールを考案する", type="primary", use_container_width=True):
    with st.spinner("データを解析中..."):
        st.session_state.temp_result = find_optimal_rule(target_pair)
        st.success("✅ 解析完了")

if "temp_result" in st.session_state:
    st.markdown(st.session_state.temp_result)
    
    # 🌟 ここがポイント：解析結果をバックテストに送るためのボタン
    if st.button("📥 このルールをバックテストに設定する", use_container_width=True):
        st.session_state.saved_rule_text = st.session_state.temp_result
        st.toast("ルールをバックテストページに保存しました！", icon="✅")