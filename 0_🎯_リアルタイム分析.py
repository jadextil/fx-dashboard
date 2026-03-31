import streamlit as st
import yfinance as yf
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime
from PIL import Image
import requests
import time
import json
import re

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

# APIキーの読み込み
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーが設定されていません。secrets.toml を確認してください。")
    st.stop()

# セッション状態の初期化
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = ""
if "technical_result" not in st.session_state:
    st.session_state.technical_result = ""
if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

# --- 1. 共通関数群 ---
def get_fx_data(ticker):
    data = yf.Ticker(ticker).history(period="2d", interval="1d")
    if len(data) >= 2:
        prev_close = float(data['Close'].iloc[-2])
        current = float(data['Close'].iloc[-1])
        diff = current - prev_close
        return current, diff
    return 0, 0

def get_current_price(ticker):
    """監視用の最新価格を1分足で取得（無料機能）"""
    data = yf.Ticker(ticker).history(period="1d", interval="1m")
    if not data.empty:
        return float(data['Close'].iloc[-1])
    return 0

def get_auto_news():
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

def send_discord_message(text):
    """Discordにメッセージを飛ばす関数"""
    try:
        webhook_url = st.secrets["DISCORD_WEBHOOK_URL"]
        payload = {"content": text}
        response = requests.post(webhook_url, json=payload)
        return response.status_code == 204
    except Exception as e:
        st.error(f"Discord通知エラー: {e}")
        return False

# ==========================================
# メイン画面構成（リアルタイム分析）
# ==========================================
st.title("🎯 リアルタイム AI相場解析 ＆ スマホ通知")
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
    
    latest_news = get_auto_news()
    st.text_area("自動取得した最新ニュース（計20本）", value=latest_news, height=150)
    
    st.write("📸 チャート画像解析（任意）")
    uploaded_file = st.file_uploader("DMM FXなどのスクショを添付", type=["png", "jpg", "jpeg"])
    if uploaded_file:
        st.image(uploaded_file, use_container_width=True)
    
    if st.button("✨ 総合解析 ＆ 目標算出", use_container_width=True, type="primary"):
        with st.spinner("AIが徹底解析中..."):
            # 1. ニュース・チャート分析・戦略
            prompt_analysis = f"ニュースから相場環境を解説して。\n{latest_news}"
            st.session_state.analysis_result = model.generate_content(prompt_analysis).text
            
            if uploaded_file:
                img = Image.open(uploaded_file)
                prompt_technical = "チャートのトレンド、支持・抵抗線を指摘して。"
                st.session_state.technical_result = model.generate_content([prompt_technical, img]).text
            
            prompt_strategy = f"現在のドル円{usd_price:.3f}円。今日のデイトレ戦略（方向性、購入目安、利確・損切りライン）を提案して。"
            st.session_state.strategy_result = model.generate_content(prompt_strategy).text

            # 2. 監視用の数値をAIにJSON形式で抽出させる
            prompt_json = f"現在のドル円{usd_price:.3f}円。先ほどの戦略に基づき、監視すべき【エントリー、利確(tp)、損切(sl)】の数値を以下のJSONのみで出力して。{{\"entry\": 150.10, \"tp\": 150.50, \"sl\": 149.80}}"
            json_res = model.generate_content(prompt_json).text
            try:
                # 応答から{...}の部分だけを抜き出す
                match = re.search(r'\{.*\}', json_res, re.DOTALL)
                if match:
                    st.session_state.target_prices = json.loads(match.group())
            except:
                st.session_state.target_prices = {"entry": usd_price, "tp": usd_price+0.4, "sl": usd_price-0.25}

# --- 右側：AIの解析結果 ＆ 通知監視 ---
with col3:
    st.subheader("💡 今日の指令 ＆ 監視")
    
    if st.session_state.strategy_result:
        with st.expander("AI戦略の詳細を確認", expanded=True):
            st.success("🎯 戦略案\n\n" + st.session_state.strategy_result)
            if st.session_state.technical_result:
                st.warning("📈 チャート分析\n\n" + st.session_state.technical_result)
        
        st.write("---")
        st.subheader("🔔 スマホ通知設定（Discord）")
        
        if st.session_state.target_prices:
            # 監視価格の微調整
            t_entry = st.number_input("エントリー監視価格", value=float(st.session_state.target_prices['entry']), step=0.01)
            t_tp = st.number_input("利確(TP)監視価格", value=float(st.session_state.target_prices['tp']), step=0.01)
            t_sl = st.number_input("損切(SL)監視価格", value=float(st.session_state.target_prices['sl']), step=0.01)
            
            interval = st.slider("チェック間隔（分）", 1, 30, 5)
            
            if st.button("🚀 監視をスタート（Discord連携）", use_container_width=True, type="primary"):
                st.info(f"監視を開始しました。{interval}分おきにチェックします。この画面を閉じないでください。")
                status_box = st.empty()
                
                # 監視ループ
                while True:
                    current_p = get_current_price("JPY=X")
                    now = datetime.now().strftime('%H:%M:%S')
                    status_box.info(f"最終チェック: {now} | 現在: {current_p:.3f} | 目標: {t_entry:.3f}")
                    
                    # 到達判定（簡易的な上下クロス判定）
                    if abs(current_p - t_entry) <= 0.02: # 0.02円以内に近づいたら通知
                        msg = f"【釘田式・FX指令】\n🔔 エントリー価格（{t_entry}円）付近に到達しました！\n現在の価格: {current_p:.3f}円\nチャートを確認してください。"
                        send_discord_message(msg)
                        st.success("Discordに通知を飛ばしました！監視を終了します。")
                        break
                    
                    if current_p >= t_tp:
                        send_discord_message(f"💰 利確価格（{t_tp}円）に到達しました！おめでとうございます！")
                        break
                        
                    if current_p <= t_sl:
                        send_discord_message(f"⚠️ 損切価格（{t_sl}円）に到達しました。ルールに従い撤退を。")
                        break

                    time.sleep(interval * 60)
    else:
        st.write("解析を実行するとここに戦略と通知設定が表示されます。")