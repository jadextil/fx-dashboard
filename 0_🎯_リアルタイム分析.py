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
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

# --- 1. 共通関数群 ---

def get_market_indicators():
    """ウォール街が重視する3大指標を取得"""
    indicators = {
        "TNX": "^TNX",  # 米国債10年利回り
        "VIX": "^VIX",  # 恐怖指数
        "DXY": "DX-Y.NYB" # ドルインデックス
    }
    results = {}
    for name, ticker in indicators.items():
        try:
            data = yf.download(ticker, period="2d", interval="1d", progress=False)
            if not data.empty:
                current = float(data['Close'].iloc[-1])
                prev = float(data['Close'].iloc[-2])
                diff = current - prev
                results[name] = {"val": current, "diff": diff}
        except:
            results[name] = {"val": 0, "diff": 0}
    return results

def get_fx_data(ticker):
    try:
        data = yf.download(ticker, period="5d", interval="1d", progress=False)
        if not data.empty:
            close_data = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            current = float(close_data.iloc[-1])
            diff = current - float(close_data.iloc[-2])
            return current, diff
    except: pass
    return 0, 0

def get_precise_calendar():
    """
    経済指標の予定時刻を取得。
    ※RSSから『〇時〇分』という時間表記を抽出するように強化
    """
    url = "https://news.yahoo.co.jp/rss/categories/business.xml"
    events = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            root = ET.fromstring(response.read())
        
        danger_keywords = ["雇用統計", "CPI", "消費者物価", "政策金利", "FOMC", "日銀", "FRB", "パウエル"]
        
        for item in root.findall('./channel/item'):
            title = item.find('title').text
            if any(k in title for k in danger_keywords):
                # タイトル内から『21:30』や『21時』などの予定時刻を探す
                time_match = re.search(r'(\d{1,2}:\d{2})|(\d{1,2}時)', title)
                sched_time = time_match.group(0) if time_match else "時間未定"
                events.append({"title": title, "time": sched_time})
        return events
    except:
        return []

def get_wall_street_news():
    urls = [
        "https://news.yahoo.co.jp/rss/categories/business.xml",
        "https://news.yahoo.co.jp/rss/categories/world.xml"
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
        return news_list[:30]
    except:
        return []

def update_github_config(side, entry, tp, sl, lots):
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        content_dict = {"side": side, "entry": entry, "tp": tp, "sl": sl, "lots": lots, "status": "waiting_entry", "is_active": True}
        content_base64 = base64.b64encode(json.dumps(content_dict, indent=2).encode()).decode()
        requests.put(url, headers=headers, json={"message": "Update strategy", "content": content_base64, "sha": res["sha"]})
        return True
    except: return False

# ==========================================
# メイン画面
# ==========================================
st.title("🎯 釘田式・プロ仕様 FX AI指令室")

col1, col2, col3 = st.columns([1.2, 2, 2])

# --- 左カラム：市場データ ＆ マクロ指標 ---
with col1:
    st.subheader("📊 為替 ＆ マクロ指標")
    usd_p, usd_d = get_fx_data("JPY=X")
    st.metric("🇺🇸 ドル/円 (USD/JPY)", f"{usd_p:.3f} 円", f"{usd_d:.3f}")
    
    # 🌟 マクロ3大指標の表示
    m_data = get_market_indicators()
    st.write("---")
    st.metric("📈 米10年債利回り", f"{m_data['TNX']['val']:.2f}%", f"{m_data['TNX']['diff']:.3f}")
    st.metric("📉 恐怖指数 (VIX)", f"{m_data['VIX']['val']:.2f}", f"{m_data['VIX']['diff']:.2f}")
    st.metric("💵 ドル指数 (DXY)", f"{m_data['DXY']['val']:.2f}", f"{m_data['DXY']['diff']:.2f}")
    
    st.write("---")
    st.subheader("📅 指標発表スケジュール")
    calendar = get_precise_calendar()
    if calendar:
        for ev in calendar[:5]:
            st.warning(f"🕒 {ev['time']} | {ev['title']}")
    else:
        st.success("本日の主要指標予定は見当たりません。")

# --- 中央カラム：ニュース ＆ 解析 ---
with col2:
    all_news = get_wall_street_news()
    news_text = "\n".join([f"・{n}" for n in all_news])
    st.subheader("📰 最新ヘッドライン (30件)")
    st.text_area("ニュース一覧", value=news_text, height=200)
    
    uploaded_file = st.file_uploader("チャート画像を分析", type=["png", "jpg", "jpeg"])
    if uploaded_file:
        st.image(uploaded_file, use_container_width=True)
    
    if st.button("✨ 総合解析を実行", use_container_width=True, type="primary"):
        with st.spinner("マクロデータとニュースを照合中..."):
            # 🌟 AIに渡す情報にマクロ数値を注入
            macro_context = f"""
            【マクロ指標データ】
            ・米国債10年利回り: {m_data['TNX']['val']:.2f}%
            ・恐怖指数(VIX): {m_data['VIX']['val']:.2f}
            ・ドルインデックス(DXY): {m_data['DXY']['val']:.2f}
            """
            prompt = f"現在{usd_p:.3f}円。以下のマクロ指標とニュース30件、チャートから戦略を立てて。\n{macro_context}\n{news_text}"
            
            if uploaded_file:
                img = Image.open(uploaded_file)
                response = model.generate_content([prompt, img])
            else:
                response = model.generate_content(prompt)
            
            st.session_state.strategy_result = response.text
            
            # 数値抽出
            json_res = model.generate_content(f"以下をJSONのみで。{{\"side\": \"buy\"/\"sell\", \"entry\": 150.1, \"tp\": 150.5, \"sl\": 149.8}}").text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match:
                st.session_state.target_prices = json.loads(match.group())

# --- 右カラム：戦略 ＆ 資金管理 ---
with col3:
    if st.session_state.strategy_result:
        st.info(st.session_state.strategy_result)
        if st.session_state.target_prices:
            tp_data = st.session_state.target_prices
            st.write("---")
            risk_cash = st.number_input("許容損失額 (円)", value=10000, step=1000)
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_data['side']=="buy" else 1)
            t_entry = st.number_input("エントリー", value=float(tp_data['entry']), step=0.01)
            t_tp = st.number_input("利確(TP)", value=float(tp_data['tp']), step=0.01)
            t_sl = st.number_input("損切(SL)", value=float(tp_data['sl']), step=0.01)
            
            pips_risk = abs(t_entry - t_sl)
            calc_lots = risk_cash / (pips_risk * 10000) if pips_risk > 0 else 0.0
            st.metric("💡 推奨ロット数", f"{round(calc_lots, 2)} ロット")

            if st.button("🚀 24時間監視予約", use_container_width=True, type="primary"):
                if update_github_config(side, t_entry, t_tp, t_sl, round(calc_lots, 2)):
                    st.success("予約完了！ 決済時にスプレッドシートへ自動記帳されます。")
