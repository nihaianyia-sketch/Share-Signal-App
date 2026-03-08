from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import akshare as ak
import pandas as pd

app = FastAPI(title="A股买卖点助手")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def calc_signal(df: pd.DataFrame):
    if df is None or len(df) < 10:
        return {"label": "数据不足", "score": 0, "reasons": ["历史数据不足"]}

    df = df.copy()
    df["close"] = pd.to_numeric(df["收盘"], errors="coerce")
    df["volume"] = pd.to_numeric(df["成交量"], errors="coerce")

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["vol5"] = df["volume"].rolling(5).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    reasons = []

    if pd.notna(last["ma5"]) and pd.notna(last["ma10"]) and last["ma5"] > last["ma10"]:
        score += 1
        reasons.append("5日均线在10日均线上方")

    if last["close"] > prev["close"]:
        score += 1
        reasons.append("最新收盘高于前一日")

    if pd.notna(last["vol5"]) and last["volume"] > last["vol5"] * 1.2:
        score += 1
        reasons.append("成交量高于5日均量")

    if pd.notna(last["ma5"]) and last["close"] < last["ma5"]:
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
    return {"message": "backend is running"}

@app.get("/quote")
def get_quote(symbol: str = Query(..., description="A股代码，如 600519")):
    spot_df = ak.stock_zh_a_spot_em()
    row = spot_df[spot_df["代码"] == symbol]

    if row.empty:
        return {"error": f"未找到股票代码 {symbol}"}

    row = row.iloc[0]
    return {
        "symbol": symbol,
        "name": row["名称"],
        "price": row["最新价"],
        "change_percent": row["涨跌幅"],
        "change_amount": row["涨跌额"],
        "volume": row["成交量"],
        "amount": row["成交额"],
        "high": row["最高"],
        "low": row["最低"],
        "open": row["今开"],
        "pre_close": row["昨收"],
    }

@app.get("/history")
def get_history(symbol: str = Query(..., description="A股代码，如 600519")):
    hist_df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date="20250101",
        end_date="20261231",
        adjust=""
    )

    if hist_df is None or hist_df.empty:
        return {"error": f"未获取到 {symbol} 的历史行情"}

    hist_df = hist_df.tail(60)
    signal = calc_signal(hist_df)

    return {
        "symbol": symbol,
        "history": hist_df.to_dict(orient="records"),
        "signal": signal,
    }
