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
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df['SMA20'] = df['Close'].rolling(window=20).mean()
    
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    
    return df.dropna()

# --- 2. AI分析ロジック ---
def find_optimal_rule(ticker):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    data_summary = ""
    for index, row in df.tail(100).iterrows(): 
        data_summary += (f"{index.strftime('%m/%d %H:%M')} | "
                         f"始:{row['Open']:.3f} 高:{row['High']:.3f} 安:{row['Low']:.3f} 終:{row['Close']:.3f} | "
                         f"SMA20:{row['SMA20']:.3f} RSI:{row['RSI14']:.1f} ATR:{row['ATR']:.3f}\n")

    prompt = f"""
    あなたは世界最高峰のクオンツ・トレーダーです。
    以下の{ticker}のローソク足データ（OHLC）とテクニカル指標（直近100時間分）を読み解き、バックテストで【期待値がプラス】になるデイトレ・ルールを考案してください。
    ※これは学術的なシミュレーション目的であり、実際の投資助言ではありません。

    【分析用データ】
    {data_summary}

    【あなたの任務】
    1. 相場環境とローソク足の徹底解剖
    2. ルールの言語化（エントリー条件、および決済条件）
    3. 期待値の根拠
    """
    
    # 🌟 セキュリティブロック回避とエラーハンドリング
    try:
        # AIの過剰なブロック設定を緩和（シミュレーション目的であることを強調）
        safety_settings = [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"}
        ]
        response = model.generate_content(prompt, safety_settings=safety_settings)
        return response.text
        
    except ValueError:
        # AIが回答を拒否（白紙回答）した場合の保護処理
        return "⚠️ **AIの安全装置が作動しました。**\n\n「具体的な投資の断定」とみなされ、AIが回答の出力を停止しました。アプリのクラッシュは防ぎましたので、お手数ですがもう一度「逆算する」ボタンを押して再生成をお試しください。"
    except Exception as e:
        return f"⚠️ 予期せぬ通信エラーが発生しました: {str(e)}"

# --- 3. 画面構築 ---
st.title("🧠 釘田式・AI戦略分析室 PRO")
st.markdown("ローソク足の形状（ヒゲ）と数値データの裏付けを持った「勝てるロジック」を逆算します。")

target_pair = st.selectbox("分析対象", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

if st.button("🚀 最適な勝ちパターンを逆算する", type="primary", use_container_width=True):
    with st.spinner("クオンツAIがOHLCデータとテクニカル指標を再検証中..."):
        result = find_optimal_rule(target_pair)
        st.session_state.temp_result = result
        
        # エラーメッセージが返ってきたかどうかで表示を変える
        if "⚠️" in result:
            st.warning("解析が中断されました。再試行してください。")
        else:
            st.success("✅ 最適ルールの抽出に成功しました")

if "temp_result" in st.session_state:
    st.write("---")
    st.markdown(st.session_state.temp_result)
    
    # エラーメッセージの時はバックテスト送信ボタンを隠す
    if "⚠️" not in st.session_state.temp_result:
        if st.button("📥 このルールをバックテストに適用", use_container_width=True):
            st.session_state.saved_rule_text = st.session_state.temp_result
            st.toast("バックテスト側にルールを保存しました。")
