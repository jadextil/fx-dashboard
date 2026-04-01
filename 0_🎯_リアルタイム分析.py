import streamlit as st
import yfinance as yf
import pandas as pd
import urllib.request
import xml.etree.ElementTree as ET
import email.utils
import google.generativeai as genai
from datetime import datetime
from PIL import Image
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

# セッション状態の初期化
if "strategy_result" not in st.session_state:
    st.session_state.strategy_result = ""
if "target_prices" not in st.session_state:
    st.session_state.target_prices = None

# --- 1. 共通関数群 ---

def get_market_indicators():
    """ウォール街が重視する3大指標（TNX, VIX, DXY）を取得。"""
    results = {}
    # 米10年債利回り
    try:
        data = yf.Ticker("^TNX").history(period="5d")
        if not data.empty and len(data) >= 2:
            c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
            results["TNX"] = {"val": c, "diff": c - p}
        else: results["TNX"] = {"val": 0.0, "diff": 0.0}
    except: results["TNX"] = {"val": 0.0, "diff": 0.0}
    
    # 恐怖指数
    try:
        data = yf.Ticker("^VIX").history(period="5d")
        if not data.empty and len(data) >= 2:
            c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
            results["VIX"] = {"val": c, "diff": c - p}
        else: results["VIX"] = {"val": 0.0, "diff": 0.0}
    except: results["VIX"] = {"val": 0.0, "diff": 0.0}
    
    # ドル指数 (DXY) - 複数のティッカーで安定取得を試行
    dxy_tickers = ["DX-Y.NYB", "DX=F", "UUP"]
    results["DXY"] = {"val": 0.0, "diff": 0.0}
    for t in dxy_tickers:
        try:
            data = yf.Ticker(t).history(period="5d")
            if not data.empty and len(data) >= 2:
                c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
                if t == "UUP": c *= 3.5; p *= 3.5 # UUP補正
                results["DXY"] = {"val": c, "diff": c - p}
                break
        except: continue
    return results

def get_technical_chart_data(ticker="JPY=X"):
    """1時間足のデータを取得し、SMA、RSI、ボリンジャーバンドを計算。"""
    try:
        data = yf.download(ticker, period="10d", interval="1h", progress=False)
        if data.empty: return None, {}
        
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
            
        close = data['Close']
        data['SMA20'] = close.rolling(window=20).mean()
        data['SMA50'] = close.rolling(window=50).mean()
        
        # ボリンジャーバンド (2σ)
        std = close.rolling(window=20).std()
        data['Upper2'] = data['SMA20'] + (std * 2)
        data['Lower2'] = data['SMA20'] - (std * 2)
        
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
        rs = gain / loss
        data['RSI14'] = 100 - (100 / (1 + rs))
        
        latest = data.iloc[-1]
        latest_tech = {
            "current": float(latest['Close']),
            "sma20": float(latest['SMA20']),
            "sma50": float(latest['SMA50']),
            "upper2": float(latest['Upper2']),
            "lower2": float(latest['Lower2']),
            "rsi14": float(latest['RSI14'])
        }
        return data, latest_tech
    except Exception as e:
        st.warning(f"チャートデータ取得エラー: {e}")
        return None, {}

def get_wall_street_news():
    """国内・海外・ビジネスの3系統からニュースを30件取得。"""
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
                if len(news_list) >= 30: return news_list
        return news_list
    except:
        return [{"title": "ニュース取得エラー", "date": "--/--"}]

def check_economic_calendar(news_list):
    """ニュースから重要経済指標をフィルタリング。"""
    danger_keywords = ["雇用統計", "CPI", "消費者物価", "政策金利", "FOMC", "日銀", "FRB", "パウエル"]
    events = []
    for news in news_list:
        title = news["title"]
        if any(keyword in title for keyword in danger_keywords):
            time_match = re.search(r'(\d{1,2}:\d{2})|(\d{1,2}時)', title)
            sched_time = time_match.group(0) if time_match else "時間未定"
            events.append({"title": title, "time": sched_time})
    return events

def send_discord_message(text):
    try:
        webhook_url = st.secrets["DISCORD_WEBHOOK_URL"]
        requests.post(webhook_url, json={"content": text})
    except: pass

def send_to_spreadsheet(data):
    try:
        gas_url = st.secrets["GAS_WEBAPP_URL"]
        requests.post(gas_url, json=data)
    except: pass

def update_github_config(side, entry, tp, sl, lots):
    """GitHubリポジトリのconfig.jsonを更新。"""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
        path = st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        res = requests.get(url, headers=headers).json()
        if "sha" not in res: return False
        
        content_dict = {
            "side": side, "entry": float(entry), "tp": float(tp), "sl": float(sl), "lots": float(lots),
            "status": "waiting_entry", "is_active": True
        }
        content_json = json.dumps(content_dict, indent=2)
        content_base64 = base64.b64encode(content_json.encode()).decode()
        
        payload = {"message": f"Update {side} @ {entry}", "content": content_base64, "sha": res["sha"]}
        response = requests.put(url, headers=headers, json=payload)
        return response.status_code == 200
    except Exception as e:
        st.error(f"GitHub連携エラー: {e}")
        return False

# ==========================================
# メイン画面
# ==========================================
st.title("🎯 釘田式・プロ仕様 FX AI指令室")

col1, col2, col3 = st.columns([1.2, 2.2, 1.8])

# --- 左カラム：市場データ ＆ マクロ指標 ---
with col1:
    st.subheader("📊 為替 ＆ マクロ指標")
    chart_data, tech_vals = get_technical_chart_data("JPY=X")
    usd_p = tech_vals.get("current", 0.0)
    st.metric("🇺🇸 ドル/円 (USD/JPY)", f"{usd_p:.3f} 円")
    
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
        for ev in calendar[:5]:
            st.warning(f"🕒 {ev['time']}: {ev['title']}")
    else:
        st.success("本日の主要指標予定なし。")

# --- 中央カラム：チャート ＆ ニュース ＆ 解析 ---
with col2:
    st.subheader("📈 チャート (1H + ボリンジャーバンド)")
    if chart_data is not None:
        fig = go.Figure(data=[go.Candlestick(x=chart_data.index,
                        open=chart_data['Open'], high=chart_data['High'],
                        low=chart_data['Low'], close=chart_data['Close'],
                        name='ローソク足')])
        
        # 指標の追加
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA20'], line=dict(color='orange', width=1.5), name='SMA20'))
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Upper2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB+2σ'))
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Lower2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB-2σ'))
        
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"💡 RSI(14):{tech_vals['rsi14']:.1f} | BB上:{tech_vals['upper2']:.2f} | BB下:{tech_vals['lower2']:.2f}")

    st.write("---")
    st.subheader("📰 最新ニュース (30本)")
    news_text = "\n".join([f"[{n['date']}] {n['title']}" for n in all_news])
    with st.expander("ニュースヘッドラインを開く"):
        st.text_area("", value=news_text, height=200, label_visibility="collapsed")
    
    if st.button("✨ 総合解析を実行（全データ注入）", use_container_width=True, type="primary"):
        with st.spinner("AIクオンツが市場とニュースを分析中..."):
            ai_context = f"""
            現在価格:{usd_p:.3f}, RSI:{tech_vals['rsi14']:.1f}, BB上:{tech_vals['upper2']:.3f}, BB下:{tech_vals['lower2']:.3f},
            米10年債:{m_data['TNX']['val']:.2f}%, VIX:{m_data['VIX']['val']:.2f}, DXY:{m_data['DXY']['val']:.2f}
            """
            prompt = f"以下の市場環境とニュースを元に、BBの収束・拡散を考慮したデイトレ戦略を立て、entry/tp/slの数値を出してください。\n\n{ai_context}\n\n【ニュース】\n{news_text}"
            
            response = model.generate_content(prompt)
            st.session_state.strategy_result = response.text
            
            json_res = model.generate_content(f"{st.session_state.strategy_result}\n上記から {{'side': 'buy'or'sell', 'entry': 数値, 'tp': 数値, 'sl': 数値}} のJSONのみ出力せよ。").text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match:
                st.session_state.target_prices = json.loads(match.group())

# --- 右カラム：戦略 ＆ 資金管理 ---
with col3:
    st.subheader("💡 AIトレード戦略")
    if st.session_state.strategy_result:
        with st.container(height=350):
            st.info(st.session_state.strategy_result)
        
        if st.session_state.target_prices:
            tp_data = st.session_state.target_prices
            st.write("---")
            st.subheader("🛡️ 資金管理設定")
            risk_cash = st.number_input("許容損失額 (円)", value=10000, step=1000)
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_data['side']=='buy' else 1)
            t_entry = st.number_input("Entry価格", value=float(tp_data['entry']), step=0.01)
            t_tp = st.number_input("利確目標 (TP)", value=float(tp_data['tp']), step=0.01)
            t_sl = st.number_input("損切ライン (SL)", value=float(tp_data['sl']), step=0.01)
            
            pips_risk = abs(t_entry - t_sl)
            calc_lots = round(risk_cash / (pips_risk * 10000), 2) if pips_risk > 0 else 0.0
            st.metric("💡 推奨ロット", f"{calc_lots} ロット")

            if st.button("🚀 24時間監視予約", use_container_width=True, type="primary"):
                if update_github_config(side, t_entry, t_tp, t_sl, calc_lots):
                    send_to_spreadsheet({"date": datetime.now().strftime('%m/%d %H:%M'), "side": side, "entry": t_entry, "lots": calc_lots, "result": "待機中"})
                    send_discord_message(f"🎯 予約確定: {side} @ {t_entry}\nTP: {t_tp} / SL: {t_sl}")
                    st.success("GitHub同期完了！")
