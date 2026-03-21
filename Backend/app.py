from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import os

import json
import base64
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts
import akshare as ak
import threading
from pydantic import BaseModel
from pypinyin import lazy_pinyin
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import time

app = FastAPI(title="A股买卖点助手 - Tushare版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()

INDEX_HISTORY_MEM_CACHE = {}
INDEX_HISTORY_MEM_CACHE_TS = {}
INDEX_HISTORY_CACHE_LOCK = threading.Lock()
INDEX_HISTORY_TTL_SECONDS = 6 * 60 * 60  # 6 hours

MARKET_SENTIMENT_CACHE = None
MARKET_SENTIMENT_CACHE_TS = 0
MARKET_SENTIMENT_TTL_SECONDS = 120

CAPITAL_FLOW_CACHE = {}
CAPITAL_FLOW_CACHE_TS = {}
CAPITAL_FLOW_TTL_SECONDS = 10 * 60

HISTORY_CACHE = {}
HISTORY_CACHE_TS = {}
HISTORY_CACHE_TTL_SECONDS = 300  # 5分钟

SOURCE_TIMEOUTS = {
    "capital_flow_source1": 0.8,
    "capital_flow_source2": 0.8,
    "market_sentiment_source1": 0.8,
    "market_sentiment_source2": 0.4,
}


STOCK_SEARCH_INDEX = None
STOCK_SEARCH_INDEX_TS = 0
STOCK_SEARCH_INDEX_TTL_SECONDS = 6 * 60 * 60



STOCK_NAME_CACHE = None




def get_pinyin_initials(name: str) -> str:
    try:
        return "".join(x[0] for x in lazy_pinyin(name) if x)
    except Exception:
        return ""


def build_stock_search_index():
    if not TOKEN:
        return []

    try:
        pro_local = ts.pro_api(TOKEN)
        df = pro_local.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name"
        )
        if df is None or df.empty:
            return []

        out = []
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code", "")).strip()
            symbol = str(row.get("symbol", "")).strip()
            name = str(row.get("name", "")).strip()
            if not symbol or not name:
                continue

            out.append({
                "symbol": symbol,
                "ts_code": ts_code,
                "name": name,
                "pinyin_initials": get_pinyin_initials(name),
            })
        return out
    except Exception as e:
        print("build_stock_search_index error:", e)
        return []


def fallback_stock_name(symbol: str | None = None, ts_code: str | None = None):
    name_map = {
        "600519": "贵州茅台",
        "300870": "欧陆通",
        "002851": "麦格米特",
        "601888": "中国中免",
        "601127": "赛力斯",
        "601567": "三星医疗",
    }

    if symbol:
        pure = symbol.split(".")[0].upper()
        if pure in name_map:
            return name_map[pure]

    if ts_code:
        pure = ts_code.split(".")[0].upper()
        if pure in name_map:
            return name_map[pure]

    return None


def get_stock_name_map():
    global STOCK_NAME_CACHE

    if STOCK_NAME_CACHE is not None and len(STOCK_NAME_CACHE) > 0:
        return STOCK_NAME_CACHE

    if not TOKEN:
        return {}

    try:
        pro_local = ts.pro_api(TOKEN)
        basic_df = pro_local.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name"
        )
        if basic_df is None or basic_df.empty:
            return {}
        STOCK_NAME_CACHE = dict(zip(basic_df["ts_code"], basic_df["name"]))
    except Exception:
        return {}

    return STOCK_NAME_CACHE

    if not TOKEN:
        STOCK_NAME_CACHE = {}
        return STOCK_NAME_CACHE

    try:
        pro_local = ts.pro_api(TOKEN)
        basic_df = pro_local.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,name"
        )
        if basic_df is None or basic_df.empty:
            STOCK_NAME_CACHE = {}
        else:
            STOCK_NAME_CACHE = dict(zip(basic_df["ts_code"], basic_df["name"]))
    except Exception:
        STOCK_NAME_CACHE = {}

    return STOCK_NAME_CACHE


class WatchlistAddRequest(BaseModel):
    watchlist: str
    symbol: str


class WatchlistRemoveRequest(BaseModel):
    watchlist: str
    symbol: str


class WatchlistCreateRequest(BaseModel):
    key: str
    label: str


class WatchlistRenameRequest(BaseModel):
    key: str
    label: str


DEFAULT_WATCHLISTS = {
    "core": {
        "label": "核心观察",
        "symbols": ["600519", "300870", "002851"],
    },
    "ai_power": {
        "label": "AI电源",
        "symbols": ["300870", "002851", "300750", "002594"],
    },
    "cpo": {
        "label": "CPO光模块",
        "symbols": ["300308", "688256"],
    },
}

WATCHLISTS_FILE = os.getenv(
    "WATCHLISTS_FILE",
    os.path.join(os.path.dirname(__file__), "data", "watchlists.json"),
)


STOCK_INDEX_PATH = os.path.join(
    os.path.dirname(__file__),
    "data",
    "stock_search_index.json",
)


def load_stock_index():
    if not os.path.exists(STOCK_INDEX_PATH):
        return []
    with open(STOCK_INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)




def lookup_stock_name_from_index(symbol: str) -> str | None:
    pure = (symbol or "").split(".")[0].strip().upper()
    if not pure:
        return None

    try:
        for item in load_stock_index():
            s = str(item.get("symbol", "")).strip().upper()
            if s == pure:
                name = str(item.get("name", "")).strip()
                return name or None
    except Exception:
        return None

    return None

def _ensure_watchlists_dir():
    os.makedirs(os.path.dirname(WATCHLISTS_FILE), exist_ok=True)


def load_watchlists():
    global WATCHLISTS

    _ensure_watchlists_dir()

    if not os.path.exists(WATCHLISTS_FILE):
        WATCHLISTS = {
            k: {
                "label": v["label"],
                "symbols": list(v["symbols"]),
            }
            for k, v in DEFAULT_WATCHLISTS.items()
        }
        save_watchlists()
        return WATCHLISTS

    try:
        with open(WATCHLISTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        WATCHLISTS = {
            k: {
                "label": v["label"],
                "symbols": list(v["symbols"]),
            }
            for k, v in DEFAULT_WATCHLISTS.items()
        }
        save_watchlists()
        return WATCHLISTS

    normalized = {}

    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, list):
                normalized[key] = {
                    "label": key,
                    "symbols": [
                        str(x).split(".")[0]
                        for x in val
                        if str(x).split(".")[0].isdigit() and len(str(x).split(".")[0]) == 6
                    ],
                }
            elif isinstance(val, dict):
                symbols = val.get("symbols", [])
                normalized[key] = {
                    "label": val.get("label", key),
                    "symbols": [
                        str(x).split(".")[0]
                        for x in symbols
                        if str(x).split(".")[0].isdigit() and len(str(x).split(".")[0]) == 6
                    ],
                }

    if not normalized:
        normalized = {
            k: {
                "label": v["label"],
                "symbols": list(v["symbols"]),
            }
            for k, v in DEFAULT_WATCHLISTS.items()
        }

    WATCHLISTS = normalized
    return WATCHLISTS


WATCHLISTS = {}
load_watchlists()

def git_commit_watchlists():

    """
    自动把 watchlists.json 提交到 GitHub
    """
    try:
        import subprocess
        repo_dir = os.path.dirname(os.path.dirname(__file__))

        subprocess.run(
            ["git", "add", "Backend/data/watchlists.json"],
            cwd=repo_dir,
            check=False,
        )

        subprocess.run(
            ["git", "commit", "-m", "update watchlists"],
            cwd=repo_dir,
            check=False,
        )

        subprocess.run(
            ["git", "push"],
            cwd=repo_dir,
            check=False,
        )

    except Exception as e:
        print("git sync failed:", e)



def save_watchlists():
    _ensure_watchlists_dir()
    with open(WATCHLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(WATCHLISTS, f, ensure_ascii=False, indent=2)

    git_commit_watchlists()


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


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=period).mean()
    return atr

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


def calc_status_judgement(hist_df, signal: dict, relative_strength: dict):
    try:
        last = hist_df.iloc[-1]
        close = float(last["close"])
        ma5 = hist_df["close"].rolling(5).mean().iloc[-1]

        atr_ratio = None
        if "atr14" in hist_df.columns:
            atr14 = hist_df["atr14"].iloc[-1]
            try:
                if atr14 is not None and close:
                    atr_ratio = float(atr14) / float(close)
            except Exception:
                atr_ratio = None

        reasons = []
        label = "中性"

        if pd.notna(ma5) and close >= ma5:
            reasons.append("短线站上MA5")

        try:
            k = signal.get("indicators", {}).get("kdj_k")
            d = signal.get("indicators", {}).get("kdj_d")
            if k is not None and d is not None and k >= d:
                reasons.append("KDJ偏强")
        except Exception:
            pass

        rs_score = 0
        if isinstance(relative_strength, dict):
            rs_score = relative_strength.get("score") or 0
            if rs_score > 0:
                reasons.append("当日跑赢大盘")

        if len(reasons) >= 2:
            label = "趋势修复"
        elif rs_score >= 2:
            label = "相对强势"
        elif (signal.get("score") or 0) >= 20:
            label = "偏强运行"

        return {
            "label": label,
            "reasons": reasons,
            "atr_ratio": round(atr_ratio, 4) if atr_ratio is not None else None,
            "rs_score": rs_score,
        }
    except Exception as e:
        return {
            "label": "中性",
            "reasons": [],
            "atr_ratio": None,
            "rs_score": 0,
            "error": safe_text(e),
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


INDEX_SNAPSHOT_CACHE = pd.DataFrame()
INDEX_SNAPSHOT_CACHE_TS = 0.0
BACKGROUND_REFRESH_INTERVAL_SECONDS = 300
BACKGROUND_REFRESH_THREAD_STARTED = False


def get_index_snapshot_cached():
    global INDEX_SNAPSHOT_CACHE
    if INDEX_SNAPSHOT_CACHE is None:
        return pd.DataFrame()
    return INDEX_SNAPSHOT_CACHE.copy()


def compute_market_mood_from_snapshot(idx_spot_df: pd.DataFrame):
    try:
        if idx_spot_df is None or idx_spot_df.empty:
            return {
                "score": 0,
                "label": "中性",
                "indices": [],
                "available": False,
                "error": "指数缓存为空",
            }

        targets = [
            ("上证综指", "000001.SH"),
            ("深证成指", "399001.SZ"),
            ("创业板指", "399006.SZ"),
            ("科创50", "000688.SH"),
        ]

        indices = []
        score = 0

        for name, ts_code in targets:
            row = pick_index_row(idx_spot_df, ts_code)
            if row is None:
                continue

            pct = row.get("pct_chg")
            if pct is None:
                pct = row.get("涨跌幅")

            close = row.get("最新价")
            try:
                pct = float(pct)
            except Exception:
                pct = 0.0

            mood_score = 0
            if pct >= 1:
                mood_score = 4
            elif pct > 0:
                mood_score = 2
            elif pct <= -1:
                mood_score = -4
            elif pct < 0:
                mood_score = -2

            score += mood_score
            indices.append({
                "name": name,
                "ts_code": ts_code,
                "trade_date": None,
                "close": round_or_none(close),
                "pct_chg": round_or_none(pct),
                "mood_score": mood_score,
            })

        if score >= 6:
            label = "偏热"
        elif score >= 2:
            label = "偏暖"
        elif score <= -6:
            label = "偏冷"
        elif score <= -2:
            label = "偏弱"
        else:
            label = "中性"

        return {
            "score": score,
            "label": label,
            "indices": indices,
            "available": True,
            "error": None,
        }
    except Exception as e:
        return {
            "score": 0,
            "label": "中性",
            "indices": [],
            "available": False,
            "error": safe_text(e),
        }


def refresh_background_caches_once():
    global INDEX_SNAPSHOT_CACHE, INDEX_SNAPSHOT_CACHE_TS
    global MARKET_SENTIMENT_CACHE, MARKET_SENTIMENT_CACHE_TS

    try:
        idx = get_index_snapshot_multi()
        if idx is not None and not idx.empty:
            INDEX_SNAPSHOT_CACHE = idx.copy()
            INDEX_SNAPSHOT_CACHE_TS = time.time()

            mood = compute_market_mood_from_snapshot(idx)

            quick_sentiment = {
                "available": True,
                "score": mood.get("score", 0),
                "label": mood.get("label", "中性"),
                "components": {"index_only": mood.get("score", 0)},
                "stats": {"indices": mood.get("indices", [])},
                "error": None,
                "source": "background_index_cache",
            }

            MARKET_SENTIMENT_CACHE = quick_sentiment
            MARKET_SENTIMENT_CACHE_TS = time.time()
            print("background cache refreshed")
    except Exception as e:
        print("background cache refresh error:", e)


def background_refresh_loop():
    while True:
        refresh_background_caches_once()
        time.sleep(BACKGROUND_REFRESH_INTERVAL_SECONDS)


def start_background_refresh_thread():
    global BACKGROUND_REFRESH_THREAD_STARTED
    if BACKGROUND_REFRESH_THREAD_STARTED:
        return

    BACKGROUND_REFRESH_THREAD_STARTED = True
    th = threading.Thread(target=background_refresh_loop, daemon=True)
    th.start()
    print("background refresh thread started")

@app.get("/")
def root():
    return {"message": "a-share backend with stock name and index fallback"}

@app.get("/history")
def get_history(symbol: str = Query(..., description="A股代码，如 600519 或 000001.SZ")):
    try:
        t0 = time.time()
        pro = get_pro()
        print("timing get_pro =", round(time.time() - t0, 3))

        t1 = time.time()
        ts_code = to_ts_code(symbol)
        print("timing to_ts_code =", round(time.time() - t1, 3))

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=260)).strftime("%Y%m%d")

        t2 = time.time()
        now = time.time()
        if ts_code in HISTORY_CACHE and now - HISTORY_CACHE_TS.get(ts_code, 0) <= HISTORY_CACHE_TTL_SECONDS:
            hist_df = HISTORY_CACHE[ts_code].copy()
        else:
            hist_df = pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )
            if hist_df is not None and not hist_df.empty:
                HISTORY_CACHE[ts_code] = hist_df.copy()
                HISTORY_CACHE_TS[ts_code] = now
        print("timing hist_df =", round(time.time() - t2, 3))

        if hist_df is None or hist_df.empty:
            return {
                "error": f"未获取到 {ts_code} 的历史行情",
                "ts_code": ts_code
            }

        hist_df = hist_df.sort_values("trade_date").reset_index(drop=True)
        signal = calc_signal(hist_df)
        out_df = hist_df.tail(80).reset_index(drop=True)

        t3 = time.time()
        stock_name = get_stock_name_local(ts_code) or get_stock_name(pro, ts_code)
        print("timing stock_name =", round(time.time() - t3, 3))

        t4 = time.time()
        benchmark_info = infer_benchmark(symbol)
        print("timing infer_benchmark =", round(time.time() - t4, 3))

        benchmark = {
            "name": benchmark_info["name"],
            "ts_code": benchmark_info["ts_code"],
            "available": False,
            "error": "对应大盘暂不可用",
        }

        market_mood = {
            "score": 0,
            "label": "中性",
            "indices": [],
            "available": False,
            "error": "指数气氛暂不可用",
        }

        try:
            idx_spot_df = get_ak_index_snapshot()
        except Exception:
            idx_spot_df = get_index_snapshot_cached()

        if idx_spot_df is not None and not idx_spot_df.empty:
            row = pick_index_row(idx_spot_df, benchmark_info["ts_code"])
            if row is not None:
                pct = row.get("pct_chg")
                if pct is None:
                    pct = row.get("涨跌幅")
                close = row.get("最新价")

                benchmark = {
                    "name": benchmark_info["name"],
                    "ts_code": benchmark_info["ts_code"],
                    "trade_date": None,
                    "close": round_or_none(close),
                    "pct_chg": round_or_none(pct),
                    "available": True,
                    "error": None,
                }

            market_mood = compute_market_mood_from_snapshot(idx_spot_df)

        t_rs = time.time()
        bench_hist_df = None
        if bench_hist_df is not None:
            relative_strength = calc_relative_strength(
                hist_df,
                bench_hist_df,
                benchmark_info["name"]
            )
        else:
            relative_strength = {
                "available": False,
                "benchmark_name": benchmark_info["name"],
                "rs_day": None,
                "rs_5": None,
                "rs_10": None,
                "rs_20": None,
                "score": 0,
                "error": "基准历史数据暂不可用",
            }
        print("timing relative_strength =", round(time.time() - t_rs, 3))

        t_ms = time.time()
        market_sentiment = get_market_sentiment_quick()
        print("timing market_sentiment =", round(time.time() - t_ms, 3))

        t_cf = time.time()
        capital_flow = get_capital_flow_multi_source(symbol)
        print("timing capital_flow =", round(time.time() - t_cf, 3))

        t_ss = time.time()
        sector_strength = {
            "available": False,
            "error": "已跳过以提升响应速度",
        }
        print("timing sector_strength =", round(time.time() - t_ss, 3))

        status_judgement = calc_status_judgement(hist_df, signal, relative_strength)
        trading_decision = calc_trading_decision(
            signal,
            relative_strength,
            market_sentiment,
            status_judgement,
            capital_flow
        )

        return {
            "symbol": symbol.split(".")[0],
            "name": stock_name or lookup_stock_name_from_index(symbol) or fallback_stock_name(symbol, ts_code),
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


@app.get("/leaders")
def get_leaders(
    symbols: str = Query(
        "",
        description="逗号分隔股票代码列表，如 600519,300750"
    ),
    watchlist: str = Query(
        "",
        description="预设观察池名称，如 core / ai_power / cpo"
    ),
    limit: int = Query(20, ge=1, le=100, description="返回前N名"),
):
    try:
        if not isinstance(symbols, str):
            symbols = ""
        if not isinstance(watchlist, str):
            watchlist = ""
        if not isinstance(limit, int):
            limit = 20

        watchlist = watchlist.strip()

        if watchlist:
            codes = WATCHLISTS.get(watchlist, [])
            if not codes:
                return {
                    "leaders": [],
                    "count": 0,
                    "universe_size": 0,
                    "error": f"未知观察池: {watchlist}"
                }
        else:
            if not symbols.strip():
                codes = WATCHLISTS.get("core", [])
            else:
                codes = [x.strip() for x in symbols.split(",") if x.strip()]

        if not codes:
            return {
                "leaders": [],
                "count": 0,
                "universe_size": 0,
                "error": "股票列表为空"
            }

        if not TOKEN:
            return {
                "leaders": [],
                "count": 0,
                "universe_size": len(codes),
                "error": "缺少 TUSHARE_TOKEN 环境变量"
            }

        pro_local = ts.pro_api(TOKEN)
        name_map = get_stock_name_map()
        results = []

        for raw_symbol in codes:
            try:
                pure_code = raw_symbol.split(".")[0].upper()

                if pure_code.startswith(("600","601","603","605","688")):
                    ts_code = pure_code + ".SH"
                    benchmark_info = {"name": "上证综指", "ts_code": "000001.SH"}
                elif pure_code.startswith("300"):
                    ts_code = pure_code + ".SZ"
                    benchmark_info = {"name": "创业板指", "ts_code": "399006.SZ"}
                else:
                    ts_code = pure_code + ".SZ"
                    benchmark_info = {"name": "深证成指", "ts_code": "399001.SZ"}

                stock_name = name_map.get(ts_code)

                if not stock_name:
                    try:
                        hist_resp = get_history(pure_code)
                        if isinstance(hist_resp, dict):
                            stock_name = hist_resp.get("name")
                    except Exception:
                        pass

                hist_df = pro_local.daily(
                    ts_code=ts_code,
                    start_date="20250101",
                    end_date=datetime.now().strftime("%Y%m%d")
                )

                if hist_df is None or hist_df.empty:
                    continue

                hist_df = hist_df.copy()
                hist_df["trade_date"] = hist_df["trade_date"].astype(str)
                hist_df = hist_df.sort_values("trade_date").reset_index(drop=True)

                for col in ["open", "high", "low", "close", "pct_chg", "vol", "amount"]:
                    if col in hist_df.columns:
                        hist_df[col] = pd.to_numeric(hist_df[col], errors="coerce")

                if "vol" in hist_df.columns and "volume" not in hist_df.columns:
                    hist_df["volume"] = hist_df["vol"]

                if len(hist_df) < 21:
                    continue

                start_date = str(hist_df["trade_date"].iloc[-30])
                end_date = str(hist_df["trade_date"].iloc[-1])

                bench_df = get_index_history_multi(
                    benchmark_info["ts_code"],
                    start_date,
                    end_date
                )

                if bench_df is None or len(bench_df) < 2:
                    continue

                rs = calc_relative_strength(hist_df, bench_df, benchmark_info["name"])

                if not rs.get("available"):
                    continue

                results.append({
                    "symbol": pure_code,
                    "ts_code": ts_code,
                    "name": stock_name,
                    "benchmark_name": rs.get("benchmark_name"),
                    "rs_day": rs.get("rs_day"),
                    "rs_5": rs.get("rs_5"),
                    "rs_10": rs.get("rs_10"),
                    "rs_20": rs.get("rs_20"),
                    "score": rs.get("score"),
                    "error": rs.get("error"),
                })

            except Exception:
                continue

        results = [
            x for x in results
            if x.get("rs_20") is not None or x.get("score") is not None or x.get("rs_day") is not None
        ]

        def rank_value(x):
            if x.get("rs_20") is not None:
                return x["rs_20"]
            if x.get("score") is not None:
                return x["score"]
            if x.get("rs_day") is not None:
                return x["rs_day"]
            return -999

        results.sort(key=rank_value, reverse=True)

        return {
            "leaders": results[:limit],
            "count": min(limit, len(results)),
            "universe_size": len(codes),
            "watchlist": watchlist or None,
            "error": None
        }

    except Exception as e:
        return {
            "leaders": [],
            "count": 0,
            "universe_size": 0,
            "watchlist": watchlist if isinstance(watchlist, str) else None,
            "error": safe_text(e)
        }

@app.get("/watchlists")
def get_watchlists():
    try:
        out = []
        for key, val in WATCHLISTS.items():
            if isinstance(val, dict):
                out.append({
                    "key": key,
                    "label": val.get("label", key),
                    "count": len(val.get("symbols", [])),
                })
            else:
                out.append({
                    "key": key,
                    "label": key,
                    "count": len(val) if isinstance(val, list) else 0,
                })

        out.sort(key=lambda x: x["key"])

        return {
            "watchlists": out,
            "count": len(out),
            "error": None,
        }
    except Exception as e:
        return {
            "watchlists": [],
            "count": 0,
            "error": safe_text(e),
        }


@app.post("/watchlists/add")
def add_to_watchlist(payload: WatchlistAddRequest):
    try:
        watchlist = (payload.watchlist or "").strip()
        symbol = (payload.symbol or "").strip().upper()

        if not watchlist:
            return {"ok": False, "error": "观察池名称不能为空"}

        if not symbol:
            return {"ok": False, "error": "股票代码不能为空"}

        if "." in symbol:
            symbol = symbol.split(".")[0]

        if not symbol.isdigit() or len(symbol) != 6:
            return {"ok": False, "error": "股票代码需为6位数字"}

        if watchlist not in WATCHLISTS:
            WATCHLISTS[watchlist] = {
                "label": watchlist,
                "symbols": [],
            }

        if isinstance(WATCHLISTS[watchlist], list):
            WATCHLISTS[watchlist] = {
                "label": watchlist,
                "symbols": WATCHLISTS[watchlist],
            }

        if symbol not in WATCHLISTS[watchlist]["symbols"]:
            WATCHLISTS[watchlist]["symbols"].append(symbol)

        save_watchlists()

        return {
            "ok": True,
            "watchlist": watchlist,
            "symbols": WATCHLISTS[watchlist]["symbols"],
            "error": None,
        }

    except Exception as e:
        return {"ok": False, "error": safe_text(e)}


@app.get("/stocks/search")
def search_stocks(
    q: str = Query("", description="代码/名称/拼音首字母"),
    limit: int = Query(20, ge=1, le=50),
):
    try:
        query = (q or "").strip().lower()
        if not query:
            return {"results": [], "count": 0, "error": None}

        items = load_stock_index()
        matches = []

        for item in items:
            symbol = str(item.get("symbol", "")).lower()
            ts_code = str(item.get("ts_code", "")).lower()
            name = str(item.get("name", "")).lower()
            initials = str(item.get("pinyin_initials") or item.get("initials", "")).lower()

            if (
                query in symbol
                or query in ts_code
                or query in name
                or initials.startswith(query)
                or query in initials
            ):
                matches.append(item)

        matches = matches[:limit]

        return {
            "results": matches,
            "count": len(matches),
            "error": None,
        }
    except Exception as e:
        return {
            "results": [],
            "count": 0,
            "error": safe_text(e),
        }


@app.post("/watchlists/remove")
def remove_from_watchlist(payload: WatchlistRemoveRequest):
    try:
        watchlist = (payload.watchlist or "").strip()
        symbol = (payload.symbol or "").strip().upper()

        if not watchlist or watchlist not in WATCHLISTS:
            return {"ok": False, "error": "观察池不存在"}

        if "." in symbol:
            symbol = symbol.split(".")[0]

        WATCHLISTS[watchlist]["symbols"] = [
            s for s in WATCHLISTS[watchlist]["symbols"]
            if s != symbol
        ]

        save_watchlists()

        return {
            "ok": True,
            "watchlist": watchlist,
            "symbols": WATCHLISTS[watchlist]["symbols"],
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "error": safe_text(e)}


@app.post("/watchlists/create")
def create_watchlist(payload: WatchlistCreateRequest):
    try:
        key = (payload.key or "").strip().lower()
        label = (payload.label or "").strip()

        if not key:
            return {"ok": False, "error": "观察池 key 不能为空"}

        if not label:
            return {"ok": False, "error": "观察池标签不能为空"}

        if key in WATCHLISTS:
            return {"ok": False, "error": "观察池已存在"}

        WATCHLISTS[key] = {
            "label": label,
            "symbols": [],
        }
        save_watchlists()

        return {
            "ok": True,
            "watchlist": {
                "key": key,
                "label": WATCHLISTS[key]["label"],
                "count": len(WATCHLISTS[key]["symbols"]),
            },
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "error": safe_text(e)}


@app.post("/watchlists/rename")
def rename_watchlist(payload: WatchlistRenameRequest):
    try:
        key = (payload.key or "").strip().lower()
        label = (payload.label or "").strip()

        if not key or key not in WATCHLISTS:
            return {"ok": False, "error": "观察池不存在"}

        if not label:
            return {"ok": False, "error": "标签不能为空"}

        if isinstance(WATCHLISTS[key], list):
            WATCHLISTS[key] = {
                "label": key,
                "symbols": WATCHLISTS[key],
            }

        WATCHLISTS[key]["label"] = label
        save_watchlists()

        return {
            "ok": True,
            "watchlist": {
                "key": key,
                "label": WATCHLISTS[key]["label"],
                "count": len(WATCHLISTS[key]["symbols"]),
            },
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "error": safe_text(e)}


@app.get("/watchlists/items")
def get_watchlist_items(
    key: str = Query(..., description="观察池 key"),
):
    try:
        wl = WATCHLISTS.get(key)
        if not wl:
            return {"items": [], "count": 0, "error": "观察池不存在"}

        if isinstance(wl, list):
            symbols = wl
            label = key
        else:
            symbols = wl.get("symbols", [])
            label = wl.get("label", key)

        items = []
        for s in symbols:
            name = (
                lookup_stock_name_from_index(s)
                or fallback_stock_name(s)
                or s
            )
            items.append({
                "symbol": s,
                "name": name,
            })

        return {
            "key": key,
            "label": label,
            "items": items,
            "count": len(items),
            "error": None,
        }
    except Exception as e:
        return {"items": [], "count": 0, "error": safe_text(e)}


def get_capital_flow_source2_tushare(symbol: str):
    """
    使用 Tushare moneyflow 作为日级 fallback
    """
    if not TOKEN:
        return {"available": False, "error": "Tushare 未配置"}

    try:
        pro_local = ts.pro_api(TOKEN)
        ts_code = symbol if "." in symbol else (
            symbol + ".SH" if symbol.startswith("6") else symbol + ".SZ"
        )

        df = pro_local.moneyflow(
            ts_code=ts_code,
            limit=1
        )

        if df is None or df.empty:
            return {"available": False, "error": "tushare 无资金流数据"}

        row = df.iloc[0]

        main = float(row.get("net_mf_amount", 0.0))

        return {
            "available": True,
            "trend_label": "日级资金",
            "main_inflow": main,
            "main_inflow_3d": None,
            "main_inflow_5d": None,
            "super_inflow": None,
            "big_inflow": None,
            "medium_inflow": None,
            "source_note": "tushare_moneyflow_daily",
            "error": None,
        }

    except Exception as e:
        return {"available": False, "error": safe_text(e)}


def get_capital_flow_multi_source(symbol: str):
    pure = (symbol or "").split(".")[0].strip().upper()

    source_specs = [
        (
            "hsgt_market",
            0.6,
            lambda: get_capital_flow_source3_hsgt(pure),
        ),
        (
            "eastmoney_realtime",
            SOURCE_TIMEOUTS["capital_flow_source1"],
            lambda: get_capital_flow(pure),
        ),
        (
            "tushare_daily",
            SOURCE_TIMEOUTS["capital_flow_source2"],
            lambda: get_capital_flow_source2_tushare(pure),
        ),
        (
            "cache",
            0.05,
            lambda: get_cached_capital_flow(pure),
        ),
    ]

    result = try_sources_with_timeout(
        source_specs,
        {
            "available": False,
            "from_cache": False,
            "error": "所有资金流源均失败",
        },
    )

    if result_available(result):
        CAPITAL_FLOW_CACHE[pure] = dict(result)
        CAPITAL_FLOW_CACHE_TS[pure] = time.time()

    return result


def get_capital_flow_source3_hsgt(symbol: str):
    if not TOKEN:
        return {"available": False, "error": "Tushare 未配置"}

    try:
        pro_local = ts.pro_api(TOKEN)
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

        df = pro_local.moneyflow_hsgt(
            start_date=start_date,
            end_date=end_date
        )

        if df is None or df.empty:
            return {"available": False, "error": "hsgt 无数据"}

        df = df.sort_values("trade_date")
        row = df.iloc[-1]

        north = row.get("north_money")
        try:
            north = float(north)
        except Exception:
            north = 0.0

        return {
            "available": True,
            "trend_label": "北向资金",
            "main_inflow": north,
            "main_inflow_3d": None,
            "main_inflow_5d": None,
            "super_inflow": None,
            "big_inflow": None,
            "medium_inflow": None,
            "source_note": "tushare_hsgt",
            "error": None,
        }
    except Exception as e:
        return {"available": False, "error": safe_text(e)}


def get_market_sentiment_source3_news():
    try:
        df = ak.index_news_sentiment_scope()
        if df is None or df.empty:
            return {"available": False, "error": "news sentiment 无数据"}

        last = df.iloc[-1]

        score_raw = None
        for col in ["情绪指数", "sentiment", "value"]:
            if col in df.columns:
                score_raw = last.get(col)
                break

        if score_raw is None:
            return {"available": False, "error": "news sentiment 字段缺失"}

        score_raw = float(score_raw)
        score = int(round((score_raw - 50) / 5))

        return {
            "available": True,
            "score": score,
            "label": calc_sentiment_label(score),
            "components": {"news_sentiment": score},
            "stats": {"raw_news_sentiment": score_raw},
            "error": None,
        }
    except Exception as e:
        return {"available": False, "error": safe_text(e)}


def get_cached_market_sentiment():
    global MARKET_SENTIMENT_CACHE, MARKET_SENTIMENT_CACHE_TS
    now = time.time()
    if MARKET_SENTIMENT_CACHE is not None and now - MARKET_SENTIMENT_CACHE_TS <= MARKET_SENTIMENT_TTL_SECONDS:
        out = dict(MARKET_SENTIMENT_CACHE)
        out["from_cache"] = True
        return out
    return None


def get_market_sentiment_source2_index_only():
    try:
        idx_spot_df = get_ak_index_snapshot()
        if idx_spot_df is None or len(idx_spot_df) == 0:
            return {
                "available": False,
                "error": "指数快照无数据",
            }

        score = 0
        labels = []

        for code in ["000001.SH", "399001.SZ", "399006.SZ"]:
            row = pick_index_row(idx_spot_df, code)
            if row is None:
                continue

            pct = row.get("pct_chg")
            if pct is None:
                pct = row.get("涨跌幅")

            try:
                pct = float(pct)
            except Exception:
                pct = 0.0

            if pct > 1:
                score += 2
            elif pct > 0:
                score += 1
            elif pct < -1:
                score -= 2
            elif pct < 0:
                score -= 1

            labels.append({
                "ts_code": code,
                "pct_chg": pct,
            })

        if score >= 2:
            label = "偏强"
        elif score <= -2:
            label = "偏弱"
        else:
            label = "中性"

        return {
            "available": True,
            "score": score,
            "label": label,
            "components": {"index_only": score},
            "stats": {"indices": labels},
            "error": None,
        }
    except Exception as e:
        return {
            "available": False,
            "error": safe_text(e),
        }


def get_market_sentiment_quick():
    source_specs = [
        ("index_quick_sentiment", 0.6, lambda: get_market_sentiment_source2_index_only()),
        ("market_sentiment_cache", 0.05, lambda: get_cached_market_sentiment()),
    ]

    return try_sources_with_timeout(
        source_specs,
        {
            "available": False,
            "score": 0,
            "label": "中性",
            "components": {},
            "stats": {},
            "error": "市场情绪指数暂不可用",
            "source": "fallback",
        },
    )


def run_with_timeout(fn, timeout_seconds, default=None):
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=timeout_seconds)
    except FuturesTimeoutError:
        fut.cancel()
        ex.shutdown(wait=False, cancel_futures=True)
        return default
    except Exception as e:
        print("run_with_timeout error:", e)
        ex.shutdown(wait=False, cancel_futures=True)
        return default
    finally:
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

def result_available(x):
    return isinstance(x, dict) and bool(x.get("available"))


def try_sources_with_timeout(source_specs, fallback_result):
    errors = []

    for source_name, timeout_seconds, fn in source_specs:
        result = run_with_timeout(fn, timeout_seconds, default=None)

        if result_available(result):
            out = dict(result)
            out["source"] = source_name
            return out

        if isinstance(result, dict):
            msg = result.get("error")
            errors.append(f"{source_name}: {msg or 'unavailable'}")
        else:
            errors.append(f"{source_name}: timeout_or_exception")

    out = dict(fallback_result)
    out["source"] = "fallback"
    out["error"] = " | ".join(errors) if errors else out.get("error")
    return out


def calc_trading_decision(signal: dict, relative_strength: dict, market_sentiment: dict, status_judgement: dict, capital_flow: dict):
    try:
        score = 0.0
        reasons = []

        signal_score = (signal or {}).get("score") or 0
        rs_score = (relative_strength or {}).get("score") or 0
        ms_score = (market_sentiment or {}).get("score") or 0

        score += signal_score * 0.4
        score += rs_score * 1.2
        score += ms_score * 0.6

        if signal_score >= 20:
            reasons.append("均线多头排列")
        if (signal or {}).get("indicators", {}).get("macd_hist") is not None:
            if (signal or {}).get("indicators", {}).get("macd_hist") > 0:
                reasons.append("MACD偏强")
        if status_judgement and status_judgement.get("label"):
            reasons.append(f'状态判断：{status_judgement.get("label")}')

        if capital_flow and capital_flow.get("available"):
            main_flow = capital_flow.get("main_inflow")
            try:
                if main_flow is not None and float(main_flow) > 0:
                    score += 1.5
                    reasons.append("资金偏正")
            except Exception:
                pass

        if score >= 16:
            action = "顺势做多"
            bias = "偏多"
            confidence = 78
            summary = "趋势与信号共振较强。"
        elif score >= 10:
            action = "轻仓试多"
            bias = "谨慎偏多"
            confidence = 66
            summary = "存在修复迹象，但中期趋势尚未完全扭转。"
        elif score <= -10:
            action = "观望回避"
            bias = "偏空"
            confidence = 72
            summary = "信号与环境偏弱，暂不宜贸然参与。"
        else:
            action = "以观察为主"
            bias = "中性"
            confidence = 55
            summary = "信号分歧较大，等待更多确认。"

        return {
            "action": action,
            "bias": bias,
            "confidence": confidence,
            "horizon": "短线到波段",
            "execution_hint": "控制仓位，结合均线与放量确认后执行。",
            "summary": summary,
            "reasons": reasons,
            "composite_score": round(score, 1),
        }
    except Exception as e:
        return {
            "action": "以观察为主",
            "bias": "中性",
            "confidence": 50,
            "horizon": "短线到波段",
            "execution_hint": "数据异常，先观察。",
            "summary": "交易决策计算失败，暂使用保守默认值。",
            "reasons": [],
            "composite_score": 0.0,
            "error": safe_text(e),
        }


def get_index_snapshot_multi():
    try:
        df = ak.stock_zh_index_spot_em()
        if df is None or df.empty:
            return pd.DataFrame()

        work = df.copy()

        # 统一字段，兼容 pick_index_row / 情绪函数
        if "代码" in work.columns:
            work["代码"] = work["代码"].astype(str)
        if "名称" in work.columns:
            work["名称"] = work["名称"].astype(str)

        if "最新价" not in work.columns and "最新" in work.columns:
            work["最新价"] = work["最新"]
        if "涨跌幅" not in work.columns and "涨跌幅(%)" in work.columns:
            work["涨跌幅"] = work["涨跌幅(%)"]

        # 给 quick sentiment 用的统一字段
        if "pct_chg" not in work.columns and "涨跌幅" in work.columns:
            work["pct_chg"] = pd.to_numeric(work["涨跌幅"], errors="coerce")

        return work
    except Exception as e:
        print("get_index_snapshot_multi error:", e)
        return pd.DataFrame()
