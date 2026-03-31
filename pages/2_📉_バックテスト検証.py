import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
import re

st.set_page_config(page_title="釘田式・バックテスト", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーの設定を確認してください。")
    st.stop()

# --- 1. AIによるバックテスト実行関数 ---
def run_ai_interpretive_backtest(ticker, rule_text):
    df = yf.download(ticker, period="1mo", interval="1h")
    price_data = ""
    for index, row in df.iterrows():
        try: p = float(row['Close'].iloc[0])
        except: p = float(row['Close'])
        price_data += f"{index.strftime('%m/%d %H:%M')},{p:.3f}\n"

    ai_prompt = f"""
    あなたはトレード実行エージェントです。以下の【ルール】に従い、提供された【価格データ】で1ヶ月間「買い(ロング)」のみのトレードをしたと仮定し、結果を抽出してください。
    【ルール】\n{rule_text}\n
    【価格データ（日時,終値）】\n{price_data}\n
    【出力形式】
    必ず以下のJSON形式のリストのみを出力してください。Markdownの```等は不要です。
    [
      {{"entry_time": "03/01 10:00", "exit_time": "03/01 15:00", "entry_price": 150.12, "exit_price": 150.52, "reason": "利確"}}
    ]
    """
    response = model.generate_content(ai_prompt).text
    try:
        json_str = re.search(r'\[.*\]', response, re.DOTALL).group()
        return json.loads(json_str)
    except:
        return []

# --- 2. AIによる敗因分析とルール改善関数 ---
def evaluate_and_improve(rule_text, trades_df):
    trades_str = trades_df.to_string()
    ai_prompt = f"""
    あなたはプロのシステムトレーダーです。以下の【現在のルール】と、そのルールで実行した【トレード履歴（結果）】を分析してください。
    
    【現在のルール】\n{rule_text}\n
    【トレード履歴（資産推移含む）】\n{trades_str}\n
    
    以下の2点を出力してください。
    1. 評価とアドバイス: なぜ負けトレードが発生したのかの分析と、勝率や利益を上げるために追加すべきフィルター条件。
    2. 改善版ルール: アドバイスを組み込んだ新しいルールの全文。必ず <NEW_RULE> と </NEW_RULE> というタグで囲んでください。
    """
    response = model.generate_content(ai_prompt).text
    
    # アドバイス部分と新ルール部分を分割して抽出
    evaluation = re.sub(r'<NEW_RULE>.*?</NEW_RULE>', '', response, flags=re.DOTALL).strip()
    try:
        new_rule = re.search(r'<NEW_RULE>(.*?)</NEW_RULE>', response, re.DOTALL).group(1).strip()
    except:
        new_rule = rule_text
        
    return evaluation, new_rule

# ==========================================
# メイン画面
# ==========================================
st.title("📉 バックテスト検証 ＆ AI自動改善")

if "saved_rule_text" in st.session_state and st.session_state.saved_rule_text:
    st.success("✅ 読み込まれた最新のルール")
    with st.expander("ルールの内容を確認"):
        st.write(st.session_state.saved_rule_text)
    
    if st.button("🚀 このルールでバックテストを実行", type="primary", use_container_width=True):
        with st.spinner("AIが過去データにルールを当てはめて計算中..."):
            trades = run_ai_interpretive_backtest("JPY=X", st.session_state.saved_rule_text)
            
            if not trades:
                st.warning("トレードチャンスが見つからなかったか、データ読み取りエラーです。もう一度お試しください。")
            else:
                balance = 1000000
                win_count = 0
                
                # 資産推移と勝率の計算
                for t in trades:
                    profit_rate = float(t['exit_price']) / float(t['entry_price'])
                    balance = int(balance * profit_rate)
                    t['balance'] = balance # 1トレードごとの残高を追加
                    
                    if profit_rate > 1.0:
                        win_count += 1
                        
                win_rate = (win_count / len(trades)) * 100
                
                # 画面切り替え時に消えないようセッションに保存
                st.session_state.test_results = trades
                st.session_state.final_balance = balance
                st.session_state.win_rate = win_rate
                
    # --- テスト結果の表示エリア ---
    if "test_results" in st.session_state:
        trades_df = pd.DataFrame(st.session_state.test_results)
        trades_df = trades_df.rename(columns={
            "entry_time": "エントリー", "exit_time": "決済",
            "entry_price": "買値", "exit_price": "売値",
            "reason": "理由", "balance": "資産残高(円)"
        })
        
        # 指標の表示（勝率を追加）
        col1, col2, col3 = st.columns(3)
        col1.metric("最終資産予測", f"{st.session_state.final_balance:,.0f} 円", f"{st.session_state.final_balance - 1000000:,.0f} 円")
        col2.metric("勝率", f"{st.session_state.win_rate:.1f} %")
        col3.metric("取引回数", f"{len(st.session_state.test_results)} 回")
        
        st.write("### 📊 トレード履歴と資産推移")
        st.dataframe(trades_df, use_container_width=True) # 資産残高を含む表を表示
        
        st.write("---")
        st.subheader("🤖 AIによる結果評価とルールの自己改善")
        
        # ルール改善ボタン
        if st.button("💡 この結果からルールを自己改善させる"):
            with st.spinner("AIが敗因を分析し、新しいルールを構築中..."):
                evaluation, new_rule = evaluate_and_improve(st.session_state.saved_rule_text, trades_df)
                st.session_state.ai_evaluation = evaluation
                st.session_state.improved_rule = new_rule
                
        # 改善案の提示と上書き保存
        if "ai_evaluation" in st.session_state:
            st.info(st.session_state.ai_evaluation)
            
            with st.expander("✨ AIが提案する『改善版ルール』の全文"):
                st.write(st.session_state.improved_rule)
                
            if st.button("📥 改善されたルールをバックテストに上書き設定する", type="primary", use_container_width=True):
                # 新しいルールで上書き
                st.session_state.saved_rule_text = st.session_state.improved_rule
                # 古いテスト結果を削除して画面をリセット
                del st.session_state.test_results
                del st.session_state.ai_evaluation
                st.toast("改善されたルールを設定しました！再度バックテストを実行してください。", icon="✅")
                st.rerun() # 画面を自動で再読み込み

else:
    st.info("💡 アナライザーページでルールを作成し、「バックテストに設定する」ボタンを押すとここでテストできます。")