import streamlit as st
import yfinance as yf
import pandas as pd
import urllib.request
import xml.etree.ElementTree as ET
import email.utils
import google.generativeai as genai
from datetime import datetime
import requests
import json
import re
import base64
import plotly.graph_objects as go

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API設定（GOOGLE_API_KEY）を確認してください。")
    st.stop()

if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

# --- 1. 共通関数群 ---

def get_market_indicators():
    """ドル指数(DXY)を含む3大指標を正確に取得"""
    results = {}
    # 米10年債利回り
    try:
        data = yf.Ticker("^TNX").history(period="5d")
        c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
        results["TNX"] = {"val": c, "diff": c - p}
    except: results["TNX"] = {"val": 0.0, "diff": 0.0}
    
    # 恐怖指数 (VIX)
    try:
        data = yf.Ticker("^VIX").history(period="5d")
        c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
        results["VIX"] = {"val": c, "diff": c - p}
    except: results["VIX"] = {"val": 0.0, "diff": 0.0}
    
    # ドル指数 (DXY) - 複数のティッカーで安定取得
    dxy_tickers = ["DX-Y.NYB", "DX=F", "UUP"]
    results["DXY"] = {"val": 0.0, "diff": 0.0}
    for t in dxy_tickers:
        try:
            data = yf.Ticker(t).history(period="5d")
            if not data.empty and len(data) >= 2:
                c, p = float(data['Close'].iloc[-1]), float(data['Close'].iloc[-2])
                if t == "UUP": c *= 3.5; p *= 3.5 # UUPはETFのため補正
                results["DXY"] = {"val": c, "diff": c - p}
                break
        except: continue
    return results

def get_technical_chart_data(ticker="JPY=X"):
    """チャートデータとボリンジャーバンド等の指標計算"""
    try:
        data = yf.download(ticker, period="10d", interval="1h", progress=False)
        if data.empty: return None, {}
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        close = data['Close']
        data['SMA20'] = close.rolling(20).mean()
        std = close.rolling(20).std()
        data['Upper2'] = data['SMA20'] + (std * 2)
        data['Lower2'] = data['SMA20'] - (std * 2)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -1 * delta.clip(upper=0).rolling(14).mean()
        data['RSI14'] = 100 - (100 / (1 + (gain / loss)))
        latest = data.iloc[-1]
        tech = {"current": float(latest['Close']), "upper2": float(latest['Upper2']), "lower2": float(latest['Lower2']), "rsi14": float(latest['RSI14']), "sma20": float(latest['SMA20'])}
        return data, tech
    except: return None, {}

def get_wall_street_news():
    """国内外・ウォール街のニュース30件を取得"""
    urls = [
        "https://news.yahoo.co.jp/rss/categories/business.xml",
        "https://news.yahoo.co.jp/rss/categories/world.xml",
        "https://news.yahoo.co.jp/rss/topics/business.xml"
    ]
    news_list = []
    seen_titles = set()
    try:
        for url in urls:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                root = ET.fromstring(response.read())
            for item in root.findall('./channel/item'):
                title = item.find('title').text
                if title in seen_titles: continue
                seen_titles.add(title)
                pub_date_str = item.find('pubDate').text
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    date_formatted = dt.astimezone().strftime("%m/%d %H:%M")
                except: date_formatted = "不明"
                news_list.append({"title": title, "date": date_formatted})
                if len(news_list) >= 30: break
            if len(news_list) >= 30: break
        return news_list
    except: return []

def check_economic_calendar(news_list):
    """ニュースから重要経済指標を抽出"""
    danger_keywords = ["雇用統計", "CPI", "消費者物価", "政策金利", "FOMC", "日銀", "FRB", "パウエル"]
    events = []
    for news in news_list:
        if any(keyword in news["title"] for keyword in danger_keywords):
            time_match = re.search(r'(\d{1,2}:\d{2})|(\d{1,2}時)', news["title"])
            sched_time = time_match.group(0) if time_match else "時間未定"
            events.append({"title": news["title"], "time": sched_time})
    return events

def update_github_config(side, entry, tp, sl, lots):
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        config_data = {"side": side, "entry": float(entry), "tp": float(tp), "sl": float(sl), "lots": float(lots), "status": "waiting_entry", "is_active": True}
        payload = {"message": f"Update Order", "content": base64.b64encode(json.dumps(config_data, indent=2).encode()).decode(), "sha": res["sha"]}
        return requests.put(url, headers=headers, json=payload).status_code == 200
    except: return False

# --- メイン画面構築 ---
col1, col2, col3 = st.columns([1.2, 2.2, 1.8])

with col1:
    st.subheader("📊 為替 ＆ マクロ指標")
    chart_data, tech_vals = get_technical_chart_data("JPY=X")
    usd_p = tech_vals.get("current", 0.0)
    st.metric("🇺🇸 ドル/円", f"{usd_p:.3f} 円")
    
    st.write("---")
    m_data = get_market_indicators()
    st.metric("📈 米10年債利回り", f"{m_data['TNX']['val']:.2f}%", f"{m_data['TNX']['diff']:.3f}")
    st.metric("📉 恐怖指数 (VIX)", f"{m_data['VIX']['val']:.2f}", f"{m_data['VIX']['diff']:.2f}")
    st.metric("💵 ドル指数 (DXY)", f"{m_data['DXY']['val']:.2f}", f"{m_data['DXY']['diff']:.2f}")
    
    st.write("---")
    st.subheader("📅 重要経済指標")
    all_news = get_wall_street_news()
    calendar = check_economic_calendar(all_news)
    if calendar:
        for ev in calendar[:5]: st.warning(f"🕒 {ev['time']}\n{ev['title']}")
    else: st.success("目立った指標予定なし")

with col2:
    st.subheader("📈 チャート (1H + BB)")
    if chart_data is not None:
        fig = go.Figure(data=[go.Candlestick(x=chart_data.index, open=chart_data['Open'], high=chart_data['High'], low=chart_data['Low'], close=chart_data['Close'], name='Candle')])
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Upper2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB +2σ'))
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Lower2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB -2σ'))
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"💡 RSI:{tech_vals['rsi14']:.1f} | BB上:{tech_vals['upper2']:.2f} | BB下:{tech_vals['lower2']:.2f}")

    st.write("---")
    st.subheader("📰 最新ニュース30本")
    news_text = "\n".join([f"[{n['date']}] {n['title']}" for n in all_news])
    with st.expander("ニュースヘッドラインを開く"):
        st.text_area("", value=news_text, height=200, label_visibility="collapsed")
    
    if st.button("✨ 総合解析を実行", use_container_width=True, type="primary"):
        with st.spinner("AIが全データを解析中..."):
            ai_context = f"USD/JPY:{usd_p:.3f}, RSI:{tech_vals['rsi14']:.1f}, BB上:{tech_vals['upper2']:.3f}, BB下:{tech_vals['lower2']:.3f}, TNX:{m_data['TNX']['val']:.2f}, VIX:{m_data['VIX']['val']:.2f}, DXY:{m_data['DXY']['val']:.2f}"
            prompt = f"以下の【市場データ】と【ニュース】を総合的に判断し、ボリンジャーバンドの戦略を立ててください。\n\n{ai_context}\n\n【ニュース】\n{news_text}"
            response = model.generate_content(prompt)
            st.session_state.strategy_result = response.text
            
            json_res = model.generate_content(f"{st.session_state.strategy_result}\n上記から {{'side': 'buy'or'sell', 'entry': 数値, 'tp': 数値, 'sl': 数値}} のJSONのみ出力せよ。").text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match: st.session_state.target_prices = json.loads(match.group())

with col3:
    st.subheader("💡 今日のAI戦略")
    if st.session_state.strategy_result:
        with st.container(height=350): st.info(st.session_state.strategy_result)
        if st.session_state.target_prices:
            tp_d = st.session_state.target_prices
            risk = st.number_input("許容損失額(円)", value=10000, step=1000)
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_d['side']=='buy' else 1)
            ent, t_tp, t_sl = st.number_input("Entry", value=float(tp_d['entry'])), st.number_input("TP", value=float(tp_d['tp'])), st.number_input("SL", value=float(tp_d['sl']))
            pips = abs(ent - t_sl)
            lots = round(risk / (pips * 10000), 2) if pips > 0 else 0.0
            st.metric("推奨ロット", f"{lots} lot")
            if st.button("🚀 24時間監視予約", use_container_width=True, type="primary"):
                if update_github_config(side, ent, t_tp, t_sl, lots): st.success("予約完了！")
