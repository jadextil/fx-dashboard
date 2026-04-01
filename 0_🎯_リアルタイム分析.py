import streamlit as st
import yfinance as yf
import pandas as pd
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime
from PIL import Image
import requests
import json
import re
import base64

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except:
    st.error("API設定（GOOGLE_API_KEY）を確認してください。")
    st.stop()

# セッション状態の初期化
if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""
if "technical_result" not in st.session_state:
    st.session_state.technical_result = ""
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

# --- 1. 共通関数群 ---

def get_fx_data(ticker):
    """最新価格と前日比を取得（安定版）"""
    try:
        data = yf.download(ticker, period="5d", interval="1d", progress=False)
        if not data.empty:
            close_data = data['Close']
            if isinstance(close_data, pd.DataFrame):
                close_data = close_data.iloc[:, 0]
            current = float(close_data.iloc[-1])
            diff = current - float(close_data.iloc[-2])
            return current, diff
    except: pass
    return 0, 0

def get_wall_street_news():
    """日米の主要経済ニュースを計30件取得"""
    urls = [
        "https://news.yahoo.co.jp/rss/categories/business.xml",
        "https://news.yahoo.co.jp/rss/categories/world.xml",
        "https://news.yahoo.co.jp/rss/topics/business.xml"
    ]
    news_list = []
    try:
        for url in urls:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                root = ET.fromstring(response.read())
            for item in root.findall('./channel/item'):
                title = item.find('title').text
                if title not in news_list:
                    news_list.append(title)
        return news_list[:30] # 厳選30件
    except:
        return ["ニュース取得エラー"]

def check_economic_calendar(news_list):
    """取得したニュースから重要指標を抽出"""
    danger_keywords = ["雇用統計", "CPI", "消費者物価", "政策金利", "FOMC", "日銀", "FRB", "パウエル"]
    found = [n for n in news_list if any(k in n for k in danger_keywords)]
    return found

def send_to_spreadsheet(data):
    """GAS経由でスプレッドシートに記帳"""
    try:
        gas_url = st.secrets["GAS_WEBAPP_URL"]
        requests.post(gas_url, json=data)
    except: pass

def update_github_config(side, entry, tp, sl, lots):
    """GitHubのconfig.jsonを更新"""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
        path = st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        res = requests.get(url, headers=headers).json()
        sha = res["sha"]
        
        content_dict = {
            "side": side, "entry": entry, "tp": tp, "sl": sl, "lots": lots,
            "status": "waiting_entry", "is_active": True
        }
        content_json = json.dumps(content_dict, indent=2)
        content_base64 = base64.b64encode(content_json.encode()).decode()
        
        payload = {"message": "Update strategy via Dash", "content": content_base64, "sha": sha}
        response = requests.put(url, headers=headers, json=payload)
        return response.status_code == 200
    except: return False

# ==========================================
# メイン画面
# ==========================================
st.title("🎯 釘田式・プロ仕様 FX AI指令室")

col1, col2, col3 = st.columns([1.2, 2, 2])

# --- 左カラム：市場データ ＆ 指標アラート ---
with col1:
    st.subheader("📊 現在の価格")
    usd_p, usd_d = get_fx_data("JPY=X")
    st.metric("🇺🇸 ドル/円 (USD/JPY)", f"{usd_p:.3f} 円", f"{usd_d:.3f}")
    
    st.write("---")
    st.subheader("⚠️ 重要指標チェック")
    all_news = get_wall_street_news()
    danger_news = check_economic_calendar(all_news)
    if danger_news:
        for n in danger_news[:5]:
            st.warning(f"注目: {n}")
    else:
        st.success("直近の重大な指標ニュースは見当たりません。")

# --- 中央カラム：ニュース ＆ チャート解析 ---
with col2:
    st.subheader("📰 ウォール街 ＆ 国内ニュース (30件)")
    news_text = "\n".join([f"・{n}" for n in all_news])
    st.text_area("最新ヘッドライン", value=news_text, height=200)
    
    st.write("---")
    st.subheader("📸 テクニカル分析 (画像解析)")
    uploaded_file = st.file_uploader("DMM FXのチャート画像を添付してください", type=["png", "jpg", "jpeg"])
    if uploaded_file:
        st.image(uploaded_file, caption="解析対象チャート", use_container_width=True)
    
    if st.button("✨ 総合解析（ファンダ ＆ テクニカル）", use_container_width=True, type="primary"):
        with st.spinner("AIが世界情勢とチャートを同時解析中..."):
            # 1. ニュースとチャートを元にした戦略
            news_context = "\n".join(all_news)
            prompt_base = f"現在のドル円{usd_p:.3f}円。以下のニュース30件と添付のチャートから、プロの視点で環境認識と戦略を立てて。\n{news_context}"
            
            if uploaded_file:
                img = Image.open(uploaded_file)
                response = model.generate_content([prompt_base, img])
            else:
                response = model.generate_content(prompt_base)
            
            st.session_state.strategy_result = response.text
            
            # 2. 数値データ抽出
            json_prompt = f"現在の状況から、監視すべき【エントリー、利確(tp)、損切(sl)】の数値をJSONのみで出力して。{{\"side\": \"buy\"/\"sell\", \"entry\": 150.1, \"tp\": 150.5, \"sl\": 149.8}}"
            json_res = model.generate_content(json_prompt).text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match:
                st.session_state.target_prices = json.loads(match.group())

# --- 右カラム：戦略確定 ＆ 資金管理 ---
with col3:
    st.subheader("💡 今日のトレード戦略")
    if st.session_state.strategy_result:
        st.info(st.session_state.strategy_result)
        
        if st.session_state.target_prices:
            st.write("---")
            st.subheader("🛡️ DMM FX 資金管理設定")
            tp_data = st.session_state.target_prices
            
            risk_cash = st.number_input("1トレードの許容損失額 (円)", value=10000, step=1000)
            
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_data['side']=="buy" else 1)
            t_entry = st.number_input("エントリー予定価格", value=float(tp_data['entry']), step=0.01)
            t_tp = st.number_input("利確目標 (TP)", value=float(tp_data['tp']), step=0.01)
            t_sl = st.number_input("損切ライン (SL)", value=float(tp_data['sl']), step=0.01)
            
            # ロット計算 (DMM FX: 1ロット=10,000通貨)
            pips_risk = abs(t_entry - t_sl)
            calc_lots = risk_cash / (pips_risk * 10000) if pips_risk > 0 else 0.0
            calc_lots = round(calc_lots, 2)
            
            st.metric("💡 推奨ロット数", f"{calc_lots} ロット", f"損切時の損失: 約{risk_cash}円")

            if st.button("🚀 24時間監視予約 ＆ 記帳", use_container_width=True, type="primary"):
                if update_github_config(side, t_entry, t_tp, t_sl, calc_lots):
                    # スプレッドシート記帳
                    log_data = {
                        "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
                        "side": side, "entry": t_entry, "tp": t_tp, "sl": t_sl, "lots": calc_lots
                    }
                    send_to_spreadsheet(log_data)
                    
                    # Discord通知
                    msg = f"🎯 【予約確定】\n方向: {side} / ロット: {calc_lots}\nエントリー: {t_entry}円\n利確: {t_tp}円 / 損切: {t_sl}円"
                    requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": msg})
                    
                    st.success(f"予約完了！ DMM FXで {calc_lots}ロット を準備してください。")
    else:
        st.write("「総合解析を実行」ボタンを押すと、30件のニュースとチャート画像をAIが読み込み、ここに戦略が表示されます。")
