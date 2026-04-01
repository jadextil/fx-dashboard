import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai

st.set_page_config(page_title="釘田式・AI戦略分析室 PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    # モデル名は安定版を指定
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error("APIキーの設定を確認してください。")
    st.stop()

if "saved_rule_text" not in st.session_state:
    st.session_state.saved_rule_text = ""

def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    return df.dropna()

def find_optimal_rule(ticker):
    # 300時間をカバーするために期間を長めに取得
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    # 🌟 直近300時間のデータを抽出
    analysis_df = df.tail(300)
    data_summary = ""
    for index, row in analysis_df.iterrows(): 
        data_summary += (f"{index.strftime('%m/%d %H:%M')} | "
                         f"始:{row['Open']:.3f} 高:{row['High']:.3f} 安:{row['Low']:.3f} 終:{row['Close']:.3f} | "
                         f"SMA20:{row['SMA20']:.3f} RSI:{row['RSI14']:.1f} ATR:{row['ATR']:.3f}\n")

    prompt = f"""
    あなたは世界最高峰のクオンツ・トレーダーです。
    {ticker}の直近300時間分のデータを分析し、「再現性が高く」「期待値がプラス」になるデイトレ・ルールを1つだけ考案してください。

    【分析用データ】
    {data_summary}

    【戦略構築の指針（重要）】
    1. **過学習の回避**: この300時間だけに通用するルールではなく、相場の原理原則（押し目買い、戻り売り、ボラティリティの収束と拡散など）に基づいたルールにしてください。
    2. **数値の明確化**: 「RSIが低い時」ではなく「RSIが30以下の時」のように、バックテストで100%機械的に判定できる数値基準を設けてください。
    3. **損益比の意識**: 利確と損切りの幅を、ATRの何倍にするかなどの論理的な出口戦略を含めてください。
    4. **フィルタリング**: トレードすべきでない「レンジ相場」や「低ボラティリティ」を排除する条件を加えてください。

    【出力項目】
    - 戦略名
    - 環境認識（現在の相場の特徴）
    - エントリー条件（ロング/ショートそれぞれ）
    - 決済条件（利確・損切り）
    """
    
    try:
        safety_settings = [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"}]
        response = model.generate_content(prompt, safety_settings=safety_settings)
        return response.text
    except Exception as e:
        return f"⚠️ エラーが発生しました: {str(e)}"

st.title("🧠 釘田式・AI戦略分析室 PRO")
target_pair = st.selectbox("分析対象", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("🚀 300時間のデータから最適ルールを逆算する", type="primary", use_container_width=True):
    with st.spinner("300時間のローソク足とテクニカル指標を精密分析中..."):
        result = find_optimal_rule(target_pair)
        st.session_state.temp_result = result

if "temp_result" in st.session_state:
    st.write("---")
    st.markdown(st.session_state.temp_result)
    if st.button("📥 このルールをバックテストに適用", use_container_width=True):
        st.session_state.saved_rule_text = st.session_state.temp_result
        st.toast("バックテスト側にルールを保存しました。")
