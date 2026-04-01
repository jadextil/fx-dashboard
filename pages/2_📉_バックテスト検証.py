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

# --- 1. テクニカル指標計算 ---
def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    close = df['Close']
    df['SMA20'] = close.rolling(window=20).mean()
    
    # ボリンジャーバンド (2σ)
    std = close.rolling(window=20).std()
    df['Upper2'] = df['SMA20'] + (std * 2)
    df['Lower2'] = df['SMA20'] - (std * 2)
    
    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    return df.dropna()

# --- 2. 共通関数群 (Discord, GitHub, GAS) ---
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

def update_github_config(side, entry, tp, sl, lots, rule_name="Rule 2"):
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
        path = st.secrets["GITHUB_TARGET_FILE"]
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        
        res = requests.get(url, headers=headers).json()
        if "sha" not in res: return False
        
        content_dict = {
            "rule_name": rule_name,
            "side": side,
            "entry": float(entry),
            "tp": float(tp),
            "sl": float(sl),
            "lots": float(lots),
            "status": "waiting_entry",
            "is_active": True
        }
        content_json = json.dumps(content_dict, indent=2)
        content_base64 = base64.b64encode(content_json.encode()).decode()
        
        payload = {"message": f"Update {rule_name} ({side} at {entry})", "content": content_base64, "sha": res["sha"]}
        response = requests.put(url, headers=headers, json=payload)
        return response.status_code == 200
    except: return False

# --- 3. AIバックテスト ＆ 改善ロジック ---
def run_ai_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    price_data = ""
    for idx, row in df.iterrows():
        price_data += f"{idx.strftime('%m/%d %H:%M')},終:{row['Close']:.3f},BB上:{row['Upper2']:.3f},BB下:{row['Lower2']:.3f},RSI:{row['RSI']:.1f}\n"

    prompt = f"""
    あなたは厳格なバックテスト・エージェントです。以下のルールをデータに適用し、全トレードをJSONリスト形式で出力してください。
    【ルール】\n{rule_text}\n
    【データ】\n{price_data}
    
    出力形式: [{{'side':'buy','entry_price':0,'exit_price':0,'entry_time':'...','exit_time':'...','reason':'...'}}]
    """
    try:
        res = model.generate_content(prompt).text
        match = re.search(r'\[.*\]', res, re.DOTALL)
        return json.loads(match.group()) if match else []
    except: return []

def evaluate_and_improve(rule_text, trades_df):
    prompt = f"""
    あなたはプロのシステムトレーダーです。以下のバックテスト結果を分析し、
    負けトレードを排除するための改善案を提示してください。
    また、改善された新ルールを <NEW_RULE> タグで囲んで出力してください。

    【現在のルール】\n{rule_text}\n
    【トレード結果】\n{trades_df.to_string()}
    """
    res = model.generate_content(prompt).text
    eval_txt = re.sub(r'<NEW_RULE>.*?</NEW_RULE>', '', res, flags=re.DOTALL).strip()
    match = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', res, re.DOTALL)
    new_rule = match.group(1).strip() if match else rule_text
    return eval_txt, new_rule

# ==========================================
# メイン画面
# ==========================================
st.title("📉 バックテスト検証 ＆ AI自動改善 (Rule 2)")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    st.success("✅ 解析済みの Rule 1 を読み込みました")
    with st.expander("現在の検証対象ルール"):
        st.write(st.session_state.saved_rule_text)
    
    target_pair = st.selectbox("テスト通貨ペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    
    if st.button("🚀 精密バックテストを実行", type="primary", use_container_width=True):
        with st.spinner("AIが1ヶ月分の全データを厳格にシミュレーション中..."):
            trades = run_ai_backtest(target_pair, st.session_state.saved_rule_text)
            
            if trades:
                initial_balance = 1000000
                balance = initial_balance
                history = []
                win_count = 0
                
                for t in trades:
                    e, ex = float(t['entry_price']), float(t['exit_price'])
                    pnl_rate = (ex - e)/e if t.get('side')=='buy' else (e - ex)/e
                    profit_yen = int(balance * pnl_rate)
                    balance += profit_yen
                    
                    win_loss = "✅ 勝ち" if profit_yen > 0 else "❌ 負け"
                    if profit_yen > 0: win_count += 1
                    
                    history.append({
                        "結果": win_loss,
                        "売買": "買い" if t.get('side')=='buy' else "売り",
                        "損益(円)": f"{profit_yen:+,}円",
                        "利率": f"{pnl_rate*100:.2f}%",
                        "エントリー価格": f"{e:.3f}",
                        "決済価格": f"{ex:.3f}",
                        "時間": t.get('entry_time'),
                        "残高": f"{int(balance):,}円",
                        "理由": t.get('reason')
                    })
                
                st.session_state.backtest_results = history
                st.session_state.backtest_summary = {
                    "final_balance": balance,
                    "net_profit": balance - initial_balance,
                    "win_rate": (win_count / len(trades)) * 100,
                    "count": len(trades)
                }
            else:
                st.warning("トレードが発生しませんでした。")

    # --- 結果表示 ＆ 改善 ---
    if "backtest_results" in st.session_state:
        summary = st.session_state.backtest_summary
        c1, c2, c3 = st.columns(3)
        c1.metric("最終資産", f"{int(summary['final_balance']):,} 円")
        c2.metric("純損益", f"{int(summary['net_profit']):+,} 円")
        c3.metric("勝率", f"{summary['win_rate']:.1f} %")
        
        st.write("### 📜 詳細トレード履歴")
        res_df = pd.DataFrame(st.session_state.backtest_results)
        st.table(res_df)

        st.write("---")
        if st.button("💡 敗因を分析して Rule 2 を生成する", use_container_width=True):
            with st.spinner("AIが改善案を思考中..."):
                eval_txt, new_r = evaluate_and_improve(st.session_state.saved_rule_text, res_df)
                st.session_state.ai_evaluation = eval_txt
                st.session_state.improved_rule = new_r

        if "ai_evaluation" in st.session_state:
            st.info(st.session_state.ai_evaluation)
            st.subheader("✨ 改善された新ルール (Rule 2)")
            st.code(st.session_state.improved_rule)
            
            st.write("---")
            st.subheader("🛡️ Rule 2 監視予約設定")
            colA, colB = st.columns(2)
            with colA:
                risk2 = st.number_input("許容損失額 (円)", value=10000, step=1000, key="r2")
                side2 = st.selectbox("売買方向", ["buy", "sell"], key="s2")
            with colB:
                ent2 = st.number_input("想定Entry価格", value=tech_vals.get('current', 150.0), step=0.01, key="e2")
                tp2 = st.number_input("想定TP価格", value=tech_vals.get('current', 150.0)+1.0, step=0.01, key="t2")
                sl2 = st.number_input("想定SL価格", value=tech_vals.get('current', 150.0)-0.5, step=0.01, key="sl2")
            
            lots2 = round(risk2 / (abs(ent2 - sl2) * 10000), 2) if abs(ent2 - sl2) > 0 else 0.0
            st.metric("💡 推奨ロット数 (Rule 2)", f"{lots2} ロット")
            
            if st.button("🚀 Rule 2 で監視予約を実行", type="primary", use_container_width=True):
                if update_github_config(side2, ent2, tp2, sl2, lots2, "Rule 2"):
                    # ルール列を「2」、売買列を「買い/売り」に分けて記帳
                    log_data = {
                        "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
                        "rule": "2",
                        "side": "買い" if side2 == "buy" else "売り",
                        "entry": ent2,
                        "exit": 0,
                        "result": "待機中",
                        "pnl": 0,
                        "lots": lots2
                    }
                    send_to_spreadsheet(log_data)
                    
                    msg = f"🔥 【Rule 2 予約確定】\n改善されたルールで監視を開始します。\nロット: {lots2}\nEntry: {ent2}円 / TP: {tp2}円 / SL: {sl2}円"
                    send_discord_message(msg)
                    st.success("Rule 2 予約完了！ GitHub同期 ＆ Discord通知を送信しました。")
else:
    st.info("分析室ページで Rule 1 を作成してください。")
