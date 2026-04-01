import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
import re
import base64
import requests
from datetime import datetime

# --- 0. 初期設定 ---
st.set_page_config(page_title="釘田式・バックテスト検証 PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API設定を確認してください。")
    st.stop()

# セッション状態の管理
if "backtest_results" not in st.session_state:
    st.session_state.backtest_results = None
if "improved_rule" not in st.session_state:
    st.session_state.improved_rule = ""

# --- 1. テクニカル指標計算関数 (SMA20/50, BB, RSI) ---
def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    
    close = df['Close']
    # 移動平均線 (SMA)
    df['SMA20'] = close.rolling(window=20).mean()
    df['SMA50'] = close.rolling(window=50).mean()
    
    # ボリンジャーバンド (2σ)
    std = close.rolling(window=20).std()
    df['Upper2'] = df['SMA20'] + (std * 2)
    df['Lower2'] = df['SMA20'] - (std * 2)
    
    # RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    
    return df.dropna()

# --- 2. 共通関数群 (Discord, GitHub, GAS) ---
def send_discord_message(text):
    try:
        requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": text})
    except: pass

def send_to_spreadsheet(data):
    try:
        requests.post(st.secrets["GAS_WEBAPP_URL"], json=data)
    except: pass

def update_github_config(side, entry, tp, sl, lots, rule_name):
    try:
        token, repo, path = st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers).json()
        
        config_data = {
            "rule_name": rule_name,
            "side": side,
            "entry": float(entry),
            "tp": float(tp),
            "sl": float(sl),
            "lots": float(lots),
            "status": "waiting_entry",
            "is_active": True
        }
        payload = {
            "message": f"Update {rule_name} via Backtest",
            "content": base64.b64encode(json.dumps(config_data, indent=2).encode()).decode(),
            "sha": res["sha"]
        }
        return requests.put(url, headers=headers, json=payload).status_code == 200
    except: return False

# --- 3. AIバックテスト ＆ 改善ロジック ---
def run_ai_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    price_data = ""
    for idx, row in df.iterrows():
        price_data += (f"{idx.strftime('%m/%d %H:%M')},終:{row['Close']:.3f},"
                       f"SMA20:{row['SMA20']:.2f},SMA50:{row['SMA50']:.2f},"
                       f"BB上:{row['Upper2']:.3f},BB下:{row['Lower2']:.3f},RSI:{row['RSI']:.1f}\n")

    prompt = f"以下のルールをデータに適用し全トレードをJSONリスト形式で出力せよ。\n【ルール】\n{rule_text}\n【データ】\n{price_data}"
    try:
        res = model.generate_content(prompt).text
        match = re.search(r'\[.*\]', res, re.DOTALL)
        return json.loads(match.group()) if match else []
    except: return []

def evaluate_and_improve(rule_text, trades_df):
    prompt = f"結果を分析し改善案を提示せよ。新ルールを <NEW_RULE>...</NEW_RULE> で囲め。\n【旧ルール】\n{rule_text}\n【結果】\n{trades_df.to_string()}"
    res = model.generate_content(prompt).text
    eval_txt = re.sub(r'<NEW_RULE>.*?</NEW_RULE>', '', res, flags=re.DOTALL).strip()
    match = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', res, re.DOTALL)
    new_rule = match.group(1).strip() if match else rule_text
    return eval_txt, new_rule

# ==========================================
# メイン画面
# ==========================================
st.title("📉 バックテスト検証 ＆ AI自動改善")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    
    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("📝 現在の検証対象ルール")
        st.info(st.session_state.saved_rule_text)
    with col_right:
        target_pair = st.selectbox("テストペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
        if st.button("🚀 このルールでバックテストを実行", type="primary", use_container_width=True):
            with st.spinner("AIが1ヶ月分のデータをSMA/BB/RSIで精密スキャン中..."):
                trades = run_ai_backtest(target_pair, st.session_state.saved_rule_text)
                if trades:
                    initial_balance, balance, win_count, history = 1000000, 1000000, 0, []
                    for t in trades:
                        e, ex = float(t['entry_price']), float(t['exit_price'])
                        pnl_rate = (ex - e)/e if t.get('side')=='buy' else (e - ex)/e
                        profit_yen = int(balance * pnl_rate)
                        balance += profit_yen
                        win_loss = "✅ 勝ち" if profit_yen > 0 else "❌ 負け"
                        if profit_yen > 0: win_count += 1
                        history.append({"結果": win_loss, "売買": "買い" if t.get('side')=='buy' else "売り", "損益(円)": f"{profit_yen:+,}円", "エントリー": e, "決済": ex, "時間": t.get('entry_time'), "残高": f"{int(balance):,}円", "理由": t.get('reason')})
                    st.session_state.backtest_results = pd.DataFrame(history)
                    st.session_state.backtest_summary = {"balance": balance, "profit": balance - initial_balance, "win_rate": (win_count/len(trades))*100, "count": len(trades)}
                else: st.warning("トレードが発生しませんでした。")

    if st.session_state.backtest_results is not None:
        st.write("---")
        sum_data = st.session_state.backtest_summary
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最終資産", f"{int(sum_data['balance']):,} 円")
        c2.metric("合計損益", f"{int(sum_data['profit']):+,} 円")
        c3.metric("勝率", f"{sum_data['win_rate']:.1f} %")
        c4.metric("取引回数", f"{sum_data['count']} 回")
        
        st.table(st.session_state.backtest_results)

        # --- 予約エリア (Rule 1) ---
        st.subheader("🚀 この結果(Rule 1)で監視予約する")
        col_r1a, col_r1b = st.columns(2)
        with col_r1a:
            risk1 = st.number_input("許容損失(円)", value=10000, key="risk1")
            side1 = st.selectbox("売買方向", ["buy", "sell"], key="side1")
        with col_r1b:
            ent1 = st.number_input("Entry", value=150.0, step=0.01, key="ent1")
            tp1 = st.number_input("TP", value=151.0, step=0.01, key="tp1")
            sl1 = st.number_input("SL", value=149.0, step=0.01, key="sl1")
        
        lots1 = round(risk1 / (abs(ent1 - sl1) * 10000), 2) if abs(ent1 - sl1) > 0 else 0.0
        if st.button("🔥 Rule 1 で予約 ＆ 通知 ＆ 記録", use_container_width=True):
            if update_github_config(side1, ent1, tp1, sl1, lots1, "Rule 1"):
                send_discord_message(f"🎯 【Rule 1 予約確定】\n方向: {side1} / ロット: {lots1}\nEntry: {ent1} / TP: {tp1} / SL: {sl1}")
                send_to_spreadsheet({"date": datetime.now().strftime('%Y-%m-%d %H:%M'), "rule": "1", "side": "買い" if side1 == "buy" else "売り", "entry": ent1, "exit": 0, "result": "待機中", "pnl": 0, "lots": lots1})
                st.success("Rule 1 予約完了！")

        st.write("---")
        # --- 改善案生成エリア (Rule 2) ---
        if st.button("💡 敗因を分析して Rule 2 (改善案) を生成する", use_container_width=True):
            with st.spinner("AIが改善案を思考中..."):
                eval_txt, new_r = evaluate_and_improve(st.session_state.saved_rule_text, st.session_state.backtest_results)
                st.session_state.ai_evaluation = eval_txt
                st.session_state.improved_rule = new_r

        if st.session_state.improved_rule:
            st.info(st.session_state.ai_evaluation)
            st.subheader("✨ 改善された新ルール (Rule 2)")
            st.code(st.session_state.improved_rule)
            
            col_loop1, col_loop2 = st.columns(2)
            with col_loop1:
                if st.button("🔄 Rule 2 をバックテスト対象に設定する", use_container_width=True):
                    st.session_state.saved_rule_text = st.session_state.improved_rule
                    st.rerun()
            
            with col_loop2:
                st.write("（上のボタンを押すと、このRule 2を再度テストできます）")

            st.write("---")
            st.subheader("🚀 改善案(Rule 2)で監視予約する")
            col_r2a, col_r2b = st.columns(2)
            with col_r2a:
                risk2 = st.number_input("許容損失(円)", value=10000, key="risk2")
                side2 = st.selectbox("売買方向", ["buy", "sell"], key="side2")
            with col_r2b:
                ent2 = st.number_input("Entry", value=150.0, step=0.01, key="ent2")
                tp2 = st.number_input("TP", value=151.0, step=0.01, key="tp2")
                sl2 = st.number_input("SL", value=149.0, step=0.01, key="sl2")
            
            lots2 = round(risk2 / (abs(ent2 - sl2) * 10000), 2) if abs(ent2 - sl2) > 0 else 0.0
            if st.button("🔥 Rule 2 で予約 ＆ 通知 ＆ 記録", use_container_width=True, type="primary"):
                if update_github_config(side2, ent2, tp2, sl2, lots2, "Rule 2"):
                    send_discord_message(f"🔥 【Rule 2 予約確定】\n改善ルールで監視を開始します。\nロット: {lots2}\nEntry: {ent2} / TP: {tp2} / SL: {sl2}")
                    send_to_spreadsheet({"date": datetime.now().strftime('%m/%d %H:%M'), "rule": "2", "side": "買い" if side2 == "buy" else "売り", "entry": ent2, "exit": 0, "result": "待機中", "pnl": 0, "lots": lots2})
                    st.success("Rule 2 予約完了！")
else:
    st.info("分析室ページで Rule 1 を作成してください。")
