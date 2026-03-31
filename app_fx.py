import streamlit as st
import yfinance as yf
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime
from PIL import Image  # 画像処理用のライブラリを追加

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AIダッシュボード", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    # マルチモーダル（画像＋テキスト）対応の最新モデル
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーが設定されていません。secrets.toml を確認してください。")
    st.stop()

# --- セッション状態の初期化 ---
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = ""
if "technical_result" not in st.session_state:
    st.session_state.technical_result = ""
if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""

# --- 1. データ取得関数 ---
def get_fx_data(ticker):
    data = yf.Ticker(ticker).history(period="2d", interval="1d")
    if len(data) >= 2:
        prev_close = data['Close'].iloc[-2]
        current = data['Close'].iloc[-1]
        diff = current - prev_close
        return current, diff
    return 0, 0

# --- 2. ニュース自動取得関数（経済＋国際で強化） ---
def get_auto_news():
    # 経済と国際（米国指標など）の2つのRSSから取得
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
            # 各カテゴリから最新10件ずつ（合計20件）抽出
            for item in root.findall('./channel/item')[:10]:
                news_list.append("・" + item.find('title').text)
        return "\n".join(news_list)
    except Exception as e:
        return f"ニュース取得エラー: {e}"

# --- メイン画面構成 ---
st.title("📈 釘田式・FX AIダッシュボード")
st.caption(f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

col1, col2, col3 = st.columns([1.2, 2, 2])

# --- 左側：データ表示 ---
with col1:
    st.subheader("📊 リアルタイム市況")
    usd_price, usd_diff = get_fx_data("JPY=X")
    st.metric(label="🇺🇸 ドル/円 (USD/JPY)", value=f"{usd_price:.3f} 円", delta=f"{usd_diff:.3f} 円")
    
    eur_price, eur_diff = get_fx_data("EURUSD=X")
    st.metric(label="🇪🇺 ユーロ/ドル (EUR/USD)", value=f"{eur_price:.5f} ドル", delta=f"{eur_diff:.5f} ドル")
    
    gbp_price, gbp_diff = get_fx_data("GBPJPY=X")
    st.metric(label="🇬🇧 ポンド/円 (GBP/JPY)", value=f"{gbp_price:.3f} 円", delta=f"{gbp_diff:.3f} 円")

# --- 中央：情報入力とAI解析トリガー ---
with col2:
    st.subheader("📰 情報収集 ＆ チャート入力")
    latest_news = get_auto_news()
    st.text_area("自動取得した最新ニュース（経済・国際 計20本）", value=latest_news, height=200)
    
    st.write("---")
    st.write("📸 チャート画像解析（任意）")
    uploaded_file = st.file_uploader("DMM FXなどのチャートのスクリーンショットを添付", type=["png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        st.image(uploaded_file, caption="アップロードされたチャート", use_container_width=True)
    
    if st.button("✨ ニュースとチャートから総合解析する", use_container_width=True, type="primary"):
        with st.spinner("AIが相場環境とチャートを徹底解析中..."):
            
            # 1. ファンダメンタルズ解析（ニュース）
            prompt_analysis = f"""
            あなたはプロの為替トレーダーです。以下の20本の最新ニュースから、現在の相場環境を解説してください。
            【最新ニュース】\n{latest_news}\n
            【出力ルール】
            ・全体的に「円安」か「円高」か。
            ・為替（特にドル円）に最も影響を与えそうなトピックを抽出し、その理由を解説。
            """
            st.session_state.analysis_result = model.generate_content(prompt_analysis).text
            
            # 2. テクニカル解析（画像がある場合のみ実行）
            if uploaded_file is not None:
                img = Image.open(uploaded_file)
                prompt_technical = """
                このFXチャート画像をテクニカル分析してください。
                以下のポイントを簡潔に指摘してください。
                ・現在のトレンド（上昇、下降、レンジ）
                ・意識されそうなサポートライン（支持線）とレジスタンスライン（抵抗線）
                ・特徴的なチャートパターン（ダブルトップ、三尊など）があれば指摘
                """
                # 画像とテキストを同時にAIに渡す
                st.session_state.technical_result = model.generate_content([prompt_technical, img]).text
            else:
                st.session_state.technical_result = "チャート画像がアップロードされていません。"
            
            # 3. 総合的なトレード戦略
            prompt_strategy = f"""
            現在のドル円は {usd_price:.3f} 円です。先ほどのニュース（ファンダメンタルズ）と、現在の価格を踏まえ、今日のデイトレード戦略を提案してください。
            以下の【必須項目】を必ず含めてください。
            
            【必須項目】
            ・方向性（買い、売り、様子見）
            ・具体的な購入目安（エントリーポイントの価格帯）
            ・出口戦略（利確ラインの価格帯と、損切りラインの価格帯）
            ・その戦略の根拠（簡潔に）
            """
            st.session_state.strategy_result = model.generate_content(prompt_strategy).text

# --- 右側：AIの解析結果と戦略 ---
with col3:
    st.subheader("💡 釘田様専用・トレード戦略室")
    
    if st.session_state.strategy_result:
        # 1. 最終的な戦略（一番重要なので上に表示）
        st.success("🎯 【結論】具体的なトレード戦略\n\n" + st.session_state.strategy_result)
        
        # 2. テクニカル分析結果（画像があった場合）
        if uploaded_file is not None:
            st.warning("📈 【チャート分析】テクニカル視点\n\n" + st.session_state.technical_result)
            
        # 3. ニュース分析結果
        st.info("📰 【環境認識】ファンダメンタルズ視点\n\n" + st.session_state.analysis_result)
        
    else:
        st.write("中央の「総合解析する」ボタンを押すと、AIが算出した【具体的な購入・出口戦略】【チャート分析】【環境認識】がここに表示されます。")