# -*- coding: utf-8 -*-
"""
news_markets.py — NEWS ⇄ MARKETS 關聯圖數據
================================================
GDELT 新聞熱度 timeline（norm 歸一化文章量）＋ CNBC 歷史 K 線，
對齊縮減成細 JSON，畀 render_v2 嵌入 HTML，前端用內聯 SVG 畫雙軌圖。

窗口：
  7d  — GDELT timespan=7d（小時桶）＋ CNBC 5D 分時線（縮成小時收盤）
  1d  — GDELT timespan=1d（15 分鐘桶）＋ CNBC 1D 1 分鐘線（縮成 15 分鐘收盤）

休市時段價格以前收盤 ffill；Pearson r 由前端計。
全部串行 + sleep，GDELT 超時寬限 120s（沙盒網絡已知慢）。
"""
import os
import json
import time
import urllib.parse
from datetime import datetime, timezone, timedelta

from collectors import http_get

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE_PATH = os.path.join(ROOT, "data_v2", "market_corr_latest.json")
PRICE_CACHE_PATH = os.path.join(ROOT, "data_v2", "_nm_prices.json")
GDERT_SLEEP = float(os.environ.get("NM_GDELT_SLEEP", "2.2"))

# timelinevolraw：data[].value = 符合 query 嘅文章數（聲量）；data[].norm = 同期全球總文章量（基數）
GDELT_URL = ("https://api.gdeltproject.org/api/v2/doc/doc?query={q}"
             "&mode=timelinevolraw&format=json&timespan={span}")
CNBC_CHART_URL = "https://ts-api.cnbc.com/harmony/app/charts/{win}.json?symbol={sym}"

# 投資者最關注嘅 6 個話題（對應事件引擎主線）
# 注意：GDELT DOC API 對括號/引號/多 OR 嘅複合 query 好易超時，保持簡短
TOPICS = [
    {"key": "sanctions", "zh": "制裁 / 關稅",
     "q": 'sanctions sourcelang:eng'},
    {"key": "rates", "zh": "利率 / 聯儲局",
     "q": 'federal reserve sourcelang:eng'},
    {"key": "oil", "zh": "原油 / 能源",
     'q': 'crude oil sourcelang:eng'},
    {"key": "geopolitics", "zh": "戰爭 / 地緣",
     "q": 'war conflict sourcelang:eng'},
    {"key": "china", "zh": "中國 / 台海",
     "q": 'Taiwan China sourcelang:eng'},
    {"key": "crypto", "zh": "加密貨幣",
     "q": 'bitcoin sourcelang:eng'},
]

MARKETS = [
    {"key": "SPX",  "zh": "S&P 500",   "sym": ".SPX"},
    {"key": "IXIC", "zh": "納斯達克",  "sym": ".IXIC"},
    {"key": "BTC",  "zh": "比特幣",    "sym": "BTC.CM="},
    {"key": "ETH",  "zh": "以太幣",    "sym": "ETH.CM="},
    {"key": "GOLD", "zh": "黃金",      "sym": "@GC.1"},
    {"key": "WTI",  "zh": "WTI 原油",  "sym": "@CL.1"},
]

WINDOWS = {
    "7d": {"gdelt_span": "7d", "cnbc_win": "5D", "sleep_after": 5.5},
    "1d": {"gdelt_span": "1d", "cnbc_win": "1D", "sleep_after": 5.5},
}


def _parse_gdelt_dt(s):
    # "20260826T180000Z" → epoch s
    return int(datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp())


def fetch_gdelt_topic(query, span, timeout=120):
    url = GDELT_URL.format(q=urllib.parse.quote(query, safe=''), span=span)
    raw = http_get(url, timeout=timeout, retries=1)
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8", "ignore"))
        rows = d["timeline"][0]["data"]
        # value = 命中話題嘅文章數（聲量）。用 value/norm*1e5 轉成「每十萬篇嘅話題密度」，
        # 消除一日之內發稿週期（亞洲/歐美時段）嘅基數波動
        pts = []
        for r in rows:
            val = float(r.get("value") or 0)
            norm = float(r.get("norm") or 0)
            density = round(val / norm * 100000, 2) if norm > 0 else 0
            pts.append([_parse_gdelt_dt(r["date"]), density])
        pts.sort(key=lambda x: x[0])
        return pts
    except Exception as e:  # noqa
        print(f"  [news_markets] GDELT parse fail: {type(e).__name__}: {str(e)[:70]}")
        return None


def fetch_cnbc_bars(symbol, win, timeout=40):
    url = CNBC_CHART_URL.format(win=win, sym=urllib.parse.quote(symbol, safe=""))
    raw = http_get(url, timeout=timeout, retries=2)
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8", "ignore"))
        bars = d["barData"]["priceBars"]
        pts = []
        for b in bars:
            ms = b.get("tradeTimeinMills")
            if ms:
                t = int(ms) // 1000
            else:
                t = int(datetime.strptime(b["tradeTime"], "%Y%m%d%H%M%S")
                        .replace(tzinfo=timezone.utc).timestamp())
            close = b.get("close")
            if close in (None, "", "0"):
                continue
            pts.append([t, round(float(close), 2)])
        pts.sort(key=lambda x: x[0])
        return pts
    except Exception as e:  # noqa
        print(f"  [news_markets] CNBC parse fail {symbol} {win}: {type(e).__name__}: {str(e)[:70]}")
        return None


def ffill_to_grid(bars, grid):
    """bars: [[t,price]...] 已排序；grid: [t...] 新聞桶時間。
    每個 grid 點取 ≤t 嘅最後收盤（休市 ffill）。返回 [[t,price]...]，無價格嘅桶跳過。"""
    if not bars:
        return []
    out, j, last = [], 0, None
    for t in grid:
        while j < len(bars) and bars[j][0] <= t:
            last = bars[j][1]
            j += 1
        if last is not None:
            out.append([t, last])
    return out


def build_market_corr(use_cache=False, cache_max_hours=14):
    """返回 dict。use_cache=True 且緩存新鮮時直接讀緩存。"""
    if use_cache and os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < cache_max_hours * 3600:
            try:
                with open(CACHE_PATH, encoding="utf-8") as f:
                    cached = json.load(f)
                print(f"[news_markets] 用緩存（{age/3600:.1f}h 前）")
                return cached
            except Exception:
                pass

    out = {
        "generated": datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M HKT"),
        "ok": False,
        "topics_meta": [{"key": t["key"], "zh": t["zh"]} for t in TOPICS],
        "markets_meta": [{"key": m["key"], "zh": m["zh"]} for m in MARKETS],
        "windows": {},
    }

    # 斷點續傳：進度盤（價格 + 已完成 GDELT topic）
    progress = {"prices": {}, "gdelt": {}}
    if os.path.exists(PRICE_CACHE_PATH):
        try:
            with open(PRICE_CACHE_PATH, encoding="utf-8") as f:
                progress = json.load(f)
            print(f"[news_markets] 續傳盤：價格 {sum(len(v) for v in progress['prices'].values())} 段、"
                  f"GDELT {len(progress['gdelt'])} 項")
        except Exception:
            progress = {"prices": {}, "gdelt": {}}

    def _save_progress():
        try:
            with open(PRICE_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass

    # CNBC 歷史價（快，每窗口每市場一次，逐段落盤）
    for wkey, wcfg in WINDOWS.items():
        for m in MARKETS:
            pk = f"{wkey}:{m['key']}"
            if pk in progress["prices"]:
                continue
            bars = fetch_cnbc_bars(m["sym"], wcfg["cnbc_win"])
            progress["prices"][pk] = bars or []
            n = len(bars) if bars else 0
            print(f"[news_markets] price {m['key']:5s} {wcfg['cnbc_win']}: {n} bars", flush=True)
            _save_progress()
            time.sleep(0.6)

    # GDELT 話題量（慢，串行 + sleep，逐項落盤）
    n_ok = 0
    for wkey, wcfg in WINDOWS.items():
        win_obj = {"topics": {}, "markets": {}}
        for t in TOPICS:
            gk = f"{wkey}:{t['key']}"
            pts = progress["gdelt"].get(gk)
            if pts is None:
                pts = fetch_gdelt_topic(t["q"], wcfg["gdelt_span"])
                progress["gdelt"][gk] = pts or False  # False=已試過失敗，唔重試
                _save_progress()
            if pts:
                win_obj["topics"][t["key"]] = pts
                n_ok += 1
                print(f"[news_markets] gdelt {t['key']:11s} {wkey}: {len(pts)} pts", flush=True)
            else:
                print(f"[news_markets] gdelt {t['key']:11s} {wkey}: FAIL", flush=True)
            time.sleep(GDERT_SLEEP)

        # 價格 ffill 到新聞時間網格
        for m in MARKETS:
            topic0 = next(iter(win_obj["topics"].values()), None)
            grid = [p[0] for p in topic0] if topic0 else None
            bars = progress["prices"].get(f"{wkey}:{m['key']}")
            if grid and bars:
                win_obj["markets"][m["key"]] = ffill_to_grid(bars, grid)
        out["windows"][wkey] = win_obj

    out["ok"] = n_ok > 0
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        print(f"[news_markets] 緩存已寫入 {CACHE_PATH}", flush=True)
        try:
            os.remove(PRICE_CACHE_PATH)  # 完成後清進度盤
        except OSError:
            pass
    except Exception as e:  # noqa
        print(f"[news_markets] 緩存寫入失敗: {e}")
    return out


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    d = build_market_corr(use_cache=not force)
    print("ok =", d["ok"], "| generated =", d["generated"])
    for wk, w in d["windows"].items():
        print(f"  window {wk}: topics={list(w['topics'].keys())} markets={list(w['markets'].keys())}")
