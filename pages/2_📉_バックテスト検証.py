import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
import re

# --- 0. 初期設定 ---
st.set_page_config(page_title="釘田式・バックテスト PRO", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーの設定を確認してください。")
    st.stop()

# --- 1. テクニカル指標計算（分析室と共通） ---
def add_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    
    close = df['Close']
    df['SMA20'] = close.rolling(window=20).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -1 * delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    df['ATR'] = (df['High'] - df['Low']).rolling(window=14).mean()
    return df.dropna()

# --- 2. AIによる精密バックテスト実行関数 ---
def run_ai_interpretive_backtest(ticker, rule_text):
    # 1ヶ月分の1時間足を取得
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    df = add_indicators(df)
    
    # 🌟 AIに渡すデータをOHLC + テクニカルに拡張
    price_data = ""
    for index, row in df.iterrows():
        price_data += (f"{index.strftime('%m/%d %H:%M')},"
                       f"始:{row['Open']:.3f},高:{row['High']:.3f},安:{row['Low']:.3f},終:{row['Close']:.3f},"
                       f"SMA20:{row['SMA20']:.3f},RSI:{row['RSI14']:.1f},ATR:{row['ATR']:.3f}\n")

    ai_prompt = f"""
    あなたは凄腕のバックテスト・エージェントです。提供された【トレードルール】を【価格データ】に適用し、1ヶ月間のシミュレーションを行ってください。

    【トレードルール】
    {rule_text}

    【価格データ（日時,始値,高値,安値,終値,SMA20,RSI,ATR）】
    {price_data}

    【実行指示】
    1. ルールに基づき「買い(long)」と「売り(short)」の両方を判定してください。
    2. 各トレードの「エントリー時刻」「決済時刻」「エントリー価格」「決済価格」「売買方向(side)」「理由」を抽出してください。
    3. ローソク足の高値・安値を考慮し、その1時間の中で損切りに触れていないか厳密にチェックしてください。

    【出力形式】
    必ず以下のJSON形式のリストのみを出力してください。
    [
      {{"side": "buy"または"sell", "entry_time": "03/01 10:00", "exit_time": "03/05 15:00", "entry_price": 150.12, "exit_price": 151.52, "reason": "利確"}}
    ]
    """
    
    response = model.generate_content(ai_prompt).text
    try:
        json_str = re.search(r'\[.*\]', response, re.DOTALL).group()
        return json.loads(json_str)
    except:
        return []

# --- 3. AIによる改善関数（プロンプト強化版） ---
def evaluate_and_improve(rule_text, trades_df):
    trades_str = trades_df.to_string()
    ai_prompt = f"""
    あなたはプロのシステムトレーダーです。現在のルールとバックテスト結果を分析し、改善案を提示してください。
    
    【現在のルール】\n{rule_text}\n
    【トレード結果】\n{trades_str}\n

    【分析指示】
    - なぜ負けたのか？（例：ボラティリティが低い時にエントリーしすぎている、RSIの逆張りが機能していない等）
    - 期待値を上げるために「削るべきエントリー」や「追加すべきフィルター」を具体的に提案してください。
    - 改善版ルールを <NEW_RULE> タグで囲んで出力してください。
    """
    response = model.generate_content(ai_prompt).text
    evaluation = re.sub(r'<NEW_RULE>.*?</NEW_RULE>', '', response, flags=re.DOTALL).strip()
    try:
        new_rule = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', response, re.DOTALL).group(1).strip()
    except:
        new_rule = rule_text
    return evaluation, new_rule

# ==========================================
# メイン画面
# ==========================================
st.title("📉 バックテスト検証 ＆ AI自動改善 PRO")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    st.success("✅ 解析済みの最新ルールを読み込みました")
    with st.expander("現在のルールの詳細"):
        st.write(st.session_state.saved_rule_text)
    
    target_pair = st.selectbox("テスト通貨ペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])
    
    if st.button("🚀 バックテストを実行（精密シミュレーション）", type="primary", use_container_width=True):
        with st.spinner("AIが全ローソク足の形状を分析してトレードを実行中..."):
            trades = run_ai_interpretive_backtest(target_pair, st.session_state.saved_rule_text)
            
            if not trades:
                st.warning("トレードが発生しませんでした。ルールの条件が厳しすぎる可能性があります。")
            else:
                balance = 1000000
                history = []
                win_count = 0
                
                for t in trades:
                    side = t.get('side', 'buy')
                    entry = float(t['entry_price'])
                    exit = float(t['exit_price'])
                    
                    # 🌟 売り・買いそれぞれの損益計算
                    if side == "buy":
                        profit_rate = exit / entry
                    else:
                        profit_rate = 1 + (entry - exit) / entry # 売りは価格が下がれば利益
                    
                    balance = int(balance * profit_rate)
                    t['pnl_rate'] = (profit_rate - 1) * 100
                    t['balance'] = balance
                    if profit_rate > 1.0: win_count += 1
                    history.append(t)
                
                st.session_state.test_results = history
                st.session_state.final_balance = balance
                st.session_state.win_rate = (win_count / len(history)) * 100

    # --- 結果表示 ---
    if "test_results" in st.session_state:
        col1, col2, col3 = st.columns(3)
        col1.metric("最終資産", f"{st.session_state.final_balance:,.0f} 円", f"{st.session_state.final_balance - 1000000:,.0f} 円")
        col2.metric("勝率", f"{st.session_state.win_rate:.1f} %")
        col3.metric("取引回数", f"{len(st.session_state.test_results)} 回")
        
        st.write("### 📊 トレード履歴（精密分析結果）")
        res_df = pd.DataFrame(st.session_state.test_results)
        st.dataframe(res_df.style.format({"entry_price": "{:.3f}", "exit_price": "{:.3f}", "pnl_rate": "{:.2f}%", "balance": "{:,}円"}), use_container_width=True)

        st.write("---")
        st.subheader("🤖 AIによる改善アドバイス")
        if st.button("💡 敗因を分析してルールを最強にアップデートする"):
            with st.spinner("AIが失敗パターンを学習中..."):
                evaluation, new_rule = evaluate_and_improve(st.session_state.saved_rule_text, res_df)
                st.session_state.ai_evaluation = evaluation
                st.session_state.improved_rule = new_rule

        if "ai_evaluation" in st.session_state:
            st.info(st.session_state.ai_evaluation)
            with st.expander("✨ 改善された新ルール（これを再度テストできます）"):
                st.code(st.session_state.improved_rule)
            
            if st.button("📥 改善ルールをメイン設定に上書き", type="primary"):
                st.session_state.saved_rule_text = st.session_state.improved_rule
                del st.session_state.test_results
                st.rerun()
else:
    st.info("💡 アナライザーページでルールを作成してください。")
