import streamlit as st
import yfinance as yf
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime
from PIL import Image

# --- 0. 初期設定 ---
# ページの名前とレイアウト設定
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

# APIキーの読み込み
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーが設定されていません。secrets.toml を確認してください。")
    st.stop()

# --- セッション状態の初期化 ---
# 画面が再読み込みされてもAIの回答が消えないようにする仕組み
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = ""
if "technical_result" not in st.session_state:
    st.session_state.technical_result = ""
if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""

# --- 1. 共通関数群 ---
def get_fx_data(ticker):
    """現在価格と前日比を取得する関数"""
    data = yf.Ticker(ticker).history(period="2d", interval="1d")
    if len(data) >= 2:
        prev_close = float(data['Close'].iloc[-2])
        current = float(data['Close'].iloc[-1])
        diff = current - prev_close
        return current, diff
    return 0, 0

def get_auto_news():
    """Yahooニュースから経済・国際ニュースを20本自動取得する関数"""
    urls = [
        "https://news.yahoo.co.jp/rss/categories/business.xml",
        "https://news.yahoo.co.jp/rss/categories/world.xml"
    ]
    news_list = []
    try:
        for url in urls:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            for item in root.findall('./channel/item')[:10]:
                news_list.append("・" + item.find('title').text)
        return "\n".join(news_list)
    except Exception as e:
        return f"ニュース取得エラー: {e}"

# ==========================================
# メイン画面構成（リアルタイム分析）
# ==========================================
st.title("🎯 リアルタイム AI相場解析")
st.caption(f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

col1, col2, col3 = st.columns([1.2, 2, 2])

# --- 左側：データ表示 ---
with col1:
    st.subheader("📊 現在の価格")
    usd_price, usd_diff = get_fx_data("JPY=X")
    st.metric(label="🇺🇸 ドル/円 (USD/JPY)", value=f"{usd_price:.3f} 円", delta=f"{usd_diff:.3f} 円")
    
    eur_price, eur_diff = get_fx_data("EURUSD=X")
    st.metric(label="🇪🇺 ユーロ/ドル (EUR/USD)", value=f"{eur_price:.5f} ドル", delta=f"{eur_diff:.5f} ドル")
    
    gbp_price, gbp_diff = get_fx_data("GBPJPY=X")
    st.metric(label="🇬🇧 ポンド/円 (GBP/JPY)", value=f"{gbp_price:.3f} 円", delta=f"{gbp_diff:.3f} 円")

# --- 中央：情報収集 ＆ 解析トリガー ---
with col2:
    st.subheader("📰 情報収集 ＆ チャート入力")
    
    # ニュース自動表示
    latest_news = get_auto_news()
    st.text_area("自動取得した最新ニュース（計20本）", value=latest_news, height=150)
    
    # 画像アップロード
    st.write("📸 チャート画像解析（任意）")
    uploaded_file = st.file_uploader("DMM FXなどのスクショを添付", type=["png", "jpg", "jpeg"])
    if uploaded_file:
        st.image(uploaded_file, use_container_width=True)
    
    # 解析ボタン
    if st.button("✨ 総合解析を実行", use_container_width=True, type="primary"):
        with st.spinner("AIが徹底解析中..."):
            
            # 1. ファンダメンタルズ解析
            prompt_analysis = f"プロトレーダーとして以下の20本のニュースから相場環境（円安か円高か、重要トピック）を解説して。\n{latest_news}"
            st.session_state.analysis_result = model.generate_content(prompt_analysis).text
            
            # 2. テクニカル解析
            if uploaded_file:
                img = Image.open(uploaded_file)
                prompt_technical = "このFXチャートのトレンド、サポート/レジスタンス、特徴的なパターンを簡潔に指摘して。"
                st.session_state.technical_result = model.generate_content([prompt_technical, img]).text
            else:
                st.session_state.technical_result = "チャート画像がアップロードされていません。"
            
            # 3. 戦略構築
            prompt_strategy = f"現在のドル円は{usd_price:.3f}円。ニュースを踏まえ、今日のデイトレ戦略（方向性、購入目安、利確・損切りライン、根拠）を提案して。"
            st.session_state.strategy_result = model.generate_content(prompt_strategy).text

# --- 右側：AIの解析結果と戦略 ---
with col3:
    st.subheader("💡 今日のトレード指令")
    
    if st.session_state.strategy_result:
        st.success("🎯 【結論】戦略\n\n" + st.session_state.strategy_result)
        
        if uploaded_file:
            st.warning("📈 【テクニカル】\n\n" + st.session_state.technical_result)
            
        st.info("📰 【ファンダメンタルズ】\n\n" + st.session_state.analysis_result)
    else:
        st.write("「総合解析を実行」ボタンを押すと、AIが算出した【戦略】【チャート分析】【環境認識】がここに表示されます。")