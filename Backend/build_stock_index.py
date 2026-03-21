import json
import tushare as ts
import os
from pypinyin import lazy_pinyin

TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("缺少 TUSHARE_TOKEN 环境变量")

pro = ts.pro_api(TOKEN)

df = pro.stock_basic(
    exchange="",
    list_status="L",
    fields="ts_code,symbol,name"
)

def initials(name: str) -> str:
    try:
        return "".join(p[0] for p in lazy_pinyin(name) if p)
    except Exception:
        return ""

items = []
for _, r in df.iterrows():
    name = str(r["name"]).strip()
    symbol = str(r["symbol"]).strip()
    ts_code = str(r["ts_code"]).strip()
    if not symbol or not name:
        continue
    items.append({
        "symbol": symbol,
        "ts_code": ts_code,
        "name": name,
        "pinyin_initials": initials(name)
    })

os.makedirs("Backend/data", exist_ok=True)
with open("Backend/data/stock_search_index.json", "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

print("index built:", len(items))
