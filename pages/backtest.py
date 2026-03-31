import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
from datetime import datetime

# --- 初期設定 ---
st.set_page_config(page_title="釘田式・バックテスト", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーの設定を確認してください。")
    st.stop()

# --- 釘田式オリジナル・バックテストエンジン ---
def run_backtest(ticker, initial_capital=1000000):
    df = yf.download(ticker, period="1mo", interval="1h")
    
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    else:
        df.index = df.index.tz_convert('UTC')
        
    df['SMA_5'] = df['Close'].rolling(window=5).mean()
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_60'] = df['Close'].rolling(window=60).mean()
    df['Min_5'] = df['Low'].rolling(window=5).min()
    
    balance = initial_capital
    position = 0
    history = [initial_capital] * 60 # 最初の60時間は待機期間
    trades = []
    
    for i in range(60, len(df)):
        current_time = df.index[i]
        current_hour = current_time.hour
        
        try:
            high = float(df['High'].iloc[i].iloc[0]) if isinstance(df['High'].iloc[i], pd.Series) else float(df['High'].iloc[i])
            low = float(df['Low'].iloc[i].iloc[0]) if isinstance(df['Low'].iloc[i], pd.Series) else float(df['Low'].iloc[i])
            close = float(df['Close'].iloc[i].iloc[0]) if isinstance(df['Close'].iloc[i], pd.Series) else float(df['Close'].iloc[i])
            prev_close = float(df['Close'].iloc[i-1].iloc[0]) if isinstance(df['Close'].iloc[i-1], pd.Series) else float(df['Close'].iloc[i-1])
            sma_5 = float(df['SMA_5'].iloc[i].iloc[0]) if isinstance(df['SMA_5'].iloc[i], pd.Series) else float(df['SMA_5'].iloc[i])
            prev_sma_5 = float(df['SMA_5'].iloc[i-1].iloc[0]) if isinstance(df['SMA_5'].iloc[i-1], pd.Series) else float(df['SMA_5'].iloc[i-1])
            sma_20 = float(df['SMA_20'].iloc[i].iloc[0]) if isinstance(df['SMA_20'].iloc[i], pd.Series) else float(df['SMA_20'].iloc[i])
            sma_60 = float(df['SMA_60'].iloc[i].iloc[0]) if isinstance(df['SMA_60'].iloc[i], pd.Series) else float(df['SMA_60'].iloc[i])
            min_5_prev = float(df['Min_5'].iloc[i-1].iloc[0]) if isinstance(df['Min_5'].iloc[i-1], pd.Series) else float(df['Min_5'].iloc[i-1])
        except:
            high, low, close, prev_close = float(df['High'].iloc[i]), float(df['Low'].iloc[i]), float(df['Close'].iloc[i]), float(df['Close'].iloc[i-1])
            sma_5, prev_sma_5 = float(df['SMA_5'].iloc[i]), float(df['SMA_5'].iloc[i-1])
            sma_20, sma_60 = float(df['SMA_20'].iloc[i]), float(df['SMA_60'].iloc[i])
            min_5_prev = float(df['Min_5'].iloc[i-1])

        # 【1】エントリー判定
        if position == 0:
            trend_ok = (close > sma_60) and (sma_20 > sma_60)
            time_ok = (7 <= current_hour <= 12)
            signal_ok = (prev_close < prev_sma_5) and (close > sma_5)
            
            if trend_ok and time_ok and signal_ok:
                position = balance / close
                entry_price = close
                entry_time = current_time
                
                # JPYペアなら0.40円、それ以外(EURUSDなど)なら0.0040の幅にする調整
                pip_multiplier = 1.0 if "JPY" in ticker else 0.01
                
                tp_price = entry_price + (0.40 * pip_multiplier)
                fixed_sl = entry_price - (0.25 * pip_multiplier)
                tech_sl = min_5_prev - (0.05 * pip_multiplier)
                sl_price = max(fixed_sl, tech_sl)
                
        # 【2】エグジット判定
        elif position > 0:
            exit_price = 0
            reason = ""
            
            if low <= sl_price:
                exit_price = sl_price
                reason = "損切り"
            elif high >= tp_price:
                exit_price = tp_price
                reason = "利確達成"
            elif current_hour >= 20:
                exit_price = close
                reason = "20時・時間決済"
                
            if exit_price > 0:
                balance = position * exit_price
                if exit_price < entry_price:
                    trades.append(f"日時: {entry_time.strftime('%m/%d %H:%M')}, 買値: {entry_price:.3f}, 売値: {exit_price:.3f} ({reason})")
                position = 0
                
        history.append(balance if position == 0 else position * close)
        
    # ここがエラーの原因でした！datesとhistoryの長さを完全に揃えました。
    return df.index, history, trades

# --- UI部分 ---
st.title("📉 釘田式オリジナル・デイトレ戦略検証")

target_pair = st.selectbox("検証する通貨ペア", ["JPY=X", "EURUSD=X", "GBPJPY=X"])

st.write("---")
st.subheader("📊 指定ルール（SMA押し目買い）の検証テスト")
st.write("・時間帯：07:00〜12:00 (UTC)\n・条件：SMA60/SMA20上昇トレンド中のSMA5上抜け\n・利確：+40pips / 損切：-25pips or 直近安値割れ / 時間決済：20:00 (UTC)")

if st.button("▶️ バックテストを開始する", type="primary"):
    with st.spinner("過去1ヶ月のデータを解析中..."):
        dates, equity_curve, bad_trades = run_backtest(target_pair)
        
        final_balance = equity_curve[-1]
        profit = final_balance - 1000000
        
        col_a, col_b = st.columns(2)
        col_a.metric("最終資産", f"{final_balance:,.0f} 円", f"{profit:,.0f} 円")
        
        st.line_chart(pd.DataFrame(equity_curve, index=dates, columns=["総資産"]))
        
        if bad_trades:
            lose_data = "\n".join(bad_trades[:5])
            reflection_prompt = f"以下の負けたデイトレードデータを見て、なぜ失敗したのか仮説を立て、次から負けないための新しいフィルター条件を提案して。\n{lose_data}"
            response = model.generate_content(reflection_prompt)
            st.warning("🤖 AI反省会\n\n" + response.text)
        else:
            st.success("この期間、負けトレードはありませんでした！")