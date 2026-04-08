import streamlit as st
import yfinance as yf
import pandas as pd
import urllib.request
import xml.etree.ElementTree as ET
import email.utils
import google.generativeai as genai
from datetime import datetime, time
import pytz
from PIL import Image
import requests
import json
import re
import base64
import plotly.graph_objects as go

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室 PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    # ユーザー様の環境で動作実績のあるバージョンを指定
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

def get_market_session():
    """現在の時刻から、東京・ロンドン・NYのどのセッションかを判定する。"""
    # 日本時間を基準にする
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst).time()
    
    sessions = []
    # 東京市場: 09:00 - 15:00
    if time(9, 0) <= now <= time(15, 0):
        sessions.append("東京市場 (Tokyo)")
    
    # ロンドン市場: 16:00 - 翌01:00 (修正済み)
    if now >= time(16, 0) or now <= time(1, 0):
        sessions.append("ロンドン市場 (London)")
    
    # ニューヨーク市場: 21:00 - 翌06:00 (修正済み)
    if now >= time(21, 0) or now <= time(6, 0):
        sessions.append("ニューヨーク市場 (NY)")
    
    if not sessions:
        sessions.append("オセアニア/時間外 (Quiet Time)")
    return " & ".join(sessions)

def get_market_indicators():
    """マクロ指標（TNX, VIX, DXY）および相関資産（N225, SPX）を取得。"""
    results = {}
    targets = {"TNX": "^TNX", "VIX": "^VIX", "N225": "^N225", "SPX": "^GSPC"}
    
    for key, ticker in targets.items():
        try:
            data = yf.Ticker(ticker).history(period="5d")
            if not data.empty:
                c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
                results[key] = {"val": c, "diff": c - p}
            else: results[key] = {"val": 0.0, "diff": 0.0}
        except: results[key] = {"val": 0.0, "diff": 0.0}
    
    # ドル指数 (DXY) の多重取得
    dxy_tickers = ["DX-Y.NYB", "DX=F", "UUP"]
    results["DXY"] = {"val": 0.0, "diff": 0.0}
    for t in dxy_tickers:
        try:
            data = yf.Ticker(t).history(period="5d")
            if not data.empty and len(data) >= 2:
                c, p = float(data['Close'].iloc[-1]), float(data['Close'].iloc[-2])
                if t == "UUP": c *= 3.5; p *= 3.5
                results["DXY"] = {"val": c, "diff": c - p}
                break
        except: continue
    return results

def get_technical_chart_data(ticker="JPY=X"):
    """SMA, BB, RSI, BB Width, レジサポ, 日足トレンドをすべて計算。"""
    try:
        # 短期分析用（1時間足）
        data = yf.download(ticker, period="10d", interval="1h", progress=False)
        if data.empty: return None, {}
        if isinstance(data.columns, pd.MultiIndex): data.columns = [col[0] for col in data.columns]
            
        close = data['Close']
        # SMA計算
        data['SMA20'] = close.rolling(window=20).mean()
        data['SMA50'] = close.rolling(window=50).mean()
        
        # ボリンジャーバンド計算
        std = close.rolling(window=20).std()
        data['Upper2'] = data['SMA20'] + (std * 2)
        data['Lower2'] = data['SMA20'] - (std * 2)
        
        # RSI(14) の計算
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = -delta.clip(upper=0).rolling(window=14).mean()
        data['RSI14'] = 100 - (100 / (1 + (gain / loss)))
        
        # BB Width（スクイーズ判定用）
        data['BB_Width'] = (data['Upper2'] - data['Lower2']) / data['SMA20']
        avg_width = data['BB_Width'].tail(100).mean()
        current_width = data['BB_Width'].iloc[-1]
        is_squeeze = current_width < (avg_width * 0.8)
        
        # 上位足（日足）トレンド
        data_daily = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if isinstance(data_daily.columns, pd.MultiIndex): data_daily.columns = [col[0] for col in data_daily.columns]
        daily_sma20 = data_daily['Close'].rolling(window=20).mean().iloc[-1]
        
        # 5日レジサポ
        high_5d = float(data['High'].tail(120).max())
        low_5d = float(data['Low'].tail(120).min())
        
        # 直近10時間分のOHLC履歴を取得して文字列化（プライスアクション判定用）
        recent_10 = data.tail(10)
        history_str = "\n".join([f"[{idx.strftime('%m/%d %H:%M')}] Open:{row['Open']:.2f}, High:{row['High']:.2f}, Low:{row['Low']:.2f}, Close:{row['Close']:.2f}" for idx, row in recent_10.iterrows()])
        
        # --- NEW: MTFデータ (15m, 4h) ---
        data_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        if isinstance(data_15m.columns, pd.MultiIndex): data_15m.columns = [col[0] for col in data_15m.columns]
        history_15m_str = "\n".join([f"[{idx.strftime('%m/%d %H:%M')}] Open:{row['Open']:.2f}, High:{row['High']:.2f}, Low:{row['Low']:.2f}, Close:{row['Close']:.2f}" for idx, row in data_15m.tail(10).iterrows()]) if not data_15m.empty else "N/A"

        # yfinanceの制限を回避するため1h足を4h足にリサンプル
        data_4h = data.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}).dropna()
        history_4h_str = "\n".join([f"[{idx.strftime('%m/%d %H:%M')}] Open:{row['Open']:.2f}, High:{row['High']:.2f}, Low:{row['Low']:.2f}, Close:{row['Close']:.2f}" for idx, row in data_4h.tail(10).iterrows()]) if not data_4h.empty else "N/A"

        latest = data.iloc[-1]
        latest_tech = {
            "current": float(latest['Close']),
            "sma20": float(latest['SMA20']),
            "sma50": float(latest['SMA50']),
            "upper2": float(latest['Upper2']),
            "lower2": float(latest['Lower2']),
            "rsi14": float(latest['RSI14']),
            "bb_width": float(current_width),
            "bb_avg_width": float(avg_width),
            "is_squeeze": is_squeeze,
            "daily_sma20": float(daily_sma20),
            "high_5d": high_5d,
            "low_5d": low_5d,
            "history_10h": history_str,
            "history_15m": history_15m_str,
            "history_4h": history_4h_str
        }
        return data, latest_tech
    except Exception as e:
        st.warning(f"データ取得エラー: {e}")
        return None, {}

def get_wall_street_news():
    """3つのRSSソースから最新ニュースを30件取得。"""
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
    except: return [{"title": "ニュース取得エラー", "date": "--/--"}]

def get_web_sentiment(news_list):
    """(代替)WEBニュースから簡易的な買い・売りセンチメント（世論の偏り）を推計する。"""
    bull_words = ["上昇", "高値", "買い", "強気", "利上げ", "タカ派", "上方修正"]
    bear_words = ["下落", "安値", "売り", "弱気", "利下げ", "ハト派", "懸念", "警戒"]
    bull_count = bear_words_count = 0
    for news in news_list:
        title = news["title"]
        bull_count += sum(1 for w in bull_words if w in title)
        bear_words_count += sum(1 for w in bear_words if w in title)
    
    total = bull_count + bear_words_count
    if total == 0:
        return {"bull_ratio": 50.0, "bear_ratio": 50.0, "status": "中立 (Neutral)"}
    bull_ratio = (bull_count / total) * 100
    status = "買い偏向 (Bullish)" if bull_ratio > 60 else "売り偏向 (Bearish)" if bull_ratio < 40 else "中立 (Neutral)"
    return {"bull_ratio": bull_ratio, "bear_ratio": 100 - bull_ratio, "status": status}

def check_economic_calendar(news_list):
    """ニュースから重要キーワードを検出し指標予定を抽出。"""
    danger_keywords = ["雇用統計", "CPI", "消費者物価", "政策金利", "FOMC", "日銀", "FRB", "パウエル"]
    events = []
    for news in news_list:
        if any(kw in news["title"] for kw in danger_keywords):
            time_match = re.search(r'(\d{1,2}:\d{2})|(\d{1,2}時)', news["title"])
            events.append({"title": news["title"], "time": time_match.group(0) if time_match else "時間未定"})
    return events

def update_github_config(side, entry, tp, sl, lots, rule_name="Rule 1"):
    """GitHubリポジトリのconfig.jsonを更新。"""
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        if "sha" not in res: return False
        content_dict = {"rule_name": rule_name, "side": side, "entry": float(entry), "tp": float(tp), "sl": float(sl), "lots": float(lots), "status": "waiting_entry", "is_active": True}
        content_json = json.dumps(content_dict, indent=2)
        payload = {"message": f"Update {rule_name}", "content": base64.b64encode(content_json.encode()).decode(), "sha": res["sha"]}
        return requests.put(url, headers=headers, json=payload).status_code == 200
    except: return False

# ==========================================
# メイン画面構築
# ==========================================
st.title("🎯 釘田式・FX AI指令室 PRO")

col1, col2, col3 = st.columns([1.2, 2.2, 1.8])

# --- 左カラム：市場データ ＆ 多角分析 ---
with col1:
    st.subheader("📊 為替 ＆ 相関資産")
    chart_data, tech = get_technical_chart_data("JPY=X")
    usd_p = tech.get("current", 0.0)
    st.metric("🇺🇸 ドル/円", f"{usd_p:.3f} 円")
    
    st.write("---")
    m = get_market_indicators()
    st.metric("📈 米10年債利回り", f"{m['TNX']['val']:.2f}%", f"{m['TNX']['diff']:.3f}")
    st.metric("💵 ドル指数(DXY)", f"{m['DXY']['val']:.2f}", f"{m['DXY']['diff']:.2f}")
    st.metric("🇯🇵 日経平均", f"{m['N225']['val']:,.0f}", f"{m['N225']['diff']:,.0f}")
    st.metric("🇺🇸 S&P500", f"{m['SPX']['val']:,.0f}", f"{m['SPX']['diff']:,.0f}")
    st.metric("📉 恐怖指数(VIX)", f"{m['VIX']['val']:.2f}", f"{m['VIX']['diff']:.2f}")
    
    st.write("---")
    st.subheader("📅 重要経済指標予定")
    all_news = get_wall_street_news()
    calendar = check_economic_calendar(all_news)
    sentiment = get_web_sentiment(all_news)
    
    st.metric("🌐 WEBセンチメント (ニュース解析)", f"{sentiment['bull_ratio']:.1f}% 買", sentiment['status'])
    st.write("---")

    if calendar:
        for ev in calendar[:5]: st.warning(f"🕒 {ev['time']}\n{ev['title']}")
    else: st.success("本日の主要指標予定なし")

# --- 中央カラム：チャート ＆ AI解析 ---
with col2:
    st.subheader("📈 テクニカルチャート (1H + BB + SMA)")
    if chart_data is not None:
        fig = go.Figure(data=[go.Candlestick(x=chart_data.index, open=chart_data['Open'], high=chart_data['High'], low=chart_data['Low'], close=chart_data['Close'], name='Candle')])
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA20'], line=dict(color='orange', width=1.5), name='SMA20'))
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Upper2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB+2σ'))
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Lower2'], line=dict(color='rgba(173,216,230,0.6)', dash='dash'), name='BB-2σ'))
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        
        status_sq = "⚠️ スクイーズ中" if tech['is_squeeze'] else "🚀 ボラ拡大中"
        st.caption(f"💡 {status_sq} | BB幅: {tech['bb_width']:.4f} | RSI(14): {tech['rsi14']:.1f}")
        st.caption(f"💡 5日高値: {tech['high_5d']:.2f} | 5日安値: {tech['low_5d']:.2f} | 日足SMA20: {tech['daily_sma20']:.2f}")

    st.write("---")
    st.subheader("📰 最新ニュース (30本)")
    news_text = "\n".join([f"[{n['date']}] {n['title']}" for n in all_news])
    with st.expander("ニュースヘッドラインを開く"):
        st.text_area("", value=news_text, height=200, label_visibility="collapsed")
    
    if st.button("✨ 総合解析を実行 (全データ注入)", use_container_width=True, type="primary"):
        with st.spinner("AIが全指標を精密分析中..."):
            current_session = get_market_session()
            ai_context = f"""
            【市場セッション】{current_session}
            【WEBセンチメント(独自のニュース解析ベース)】{sentiment['status']} (買比率: {sentiment['bull_ratio']:.1f}%)
            
            【プライスアクション・フラクタル構造(MTF)】
            [15分足 (直近10本: エントリータイミング用)]
            {tech.get('history_15m', '')}
            
            [1時間足 (直近10本: メイントレンド用)]
            {tech.get('history_10h', '')}
            
            [4時間足 (直近10本: 大局の環境認識用)]
            {tech.get('history_4h', '')}
            
            【短期足(1H) テクニカル詳細】現在:{usd_p:.3f}, SMA20:{tech['sma20']:.3f}, SMA50:{tech['sma50']:.3f}, BB上2σ:{tech['upper2']:.3f}, BB下2σ:{tech['lower2']:.3f}, RSI(14):{tech['rsi14']:.1f}
            【ボラティリティ】BB幅:{tech['bb_width']:.4f}, 平均幅:{tech['bb_avg_width']:.4f}, 状態:{'スクイーズ' if tech['is_squeeze'] else 'エクスパンション'}
            【長期足(日足) トレンド】日足SMA20:{tech['daily_sma20']:.3f}, 5日高値:{tech['high_5d']:.3f}, 5日安値:{tech['low_5d']:.3f}
            【外部環境・マクロ】米10年債:{m['TNX']['val']:.2f}%, ドル指数:{m['DXY']['val']:.2f}, 日経平均:{m['N225']['val']:,.0f}, SP500:{m['SPX']['val']:,.0f}, VIX:{m['VIX']['val']:.2f}
            """
            
            prompt = f"""あなたは世界最高峰のFXプロトレーダーです。ダウ理論・エリオット波動・プライスアクション（ローソク足の形状やヒゲ）を考慮し、論理的かつ厳格なトレード戦略を立ててください。
以下の【市場データ】と【ニュース】を元に、現在の相場環境を分析し、最適なエントリーポイント、利益確定(TP)、損切り(SL)を決定します。
【厳守ルール】
・リスクリワード比率は1:1.5以上を確保すること。
・理由のないブレイクアウト狙いは避け、レジサポでの反発（押し目買い・戻り売り）を基本とすること。
・具体的な戦略の根拠を明確に解説すること。

{ai_context}

【ニュース】
{news_text}
"""
            
            # 戦略テキストの生成
            response = model.generate_content(prompt)
            st.session_state.strategy_result = response.text
            
            # JSON抽出プロンプト (Structured Output使用)
            json_prompt = f"""以下の分析結果をもとに、具体的なトレード条件をJSONフォーマットのみで抽出してください。
価格は現在の {usd_p} 円を基準に論理的に計算してください。
出力フォーマット:
{{
    "side": "buy" または "sell",
    "entry": 数値 (例: 150.25),
    "tp": 数値 (例: 151.00),
    "sl": 数値 (例: 149.50)
}}

分析結果:
{st.session_state.strategy_result}
"""
            try:
                json_res = model.generate_content(
                    json_prompt,
                    generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
                )
                st.session_state.target_prices = json.loads(json_res.text)
            except Exception as e:
                st.error(f"JSON解析エラーが発生しました。AIの出力を確認してください。詳細: {e}")

# --- 右カラム：戦略 ＆ 資金管理 ---
with col3:
    st.subheader("💡 AI特化型戦略 (Rule 1)")
    if st.session_state.strategy_result:
        with st.container(height=350): st.info(st.session_state.strategy_result)
        if st.session_state.target_prices:
            tp_d = st.session_state.target_prices
            risk = st.number_input("許容損失額 (円)", value=10000, step=1000)
            side = st.selectbox("売買方向", ["buy", "sell"], index=0 if tp_d['side']=='buy' else 1)
            t_ent = st.number_input("Entry", value=float(tp_d['entry']), step=0.01)
            t_tp = st.number_input("TP (利確)", value=float(tp_d['tp']), step=0.01)
            t_sl = st.number_input("SL (損切)", value=float(tp_d['sl']), step=0.01)
            lots = round(risk / (abs(t_ent - t_sl) * 10000), 2) if abs(t_ent - t_sl) > 0 else 0.0
            st.metric("💡 推奨ロット", f"{lots} ロット")

            if st.button("🚀 24時間監視予約を実行", use_container_width=True, type="primary"):
                if update_github_config(side, t_ent, t_tp, t_sl, lots, "Rule 1"):
                    requests.post(st.secrets["GAS_WEBAPP_URL"], json={"date": datetime.now().strftime('%Y-%m-%d %H:%M'), "rule": "1", "side": "買い" if side == "buy" else "売り", "entry": t_ent, "exit": 0, "result": "待機中", "pnl": 0, "lots": lots})
                    requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": f"🎯 【Rule 1 予約確定】\nセッション: {get_market_session()}\nRSI: {tech['rsi14']:.1f}\n方向: {side} / ロット: {lots}\nEntry: {t_ent}円 / TP: {t_tp}円 / SL: {t_sl}"})
                    st.success("Rule 1 予約完了！")
