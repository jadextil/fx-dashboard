import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 0. 初期設定 ---
st.set_page_config(page_title="⛩️ 釘田式・FX AI指令室", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except:
    st.error("APIキーの設定を確認してください。")
    st.stop()

# --- 1. バックテスト用ロジック ---
def run_backtest(ticker, initial_capital=1000000):
    # 過去1ヶ月の1時間足を取得
    df = yf.download(ticker, period="1mo", interval="1h")
    
    # 簡易的な戦略（例：RSIが30以下で買い、70以上で売り）
    # RSI計算
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # シミュレーション変数
    balance = initial_capital
    position = 0
    history = [initial_capital]
    trades = [] # 負けたトレードの記録用

    for i in range(1, len(df)):
        price = df['Close'].iloc[i]
        rsi = df['RSI'].iloc[i]
        
        # 買いシグナル (RSI < 30) かつ ポジションなし
        if rsi < 30 and position == 0:
            position = balance / price
            entry_price = price
            entry_time = df.index[i]
        
        # 売りシグナル (RSI > 70) かつ ポジションあり
        elif rsi > 70 and position > 0:
            balance = position * price
            p_l = balance - initial_capital # 簡易的なP/L
            if price < entry_price: # 負けトレード
                trades.append(f"時刻: {entry_time}, 買値: {entry_price:.2f}, 売値: {price:.2f}")
            position = 0
        
        history.append(balance if position == 0 else position * price)

    return df.index, history, trades

# --- メイン画面 ---
tab1, tab2 = st.tabs(["🚀 リアルタイム分析", "📊 過去データ検証（バックテスト）"])

with tab1:
    st.write("（※ここには以前のリアルタイム分析・チャート解析コードが入ります）")
    st.info("リアルタイム分析画面はこれまでのコードをご使用ください。")

with tab2:
    st.header("📈 戦略のシミュレーション")
    st.write("「もし100万円でAI戦略を運用していたら？」を検証します。")
    
    target_pair = st.selectbox("検証する通貨ペア", ["JPY=X", "EURUSD=X"], index=0)
    
    if st.button("バックテストを開始する", type="primary"):
        with st.spinner("過去1ヶ月のデータを解析中..."):
            dates, equity_curve, bad_trades = run_backtest(target_pair)
            
            # 資産曲線の表示
            final_balance = equity_curve[-1]
            profit = final_balance - 1000000
            
            col_a, col_b = st.columns(2)
            col_a.metric("最終資産", f"{final_balance:,.0f} 円", f"{profit:,.0f} 円")
            
            # グラフ表示
            st.line_chart(pd.DataFrame(equity_curve, index=dates, columns=["総資産"]))
            
            st.write("---")
            st.subheader("🤖 AIによる『負けトレード』の反省会")
            
            if bad_trades:
                # 負けたトレードの情報をAIに渡す
                lose_data = "\n".join(bad_trades[:3]) # 直近3つ
                reflection_prompt = f"""
                あなたは凄腕のFXトレーダーです。以下の「負けたトレード（損切り）」のデータを見て、
                なぜこのタイミングでの買いが失敗したのか、市場の背景を推測して反省文を作成してください。
                
                【負けたデータ】
                {lose_data}
                
                【指示】
                ・負けた理由の仮説を立ててください。
                ・次から同じ負けを繰り返さないための「新しいルール（例：〇〇の時はエントリーしない）」を提案してください。
                ・釘田様を励ます前向きな言葉で締めてください。
                """
                
                response = model.generate_content(reflection_prompt)
                st.warning(response.text)
            else:
                st.success("この期間、大きな負けトレードはありませんでした！素晴らしい戦略です。")
