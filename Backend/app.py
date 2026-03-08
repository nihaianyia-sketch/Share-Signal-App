from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import os
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts

app = FastAPI(title="A股买卖点助手 - Tushare版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()

def get_pro():
    if not TOKEN:
        raise RuntimeError("缺少 TUSHARE_TOKEN 环境变量")
    ts.set_token(TOKEN)
    return ts.pro_api()

def to_ts_code(symbol: str) -> str:
    s = str(symbol).strip().upper()
    if "." in s:
        return s
    if s.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return f"{s}.SH"
    return f"{s}.SZ"

def safe_text(s):
    if s is None:
        return None
    return str(s)

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calc_macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

def round_or_none(x, n=2):
    if pd.isna(x):
        return None
    return round(float(x), n)

def clamp_score(x, lo=-10, hi=10):
    return max(lo, min(hi, int(x)))

def calc_signal(df: pd.DataFrame):
    if df is None or len(df) < 35:
        return {
            "label": "数据不足",
            "score": 0,
            "reasons": ["历史数据不足，无法计算完整技术指标"],
            "indicators": {},
            "component_scores": {},
        }

    df = df.copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    df["vol"] = pd.to_numeric(df["vol"], errors="coerce")
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["vol5"] = df["vol"].rolling(5).mean()
    df["rsi14"] = calc_rsi(df["close"], 14)

    macd, macd_signal, macd_hist = calc_macd(df["close"])
    df["macd"] = macd
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    last = df.iloc[-1]
    prev = df.iloc[-2]

    prev_20 = df.iloc[-21:-1] if len(df) >= 21 else df.iloc[:-1]
    high_20 = prev_20["high"].max() if len(prev_20) else pd.NA
    low_20 = prev_20["low"].min() if len(prev_20) else pd.NA

    vol_ratio_5 = (
        last["vol"] / last["vol5"]
        if pd.notna(last["vol"]) and pd.notna(last["vol5"]) and last["vol5"] != 0
        else pd.NA
    )

    reasons = []
    component_scores = {
        "trend_ma": 0,
        "price_vs_ma5": 0,
        "rsi": 0,
        "macd": 0,
        "volume_price": 0,
        "breakout_20d": 0,
        "daily_strength": 0,
    }

    # 1) 均线结构
    if pd.notna(last["ma5"]) and pd.notna(last["ma10"]):
        if last["ma5"] > last["ma10"]:
            component_scores["trend_ma"] += 3
            reasons.append("MA5 在 MA10 上方")
        elif last["ma5"] < last["ma10"]:
            component_scores["trend_ma"] -= 3
            reasons.append("MA5 在 MA10 下方")

    if pd.notna(last["ma10"]) and pd.notna(last["ma20"]):
        if last["ma10"] > last["ma20"]:
            component_scores["trend_ma"] += 3
            reasons.append("MA10 在 MA20 上方")
        elif last["ma10"] < last["ma20"]:
            component_scores["trend_ma"] -= 3
            reasons.append("MA10 在 MA20 下方")

    # 2) 收盘相对 MA5
    if pd.notna(last["close"]) and pd.notna(last["ma5"]):
        diff_pct = (last["close"] - last["ma5"]) / last["ma5"] * 100
        if diff_pct > 1.5:
            component_scores["price_vs_ma5"] = 5
            reasons.append("收盘价明显站上 MA5")
        elif diff_pct > 0:
            component_scores["price_vs_ma5"] = 2
            reasons.append("收盘价站上 MA5")
        elif diff_pct < -1.5:
            component_scores["price_vs_ma5"] = -5
            reasons.append("收盘价明显跌破 MA5")
        else:
            component_scores["price_vs_ma5"] = -2
            reasons.append("收盘价跌破 MA5")

    # 3) RSI
    if pd.notna(last["rsi14"]):
        rsi = float(last["rsi14"])
        if rsi < 20:
            component_scores["rsi"] = 7
            reasons.append("RSI14 很低，偏超卖")
        elif rsi < 30:
            component_scores["rsi"] = 4
            reasons.append("RSI14 低于 30，偏超卖")
        elif rsi > 80:
            component_scores["rsi"] = -7
            reasons.append("RSI14 很高，偏超买")
        elif rsi > 70:
            component_scores["rsi"] = -4
            reasons.append("RSI14 高于 70，偏超买")
        else:
            component_scores["rsi"] = 0
            reasons.append("RSI14 处于中性区间")

    # 4) MACD
    if pd.notna(last["macd"]) and pd.notna(last["macd_signal"]):
        if last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
            component_scores["macd"] = 7
            reasons.append("MACD 金叉")
        elif last["macd"] < last["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
            component_scores["macd"] = -7
            reasons.append("MACD 死叉")
        elif last["macd"] > last["macd_signal"]:
            component_scores["macd"] = 3
            reasons.append("MACD 位于信号线之上")
        elif last["macd"] < last["macd_signal"]:
            component_scores["macd"] = -3
            reasons.append("MACD 位于信号线之下")

    # 5) 量价
    if pd.notna(vol_ratio_5) and pd.notna(last["pct_chg"]):
        if vol_ratio_5 > 1.8 and last["pct_chg"] > 0:
            component_scores["volume_price"] = 8
            reasons.append("强放量上涨")
        elif vol_ratio_5 > 1.5 and last["pct_chg"] > 0:
            component_scores["volume_price"] = 5
            reasons.append("放量上涨")
        elif vol_ratio_5 > 1.8 and last["pct_chg"] < 0:
            component_scores["volume_price"] = -8
            reasons.append("强放量下跌")
        elif vol_ratio_5 > 1.5 and last["pct_chg"] < 0:
            component_scores["volume_price"] = -5
            reasons.append("放量下跌")
        elif vol_ratio_5 < 0.8:
            component_scores["volume_price"] = -1
            reasons.append("成交量低于 5 日均量")

    # 6) 20日突破
    if pd.notna(high_20) and pd.notna(last["close"]) and last["close"] > high_20:
        component_scores["breakout_20d"] = 8
        reasons.append("收盘价突破近 20 日高点")
    elif pd.notna(low_20) and pd.notna(last["close"]) and last["close"] < low_20:
        component_scores["breakout_20d"] = -8
        reasons.append("收盘价跌破近 20 日低点")

    # 7) 当日强弱
    if pd.notna(last["close"]) and pd.notna(prev["close"]):
        if last["close"] > prev["close"]:
            component_scores["daily_strength"] = 2
            reasons.append("最新收盘高于前一日")
        elif last["close"] < prev["close"]:
            component_scores["daily_strength"] = -2
            reasons.append("最新收盘低于前一日")

    component_scores = {k: clamp_score(v) for k, v in component_scores.items()}
    score = int(sum(component_scores.values()))

    if score >= 12:
        label = "偏多"
    elif score >= 4:
        label = "轻度偏多"
    elif score <= -12:
        label = "偏空"
    elif score <= -4:
        label = "轻度偏空"
    else:
        label = "观望"

    indicators = {
        "close": round_or_none(last["close"]),
        "ma5": round_or_none(last["ma5"]),
        "ma10": round_or_none(last["ma10"]),
        "ma20": round_or_none(last["ma20"]),
        "rsi14": round_or_none(last["rsi14"]),
        "vol_ratio_5": round_or_none(vol_ratio_5),
        "macd": round_or_none(last["macd"]),
        "macd_signal": round_or_none(last["macd_signal"]),
        "macd_hist": round_or_none(last["macd_hist"]),
        "high_20": round_or_none(high_20),
        "low_20": round_or_none(low_20),
    }

    return {
        "label": label,
        "score": score,
        "reasons": reasons,
        "indicators": indicators,
        "component_scores": component_scores,
    }

@app.get("/")
def root():
    return {"message": "a-share backend with advanced technical analysis"}

@app.get("/history")
def get_history(symbol: str = Query(..., description="A股代码，如 600519 或 000001.SZ")):
    try:
        pro = get_pro()
        ts_code = to_ts_code(symbol)

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=220)).strftime("%Y%m%d")

        hist_df = pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )

        if hist_df is None or hist_df.empty:
            return {
                "error": f"未获取到 {ts_code} 的历史行情",
                "ts_code": ts_code
            }

        hist_df = hist_df.sort_values("trade_date").reset_index(drop=True)
        signal = calc_signal(hist_df)
        out_df = hist_df.tail(80).reset_index(drop=True)

        return {
            "symbol": symbol,
            "ts_code": ts_code,
            "history": out_df.to_dict(orient="records"),
            "signal": signal,
        }
    except Exception as e:
        return {
            "error": "获取历史行情失败",
            "detail": safe_text(e)
        }
