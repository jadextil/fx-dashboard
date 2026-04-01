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

st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API設定を確認してください。")
    st.stop()

if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

def get_market_indicators():
    results = {}
    for k, t in {"TNX": "^TNX", "VIX": "^VIX", "DXY": "DX-Y.NYB"}.items():
        try:
            data = yf.Ticker(t).history(period="5d")
            c, p = float(data['Close'].iloc[-1]), float(data['Close'].iloc[-2])
            results[k] = {"val": c, "diff": c - p}
        except: results[k] = {"val": 0.0, "diff": 0.0}
    return results

def get_technical_chart_data(ticker="JPY=X"):
    try:
        data = yf.download(ticker, period="10d", interval="1h", progress=False)
        if data.empty: return None, {}
        if isinstance(data.columns, pd.MultiIndex): data.columns = [col[0] for col in data.columns]
        close = data['Close']
        data['SMA20'] = close.rolling(20).mean()
        std = close.rolling(20).std()
        data['Upper2'] = data['SMA20'] + (std * 2)
        data['Lower2'] = data['SMA20'] - (std * 2)
        delta = close.diff()
        gain, loss = delta.clip(lower=0).rolling(14).mean(), -delta.clip(upper=0).rolling(14).mean()
        data['RSI14'] = 100 - (100 / (1 + (gain / loss)))
        latest = data.iloc[-1]
        return data, {"current": float(latest['Close']), "upper2": float(latest['Upper2']), "lower2": float(latest['Lower2']), "rsi14": float(latest['RSI14'])}
    except: return None, {}

def get_wall_street_news():
    urls = ["https://news.yahoo.co.jp/rss/categories/business.xml", "https://news.yahoo.co.jp/rss/categories/world.xml", "https://news.yahoo.co.jp/rss/topics/business.xml"]
    news_list = []
    seen = set()
    try:
        for url in urls:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                root = ET.fromstring(response.read())
            for item in root.findall('./channel/item'):
                title = item.find('title').text
                if title not in seen:
                    seen.add(title)
                    news_list.append({"title": title, "date": "最新"})
        return news_list[:30]
    except: return []

def update_github_config(side, entry, tp, sl, lots, rule_name="Rule 1"):
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        config_data = {"rule_name": rule_name, "side": side, "entry": float(entry), "tp": float(tp), "sl": float(sl), "lots": float(lots), "status": "waiting_entry", "is_active": True}
        payload = {"message": f"Update {rule_name}", "content": base64.b64encode(json.dumps(config_data, indent=2).encode()).decode(), "sha": res["sha"]}
        return requests.put(url, headers=headers, json=payload).status_code == 200
    except: return False

# --- メイン画面 ---
col1, col2, col3 = st.columns([1.2, 2.2, 1.8])

with col1:
    st.subheader("📊 為替 ＆ 市場指標")
    chart_data, tech = get_technical_chart_data("JPY=X")
    usd_p = tech.get("current", 0.0)
    st.metric("🇺🇸 ドル/円", f"{usd_p:.3f} 円")
    m = get_market_indicators()
    st.metric("📈 米10年債利回り", f"{m['TNX']['val']:.2f}%", f"{m['TNX']['diff']:.3f}")
    st.metric("📉 恐怖指数 (VIX)", f"{m['VIX']['val']:.2f}", f"{m['VIX']['diff']:.2f}")
    st.metric("💵 ドル指数 (DXY)", f"{m['DXY']['val']:.2f}", f"{m['DXY']['diff']:.2f}")

with col2:
    st.subheader("📈 チャート (1H + BB)")
    if chart_data is not None:
        fig = go.Figure(data=[go.Candlestick(x=chart_data.index, open=chart_data['Open'], high=chart_data['High'], low=chart_data['Low'], close=chart_data['Close'], name='Candle')])
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Upper2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB +2σ'))
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Lower2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB -2σ'))
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
    
    if st.button("✨ 総合解析を実行", use_container_width=True, type="primary"):
        with st.spinner("AIクオンツ解析中..."):
            news = get_wall_street_news()
            prompt = f"USD/JPY:{usd_p}, RSI:{tech['rsi14']}, BB上:{tech['upper2']}, BB下:{tech['lower2']}。戦略を立てよ。ニュース：\n" + "\n".join([n['title'] for n in news])
            st.session_state.strategy_result = model.generate_content(prompt).text
            json_res = model.generate_content(f"{st.session_state.strategy_result}\n上記から {{'side': 'buy'or'sell', 'entry':数値, 'tp':数値, 'sl':数値}} のJSONのみ出せ").text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match: st.session_state.target_prices = json.loads(match.group())

with col3:
    st.subheader("💡 今日のAI戦略 (Rule 1)")
    if st.session_state.strategy_result:
        with st.container(height=350): st.info(st.session_state.strategy_result)
        if st.session_state.target_prices:
            tp_d = st.session_state.target_prices
            risk = st.number_input("許容損失額 (円)", value=10000, step=1000)
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_d['side']=='buy' else 1)
            ent, t_tp, t_sl = st.number_input("Entry", value=float(tp_d['entry'])), st.number_input("TP", value=float(tp_d['tp'])), st.number_input("SL", value=float(tp_d['sl']))
            lots = round(risk / (abs(ent - t_sl) * 10000), 2) if abs(ent - t_sl) > 0 else 0.0
            st.metric("推奨ロット", f"{lots} ロット")
            if st.button("🚀 Rule 1 で監視予約", use_container_width=True, type="primary"):
                if update_github_config(side, ent, t_tp, t_sl, lots, "Rule 1"):
                    requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": f"🎯 【Rule 1 予約確定】\n方向: {side} / ロット: {lots}\nEntry: {ent} / TP: {t_tp} / SL: {t_sl}"})
                    requests.post(st.secrets["GAS_WEBAPP_URL"], json={"date": datetime.now().strftime('%m/%d %H:%M'), "side": side, "entry": ent, "lots": lots, "result": "待機中(Rule 1)"})
                    st.success("Rule 1 予約完了！")
