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
if "backtest_summary" not in st.session_state:
    st.session_state.backtest_summary = None
if "ai_evaluation" not in st.session_state:
    st.session_state.ai_evaluation = ""
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
    # 1ヶ月分のデータを取得
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    # AIが読み取りやすいCSV形式のテキストデータを作成
    price_data = "DateTime,Close,SMA20,SMA50,Upper2,Lower2,RSI\n"
    for idx, row in df.iterrows():
        price_data += (f"{idx.strftime('%m/%d %H:%M')},{row['Close']:.3f},"
                       f"{row['SMA20']:.2f},{row['SMA50']:.2f},"
                       f"{row['Upper2']:.3f},{row['Lower2']:.3f},{row['RSI']:.1f}\n")

    prompt = f"""
    あなたは世界最高峰のバックテスト・エンジニアです。
    以下の【トレードルール】を【価格データ】に適用し、1ヶ月間で行われた全てのトレードを抽出してください。

    【トレードルール】
    {rule_text}

    【価格データ (1時間足)】
    {price_data}

    【実行指示】
    1. ルールの条件（SMAの向き、BBのタッチ、RSIの数値など）に合致するポイントを、1本ずつのローソク足から厳密に探してください。
    2. ルールの条件が「多少曖昧」であっても、トレーダーの意図を汲み取り、論理的にエントリー・決済ポイントを特定してください。
    3. 1ヶ月の中でトレードが「ゼロ」になることは稀です。ルールの本質に沿ったチャンスを必ず見つけ出してください。
    4. 結果は必ず以下のJSONリスト形式のみで出力してください。

    出力形式例:
    [
      {{"side": "buy", "entry_time": "03/01 10:00", "exit_time": "03/02 15:00", "entry_price": 150.10, "exit_price": 151.50, "reason": "SMA20上抜け+RSI30反発"}}
    ]
    """
    try:
        response = model.generate_content(prompt)
        # JSON部分を正規表現で抽出
        match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return []
    except Exception as e:
        st.error(f"AI解析エラー: {e}")
        return []

def evaluate_and_improve(rule_text, trades_df):
    prompt = f"""
    あなたはプロのシステムトレーダーです。以下のバックテスト結果を分析し、
    期待値をさらに高めるための「改善案」を提示してください。
    改善された新ルールは、必ず <NEW_RULE> タグで囲んで記述してください。

    【現在のルール】
    {rule_text}

    【バックテスト結果（トレード履歴）】
    {trades_df.to_string()}
    """
    try:
        res = model.generate_content(prompt).text
        eval_txt = re.sub(r'<NEW_RULE>.*?</NEW_RULE>', '', res, flags=re.DOTALL).strip()
        match = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', res, re.DOTALL)
        new_rule = match.group(1).strip() if match else rule_text
        return eval_txt, new_rule
    except:
        return "改善案の生成に失敗しました。", rule_text

# ==========================================
# メイン画面
# ==========================================
st.title("📉 バックテスト検証 ＆ AI自動改善")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    
    # 🌟 ルールを折りたたみ式にして最上部に配置
    with st.expander("📝 現在のバックテスト対象ルールを確認", expanded=False):
        st.info(st.session_state.saved_rule_text)
    
    st.write("---")
    
    # テスト実行エリア
    col_setup1, col_setup2 = st.columns([2, 1])
    with col_setup1:
        target_pair = st.selectbox("テスト通貨ペアを選択", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    with col_setup2:
        st.write(" ") # 余白
        run_bt = st.button("🚀 バックテストを開始", type="primary", use_container_width=True)

    if run_bt:
        with st.spinner("AIが1ヶ月分のデータをSMA/BB/RSIで精密スキャン中..."):
            trades = run_ai_backtest(target_pair, st.session_state.saved_rule_text)
            
            if trades:
                initial_balance = 1000000
                balance = initial_balance
                history = []
                win_count = 0
                
                for t in trades:
                    e, ex = float(t['entry_price']), float(t['exit_price'])
                    # 損益計算
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
                
                st.session_state.backtest_results = pd.DataFrame(history)
                st.session_state.backtest_summary = {
                    "balance": balance,
                    "profit": balance - initial_balance,
                    "win_rate": (win_count/len(trades))*100,
                    "count": len(trades)
                }
                st.success(f"✅ {len(trades)}件のトレードを検出しました")
            else:
                st.session_state.backtest_results = None
                st.error("⚠️ トレードが発生しませんでした。ルールの条件が厳しすぎるか、現在の相場に合致していない可能性があります。")

    # --- 結果表示エリア ---
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
            risk1 = st.number_input("1トレ許容損失(円)", value=10000, key="risk1")
            side1 = st.selectbox("売買方向", ["buy", "sell"], key="side1")
        with col_r1b:
            ent1 = st.number_input("Entry価格", value=float(trades[-1]['exit_price']) if trades else 150.0, step=0.01, key="ent1")
            tp1 = st.number_input("TP価格", value=float(trades[-1]['exit_price'])+1.0 if trades else 151.0, step=0.01, key="tp1")
            sl1 = st.number_input("SL価格", value=float(trades[-1]['exit_price'])-0.5 if trades else 149.5, step=0.01, key="sl1")
        
        lots1 = round(risk1 / (abs(ent1 - sl1) * 10000), 2) if abs(ent1 - sl1) > 0 else 0.0
        st.metric("推奨ロット (Rule 1)", f"{lots1} lot")
        
        if st.button("🔥 Rule 1 で予約 ＆ 通知 ＆ 記録を実行", use_container_width=True):
            if update_github_config(side1, ent1, tp1, sl1, lots1, "Rule 1"):
                requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": f"🎯 【Rule 1 予約確定】\n方向: {side1} / ロット: {lots1}\nEntry: {ent1} / TP: {tp1} / SL: {sl1}"})
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
                st.caption("※上のボタンを押すと、このRule 2を再度テスト（ループ検証）できます。")

            st.write("---")
            st.subheader("🚀 改善案(Rule 2)で監視予約する")
            col_r2a, col_r2b = st.columns(2)
            with col_r2a:
                risk2 = st.number_input("1トレ許容損失(円)", value=10000, key="risk2")
                side2 = st.selectbox("売買方向", ["buy", "sell"], key="side2")
            with col_r2b:
                ent2 = st.number_input("Entry価格", value=150.0, step=0.01, key="ent2")
                tp2 = st.number_input("TP価格", value=151.0, step=0.01, key="tp2")
                sl2 = st.number_input("SL価格", value=149.5, step=0.01, key="sl2")
            
            lots2 = round(risk2 / (abs(ent2 - sl2) * 10000), 2) if abs(ent2 - sl2) > 0 else 0.0
            st.metric("推奨ロット (Rule 2)", f"{lots2} lot")
            
            if st.button("🔥 Rule 2 で予約 ＆ 通知 ＆ 記録を実行", use_container_width=True, type="primary"):
                if update_github_config(side2, ent2, tp2, sl2, lots2, "Rule 2"):
                    requests.post(st.secrets["DISCORD_WEBHOOK_URL"], json={"content": f"🔥 【Rule 2 予約確定】\n改善ルールで監視を開始します。\nロット: {lots2}\nEntry: {ent2} / TP: {tp2} / SL: {sl2}"})
                    send_to_spreadsheet({"date": datetime.now().strftime('%Y-%m-%d %H:%M'), "rule": "2", "side": "買い" if side2 == "buy" else "売り", "entry": ent2, "exit": 0, "result": "待機中", "pnl": 0, "lots": lots2})
                    st.success("Rule 2 予約完了！")
else:
    st.info("分析室ページで Rule 1 を作成してください。")
