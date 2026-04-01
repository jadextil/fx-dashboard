import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai

# --- 0. 初期設定 ---
st.set_page_config(page_title="釘田式・AI戦略分析室 PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    # ユーザー様の環境で動作実績のあるバージョンを指定
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API設定を確認してください。")
    st.stop()

# メモリの初期化
if "saved_rule_text" not in st.session_state:
    st.session_state.saved_rule_text = ""

# --- 1. テクニカル指標計算関数 (SMA20/50, BB, RSI) ---
def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    
    close = df['Close']
    
    # 移動平均線 (SMA)
    df['SMA20'] = close.rolling(window=20).mean()
    df['SMA50'] = close.rolling(window=50).mean()
    
    # ボリンジャーバンド (2σ)
    std = close.rolling(window=20).std()
    df['Upper2'] = df['SMA20'] + (std * 2)
    df['Lower2'] = df['SMA20'] - (std * 2)
    
    # RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ATR (ボラティリティ参考用)
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    
    return df.dropna()

# --- 2. AI戦略分析ロジック ---
def find_optimal_rule(ticker):
    # 300時間をカバーするために1ヶ月分を取得
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df).tail(300) # 🌟 300時間に拡大
    
    # AIに渡すデータサマリーの構築
    data_summary = ""
    for idx, row in df.iterrows():
        data_summary += (f"{idx.strftime('%m/%d %H:%M')} | "
                         f"終:{row['Close']:.3f} | "
                         f"SMA20:{row['SMA20']:.3f} SMA50:{row['SMA50']:.3f} | "
                         f"BB上:{row['Upper2']:.3f} BB下:{row['Lower2']:.3f} | "
                         f"RSI:{row['RSI']:.1f}\n")

    prompt = f"""
    あなたは世界最高峰のクオンツ・トレーダーです。
    提供された{ticker}の直近300時間データに基づき、
    【期待値が最大化されるデイトレ・ルール】を1つ立案してください。

    【分析用データ】
    {data_summary}

    【あなたの任務: 以下の指標を全て使い切ること】
    1. **SMA20 & SMA50**: 中長期トレンドの方向性を定義し、押し目買い・戻り売りの基準とせよ。
    2. **ボリンジャーバンド(BB)**: スクイーズ（収束）からのブレイクアウト、または±2σでの反発を判定せよ。
    3. **RSI**: 買われすぎ・売られすぎの過熱感をエントリーの最終フィルターとせよ。
    
    【出力項目】
    - 戦略名
    - 環境認識（現在のトレンド状況）
    - エントリー条件（数値で具体的に）
    - 決済条件（利確・損切りの数値根拠）
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ 解析エラーが発生しました: {str(e)}"

# --- 3. 画面構築 ---
st.title("🧠 釘田式・AI戦略分析室 PRO")
st.markdown("直近300時間の「SMA・BB・RSI」を複合解析し、勝てるロジックを逆算します。")

target_pair = st.selectbox("分析対象通貨ペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("🚀 300時間のデータから最適ルールを逆算する", type="primary", use_container_width=True):
    with st.spinner("クオンツAIがSMAトレンドとボラティリティを精密検証中..."):
        result = find_optimal_rule(target_pair)
        st.session_state.temp_result = result
        
        if "⚠️" in result:
            st.error(result)
        else:
            st.success("✅ 最適ルールの抽出に成功しました")

if "temp_result" in st.session_state:
    st.write("---")
    st.markdown(st.session_state.temp_result)
    
    if "⚠️" not in st.session_state.temp_result:
        if st.button("📥 このルールをバックテストに適用", use_container_width=True):
            st.session_state.saved_rule_text = st.session_state.temp_result
            st.toast("バックテスト側にルールを保存しました。")
