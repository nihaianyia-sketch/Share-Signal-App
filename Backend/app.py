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

    atr14 = calc_atr(df, 14)
    df["atr14"] = atr14

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

    atr_ratio = (
        last["atr14"] / last["close"]
        if pd.notna(last["atr14"]) and pd.notna(last["close"]) and last["close"] != 0
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
        "volatility": 0,
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

    if pd.notna(atr_ratio):
        if atr_ratio > 0.04:
            component_scores["volatility"] = 3
            reasons.append("ATR波动率较高")
        elif atr_ratio < 0.015:
            component_scores["volatility"] = -2
            reasons.append("ATR波动率较低")

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
        "atr14": round_or_none(last["atr14"]),
        "atr_ratio": round_or_none(atr_ratio, 4),
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

        if (
            (not relative_strength.get("available"))
            and benchmark.get("pct_chg") is not None
            and hist_df is not None
            and len(hist_df) >= 2
        ):
            try:
                stock_pct = float(hist_df["pct_chg"].iloc[-1])
                bench_pct = float(benchmark["pct_chg"])
                rs_day = round(stock_pct - bench_pct, 2)
                relative_strength = {
                    "available": True,
                    "benchmark_name": benchmark_info["name"],
                    "rs_day": rs_day,
                    "rs_5": None,
                    "rs_10": None,
                    "rs_20": None,
                    "score": int(round(rs_day / 2)),
                    "error": "部分周期数据不足"
                }
            except Exception:
                pass

        market_sentiment = get_market_sentiment()
        capital_flow = get_capital_flow(symbol)
        sector_strength = get_sector_strength(symbol)
        status_judgement = calc_status_judgement(hist_df, signal, relative_strength)
        trading_decision = calc_trading_decision(
            signal,
            relative_strength,
            market_sentiment,
            status_judgement,
            capital_flow
        )

        return {
            "symbol": symbol,
            "name": stock_name,
            "ts_code": ts_code,
            "history": out_df.to_dict(orient="records"),
            "signal": signal,
            "benchmark": benchmark,
            "market_mood": market_mood,
            "relative_strength": relative_strength,
            
            "sector_strength": sector_strength,
            "market_sentiment": market_sentiment,
            "capital_flow": capital_flow,

            "status_judgement": status_judgement,
            "trading_decision": trading_decision,
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

import time
import pandas as pd

import os
import time
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

import os
import time
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")




def get_index_history_multi(ts_code: str, start_date: str, end_date: str):
    symbol_map_hist = {
        "000001.SH": "000001",
        "399001.SZ": "399001",
        "399006.SZ": "399006",
        "000688.SH": "000688",
    }

    symbol_map_daily = {
        "000001.SH": "sh000001",
        "399001.SZ": "sz399001",
        "399006.SZ": "sz399006",
        "000688.SH": "sh000688",
    }

    symbol_map_yf = {
        "000001.SH": "000001.SS",
        "399001.SZ": "399001.SZ",
        "399006.SZ": "399006.SZ",
        "000688.SH": "000688.SS",
    }

    cache_dir = os.path.join(os.path.dirname(__file__), "cache")
    cache_file = os.path.join(cache_dir, f"index_{ts_code.replace('.', '_')}.csv")

    def normalize_df(df):
        if df is None or df.empty:
            return None

        df = df.copy()

        rename_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=rename_map)

        if "trade_date" not in df.columns:
            if "date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
            elif df.index.name is not None or isinstance(df.index, pd.DatetimeIndex):
                df["trade_date"] = pd.to_datetime(df.index).strftime("%Y%m%d")
            else:
                return None

        for col in ["open", "close", "high", "low", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["trade_date"] = df["trade_date"].astype(str)
        df = df.sort_values("trade_date").reset_index(drop=True)

        if "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
        else:
            df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")

        df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]

        if df.empty:
            return None

        keep_cols = [c for c in ["trade_date", "open", "close", "high", "low", "volume", "amount", "pct_chg"] if c in df.columns]
        return df[keep_cols].reset_index(drop=True)

    # source 1
    symbol1 = symbol_map_hist.get(ts_code)
    if symbol1 is not None:
        for attempt in range(2):
            try:
                import akshare as ak
                df = ak.index_zh_a_hist(symbol=symbol1, period="daily")
                df = normalize_df(df)
                if df is not None:
                    os.makedirs(cache_dir, exist_ok=True)
                    df.to_csv(cache_file, index=False)
                    return df
            except Exception as e:
                if attempt == 1:
                    print("source1 failed:", e)
                time.sleep(1)

    # source 2
    symbol2 = symbol_map_daily.get(ts_code)
    if symbol2 is not None:
        for attempt in range(2):
            try:
                import akshare as ak
                df = ak.stock_zh_index_daily_em(symbol=symbol2)
                df = normalize_df(df)
                if df is not None:
                    os.makedirs(cache_dir, exist_ok=True)
                    df.to_csv(cache_file, index=False)
                    return df
            except Exception as e:
                if attempt == 1:
                    print("source2 failed:", e)
                time.sleep(1)

    # source 3: yahoo finance
    symbol3 = symbol_map_yf.get(ts_code)
    if symbol3 is not None:
        for attempt in range(2):
            try:
                import yfinance as yf

                df = yf.download(
                    symbol3,
                    start=pd.to_datetime(start_date).strftime("%Y-%m-%d"),
                    end=(pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    auto_adjust=False,
                    progress=False,
                    group_by="column",
                )

                if df is None or df.empty:
                    raise Exception("empty dataframe from yfinance")

                # 处理可能的 MultiIndex columns
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

                df = df.rename(columns={
                    "Open": "open",
                    "Close": "close",
                    "High": "high",
                    "Low": "low",
                    "Volume": "volume",
                }).copy()

                needed = ["open", "close", "high", "low", "volume"]
                for col in needed:
                    if col not in df.columns:
                        raise Exception(f"missing {col} column from yfinance")

                df["amount"] = pd.NA
                df["trade_date"] = pd.to_datetime(df.index).strftime("%Y%m%d")

                for col in ["open", "close", "high", "low", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                df = df.sort_values("trade_date").reset_index(drop=True)
                df["pct_chg"] = df["close"].pct_change() * 100
                df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]

                keep_cols = ["trade_date", "open", "close", "high", "low", "volume", "amount", "pct_chg"]
                df = df[keep_cols]

                if df is not None and not df.empty:
                    os.makedirs(cache_dir, exist_ok=True)
                    df.to_csv(cache_file, index=False)
                    return df.reset_index(drop=True)

            except Exception as e:
                if attempt == 1:
                    print("source3 failed:", e)
                time.sleep(1)

    # cache
    if os.path.exists(cache_file):
        try:
            df = pd.read_csv(cache_file)
            df = normalize_df(df)
            if df is not None:
                print("using cached index history", ts_code)
                return df
        except Exception as e:
            print("cache failed:", e)

    return None



def calc_relative_strength(stock_df, bench_df, benchmark_name):
    try:
        import pandas as pd

        if stock_df is None or bench_df is None:
            return {
                "available": False,
                "benchmark_name": benchmark_name,
                "rs_day": None,
                "rs_5": None,
                "rs_10": None,
                "rs_20": None,
                "score": 0,
                "error": "缺少股票或指数数据"
            }

        df = pd.merge(
            stock_df[["trade_date", "close"]],
            bench_df[["trade_date", "close"]],
            on="trade_date",
            suffixes=("_stock", "_bench")
        ).sort_values("trade_date")

        if len(df) < 2:
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

        df["ret_stock"] = df["close_stock"].pct_change()
        df["ret_bench"] = df["close_bench"].pct_change()
        df["rs"] = (df["ret_stock"] - df["ret_bench"]) * 100

        rs_day = df["rs"].iloc[-1]

        def window_rs(n):
            if len(df) >= n + 1:
                s = df["close_stock"].iloc[-1] / df["close_stock"].iloc[-(n + 1)] - 1
                b = df["close_bench"].iloc[-1] / df["close_bench"].iloc[-(n + 1)] - 1
                return (s - b) * 100
            return None

        rs_5 = window_rs(5)
        rs_10 = window_rs(10)
        rs_20 = window_rs(20)

        values = []
        weights = []

        if rs_5 is not None:
            values.append(rs_5); weights.append(0.5)
        if rs_10 is not None:
            values.append(rs_10); weights.append(0.3)
        if rs_20 is not None:
            values.append(rs_20); weights.append(0.2)

        if values:
            score_raw = sum(v * w for v, w in zip(values, weights)) / sum(weights)
        else:
            score_raw = rs_day if rs_day is not None else 0

        score = int(round(score_raw / 2)) if score_raw is not None else 0

        error = None
        if rs_5 is None or rs_10 is None or rs_20 is None:
            error = "部分周期数据不足"

        return {
            "available": True,
            "benchmark_name": benchmark_name,
            "rs_day": round(float(rs_day), 2) if rs_day is not None else None,
            "rs_5": round(float(rs_5), 2) if rs_5 is not None else None,
            "rs_10": round(float(rs_10), 2) if rs_10 is not None else None,
            "rs_20": round(float(rs_20), 2) if rs_20 is not None else None,
            "score": score,
            "error": error
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

        idx_pct_list = []
        index_parts = []

        for idx in index_targets:
            row = pick_index_row(idx_df, idx["ts_code"])
            if row is None:
                continue

            pct = row.get("涨跌幅")
            if pct is None:
                continue

            idx_pct_list.append(float(pct))

        avg_pct = sum(idx_pct_list) / len(idx_pct_list) if idx_pct_list else 0

        if avg_pct >= 2:
            index_move = 8
        elif avg_pct >= 0.8:
            index_move = 4
        elif avg_pct <= -2:
            index_move = -8
        elif avg_pct <= -0.8:
            index_move = -4
        else:
            index_move = 0

        breadth = get_market_breadth()
        limits = get_limit_stats()

        breadth_score = breadth["score"]
        limit_score = limits["score"]

        weighted_parts = []
        if index_parts is not None:
            weighted_parts.append((index_move, 0.4))
        if breadth.get("up") is not None and breadth.get("down") is not None:
            weighted_parts.append((breadth_score, 0.3))
        if limits.get("limit_up") is not None and limits.get("limit_down") is not None:
            weighted_parts.append((limit_score, 0.3))

        if weighted_parts:
            total_weight = sum(w for _, w in weighted_parts)
            total_score = round(sum(v * w for v, w in weighted_parts) / total_weight)
        else:
            total_score = 0

        return {
            "available": True,
            "score": total_score,
            "label": calc_sentiment_label(total_score),
            "components": {
                "index_move": index_move,
                "breadth": breadth_score,
                "limit_up_down": limit_score
            },
            "stats": {
                "up_count": breadth.get("up"),
                "down_count": breadth.get("down"),
                "limit_up": limits.get("limit_up"),
                "limit_down": limits.get("limit_down"),
                "breadth_error": breadth.get("error"),
                "limit_error": limits.get("error"),
                "breadth_from_cache": breadth.get("from_cache")
            },
            "error": None
        }

    except Exception as e:
        return {
            "available": False,
            "score": 0,
            "label": "中性",
            "error": safe_text(e)
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


def get_market_breadth():
    cache_dir = os.path.join(os.path.dirname(__file__), "cache")
    cache_file = os.path.join(cache_dir, "market_breadth.json")

    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty or "涨跌幅" not in df.columns:
            raise Exception("breadth source empty")

        pct = pd.to_numeric(df["涨跌幅"], errors="coerce")
        up = int((pct > 0).sum())
        down = int((pct < 0).sum())

        total = up + down
        score = clamp_score(round(((up - down) / total) * 10)) if total > 0 else 0

        os.makedirs(cache_dir, exist_ok=True)
        pd.DataFrame([{
            "up": up,
            "down": down,
            "score": score,
        }]).to_json(cache_file, orient="records", force_ascii=False)

        return {
            "score": score,
            "up": up,
            "down": down,
            "error": None,
            "from_cache": False,
        }

    except Exception as e:
        if os.path.exists(cache_file):
            try:
                cached = pd.read_json(cache_file)
                if cached is not None and not cached.empty:
                    row = cached.iloc[-1]
                    return {
                        "score": int(row.get("score", 0)),
                        "up": int(row.get("up")) if pd.notna(row.get("up")) else None,
                        "down": int(row.get("down")) if pd.notna(row.get("down")) else None,
                        "error": f"实时涨跌家数获取失败，当前使用缓存：{safe_text(e)}",
                        "from_cache": True,
                    }
            except Exception:
                pass

        return {
            "score": 0,
            "up": None,
            "down": None,
            "error": safe_text(e),
            "from_cache": False,
        }


def get_limit_stats():
    up = None
    down = None
    up_err = None
    down_err = None

    trade_date = None
    try:
        trade_hist = ak.tool_trade_date_hist_sina()
        if trade_hist is not None and not trade_hist.empty:
            dates = pd.to_datetime(trade_hist["trade_date"])
            dates = dates[dates <= pd.Timestamp.today()]
            if not dates.empty:
                trade_date = dates.iloc[-1].strftime("%Y%m%d")
    except Exception as e:
        down_err = safe_text(e)

    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    try:
        up_df = ak.stock_zt_pool_em(date=trade_date)
        if up_df is not None:
            up = len(up_df)
    except Exception as e:
        up_err = safe_text(e)

    try:
        down_df = ak.stock_zt_pool_dtgc_em(date=trade_date)
        if down_df is not None:
            down = len(down_df)
    except Exception as e:
        down_err = safe_text(e)

    if up is None or down is None:
        return {
            "score": 0,
            "limit_up": up,
            "limit_down": down,
            "error": f"date={trade_date}; up_err={up_err}; down_err={down_err}"
        }

    total = up + down
    if total == 0:
        score = 0
    else:
        score = clamp_score(round((up - down) / total * 10))

    return {
        "score": score,
        "limit_up": up,
        "limit_down": down,
        "error": None
    }


def calc_atr(df: pd.DataFrame, period: int = 14):
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    return atr


def calc_status_judgement(df: pd.DataFrame, signal: dict, relative_strength: dict):
    try:
        last = df.iloc[-1]
        atr_ratio = signal.get("indicators", {}).get("atr_ratio")
        rs_score = relative_strength.get("score", 0) if relative_strength else 0
        rs_day = relative_strength.get("rs_day") if relative_strength else None
        label = "震荡整理"
        reasons = []

        ma5 = signal.get("indicators", {}).get("ma5")
        ma10 = signal.get("indicators", {}).get("ma10")
        ma20 = signal.get("indicators", {}).get("ma20")
        rsi14 = signal.get("indicators", {}).get("rsi14")
        macd = signal.get("indicators", {}).get("macd")
        macd_signal = signal.get("indicators", {}).get("macd_signal")
        kdj_k = signal.get("indicators", {}).get("kdj_k")
        kdj_d = signal.get("indicators", {}).get("kdj_d")
        close = signal.get("indicators", {}).get("close")

        if (
            ma5 is not None and ma10 is not None and ma20 is not None
            and macd is not None and macd_signal is not None
            and close is not None
            and ma5 > ma10 > ma20
            and close > ma5
            and macd > macd_signal
            and rs_score >= 2
        ):
            label = "强势上升"
            reasons = ["均线多头", "MACD偏强", "相对大盘偏强"]

        elif (
            ma5 is not None and ma10 is not None and ma20 is not None
            and macd is not None and macd_signal is not None
            and ma5 < ma10 < ma20
            and macd < macd_signal
            and rs_score <= -2
        ):
            label = "下行趋势"
            reasons = ["均线空头", "MACD偏弱", "相对大盘偏弱"]

        elif (
            rsi14 is not None and kdj_k is not None and kdj_d is not None
            and close is not None and ma5 is not None
            and rsi14 < 35
            and kdj_k > kdj_d
            and close >= ma5
        ):
            label = "超卖反弹观察"
            reasons = ["RSI偏低", "KDJ修复", "价格回到短均线上方"]

        elif (
            close is not None and ma5 is not None
            and kdj_k is not None and kdj_d is not None
            and close > ma5
            and kdj_k > kdj_d
            and (rs_day is not None and rs_day > 0)
        ):
            label = "趋势修复"
            reasons = ["短线站上MA5", "KDJ偏强", "当日跑赢大盘"]

        elif atr_ratio is not None and atr_ratio > 0.04:
            label = "高波动博弈"
            reasons = ["ATR波动率较高", "短线波动明显放大"]

        elif atr_ratio is not None and atr_ratio < 0.015:
            label = "低波整理"
            reasons = ["ATR波动率较低", "市场偏盘整"]

        else:
            reasons = ["趋势与动量信号混合", "暂以整理看待"]

        return {
            "label": label,
            "reasons": reasons,
            "atr_ratio": atr_ratio,
            "rs_score": rs_score,
        }
    except Exception as e:
        return {
            "label": "未知",
            "reasons": [safe_text(e)],
            "atr_ratio": None,
            "rs_score": 0,
        }


def calc_trading_decision(signal: dict, relative_strength: dict, market_sentiment: dict, status_judgement: dict, capital_flow: dict):
    try:
        signal_score = signal.get("score", 0) if signal else 0
        rs_score = relative_strength.get("score", 0) if relative_strength else 0
        market_score = market_sentiment.get("score", 0) if market_sentiment else 0
        status_label = status_judgement.get("label", "") if status_judgement else ""

        indicators = signal.get("indicators", {}) if signal else {}
        rsi14 = indicators.get("rsi14")
        macd = indicators.get("macd")
        macd_signal = indicators.get("macd_signal")
        close = indicators.get("close")
        ma5 = indicators.get("ma5")
        ma10 = indicators.get("ma10")
        ma20 = indicators.get("ma20")
        atr_ratio = indicators.get("atr_ratio")

        reasons = []
        action = "观望等待"
        bias = "中性"
        confidence = 50
        horizon = "短线观察"
        execution_hint = "等待更明确的趋势或动量确认。"
        summary = "信号分化，暂不适合激进参与。"

        composite = 0.5 * signal_score + 0.3 * rs_score + 0.2 * market_score

        capital_score = 0
        if capital_flow and capital_flow.get("available"):
            main_flow = capital_flow.get("main_inflow")
            main_flow_5d = capital_flow.get("main_inflow_5d")

            if main_flow is not None and main_flow_5d is not None:
                if main_flow > 0 and main_flow_5d > 0:
                    capital_score = 3
                    reasons.append("主力资金单日与5日累计均为净流入")
                elif main_flow < 0 and main_flow_5d < 0:
                    capital_score = -3
                    reasons.append("主力资金单日与5日累计均为净流出")
                elif main_flow > 0:
                    capital_score = 1
                    reasons.append("主力资金单日净流入")
                elif main_flow < 0:
                    capital_score = -1
                    reasons.append("主力资金单日净流出")

        composite = composite + 0.2 * capital_score


        if ma5 is not None and ma10 is not None and ma20 is not None:
            if ma5 > ma10 > ma20:
                reasons.append("均线多头排列")
            elif ma5 < ma10 < ma20:
                reasons.append("均线空头排列")

        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                reasons.append("MACD偏强")
            else:
                reasons.append("MACD偏弱")

        if rs_score >= 2:
            reasons.append("相对大盘偏强")
        elif rs_score <= -2:
            reasons.append("相对大盘偏弱")

        if market_score >= 2:
            reasons.append("市场情绪偏暖")
        elif market_score <= -2:
            reasons.append("市场情绪偏弱")

        if status_label:
            reasons.append(f"状态判断：{status_label}")

        # 1) 强趋势多头
        if composite >= 5 and rs_score >= 2 and market_score >= 0 and status_label in ["强势上升", "趋势修复"]:
            action = "趋势做多"
            bias = "偏多"
            confidence = 78
            horizon = "波段"
            execution_hint = "优先等回踩短均线或放量突破时参与，不建议无条件追高。"
            summary = "趋势、相对强弱和市场环境较一致，适合顺势寻找做多机会。"

        # 2) 修复型机会
        elif composite >= 2 and status_label == "趋势修复":
            action = "轻仓试多"
            bias = "谨慎偏多"
            confidence = 66
            horizon = "短线到波段"
            execution_hint = "控制仓位，优先等待确认站稳 MA5/MA10。"
            summary = "存在修复迹象，但中期趋势尚未完全扭转。"

        # 3) 超卖反弹
        elif status_label == "超卖反弹观察" or (rsi14 is not None and rsi14 < 25):
            action = "反弹博弈"
            bias = "短线博弈"
            confidence = 61
            horizon = "短线"
            execution_hint = "更适合短线快进快出，不适合直接当成中线反转。"
            summary = "处于超卖后的修复观察阶段，可关注短线反弹而非趋势反转。"

        # 4) 偏弱但开始修复
        elif composite > -2 and (status_label in ["趋势修复", "震荡整理"] or (ma5 is not None and close is not None and close >= ma5)):
            action = "观察名单"
            bias = "中性偏谨慎"
            confidence = 58
            horizon = "短线观察"
            execution_hint = "先放入观察名单，等放量、站稳均线或相对强弱继续改善。"
            summary = "部分信号改善，但仍缺少足够强的趋势确认。"

        # 5) 明显弱势
        elif composite <= -5 and rs_score <= -2:
            action = "弱势回避"
            bias = "偏空"
            confidence = 80
            horizon = "防守"
            execution_hint = "不宜逆势抄底，优先等待弱势结构改善。"
            summary = "个股偏弱且相对大盘不占优，当前应以回避为主。"

        # 6) 普通谨慎状态
        elif composite <= -2:
            action = "观望等待"
            bias = "中性偏谨慎"
            confidence = 64
            horizon = "短线观察"
            execution_hint = "等待趋势改善、相对强弱转正或市场环境回暖后再看。"
            summary = "整体信号略偏弱，不适合激进参与。"

        # 根据中期均线位置微调
        if close is not None and ma20 is not None and close < ma20:
            confidence = max(35, confidence - 6)

        # 高波动提醒
        if atr_ratio is not None and atr_ratio > 0.04:
            execution_hint += " 当前波动较大，需降低仓位、放宽止损。"

        return {
            "action": action,
            "bias": bias,
            "confidence": int(confidence),
            "horizon": horizon,
            "execution_hint": execution_hint,
            "summary": summary,
            "reasons": reasons[:6],
            "composite_score": round(composite, 2),
        }

    except Exception as e:
        return {
            "action": "未知",
            "bias": "未知",
            "confidence": 0,
            "horizon": "未知",
            "execution_hint": "交易决策生成失败",
            "summary": "交易决策生成失败",
            "reasons": [safe_text(e)],
            "composite_score": 0,
        }




def get_capital_flow(symbol: str):
    try:
        import akshare as ak

        df = ak.stock_individual_fund_flow(stock=symbol)

        if df is None:
            return {
                "available": False,
                "error": "资金流接口返回空"
            }

        if getattr(df, "empty", True):
            return {
                "available": False,
                "error": "资金流接口当前无数据"
            }

        def to_num(v):
            if v is None:
                return None
            if isinstance(v, str):
                v = v.replace(",", "").replace("%", "").strip()
                if v == "":
                    return None
            try:
                return float(v)
            except Exception:
                return None

        df = df.copy()

        main_col = "主力净流入-净额"
        super_col = "超大单净流入-净额"
        big_col = "大单净流入-净额"
        medium_col = "中单净流入-净额"
        small_col = "小单净流入-净额"

        if main_col not in df.columns:
            return {
                "available": False,
                "error": "资金流字段缺失"
            }

        for col in [main_col, super_col, big_col, medium_col, small_col]:
            if col in df.columns:
                df[col] = df[col].apply(to_num)

        if len(df) == 0:
            return {
                "available": False,
                "error": "资金流数据为空"
            }

        row = df.iloc[-1]
        if row is None:
            return {
                "available": False,
                "error": "资金流最新行为空"
            }

        main_3d = df[main_col].tail(3).sum() if main_col in df.columns else None
        main_5d = df[main_col].tail(5).sum() if main_col in df.columns else None

        latest_main = to_num(row.get(main_col))

        if latest_main is None:
            trend_label = "未知"
        elif latest_main > 0 and (main_5d is not None and main_5d > 0):
            trend_label = "资金偏多"
        elif latest_main < 0 and (main_5d is not None and main_5d < 0):
            trend_label = "资金偏空"
        else:
            trend_label = "资金分化"

        return {
            "available": True,
            "main_inflow": latest_main,
            "super_inflow": to_num(row.get(super_col)) if super_col in df.columns else None,
            "big_inflow": to_num(row.get(big_col)) if big_col in df.columns else None,
            "medium_inflow": to_num(row.get(medium_col)) if medium_col in df.columns else None,
            "small_inflow": to_num(row.get(small_col)) if small_col in df.columns else None,
            "main_inflow_3d": to_num(main_3d),
            "main_inflow_5d": to_num(main_5d),
            "trend_label": trend_label,
            "raw_date": row.get("日期") or row.get("trade_date"),
            "error": None,
        }

    except Exception as e:
        msg = safe_text(e)
        if "NoneType" in msg:
            msg = "资金流接口当前无数据"
        return {
            "available": False,
            "error": msg
        }

def _safe_to_float(v):
    try:
        if v is None:
            return None
        if isinstance(v, str):
            v = v.replace(",", "").replace("%", "").strip()
            if v == "":
                return None
        return float(v)
    except Exception:
        return None


def get_stock_sector(symbol: str):
    cache_dir = os.path.join(os.path.dirname(__file__), "cache")
    cache_file = os.path.join(cache_dir, "sector_cons.csv")

    # source 1: AKShare industry constituents
    try:
        import akshare as ak

        # 行业列表
        board_df = ak.stock_board_industry_name_em()
        if board_df is not None and not board_df.empty:
            os.makedirs(cache_dir, exist_ok=True)

            all_rows = []
            for _, row in board_df.iterrows():
                board_name = row.get("板块名称")
                if not board_name:
                    continue
                try:
                    cons = ak.stock_board_industry_cons_em(symbol=board_name)
                    if cons is not None and not cons.empty:
                        cons = cons.copy()
                        cons["所属板块"] = board_name
                        all_rows.append(cons)
                except Exception:
                    continue

            if all_rows:
                cons_df = pd.concat(all_rows, ignore_index=True)
                cons_df.to_csv(cache_file, index=False)

                code_cols = [c for c in ["代码", "证券代码", "股票代码"] if c in cons_df.columns]
                name_cols = [c for c in ["名称", "股票名称"] if c in cons_df.columns]

                if code_cols:
                    code_col = code_cols[0]
                    cons_df[code_col] = cons_df[code_col].astype(str).str.zfill(6)
                    hit = cons_df[cons_df[code_col] == str(symbol).zfill(6)]
                    if not hit.empty:
                        return {
                            "available": True,
                            "sector_name": hit.iloc[0].get("所属板块"),
                            "stock_name": hit.iloc[0].get(name_cols[0]) if name_cols else None,
                            "error": None,
                        }
    except Exception:
        pass

    # source 2: cache
    if os.path.exists(cache_file):
        try:
            cons_df = pd.read_csv(cache_file)
            code_cols = [c for c in ["代码", "证券代码", "股票代码"] if c in cons_df.columns]
            name_cols = [c for c in ["名称", "股票名称"] if c in cons_df.columns]
            if code_cols:
                code_col = code_cols[0]
                cons_df[code_col] = cons_df[code_col].astype(str).str.zfill(6)
                hit = cons_df[cons_df[code_col] == str(symbol).zfill(6)]
                if not hit.empty:
                    return {
                        "available": True,
                        "sector_name": hit.iloc[0].get("所属板块"),
                        "stock_name": hit.iloc[0].get(name_cols[0]) if name_cols else None,
                        "error": None,
                    }
        except Exception as e:
            return {"available": False, "error": safe_text(e)}

    return {"available": False, "error": "未获取到所属板块"}


def get_sector_strength(symbol: str):
    cache_dir = os.path.join(os.path.dirname(__file__), "cache")
    sector_info = get_stock_sector(symbol)

    if not sector_info.get("available"):
        return {
            "available": False,
            "sector_name": None,
            "pct_chg_day": None,
            "pct_chg_5d": None,
            "score": 0,
            "label": "未知",
            "error": sector_info.get("error"),
        }

    sector_name = sector_info.get("sector_name")
    cache_file = os.path.join(cache_dir, f"sector_{sector_name}.csv")

    def score_from_changes(day_chg, chg_5d):
        score = 0
        if day_chg is not None:
            if day_chg >= 2:
                score += 4
            elif day_chg >= 0.8:
                score += 2
            elif day_chg <= -2:
                score -= 4
            elif day_chg <= -0.8:
                score -= 2

        if chg_5d is not None:
            if chg_5d >= 5:
                score += 4
            elif chg_5d >= 2:
                score += 2
            elif chg_5d <= -5:
                score -= 4
            elif chg_5d <= -2:
                score -= 2

        score = max(-10, min(10, score))
        if score >= 6:
            label = "强势"
        elif score >= 2:
            label = "偏强"
        elif score <= -6:
            label = "弱势"
        elif score <= -2:
            label = "偏弱"
        else:
            label = "中性"
        return score, label

    # source 1: AKShare board history
    try:
        import akshare as ak

        hist = ak.stock_board_industry_hist_em(symbol=sector_name, adjust="")
        if hist is not None and not hist.empty:
            hist = hist.copy()
            hist = hist.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "涨跌幅": "pct_chg",
            })

            if "date" in hist.columns:
                hist["trade_date"] = pd.to_datetime(hist["date"]).dt.strftime("%Y%m%d")

            if "close" in hist.columns:
                hist["close"] = pd.to_numeric(hist["close"], errors="coerce")
            if "pct_chg" in hist.columns:
                hist["pct_chg"] = pd.to_numeric(hist["pct_chg"], errors="coerce")

            hist = hist.sort_values("trade_date").reset_index(drop=True)

            if "close" in hist.columns and len(hist) >= 6:
                last_close = hist["close"].iloc[-1]
                prev_5_close = hist["close"].iloc[-6]
                chg_5d = ((last_close / prev_5_close) - 1) * 100 if pd.notna(last_close) and pd.notna(prev_5_close) and prev_5_close != 0 else None
            else:
                chg_5d = None

            pct_chg_day = _safe_to_float(hist["pct_chg"].iloc[-1]) if "pct_chg" in hist.columns and len(hist) > 0 else None

            os.makedirs(cache_dir, exist_ok=True)
            hist.to_csv(cache_file, index=False)

            score, label = score_from_changes(pct_chg_day, chg_5d)

            return {
                "available": True,
                "sector_name": sector_name,
                "pct_chg_day": round_or_none(pct_chg_day),
                "pct_chg_5d": round_or_none(chg_5d),
                "score": score,
                "label": label,
                "error": None,
            }
    except Exception:
        pass

    # source 2: cache
    if os.path.exists(cache_file):
        try:
            hist = pd.read_csv(cache_file)
            hist = hist.sort_values("trade_date").reset_index(drop=True)

            if "close" in hist.columns:
                hist["close"] = pd.to_numeric(hist["close"], errors="coerce")
            if "pct_chg" in hist.columns:
                hist["pct_chg"] = pd.to_numeric(hist["pct_chg"], errors="coerce")

            if len(hist) >= 6:
                last_close = hist["close"].iloc[-1]
                prev_5_close = hist["close"].iloc[-6]
                chg_5d = ((last_close / prev_5_close) - 1) * 100 if pd.notna(last_close) and pd.notna(prev_5_close) and prev_5_close != 0 else None
            else:
                chg_5d = None

            pct_chg_day = _safe_to_float(hist["pct_chg"].iloc[-1]) if "pct_chg" in hist.columns and len(hist) > 0 else None
            score, label = score_from_changes(pct_chg_day, chg_5d)

            return {
                "available": True,
                "sector_name": sector_name,
                "pct_chg_day": round_or_none(pct_chg_day),
                "pct_chg_5d": round_or_none(chg_5d),
                "score": score,
                "label": label,
                "error": None,
            }
        except Exception as e:
            return {
                "available": False,
                "sector_name": sector_name,
                "pct_chg_day": None,
                "pct_chg_5d": None,
                "score": 0,
                "label": "未知",
                "error": safe_text(e),
            }

    return {
        "available": False,
        "sector_name": sector_name,
        "pct_chg_day": None,
        "pct_chg_5d": None,
        "score": 0,
        "label": "未知",
        "error": "板块历史暂不可用",
    }

