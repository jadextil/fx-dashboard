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
import plotly.graph_objects as go  # 🌟 チャート自動描画用のライブラリを追加

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
    """ウォール街が重視する3大指標を取得。"""
    results = {}
    try:
        data = yf.Ticker("^TNX").history(period="5d")
        if not data.empty and len(data) >= 2:
            c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
            results["TNX"] = {"val": c, "diff": c - p}
        else: results["TNX"] = {"val": 0.0, "diff": 0.0}
    except: results["TNX"] = {"val": 0.0, "diff": 0.0}
    
    try:
        data = yf.Ticker("^VIX").history(period="5d")
        if not data.empty and len(data) >= 2:
            c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
            results["VIX"] = {"val": c, "diff": c - p}
        else: results["VIX"] = {"val": 0.0, "diff": 0.0}
    except: results["VIX"] = {"val": 0.0, "diff": 0.0}
    
    dxy_tickers = ["DX-Y.NYB", "DX=F", "UUP"]
    results["DXY"] = {"val": 0.0, "diff": 0.0}
    for t in dxy_tickers:
        try:
            data = yf.Ticker(t).history(period="5d")
            if not data.empty and len(data) >= 2:
                c = float(data['Close'].iloc[-1]); p = float(data['Close'].iloc[-2])
                if t == "UUP": c *= 3.5; p *= 3.5
                results["DXY"] = {"val": c, "diff": c - p}
                break
        except: continue
    return results

def get_technical_chart_data(ticker="JPY=X"):
    """🌟 1時間足のデータを取得し、テクニカル指標を自動計算する"""
    try:
        data = yf.download(ticker, period="5d", interval="1h", progress=False)
        if data.empty: return None, {}
        
        # yfinanceのバージョンによるデータ構造(MultiIndex)の吸収
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
            
        close = data['Close']
        
        # 移動平均線 (SMA20, SMA50)
        data['SMA20'] = close.rolling(window=20).mean()
        data['SMA50'] = close.rolling(window=50).mean()
        
        # RSI(14) の計算
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
        rs = gain / loss
        data['RSI14'] = 100 - (100 / (1 + rs))
        
        latest_tech = {
            "current": float(close.iloc[-1]),
            "sma20": float(data['SMA20'].iloc[-1]),
            "sma50": float(data['SMA50'].iloc[-1]),
            "rsi14": float(data['RSI14'].iloc[-1])
        }
        return data, latest_tech
    except Exception as e:
        st.warning(f"チャートデータ取得エラー: {e}")
        return None, {}

def get_wall_street_news():
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
                except: date_formatted = "日時不明"
                
                news_list.append({"title": title, "date": date_formatted})
                if len(news_list) >= 30: return news_list
        return news_list
    except Exception as e:
        st.sidebar.warning(f"ニュース取得エラー: {e}")
        return [{"title": "ニュース取得エラー", "date": "--/--"}]

def check_economic_calendar(news_list):
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
    except Exception as e:
        st.sidebar.error(f"Discord通知エラー: {e}")

def send_to_spreadsheet(data):
    try:
        gas_url = st.secrets["GAS_WEBAPP_URL"]
        requests.post(gas_url, json=data)
    except Exception as e:
        st.sidebar.error(f"スプレッドシート記帳エラー: {e}")

def update_github_config(side, entry, tp, sl, lots):
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
        path = st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        res = requests.get(url, headers=headers).json()
        if "sha" not in res: return False
        
        content_dict = {
            "side": side, "entry": entry, "tp": tp, "sl": sl, "lots": lots,
            "status": "waiting_entry", "is_active": True
        }
        content_json = json.dumps(content_dict, indent=2)
        content_base64 = base64.b64encode(content_json.encode()).decode()
        
        payload = {"message": f"Update strategy ({side} at {entry})", "content": content_base64, "sha": res["sha"]}
        response = requests.put(url, headers=headers, json=payload)
        return response.status_code == 200
    except Exception as e:
        st.error(f"GitHub連携エラー: {e}")
        return False

# ==========================================
# メイン画面構築
# ==========================================
st.title("🎯 釘田式・プロ仕様 FX AI指令室")

# チャートを大きく見せるために中央の幅を広く設定
col1, col2, col3 = st.columns([1.2, 2.2, 1.8])

# --- 左カラム：市場データ ＆ マクロ指標 ---
with col1:
    st.subheader("📊 為替 ＆ マクロ指標")
    
    # 🌟 チャートデータとテクニカル数値を一括取得
    chart_data, tech_vals = get_technical_chart_data("JPY=X")
    usd_p = tech_vals.get("current", 0.0)
    
    st.metric("🇺🇸 ドル/円 (USD/JPY)", f"{usd_p:.3f} 円")
    
    st.write("---")
    st.write("🌍 **機関投資家の注目データ**")
    m_data = get_market_indicators()
    st.metric("📈 米10年債利回り (TNX)", f"{m_data['TNX']['val']:.2f}%", f"{m_data['TNX']['diff']:.3f}")
    st.metric("📉 恐怖指数 (VIX)", f"{m_data['VIX']['val']:.2f}", f"{m_data['VIX']['diff']:.2f}")
    st.metric("💵 ドル指数 (DXY)", f"{m_data['DXY']['val']:.2f}", f"{m_data['DXY']['diff']:.2f}")
    
    st.write("---")
    st.subheader("📅 指標発表スケジュール")
    all_news = get_wall_street_news()
    calendar = check_economic_calendar(all_news)
    
    if calendar:
        for ev in calendar[:5]:
            st.warning(f"🕒 予定時刻: {ev['time']}\n{ev['title']}")
    else:
        st.success("本日の主要指標予定は見当たりません。")

# --- 中央カラム：自動チャート ＆ ニュース ＆ 解析 ---
with col2:
    st.subheader("📈 テクニカルチャート (1時間足)")
    
    # 🌟 Plotlyを使ったローソク足チャートの自動描画
    if chart_data is not None:
        fig = go.Figure(data=[go.Candlestick(x=chart_data.index,
                        open=chart_data['Open'], high=chart_data['High'],
                        low=chart_data['Low'], close=chart_data['Close'],
                        name='ローソク足')])
        
        # 移動平均線の追加
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA20'], line=dict(color='orange', width=1.5), name='SMA20'))
        fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA50'], line=dict(color='blue', width=1.5), name='SMA50'))
        
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        
        # 現在のテクニカル数値を表示
        st.caption(f"💡 現在のテクニカル: 【RSI(14)】{tech_vals.get('rsi14', 0):.1f}  【SMA20】{tech_vals.get('sma20', 0):.2f}円  【SMA50】{tech_vals.get('sma50', 0):.2f}円")
    else:
        st.warning("チャートデータを取得できませんでした。")

    st.write("---")
    st.subheader("📰 ウォール街 ＆ 国内ニュース")
    news_text = "\n".join([f"[{n['date']}] {n['title']}" for n in all_news])
    
    # ニュース枠をスッキリさせるためにアコーディオン（折りたたみ）化
    with st.expander("ニュース・ヘッドライン（30件）を開く"):
        st.text_area("", value=news_text, height=200, label_visibility="collapsed")
    
    if st.button("✨ 総合解析を実行（全自動データ注入）", use_container_width=True, type="primary"):
        with st.spinner("AIがプロの視点で市場とチャート数値を分析中..."):
            
            # 🌟 AIに渡すプロンプトに「テクニカルの具体的な数値」を直接注入！
            ai_context = f"""
            【現在の市場データ（ドル円: {usd_p:.3f}円）】
            ▼ テクニカル指標 (1時間足)
            ・RSI(14): {tech_vals.get('rsi14', 0):.1f} (※70以上は買われすぎ、30以下は売られすぎ)
            ・20期間移動平均線(SMA20): {tech_vals.get('sma20', 0):.3f}円
            ・50期間移動平均線(SMA50): {tech_vals.get('sma50', 0):.3f}円

            ▼ マクロ指標データ
            ・米国債10年利回り: {m_data['TNX']['val']:.2f}%
            ・恐怖指数(VIX): {m_data['VIX']['val']:.2f}
            ・ドルインデックス(DXY): {m_data['DXY']['val']:.2f}
            """
            
            prompt = f"以下の【市場データ】と【ニュース30件】を総合的に判断し、本日のデイトレ戦略（環境認識、売り買いの方向、具体的な目標価格）をプロのトレーダーとして解説してください。\n\n{ai_context}\n\n【ニュース】\n{news_text}"
            
            # 画像の送信は不要になり、テキストのみで圧倒的に高精度な分析を行う
            response = model.generate_content(prompt)
            st.session_state.strategy_result = response.text
            
            json_prompt = f"""
            現在のドル円価格は {usd_p:.3f} 円です。
            以下の【あなたが作成した戦略】を正確に読み取り、監視すべき数値をJSON形式のみで出力してください。

            【あなたが作成した戦略】
            {st.session_state.strategy_result}

            【厳格なルール】
            ・戦略が「売り（ショート）」の場合は必ず "sell" を指定し、tp（利確）はentryより低く、sl（損切）は高く設定すること。
            ・戦略が「買い（ロング）」の場合は必ず "buy" を指定し、tp（利確）はentryより高く、sl（損切）は低く設定すること。
            ・出力例のような形式で、必ず現在の価格({usd_p:.3f}円)や戦略に沿った現実的な数値を入れること。
            
            出力例: {{"side": "sell", "entry": 150.10, "tp": 149.50, "sl": 150.50}}
            """
            json_res = model.generate_content(json_prompt).text
            match = re.search(r'\{.*\}', json_res, re.DOTALL)
            if match:
                st.session_state.target_prices = json.loads(match.group())

# --- 右カラム：戦略 ＆ 資金管理 ---
with col3:
    st.subheader("💡 今日のトレード戦略")
    if st.session_state.strategy_result:
        
        # 戦略結果をスクロール可能な枠に収める
        with st.container(height=350):
            st.info(st.session_state.strategy_result)
        
        if st.session_state.target_prices:
            tp_data = st.session_state.target_prices
            st.write("---")
            st.subheader("🛡️ DMM FX 資金管理設定")
            
            risk_cash = st.number_input("1トレードの許容損失額 (円)", value=10000, step=1000)
            
            side_index = 0 if tp_data.get('side', 'buy') == 'buy' else 1
            side = st.selectbox("売買方向", ["buy", "sell"], index=side_index)
            
            t_entry = st.number_input("エントリー価格", value=float(tp_data['entry']), step=0.01)
            t_tp = st.number_input("利確目標 (TP)", value=float(tp_data['tp']), step=0.01)
            t_sl = st.number_input("損切ライン (SL)", value=float(tp_data['sl']), step=0.01)
            
            pips_risk = abs(t_entry - t_sl)
            calc_lots = risk_cash / (pips_risk * 10000) if pips_risk > 0 else 0.0
            calc_lots = round(calc_lots, 2)
            
            st.metric("💡 推奨ロット数", f"{calc_lots} ロット", f"損切時の損失を 約{risk_cash}円 に固定")

            if st.button("🚀 24時間監視予約", use_container_width=True, type="primary"):
                if update_github_config(side, t_entry, t_tp, t_sl, calc_lots):
                    
                    log_data = {
                        "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
                        "side": "買い(予約)" if side == "buy" else "売り(予約)",
                        "entry": t_entry,
                        "exit": 0,
                        "result": "待機中",
                        "pnl": 0,
                        "lots": calc_lots
                    }
                    send_to_spreadsheet(log_data)
                    
                    msg = f"🎯 【予約確定】\n方向: {side} / ロット: {calc_lots}\nエントリー: {t_entry}円\n利確: {t_tp}円 / 損切: {t_sl}円"
                    send_discord_message(msg)
                    
                    st.success("予約完了！ 決済時に正確な損益がスプレッドシートへ自動記帳されます。")
    else:
        st.write("「総合解析を実行」ボタンを押すと、戦略が表示されます。")
