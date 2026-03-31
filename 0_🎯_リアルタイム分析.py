import streamlit as st
import yfinance as yf
import pandas as pd
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime
from PIL import Image
import requests
import time
import json
import re
import base64

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーが設定されていません。secrets.toml を確認してください。")
    st.stop()

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = ""
if "technical_result" not in st.session_state:
    st.session_state.technical_result = ""
if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

# --- 1. 共通関数群（超・安定版） ---

def get_fx_data(ticker):
    """現在価格と前日比を取得する関数（安定のdownload方式）"""
    try:
        # Tickerではなくエラーの少ないdownloadを使用
        data = yf.download(ticker, period="5d", interval="1d", progress=False)
        if data is not None and not data.empty and len(data) >= 2:
            # yfinanceのバージョン違いによるエラーを吸収
            close_data = data['Close']
            if isinstance(close_data, pd.DataFrame):
                close_data = close_data.iloc[:, 0]
                
            prev_close = float(close_data.iloc[-2])
            current = float(close_data.iloc[-1])
            diff = current - prev_close
            return current, diff
    except Exception as e:
        st.error(f"価格データ取得エラー({ticker}): {e}")
    return 0, 0

def get_current_price(ticker):
    """監視用の最新価格を1分足で取得（安定のdownload方式）"""
    try:
        data = yf.download(ticker, period="1d", interval="1m", progress=False)
        if data is not None and not data.empty:
            close_data = data['Close']
            if isinstance(close_data, pd.DataFrame):
                close_data = close_data.iloc[:, 0]
            return float(close_data.iloc[-1])
    except Exception as e:
        st.sidebar.error(f"監視用データ取得エラー: {e}")
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
    try:
        webhook_url = st.secrets["DISCORD_WEBHOOK_URL"]
        requests.post(webhook_url, json={"content": text})
    except:
        pass

def update_github_config(entry, tp, sl):
    """GitHubに「エントリー待ち状態」として指令を送信"""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
        path = st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        sha = res["sha"]
        
        content_dict = {
            "entry": entry, "tp": tp, "sl": sl, 
            "status": "waiting_entry", "is_active": True
        }
        content_json = json.dumps(content_dict, indent=2)
        content_base64 = base64.b64encode(content_json.encode()).decode()
        
        data = {"message": "Update targets", "content": content_base64, "sha": sha}
        response = requests.put(url, headers=headers, json=data)
        return response.status_code == 200
    except Exception as e:
        st.error(f"GitHub連携エラー: {e}")
        return False

# ==========================================
# メイン画面構成
# ==========================================
st.title("🎯 リアルタイム AI相場解析 ＆ スマホ通知")

col1, col2, col3 = st.columns([1.2, 2, 2])

with col1:
    st.subheader("📊 現在の価格")
    usd_price, usd_diff = get_fx_data("JPY=X")
    st.metric(label="🇺🇸 ドル/円 (USD/JPY)", value=f"{usd_price:.3f} 円", delta=f"{usd_diff:.3f} 円")
    eur_price, eur_diff = get_fx_data("EURUSD=X")
    st.metric(label="🇪🇺 ユーロ/ドル", value=f"{eur_price:.5f} ドル", delta=f"{eur_diff:.5f} ドル")

with col2:
    st.subheader("📰 情報収集 ＆ チャート入力")
    latest_news = get_auto_news()
    st.text_area("自動取得した最新ニュース", value=latest_news, height=150)
    uploaded_file = st.file_uploader("チャート画像を添付", type=["png", "jpg", "jpeg"])
    
    if st.button("✨ 総合解析 ＆ 目標算出", use_container_width=True, type="primary"):
        with st.spinner("AIが徹底解析中..."):
            st.session_state.analysis_result = model.generate_content(f"ニュースから相場環境を解説して。\n{latest_news}").text
            if uploaded_file:
                st.session_state.technical_result = model.generate_content(["チャートのトレンドを指摘して。", Image.open(uploaded_file)]).text
            st.session_state.strategy_result = model.generate_content(f"現在のドル円{usd_price:.3f}円。今日のデイトレ戦略を提案して。").text

            json_res = model.generate_content(f"現在{usd_price:.3f}円。監視すべき【エントリー、利確(tp)、損切(sl)】の数値をJSONのみで出力して。{{\"entry\": 150.10, \"tp\": 150.50, \"sl\": 149.80}}").text
            try:
                match = re.search(r'\{.*\}', json_res, re.DOTALL)
                if match:
                    st.session_state.target_prices = json.loads(match.group())
            except:
                st.session_state.target_prices = {"entry": usd_price, "tp": usd_price+0.4, "sl": usd_price-0.25}

with col3:
    st.subheader("💡 今日の指令 ＆ 監視")
    if st.session_state.strategy_result:
        with st.expander("AI戦略の詳細を確認", expanded=True):
            st.success(st.session_state.strategy_result)
        
        st.write("---")
        st.subheader("🔔 スマホ通知設定（Discord）")
        
        if st.session_state.target_prices:
            t_entry = st.number_input("エントリー監視価格", value=float(st.session_state.target_prices['entry']), step=0.01)
            t_tp = st.number_input("利確(TP)監視価格", value=float(st.session_state.target_prices['tp']), step=0.01)
            t_sl = st.number_input("損切(SL)監視価格", value=float(st.session_state.target_prices['sl']), step=0.01)
            
            # --- クラウド監視 ---
            if st.button("🌐 24時間クラウド監視を予約（推奨）", use_container_width=True, type="primary"):
                with st.spinner("GitHubに指令を送信中..."):
                    if update_github_config(t_entry, t_tp, t_sl):
                        st.success("予約完了！画面を閉じてもAIが裏側で最後まで監視を続けます。")
                        send_discord_message(f"✅ 【クラウド予約】エントリー({t_entry}円)の監視を開始。")
            
            # --- ローカル監視（自動フェーズ移行対応版） ---
            interval = st.slider("ブラウザ監視の間隔（分）", 1, 30, 5)
            if st.button("💻 ブラウザで全自動監視をスタート", use_container_width=True):
                status_box = st.empty()
                entry_reached = False
                
                # フェーズ1：エントリー監視
                st.info("フェーズ1：エントリーポイントを監視中...")
                while not entry_reached:
                    current_p = get_current_price("JPY=X")
                    now = datetime.now().strftime('%H:%M:%S')
                    status_box.info(f"最終チェック: {now} | 現在: {current_p:.3f} | 目標: {t_entry:.3f}")
                    
                    if abs(current_p - t_entry) <= 0.02:
                        send_discord_message(f"🔔 【エントリー到達】{t_entry}円付近です！自動で利確・損切りの監視に移行します。")
                        st.success("エントリーポイント到達！自動でフェーズ2（利確・損切り監視）へ移行します。")
                        entry_reached = True
                        break
                    time.sleep(interval * 60)
                
                # フェーズ2：利確・損切り監視
                if entry_reached:
                    st.warning("フェーズ2：利確・損切りを監視中...")
                    while True:
                        current_p = get_current_price("JPY=X")
                        now = datetime.now().strftime('%H:%M:%S')
                        status_box.warning(f"最終チェック: {now} | 現在: {current_p:.3f} | TP: {t_tp} / SL: {t_sl}")
                        
                        if current_p >= t_tp:
                            send_discord_message(f"💰 【利確達成】{t_tp}円に到達しました！監視終了。")
                            st.success("利確達成！監視を終了します。")
                            break
                        if current_p <= t_sl:
                            send_discord_message(f"⚠️ 【損切到達】{t_sl}円に到達しました。監視終了。")
                            st.error("損切り到達。監視を終了します。")
                            break
                        time.sleep(interval * 60)
    else:
        st.write("解析を実行するとここに戦略と通知設定が表示されます。")
