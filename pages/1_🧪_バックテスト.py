import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import json
from datetime import datetime, timedelta

# --- 初期設定 ---
st.set_page_config(page_title="バックテスト検証", layout="wide")
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API設定を確認してください。")
    st.stop()

st.title("🧪 AI戦略バックテスト・シミュレータ")
st.write("過去の特定のチャート情報のみをAIに渡し、その後の値動きで実際に予測が当たるか検証します。")

# 検証用の仮設定
ticker = "JPY=X"
days_ago = st.slider("何日前のデータを基準にテストしますか？", min_value=1, max_value=7, value=2)

if st.button("🚀 バックテストを実行する", type="primary"):
    with st.spinner(f"{days_ago}日前の相場でAIに戦略を立てさせています..."):
        # 基準日時を決定（X日前の15:00等を想定）
        end_date = datetime.now() - timedelta(days=days_ago)
        start_date = end_date - timedelta(days=5)
        
        try:
            # --- 1. AIが見る過去のデータ準備 ---
            df_past = yf.download(ticker, start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), interval="1h", progress=False)
            if isinstance(df_past.columns, pd.MultiIndex):
                df_past.columns = [col[0] for col in df_past.columns]
                
            if df_past.empty:
                st.warning("データが取得できませんでした。休場日などの可能性があります。")
                st.stop()
                
            past_10_str = "\n".join([f"[{idx.strftime('%m/%d %H:%M')}] Open:{row['Open']:.2f}, High:{row['High']:.2f}, Low:{row['Low']:.2f}, Close:{row['Close']:.2f}" for idx, row in df_past.tail(10).iterrows()])
            current_p = float(df_past['Close'].iloc[-1])
            
            # --- 2. プロンプト生成とJSON受け取り ---
            json_prompt = f"""あなたはプロのFXトレーダーです。
            以下の過去のチャート履歴(1H足)から現在の相場環境を分析し、
            「買い」か「売り」と、最適なEntry・TP・SLの価格を出力してください。
            現在価格：{current_p:.3f}円
            
            【直近10時間の中期トレンド】
            {past_10_str}
            
            出力フォーマット:
            {{
                "side": "buy" または "sell",
                "entry": 数値,
                "tp": 数値,
                "sl": 数値
            }}
            """
            
            json_res = model.generate_content(
                json_prompt,
                generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
            )
            strategy = json.loads(json_res.text)
            
            st.success("AIの戦略生成が完了しました！")
            st.json(strategy)
            
        except Exception as e:
            st.error(f"シミュレーション準備中にエラーが発生しました: {e}")
            st.stop()
            
    with st.spinner("生成された戦略で未来のチャート推移と照合しています..."):
        try:
            # --- 3. その後の未来データ（1分足）を取得して検証 ---
            # days_agoが古いと1m足が取れないため今回は5m足を保険で利用する。yfinanceの1mは直近7日のみ。
            future_start = end_date
            future_end = future_start + timedelta(days=1)
            interval = "1m" if days_ago <= 5 else "5m"
            df_future = yf.download(ticker, start=future_start.strftime('%Y-%m-%d'), end=future_end.strftime('%Y-%m-%d'), interval=interval, progress=False)
            
            if isinstance(df_future.columns, pd.MultiIndex):
                df_future.columns = [col[0] for col in df_future.columns]
                
            if df_future.empty:
                st.warning("未来のデータ照合ができませんでした。（土日の可能性があります）")
                st.stop()
                
            st.subheader(f"📊 その後の24時間 ({future_start.strftime('%m/%d')}～) の検証結果")
            
            status = "waiting_entry"
            result = "エントリー到達せず"
            entry_p = strategy['entry']
            tp_p = strategy['tp']
            sl_p = strategy['sl']
            side = strategy['side']
            
            pnl = 0
            
            for idx, row in df_future.iterrows():
                high, low, close = float(row['High']), float(row['Low']), float(row['Close'])
                
                # エントリー判定
                if status == "waiting_entry":
                    if (side == "buy" and low <= entry_p) or (side == "sell" and high >= entry_p):
                        status = "holding"
                        st.info(f"[{idx.strftime('%H:%M')}] エントリー成功 ({entry_p}円)")
                
                # 決済判定
                elif status == "holding":
                    is_tp = False
                    is_sl = False
                    
                    if side == "buy":
                        if high >= tp_p: is_tp = True
                        if low <= sl_p: is_sl = True
                    elif side == "sell":
                        if low <= tp_p: is_tp = True
                        if high >= sl_p: is_sl = True
                        
                    if is_tp and is_sl:
                        # どっちも触れた場合は保守的に負けとする
                        result = "損切り (ボラティリティ過大)"
                        pnl = -abs(entry_p - sl_p)
                        st.error(f"[{idx.strftime('%H:%M')}] 損切り到達: {sl_p}円")
                        break
                    elif is_tp:
                        result = "利確 (勝ち)"
                        pnl = abs(tp_p - entry_p)
                        st.success(f"[{idx.strftime('%H:%M')}] 🎉 利確到達: {tp_p}円")
                        break
                    elif is_sl:
                        result = "損切り (負け)"
                        pnl = -abs(entry_p - sl_p)
                        st.error(f"[{idx.strftime('%H:%M')}] 😢 損切り到達: {sl_p}円")
                        break
            
            if status == "holding" and result == "エントリー到達せず":
                result = "手仕舞い（時間切れ）"
                st.warning("24時間経過時点で決済到達せず")
                
            st.metric("シミュレーション最終結果", result)
            
        except Exception as e:
            st.error(f"シミュレーション実行中にエラーが発生しました: {e}")
