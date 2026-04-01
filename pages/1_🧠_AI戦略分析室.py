import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai

# --- 0. 初期設定 ---
st.set_page_config(page_title="釘田式・AI戦略分析室 PRO", layout="wide")

MODEL_NAME = 'gemini-2.5-flash' 

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(MODEL_NAME)
except Exception as e:
    st.error(f"API設定を確認してください: {e}")
    st.stop()

if "saved_rule_text" not in st.session_state:
    st.session_state.saved_rule_text = ""

# --- 1. インジケーター計算（BB追加） ---
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

def find_optimal_rule(ticker):
    # 300時間を取得するために、1ヶ月分を取得
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    # 🌟 直近300時間のデータを抽出
    analysis_df = df.tail(300)
    data_summary = ""
    for index, row in analysis_df.iterrows(): 
        data_summary += (f"{index.strftime('%m/%d %H:%M')} | "
                         f"終:{row['Close']:.3f} BB上:{row['Upper2']:.3f} BB下:{row['Lower2']:.3f} "
                         f"SMA:{row['SMA20']:.3f} RSI:{row['RSI14']:.1f} ATR:{row['ATR']:.3f}\n")

    prompt = f"""
    あなたは世界最高峰のクオンツです。{ticker}の直近300時間のデータを元に、ボリンジャーバンド(BB)を活用した勝てる戦略を1つ立案してください。

    【分析用データ（直近300時間）】
    {data_summary}

    【戦略立案の最優先事項（結果を出すための指示）】
    1. **ボラティリティの選別**: BBがスクイーズ（狭まっている）している停滞期を避け、エクスパンション（広がり）が始まったタイミングを狙うなど、無駄なエントリーを削る条件を入れてください。
    2. **優位性の根拠**: なぜその条件で勝てると判断したのか、300時間のデータ傾向から説明してください。
    3. **出口の厳格化**: 利確・損切りをBBの±2σやATRの何倍にするか等、ボラティリティに基づいた設定にしてください。
    
    【出力項目】
    - 戦略名
    - エントリー条件（数値で具体的に）
    - 決済条件（利確・損切り）
    - この300時間で特に機能すると判断した理由
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ エラーが発生しました: {str(e)}"

st.title("🧠 釘田式・AI戦略分析室 PRO")
target_pair = st.selectbox("分析対象", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("🚀 300時間のデータとBBから最適ルールを逆算", type="primary", use_container_width=True):
    with st.spinner("300時間のローソク足とBBを精密分析中..."):
        result = find_optimal_rule(target_pair)
        st.session_state.temp_result = result

if "temp_result" in st.session_state:
    st.write("---")
    st.markdown(st.session_state.temp_result)
    if st.button("📥 このルールをバックテストに適用", use_container_width=True):
        st.session_state.saved_rule_text = st.session_state.temp_result
        st.toast("保存完了！バックテストページへ")
