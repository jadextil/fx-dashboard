import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import re
import json

# --- 0. 初期設定 ---
st.set_page_config(page_title="釘田式・AI戦略分析室 PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except:
    st.error("APIキーの設定を確認してください。")
    st.stop()

# --- 1. テクニカル指標計算関数 ---
def add_indicators(df):
    close = df['Close']
    if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
    
    # 移動平均線
    df['SMA20'] = close.rolling(window=20).mean()
    # RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    # ボラティリティ (簡易ATR)
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    
    return df.dropna()

# --- 2. AI分析ロジック ---
def find_optimal_rule(ticker):
    # 1ヶ月分の1時間足データを取得
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    
    df = add_indicators(df)
    
    # AIに渡すデータを要約（全行送ると制限に引っかかるため、特徴的な部分を抽出）
    data_summary = ""
    for index, row in df.tail(100).iterrows(): # 直近100時間を重点的に
        data_summary += (f"{index.strftime('%m/%d %H:%M')} | "
                        f"価格:{row['Close']:.3f} | SMA20:{row['SMA20']:.3f} | "
                        f"RSI:{row['RSI14']:.1f} | ATR:{row['ATR']:.3f}\n")

    prompt = f"""
    あなたは世界最高峰のクオンツ・トレーダーです。
    以下の{ticker}のテクニカルデータ（直近1ヶ月）を読み解き、バックテストで【期待値がプラス】になる最強のデイトレ・ルールを逆算してください。

    【分析用データ】
    {data_summary}

    【あなたの任務】
    1. 相場環境の徹底解剖（今の相場はSMA20に対してどう動いているか？）
    2. ルールの言語化：
       - エントリー条件（例：RSIが30以下で、かつSMA20を上抜けた瞬間など）
       - 決済条件（利確・損切りをATRの何倍に設定すべきか？）
    3. 期待値の根拠（なぜこのルールなら、偶然ではなく必然的に勝てるのか？）

    【注意】
    「なんとなく」のルールは不要です。過去のデータに基づいて、最も安定して資金が増えるロジックを1つだけ提示してください。
    """
    return model.generate_content(prompt).text

# --- 3. 画面構築 ---
st.title("🧠 釘田式・AI戦略分析室 PRO")
st.markdown("数値データの裏付けを持った「勝てるロジック」を逆算します。")

target_pair = st.selectbox("分析対象", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("🚀 最適な勝ちパターンを逆算する", type="primary", use_container_width=True):
    with st.spinner("クオンツAIが1ヶ月分の全データを再検証中..."):
        result = find_optimal_rule(target_pair)
        st.session_state.temp_result = result
        st.success("✅ 最適ルールの抽出に成功しました")

if "temp_result" in st.session_state:
    st.write("---")
    st.markdown(st.session_state.temp_result)
    
    if st.button("📥 このルールをバックテストに適用", use_container_width=True):
        st.session_state.saved_rule_text = st.session_state.temp_result
        st.toast("バックテスト側にルールを保存しました。")
