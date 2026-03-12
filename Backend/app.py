from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts
import akshare as ak

app = FastAPI(title="A股买卖点助手 - Tushare版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()


STOCK_NAME_FILE = os.path.join(os.path.dirname(__file__), "stock_names.json")

def load_stock_names():
    try:
        with open(STOCK_NAME_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

LOCAL_STOCK_NAMES = load_stock_names()

def get_stock_name_local(ts_code: str):
    return LOCAL_STOCK_NAMES.get(ts_code)


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

def infer_benchmark(symbol: str):
    s = str(symbol).strip()
    if s.startswith(("688", "689")):
        return {"name": "科创50", "ts_code": "000688.SH"}
    if s.startswith("300"):
        return {"name": "创业板指", "ts_code": "399006.SZ"}
    if s.startswith(("600", "601", "603", "605", "900")):
        return {"name": "上证综指", "ts_code": "000001.SH"}
    return {"name": "深证成指", "ts_code": "399001.SZ"}

def safe_text(s):
    if s is None:
        return None
    return str(s)

def get_stock_name(pro, ts_code: str):
    try:
        df = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
        if df is not None and not df.empty:
            return safe_text(df.iloc[0].get("name"))
    except Exception:
        pass
    return None

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


def calc_kdj(df: pd.DataFrame, n: int = 9):
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, pd.NA) * 100
    rsv = rsv.fillna(50)

    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j

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

    kdj_k, kdj_d, kdj_j = calc_kdj(df)
    df["kdj_k"] = kdj_k
    df["kdj_d"] = kdj_d
    df["kdj_j"] = kdj_j

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
        "kdj": 0,
        "volume_price": 0,
        "breakout_20d": 0,
        "daily_strength": 0,
        "relative_strength": 0,
    }

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


    if pd.notna(last["kdj_k"]) and pd.notna(last["kdj_d"]) and pd.notna(prev["kdj_k"]) and pd.notna(prev["kdj_d"]):
        if last["kdj_k"] > last["kdj_d"] and prev["kdj_k"] <= prev["kdj_d"]:
            component_scores["kdj"] = 5
            reasons.append("KDJ 金叉")
        elif last["kdj_k"] < last["kdj_d"] and prev["kdj_k"] >= prev["kdj_d"]:
            component_scores["kdj"] = -5
            reasons.append("KDJ 死叉")
        elif last["kdj_k"] > last["kdj_d"]:
            component_scores["kdj"] = 2
            reasons.append("KDJ 多头")
        elif last["kdj_k"] < last["kdj_d"]:
            component_scores["kdj"] = -2
            reasons.append("KDJ 空头")

        if last["kdj_k"] < 20 and last["kdj_d"] < 20 and last["kdj_k"] > last["kdj_d"]:
            component_scores["kdj"] += 2
            reasons.append("KDJ 低位拐头")
        elif last["kdj_k"] > 80 and last["kdj_d"] > 80 and last["kdj_k"] < last["kdj_d"]:
            component_scores["kdj"] -= 2
            reasons.append("KDJ 高位转弱")

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

    if pd.notna(high_20) and pd.notna(last["close"]) and last["close"] > high_20:
        component_scores["breakout_20d"] = 8
        reasons.append("收盘价突破近 20 日高点")
    elif pd.notna(low_20) and pd.notna(last["close"]) and last["close"] < low_20:
        component_scores["breakout_20d"] = -8
        reasons.append("收盘价跌破近 20 日低点")

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
        "kdj_k": round_or_none(last["kdj_k"]),
        "kdj_d": round_or_none(last["kdj_d"]),
        "kdj_j": round_or_none(last["kdj_j"]),
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

def get_ak_index_snapshot():
    return get_index_snapshot_multi()

def pick_index_row(df: pd.DataFrame, ts_code: str):
    if df is None or df.empty:
        return None

    code_map = {
        "000001.SH": ["000001", "sh000001", "上证指数", "上证综指"],
        "399001.SZ": ["399001", "sz399001", "深证成指"],
        "399006.SZ": ["399006", "sz399006", "创业板指"],
        "000688.SH": ["000688", "sh000688", "科创50"],
    }

    keys = code_map.get(ts_code, [])
    if not keys:
        return None

    work = df.copy()
    if "代码" in work.columns:
        work["代码"] = work["代码"].astype(str)
    if "名称" in work.columns:
        work["名称"] = work["名称"].astype(str)
    if "原始代码" in work.columns:
        work["原始代码"] = work["原始代码"].astype(str)

    for k in keys:
        cond = None
        if "代码" in work.columns:
            cond = (work["代码"] == k) if cond is None else (cond | (work["代码"] == k))
        if "原始代码" in work.columns:
            cond = (work["原始代码"] == k) if cond is None else (cond | (work["原始代码"] == k))
        if "名称" in work.columns:
            cond = (work["名称"].str.contains(k, na=False)) if cond is None else (cond | work["名称"].str.contains(k, na=False))

        if cond is not None:
            row = work[cond]
            if not row.empty:
                return row.iloc[0]

    return None
@app.get("/")
def root():
    return {"message": "a-share backend with stock name and index fallback"}

@app.get("/history")
def get_history(symbol: str = Query(..., description="A股代码，如 600519 或 000001.SZ")):
    try:
        pro = get_pro()
        ts_code = to_ts_code(symbol)

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=260)).strftime("%Y%m%d")

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
        stock_name = get_stock_name_local(ts_code) or get_stock_name(pro, ts_code)

        benchmark_info = infer_benchmark(symbol)

        benchmark = {
            "name": benchmark_info["name"],
            "ts_code": benchmark_info["ts_code"],
            "available": False,
            "error": None,
        }

        market_mood = {
            "score": 0,
            "label": "中性",
            "indices": [],
            "available": False,
            "error": None,
        }

        try:
            idx_spot_df = get_ak_index_snapshot()

            row = pick_index_row(idx_spot_df, benchmark_info["ts_code"])
            if row is not None:
                benchmark = {
                    "name": benchmark_info["name"],
                    "ts_code": benchmark_info["ts_code"],
                    "trade_date": None,
                    "close": round_or_none(row.get("最新价")),
                    "pct_chg": round_or_none(row.get("涨跌幅")),
                    "available": True,
                    "error": None,
                }

            market_indices = [
                {"name": "上证综指", "ts_code": "000001.SH"},
                {"name": "深证成指", "ts_code": "399001.SZ"},
                {"name": "创业板指", "ts_code": "399006.SZ"},
                {"name": "科创50", "ts_code": "000688.SH"},
            ]

            market_parts = []
            mood_scores = []

            for idx in market_indices:
                row = pick_index_row(idx_spot_df, idx["ts_code"])
                if row is None:
                    continue

                pct_chg = round_or_none(row.get("涨跌幅"))
                latest = round_or_none(row.get("最新价"))

                mood_score = 0
                if pct_chg is not None:
                    if pct_chg > 2:
                        mood_score = 8
                    elif pct_chg > 0:
                        mood_score = 4
                    elif pct_chg < -2:
                        mood_score = -8
                    elif pct_chg < 0:
                        mood_score = -4

                part = {
                    "name": idx["name"],
                    "ts_code": idx["ts_code"],
                    "trade_date": None,
                    "close": latest,
                    "pct_chg": pct_chg,
                    "mood_score": mood_score,
                }
                market_parts.append(part)
                mood_scores.append(mood_score)

            market_mood_score = round(sum(mood_scores) / len(mood_scores)) if mood_scores else 0
            market_mood_score = clamp_score(market_mood_score)

            if market_mood_score >= 6:
                market_mood_label = "偏热"
            elif market_mood_score >= 2:
                market_mood_label = "偏暖"
            elif market_mood_score <= -6:
                market_mood_label = "偏冷"
            elif market_mood_score <= -2:
                market_mood_label = "偏弱"
            else:
                market_mood_label = "中性"

            market_mood = {
                "score": market_mood_score,
                "label": market_mood_label,
                "indices": market_parts,
                "available": True if market_parts else False,
                "error": None if market_parts else "未获取到指数数据",
            }

        except Exception:
            benchmark["error"] = "指数接口不可用"
            market_mood["error"] = "指数接口不可用"

        bench_hist_df = get_index_history_multi(
            benchmark_info["ts_code"],
            start_date,
            end_date
        )

        relative_strength = calc_relative_strength(
            hist_df,
            bench_hist_df,
            benchmark_info["name"]
        )

        market_sentiment = get_market_sentiment()

        return {
            "symbol": symbol,
            "name": stock_name,
            "ts_code": ts_code,
            "history": out_df.to_dict(orient="records"),
            "signal": signal,
            "benchmark": benchmark,
            "market_mood": market_mood,
            "relative_strength": relative_strength,
            "market_sentiment": market_sentiment,
        }
    except Exception as e:
        return {
            "error": "获取历史行情失败",
            "detail": safe_text(e)
        }

def get_index_snapshot_em():
    try:
        df = ak.stock_zh_index_spot_em(symbol="沪深重要指数")
        if df is not None and not df.empty:
            df = df.copy()
            if "代码" in df.columns:
                df["代码"] = df["代码"].astype(str)
            if "名称" in df.columns:
                df["名称"] = df["名称"].astype(str)
            return df
    except Exception:
        pass
    return None

def get_index_snapshot_sina():
    try:
        df = ak.stock_zh_index_spot_sina()
        if df is not None and not df.empty:
            df = df.copy()
            if "代码" in df.columns:
                df["原始代码"] = df["代码"].astype(str)
                df["代码"] = (
                    df["原始代码"]
                    .str.replace("sh", "", regex=False)
                    .str.replace("sz", "", regex=False)
                )
            if "名称" in df.columns:
                df["名称"] = df["名称"].astype(str)
            return df
    except Exception:
        pass
    return None

def get_index_snapshot_multi():
    for fn in [get_index_snapshot_em, get_index_snapshot_sina]:
        df = fn()
        if df is not None and not df.empty:
            return df
    return None

def get_index_history_ak_hist(ts_code: str, start_date: str, end_date: str):
    try:
        symbol_map = {
            "000001.SH": "000001",
            "399001.SZ": "399001",
            "399006.SZ": "399006",
            "000688.SH": "000688",
        }
        symbol = symbol_map.get(ts_code)
        if not symbol:
            return None

        df = ak.index_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date
        )
        if df is None or df.empty:
            return None

        rename_map = {
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "涨跌幅": "pct_chg",
        }
        df = df.rename(columns=rename_map).copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
        for col in ["open", "close", "high", "low", "pct_chg"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.sort_values("trade_date").reset_index(drop=True)
    except Exception:
        return None

def get_index_history_daily_em(ts_code: str, start_date: str, end_date: str):
    try:
        symbol_map = {
            "000001.SH": "sh000001",
            "399001.SZ": "sz399001",
            "399006.SZ": "sz399006",
            "000688.SH": "sh000688",
        }
        symbol = symbol_map.get(ts_code)
        if not symbol:
            return None

        df = ak.stock_zh_index_daily_em(symbol=symbol)
        if df is None or df.empty:
            return None

        df = df.copy()
        if "date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        for col in ["open", "close", "high", "low"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100

        df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]
        return df.sort_values("trade_date").reset_index(drop=True)
    except Exception:
        return None

def get_index_history_multi(ts_code: str, start_date: str, end_date: str):
    for fn in [get_index_history_ak_hist, get_index_history_daily_em]:
        df = fn(ts_code, start_date, end_date)
        if df is not None and not df.empty:
            return df
    return None


def calc_relative_strength(stock_df: pd.DataFrame, bench_df: pd.DataFrame, benchmark_name: str):
    try:
        if stock_df is None or stock_df.empty or bench_df is None or bench_df.empty:
            return {
                "available": False,
                "benchmark_name": benchmark_name,
                "rs_day": None,
                "rs_5": None,
                "rs_10": None,
                "rs_20": None,
                "score": 0,
                "error": "对应大盘历史数据暂不可用"
            }

        s = stock_df.copy()[["trade_date", "close", "pct_chg"]]
        b = bench_df.copy()[["trade_date", "close", "pct_chg"]]

        s["close"] = pd.to_numeric(s["close"], errors="coerce")
        b["close"] = pd.to_numeric(b["close"], errors="coerce")
        s["pct_chg"] = pd.to_numeric(s["pct_chg"], errors="coerce")
        b["pct_chg"] = pd.to_numeric(b["pct_chg"], errors="coerce")

        merged = pd.merge(s, b, on="trade_date", suffixes=("_stock", "_bench"))
        merged = merged.sort_values("trade_date").reset_index(drop=True)

        if len(merged) < 21:
            return {
                "available": False,
                "benchmark_name": benchmark_name,
                "rs_day": None,
                "rs_5": None,
                "rs_10": None,
                "rs_20": None,
                "score": 0,
                "error": "对应大盘历史数据不足"
            }

        last = merged.iloc[-1]

        def period_return(series, n):
            if len(series) < n + 1:
                return None
            start = series.iloc[-(n + 1)]
            end = series.iloc[-1]
            if pd.isna(start) or pd.isna(end) or start == 0:
                return None
            return (end / start - 1) * 100

        stock_close = merged["close_stock"]
        bench_close = merged["close_bench"]

        rs_day = None
        if pd.notna(last["pct_chg_stock"]) and pd.notna(last["pct_chg_bench"]):
            rs_day = float(last["pct_chg_stock"]) - float(last["pct_chg_bench"])

        stock_5 = period_return(stock_close, 5)
        bench_5 = period_return(bench_close, 5)
        rs_5 = (stock_5 - bench_5) if stock_5 is not None and bench_5 is not None else None

        stock_10 = period_return(stock_close, 10)
        bench_10 = period_return(bench_close, 10)
        rs_10 = (stock_10 - bench_10) if stock_10 is not None and bench_10 is not None else None

        stock_20 = period_return(stock_close, 20)
        bench_20 = period_return(bench_close, 20)
        rs_20 = (stock_20 - bench_20) if stock_20 is not None and bench_20 is not None else None

        weighted = 0.0
        if rs_5 is not None:
            weighted += 0.5 * rs_5
        if rs_10 is not None:
            weighted += 0.3 * rs_10
        if rs_20 is not None:
            weighted += 0.2 * rs_20

        if weighted >= 5:
            score = 8
        elif weighted >= 2:
            score = 5
        elif weighted > 0:
            score = 2
        elif weighted <= -5:
            score = -8
        elif weighted <= -2:
            score = -5
        elif weighted < 0:
            score = -2
        else:
            score = 0

        return {
            "available": True,
            "benchmark_name": benchmark_name,
            "rs_day": round_or_none(rs_day),
            "rs_5": round_or_none(rs_5),
            "rs_10": round_or_none(rs_10),
            "rs_20": round_or_none(rs_20),
            "score": score,
            "error": None
        }
    except Exception as e:
        return {
            "available": False,
            "benchmark_name": benchmark_name,
            "rs_day": None,
            "rs_5": None,
            "rs_10": None,
            "rs_20": None,
            "score": 0,
            "error": safe_text(e)
        }


def get_market_sentiment():
    try:
        idx_df = get_index_snapshot_multi()

        index_targets = [
            {"name": "上证综指", "ts_code": "000001.SH"},
            {"name": "深证成指", "ts_code": "399001.SZ"},
            {"name": "创业板指", "ts_code": "399006.SZ"},
            {"name": "科创50", "ts_code": "000688.SH"},
        ]

        scores = []

        for idx in index_targets:
            row = pick_index_row(idx_df, idx["ts_code"])
            if row is None:
                continue

            pct = row.get("涨跌幅")
            if pct is None:
                continue

            pct = float(pct)

            if pct > 2:
                scores.append(8)
            elif pct > 0:
                scores.append(4)
            elif pct < -2:
                scores.append(-8)
            elif pct < 0:
                scores.append(-4)
            else:
                scores.append(0)

        score = int(sum(scores) / len(scores)) if scores else 0

        return {
            "available": True,
            "score": score,
            "label": calc_sentiment_label(score),
            "error": None,
        }

    except Exception as e:
        return {
            "available": False,
            "score": 0,
            "label": "中性",
            "error": safe_text(e),
        }


def calc_sentiment_label(score: int):
    if score >= 6:
        return "偏热"
    if score >= 2:
        return "偏暖"
    if score <= -6:
        return "偏冷"
    if score <= -2:
        return "偏弱"
    return "中性"

