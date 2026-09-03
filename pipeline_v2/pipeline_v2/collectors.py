# -*- coding: utf-8 -*-
"""
collectors.py — Ernest 每日市觀 WorldMonitor Phase 1 數據採集層
================================================================
全部數據源均為免費公開源、純 Python 標準庫（urllib / xml / csv / json），
每個數據源獨立 try/except，單源失敗唔會阻塞其他源。

數據源（已實測 2026-09-01，沙盒＝大陸 IP）：
  ① CNBC Quote API   行情主源（VIX/DXY/US10Y/金/油/銀/GDX/BTC/6 持倉股）
  ② FRED CSV         債息/美元指數每日收盤備份（DGS10/DGS2/DTWEXBGS）
  ③ 新浪 hq.sinajs    行情備援（必須帶 Referer，GBK 編碼）
  ④ ForexFactory JSON 經濟日曆（impact 等級）
  ⑤ 英文 RSS ×7      CNBC×5 / MarketWatch×2 / FXStreet / ForexLive(-L) / Mining / OilPrice / CoinTelegraph
  ⑥ 新浪 7x24        中文實況快訊
  ⑦ GDELT DOC 2.0    地緣專用（串行 + sleep 5.5s + 超時 120s + IPv4；失敗跳過用 RSS 頂）

⚠️ 已封不可用（唔好再試）：Yahoo Finance、Google News RSS、CME FedWatch、stooq、investing.com
"""
import json
import re
import csv
import io
import time
import socket
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

HKT = timezone(timedelta(hours=8))
UTC = timezone.utc

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# ------------------------------------------------------------------ 通用 HTTP
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(host, port, family=0, *args, **kw):
    """沙盒無 IPv6 出口，統一過濾為 IPv4（等同 curl -4）。"""
    res = _orig_getaddrinfo(host, port, socket.AF_INET, *args, **kw)
    return [r for r in res if r[0] == socket.AF_INET] or res
socket.getaddrinfo = _ipv4_only_getaddrinfo  # 模塊導入即生效


def http_get(url, timeout=25, retries=2, extra_headers=None):
    """純 urllib GET，返回 bytes；失敗返回 None（不拋異常）。"""
    headers = {
        "User-Agent": UA,
        "Accept": "application/json,application/xml,text/xml,text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9,zh-HK;q=0.8",
    }
    if extra_headers:
        headers.update(extra_headers)
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa
            last_err = e
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    print(f"  [HTTP-FAIL] {url[:78]} → {type(last_err).__name__}: {str(last_err)[:70]}")
    return None


def _num(s):
    """'4,444.31' / '4.776%' / 'UNCH' / '' → float | None"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("%", "").replace("+", "")
    if s in ("", "UNCH", "--", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ================================================================== ① CNBC 行情
CNBC_URL = ("https://quote.cnbc.com/quote-html-webservice/restQuote/"
            "symbolType/symbol?symbols={syms}&requestMethod=itv&noform=1"
            "&partnerId=2&fund=1&exthrs=1&output=json")

# 面板符號 → 內部 key
CNBC_SYMBOLS = {
    ".VIX": "VIX",
    ".DXY": "DXY",
    "US10Y": "US10Y",
    "US2Y": "US2Y",
    "XAU=": "XAU",        # 現貨金（XAUUSD EA 對標）
    "XAG=": "XAG",        # 現貨白銀（XAGUSD EA 對標）
    "@GC.1": "GOLD_FUT",  # COMEX 期金（備）
    "@CL.1": "WTI",       # WTI 原油期貨
    "@SI.1": "SILVER_FUT",
    "GDX": "GDX",
    "BTC.CM=": "BTC",
    # 持倉股
    "SBTU": "SBTU", "VEEV": "VEEV", "FND": "FND",
    "TEX": "TEX", "UHS": "UHS", "ILMN": "ILMN",
}


def fetch_cnbc_quotes():
    """批量報價。返回 (quotes_dict, raw_list)；失敗 ({}, [])。"""
    syms = "|".join(CNBC_SYMBOLS.keys())
    url = CNBC_URL.format(syms=urllib.request.quote(syms, safe="|=.@"))
    data = http_get(url, timeout=25, retries=2)
    quotes, raw = {}, []
    if not data:
        return quotes, raw
    try:
        j = json.loads(data.decode("utf-8", errors="ignore"))
        res = j.get("FormattedQuoteResult", {}).get("FormattedQuote", [])
        if isinstance(res, dict):
            res = [res]
        for q in res:
            if str(q.get("code", "0")) != "0":
                continue
            sym = q.get("symbol", "")
            key = CNBC_SYMBOLS.get(sym, sym)
            last = _num(q.get("last"))
            prev = _num(q.get("previous_day_closing"))
            chg_pct = _num(q.get("change_pct"))
            item = {
                "symbol": sym,
                "key": key,
                "name": q.get("name") or q.get("shortName") or "",
                "last": last,
                "change": _num(q.get("change")),
                "change_pct": chg_pct,
                "prev_close": prev,
                "open": _num(q.get("open")),
                "high": _num(q.get("high")),
                "low": _num(q.get("low")),
                "real_time": str(q.get("realTime", "")).lower() == "true",
                "mkt_status": q.get("curmktstatus", ""),
                "last_timedate": q.get("last_timedate", ""),
                "currency": q.get("currencyCode", "USD"),
                "source": "CNBC",
            }
            # US10Y/US2Y 升跌 bp =（last − prev_close）×100（收益率單位為 %）
            if key in ("US10Y", "US2Y") and last is not None and prev is not None:
                item["change_bp"] = round((last - prev) * 100, 1)
            else:
                item["change_bp"] = None
            quotes[key] = item
            raw.append(item)
    except Exception as e:
        print(f"  [CNBC] 解析失敗: {type(e).__name__}: {str(e)[:80]}")
    return quotes, raw


# ================================================================== ② FRED CSV
FRED_SERIES = {"DGS10": "US10Y_FRED", "DGS2": "US2Y_FRED", "DTWEXBGS": "DXY_FRED"}


def fetch_fred():
    """每日收盤備份（滯後約 1 日）。返回 {key: {date, value, prev_date, prev_value, change_bp?}}"""
    out = {}
    for sid, key in FRED_SERIES.items():
        try:
            data = http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                            timeout=30, retries=1)
            if not data:
                continue
            rows = [r for r in csv.DictReader(io.StringIO(data.decode("utf-8")))
                    if r.get(sid) and r[sid] != "."]
            if len(rows) >= 2:
                last_row, prev_row = rows[-1], rows[-2]
                val = float(last_row[sid])
                prev_val = float(prev_row[sid])
                entry = {
                    "series": sid, "date": last_row["observation_date"],
                    "value": val, "prev_date": prev_row["observation_date"],
                    "prev_value": prev_val, "source": "FRED",
                }
                if sid.startswith("DGS"):
                    entry["change_bp"] = round((val - prev_val) * 100, 1)
                else:
                    entry["change_pct"] = round((val - prev_val) / prev_val * 100, 3)
                out[key] = entry
        except Exception as e:
            print(f"  [FRED-{sid}] 失敗: {type(e).__name__}: {str(e)[:60]}")
    return out


# ================================================================== ③ 新浪備援
SINA_FUT = {"hf_VX": "VIX", "hf_GC": "GOLD_FUT", "hf_CL": "WTI",
            "hf_SI": "SILVER_FUT", "hf_NG": "NATGAS"}


def fetch_sina_quotes():
    """新浪期貨行情備援（GBK）。返回 {key: {last, prev_close, time, source:'Sina'}}"""
    out = {}
    try:
        url = "https://hq.sinajs.cn/list=" + ",".join(SINA_FUT.keys())
        data = http_get(url, timeout=12, retries=1,
                        extra_headers={"Referer": "https://finance.sina.com.cn"})
        if not data:
            return out
        text = data.decode("gbk", errors="ignore")
        for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', text):
            code, payload = m.group(1), m.group(2)
            key = SINA_FUT.get(code)
            if not key or not payload:
                continue
            f = payload.split(",")
            # 新浪期貨：0=最新價 ... 7=昨結算, 日期/時間在 f[12]/f[6] 附近（欄位隨品種略有差異）
            try:
                out[key] = {
                    "last": float(f[0]),
                    "prev_close": float(f[7]) if len(f) > 7 and f[7] else None,
                    "time": f"{f[12]} {f[6]}" if len(f) > 12 else "",
                    "name": f[13] if len(f) > 13 else code,
                    "source": "Sina",
                }
            except (ValueError, IndexError):
                continue
    except Exception as e:
        print(f"  [Sina-quote] 失敗: {type(e).__name__}: {str(e)[:60]}")
    return out


# ================================================================== ④ 經濟日曆
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def fetch_economic_calendar(window_hours=(24, 48)):
    """ForexFactory 本週日曆 → 未來 24h / 24-48h High impact 事件。
    返回 {'next24h': [...], 'next48h': [...], 'all_high': [...]}，時間已轉 HKT。"""
    out = {"next24h": [], "next48h": [], "all_high": []}
    data = http_get(FF_URL, timeout=20, retries=2)
    if not data:
        return out
    try:
        events = json.loads(data.decode("utf-8", errors="ignore"))
        now_hkt = datetime.now(HKT)
        for e in events:
            if e.get("impact") != "High":
                continue
            try:
                dt = datetime.fromisoformat(e["date"]).astimezone(HKT)
            except Exception:
                continue
            delta_h = (dt - now_hkt).total_seconds() / 3600
            item = {
                "title": e.get("title", ""),
                "country": e.get("country", ""),
                "time_hkt": dt.strftime("%Y-%m-%d %H:%M"),
                "time_hm": dt.strftime("%H:%M"),
                "date_label": dt.strftime("%m/%d"),
                "delta_hours": round(delta_h, 1),
                "forecast": e.get("forecast", ""),
                "previous": e.get("previous", ""),
                "impact": "High",
                "source": "ForexFactory",
            }
            out["all_high"].append(item)
            if -1 <= delta_h <= window_hours[0]:
                out["next24h"].append(item)
            elif window_hours[0] < delta_h <= window_hours[1]:
                out["next48h"].append(item)
        out["next24h"].sort(key=lambda x: x["delta_hours"])
        out["next48h"].sort(key=lambda x: x["delta_hours"])
        out["all_high"].sort(key=lambda x: x["delta_hours"])
    except Exception as e:
        print(f"  [ForexFactory] 解析失敗: {type(e).__name__}: {str(e)[:60]}")
    return out


# ================================================================== ⑤ 英文 RSS
RSS_FEEDS = [
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC"),
    ("https://www.cnbc.com/id/20910258/device/rss/rss.html", "CNBC Economy"),
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html", "CNBC Finance"),
    ("https://www.cnbc.com/id/15839135/device/rss/rss.html", "CNBC Investing"),
    ("https://www.cnbc.com/id/100727362/device/rss/rss.html", "CNBC World"),
    ("https://feeds.content.dowjones.io/public/rss/mw_topstories", "MarketWatch"),
    ("https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "MarketWatch"),
    ("https://www.fxstreet.com/rss/news", "FXStreet"),
    ("https://www.forexlive.com/feed", "ForexLive"),   # 需 -L 跟重定向
    ("https://www.mining.com/feed/", "Mining.com"),
    ("https://oilprice.com/rss/main", "OilPrice"),
    ("https://cointelegraph.com/rss", "CoinTelegraph"),
]


def _strip_tag(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_pubdate(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None


def fetch_rss(feeds=None):
    """抓全部英文 RSS。返回新聞 list（dict）；單 feed 失敗跳過。"""
    feeds = feeds or RSS_FEEDS
    items, seen_urls = [], set()
    for url, source in feeds:
        try:
            data = http_get(url, timeout=14, retries=0)  # urllib 默認會跟 301/302；單源失敗即跳
            if not data:
                continue
            root = ET.fromstring(data)
            n = 0
            for it in root.iter("item"):
                title = _strip_tag((it.findtext("title") or ""))
                link = (it.findtext("link") or "").strip()
                desc = _strip_tag(it.findtext("description") or "")
                pub = _parse_pubdate(it.findtext("pubDate") or "")
                if not title or not link or link in seen_urls:
                    continue
                seen_urls.add(link)
                items.append({
                    "title": title,
                    "url": link,
                    "snippet": desc[:300],
                    "source": source,
                    "published": pub.astimezone(UTC).isoformat() if pub else None,
                    "lang": "en",
                })
                n += 1
            print(f"  [RSS] {source:14s} → {n} 條")
        except Exception as e:
            print(f"  [RSS] {source:14s} 失敗: {type(e).__name__}: {str(e)[:50]}")
    return items


# ================================================================== ⑥ 新浪 7x24
SINA_7X24 = ("https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=60"
             "&zhibo_id=152&tag_id=0&dire=f&dpc=1&pagesize=60")


def fetch_sina_7x24():
    """中文實況快訊。返回新聞 list。"""
    items = []
    try:
        data = http_get(SINA_7X24, timeout=12, retries=1,
                        extra_headers={"Referer": "https://finance.sina.com.cn"})
        if not data:
            return items
        j = json.loads(data.decode("utf-8", errors="ignore"))
        feed = j.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
        for entry in feed:
            text = (entry.get("rich_text") or "").strip()
            if not text or len(text) < 10:
                continue
            m = re.match(r"【([^】]+)】", text)
            if m:
                title, snippet = m.group(1), text[len(m.group(0)):].strip()[:200]
            else:
                title, snippet = text[:80], text[:200]
            ct = (entry.get("create_time") or "").strip()
            pub = None
            try:
                pub = datetime.strptime(ct, "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT).astimezone(UTC)
            except Exception:
                pass
            items.append({
                "title": title[:200],
                "url": (entry.get("docurl") or "https://finance.sina.com.cn/7x24/").strip(),
                "snippet": snippet,
                "source": "新浪7x24",
                "published": pub.isoformat() if pub else None,
                "lang": "zh",
            })
        print(f"  [新浪7x24] → {len(items)} 條")
    except Exception as e:
        print(f"  [新浪7x24] 失敗: {type(e).__name__}: {str(e)[:60]}")
    return items


# ================================================================== ⑦ GDELT
GDELT_QUERIES = [
    ("hormuz", "(Hormuz OR Iran) AND (tanker OR seizure OR blockade OR strait OR attack OR navy)"),
    ("redsea", "(Red Sea OR Houthi OR Yemen OR Bab el-Mandeb OR Suez) AND (ship OR shipping OR attack OR vessel)"),
    ("taiwan", "(Taiwan OR Taiwan Strait) AND (military OR drill OR exercise OR blockade OR PLA OR navy)"),
    ("fed",    "(Federal Reserve OR Powell OR FOMC) AND (rate cut OR rate hike OR hawkish OR dovish OR interest rate)"),
]


def _gdelt_seendate(s):
    """'20260831T080000Z' → datetime(UTC)"""
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except Exception:
        return None


def fetch_gdelt(enable=True):
    """4 組地緣查詢，串行 + sleep 5.5s，超時 120s。失敗跳過（由 RSS 補頂）。"""
    items = []
    if not enable:
        print("  [GDELT] 已停用（--no-gdelt），地緣新聞由 RSS 補頂")
        return items
    for i, (tag, query) in enumerate(GDELT_QUERIES):
        if i > 0:
            time.sleep(5.5)  # 限速：每 5 秒最多 1 請求
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query="
               + urllib.request.quote(query)
               + "&mode=artlist&format=json&timespan=24h&maxrecords=10&sort=hybridrel")
        try:
            print(f"  [GDELT] {tag} 查詢中（TLS 可能 ~35s）…")
            data = http_get(url, timeout=120, retries=0)
            if not data:
                print(f"  [GDELT] {tag} 失敗/超時，跳過")
                continue
            j = json.loads(data.decode("utf-8", errors="ignore"))
            arts = j.get("articles", [])
            n = 0
            for a in arts:
                title = (a.get("title") or "").strip()
                if not title:
                    continue
                pub = _gdelt_seendate(a.get("seendate", ""))
                items.append({
                    "title": title[:300],
                    "url": a.get("url", ""),
                    "snippet": "",
                    "source": f"GDELT/{a.get('domain','')}",
                    "published": pub.isoformat() if pub else None,
                    "lang": a.get("language", "eng"),
                    "sourcecountry": a.get("sourcecountry", ""),
                    "gdelt_tag": tag,
                })
                n += 1
            print(f"  [GDELT] {tag} → {n} 條")
        except Exception as e:
            print(f"  [GDELT] {tag} 異常: {type(e).__name__}: {str(e)[:60]}")
    return items


# ================================================================== 彙總入口
def _safe(name, fn, status):
    try:
        return fn()
    except Exception as e:
        status[name] = f"FAIL: {type(e).__name__}: {str(e)[:50]}"
        print(f"[{name}] 未捕獲異常: {type(e).__name__}: {str(e)[:80]}")
        return None


def collect_all(use_gdelt=True):
    """一次過採集全部源（行情/日曆/RSS 並行；GDELT 串行最後做）。返回單一 dict。"""
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.time()
    now = datetime.now(HKT)
    status = {}
    bundle = {
        "collected_at": now.isoformat(),
        "collected_at_hkt": now.strftime("%Y-%m-%d %H:%M HKT"),
        "sources_status": status,
        "quotes": {}, "quotes_raw": [], "fred": {}, "sina_quotes": {},
        "calendar": {"next24h": [], "next48h": [], "all_high": []},
        "news": [],
    }

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_cnbc = ex.submit(_safe, "cnbc", fetch_cnbc_quotes, status)
        f_fred = ex.submit(_safe, "fred", fetch_fred, status)
        f_sinaq = ex.submit(_safe, "sina_quotes", fetch_sina_quotes, status)
        f_cal = ex.submit(_safe, "forexfactory", fetch_economic_calendar, status)
        f_rss = ex.submit(_safe, "rss", fetch_rss, status)
        f_sina7 = ex.submit(_safe, "sina7x24", fetch_sina_7x24, status)

        q = f_cnbc.result()
        if q:
            bundle["quotes"], bundle["quotes_raw"] = q
            status["cnbc"] = f"OK · {len(bundle['quotes'])} 符號"
        else:
            status.setdefault("cnbc", "FAIL")
        fred = f_fred.result()
        if fred:
            bundle["fred"] = fred
            status["fred"] = f"OK · {len(fred)} 系列"
        else:
            status.setdefault("fred", "FAIL")
        sq = f_sinaq.result()
        if sq:
            bundle["sina_quotes"] = sq
            status["sina_quotes"] = f"OK · {len(sq)} 品種（備援）"
        else:
            status.setdefault("sina_quotes", "FAIL")
        cal = f_cal.result()
        if cal:
            bundle["calendar"] = cal
            status["forexfactory"] = f"OK · 未來24h {len(cal.get('next24h', []))} 個 High 事件"
        else:
            status.setdefault("forexfactory", "FAIL")

        news = []
        rss_items = f_rss.result()
        if rss_items:
            news.extend(rss_items)
        s7 = f_sina7.result()
        if s7:
            news.extend(s7)

    # ⑦ GDELT（限速 5s/請求，必須串行；放最後，失敗由 RSS 補頂）
    g = _safe("gdelt", lambda: fetch_gdelt(enable=use_gdelt), status) or []
    news.extend(g)
    if g:
        status["gdelt"] = f"OK · {len(g)} 條"
    else:
        status.setdefault("gdelt", "SKIP/FAIL（RSS 補頂）")

    # 按時間排序（最新在前），去重
    seen, deduped = set(), []
    for it in sorted(news, key=lambda x: x.get("published") or "", reverse=True):
        u = it.get("url") or it.get("title", "")[:60]
        if u in seen:
            continue
        seen.add(u)
        deduped.append(it)
    bundle["news"] = deduped
    bundle["elapsed_sec"] = round(time.time() - t0, 1)
    print(f"\n[collectors] 完成：{len(deduped)} 條新聞、{len(bundle['quotes'])} 報價、"
          f"耗時 {bundle['elapsed_sec']}s")
    return bundle


if __name__ == "__main__":
    import sys
    b = collect_all(use_gdelt=("--no-gdelt" not in sys.argv))
    print(json.dumps(b["sources_status"], ensure_ascii=False, indent=1))
