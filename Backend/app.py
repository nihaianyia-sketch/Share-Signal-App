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

def calc_signal(df: pd.DataFrame):
    if df is None or len(df) < 10:
        return {"label": "数据不足", "score": 0, "reasons": ["历史数据不足"]}

    df = df.copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["vol"] = pd.to_numeric(df["vol"], errors="coerce")

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["vol5"] = df["vol"].rolling(5).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    reasons = []

    if pd.notna(last["ma5"]) and pd.notna(last["ma10"]) and last["ma5"] > last["ma10"]:
        score += 1
        reasons.append("5日均线在10日均线上方")

    if pd.notna(last["close"]) and pd.notna(prev["close"]) and last["close"] > prev["close"]:
        score += 1
        reasons.append("最新收盘高于前一日")

    if pd.notna(last["vol5"]) and pd.notna(last["vol"]) and last["vol"] > last["vol5"] * 1.2:
        score += 1
        reasons.append("成交量高于5日均量")

    if pd.notna(last["ma5"]) and pd.notna(last["close"]) and last["close"] < last["ma5"]:
        score -= 1
        reasons.append("收盘跌破5日均线")

    if score >= 2:
        label = "偏多"
    elif score <= -1:
        label = "偏空"
    else:
        label = "观望"

    return {"label": label, "score": score, "reasons": reasons}

@app.get("/")
def root():
    return {"message": "a-share backend with tushare"}

@app.get("/quote")
def get_quote(symbol: str = Query(..., description="A股代码，如 600519 或 000001.SZ")):
    try:
        pro = get_pro()
        ts_code = to_ts_code(symbol)

        basic_df = pro.stock_basic(
            ts_code=ts_code,
            fields="ts_code,symbol,name,area,industry,market,list_date"
        )

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")

        daily_df = pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )

        if daily_df is None or daily_df.empty:
            return {
                "error": f"未获取到 {ts_code} 的日线行情",
                "ts_code": ts_code
            }

        daily_df = daily_df.sort_values("trade_date")
        row = daily_df.iloc[-1]

        name = None
        area = None
        industry = None
        market = None
        list_date = None

        if basic_df is not None and not basic_df.empty:
            b = basic_df.iloc[0]
            name = b.get("name")
            area = b.get("area")
            industry = b.get("industry")
            market = b.get("market")
            list_date = b.get("list_date")

        return {
            "symbol": symbol,
            "ts_code": ts_code,
            "name": name,
            "area": area,
            "industry": industry,
            "market": market,
            "list_date": list_date,
            "trade_date": row.get("trade_date"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "pre_close": row.get("pre_close"),
            "change": row.get("change"),
            "pct_chg": row.get("pct_chg"),
            "vol": row.get("vol"),
            "amount": row.get("amount"),
        }
    except Exception as e:
        return {
            "error": "获取行情失败",
            "detail": str(e)
        }

@app.get("/history")
def get_history(symbol: str = Query(..., description="A股代码，如 600519 或 000001.SZ")):
    try:
        pro = get_pro()
        ts_code = to_ts_code(symbol)

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=140)).strftime("%Y%m%d")

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

        hist_df = hist_df.sort_values("trade_date").tail(60).reset_index(drop=True)
        signal = calc_signal(hist_df)

        return {
            "symbol": symbol,
            "ts_code": ts_code,
            "history": hist_df.to_dict(orient="records"),
            "signal": signal,
        }
    except Exception as e:
        return {
            "error": "获取历史行情失败",
            "detail": str(e)
        }
