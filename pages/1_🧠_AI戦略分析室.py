import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai

# --- 0. 初期設定 ---
st.set_page_config(page_title="釘田式・AI戦略分析室 PRO", layout="wide")

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

# --- 1. テクニカル指標計算関数 ---
def add_indicators(df):
    # yfinanceのマルチインデックス対策
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    # 移動平均線
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    
    # ボラティリティ (簡易ATR)
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    
    return df.dropna()

# --- 2. AI分析ロジック ---
def find_optimal_rule(ticker):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    # 🌟 OHLC（始値・高値・安値・終値）をすべてAIに渡す！
    data_summary = ""
    for index, row in df.tail(100).iterrows(): 
        data_summary += (f"{index.strftime('%m/%d %H:%M')} | "
                         f"始:{row['Open']:.3f} 高:{row['High']:.3f} 安:{row['Low']:.3f} 終:{row['Close']:.3f} | "
                         f"SMA20:{row['SMA20']:.3f} RSI:{row['RSI14']:.1f} ATR:{row['ATR']:.3f}\n")

    prompt = f"""
    あなたは世界最高峰のクオンツ・トレーダーです。
    以下の{ticker}のローソク足データ（OHLC）とテクニカル指標（直近100時間分）を読み解き、バックテストで【期待値がプラス】になる最強のデイトレ・ルールを逆算してください。

    【分析用データ】
    {data_summary}

    【あなたの任務】
    1. 相場環境とローソク足の徹底解剖（ヒゲの長さ、高値・安値の切り上げ/切り下げ等に注目してください）
    2. ルールの言語化：
       - エントリー条件（テクニカル指標とローソク足のプライスアクションを組み合わせること）
       - 決済条件（最高値・最低値やATRを基準にした、現実的で狩られにくい利確・損切りの幅）
    3. 期待値の根拠（なぜこのルールなら優位性が発生するのか？）

    【注意】
    過去のデータに基づいて、最も安定して資金が増えるロジックを1つだけ提示してください。
    """
    return model.generate_content(prompt).text

# --- 3. 画面構築 ---
st.title("🧠 釘田式・AI戦略分析室 PRO")
st.markdown("ローソク足の形状（ヒゲ）と数値データの裏付けを持った「勝てるロジック」を逆算します。")

target_pair = st.selectbox("分析対象", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("🚀 最適な勝ちパターンを逆算する", type="primary", use_container_width=True):
    with st.spinner("クオンツAIがOHLCデータとテクニカル指標を再検証中..."):
        result = find_optimal_rule(target_pair)
        st.session_state.temp_result = result
        st.success("✅ 最適ルールの抽出に成功しました")

if "temp_result" in st.session_state:
    st.write("---")
    st.markdown(st.session_state.temp_result)
    
    if st.button("📥 このルールをバックテストに適用", use_container_width=True):
        st.session_state.saved_rule_text = st.session_state.temp_result
        st.toast("バックテスト側にルールを保存しました。")
