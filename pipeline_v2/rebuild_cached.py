"""快速重建：用 data_v2 內 cached 新聞＋報價重跑事件引擎/溫度計/Brief/渲染，唔使重新採集。
用法：python3 pipeline_v2/rebuild_cached.py [evening|morning]
"""
import os, sys, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import event_engine
import thermometer as thermo_mod
import brief_builder
import run_v2
from render_v2 import render_html, merge_holdings

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data_v2")
OUT_DIR = os.path.join(BASE, "output")
HKT = timezone(timedelta(hours=8))
WEEKDAY_ZH = "一二三四五六日"

edition = sys.argv[1] if len(sys.argv) > 1 else "evening"
edition_label = "晨間版" if edition == "morning" else "晚間版"
now = datetime.now(HKT)

# 1) 讀 cached
with open(os.path.join(DATA_DIR, "news_latest.json"), encoding="utf-8") as f:
    news = json.load(f)
with open(os.path.join(DATA_DIR, "dashboard_latest.json"), encoding="utf-8") as f:
    cached = json.load(f)
old_dd = cached["dash_data"]
bundle_no_news = cached.get("bundle", {})

# 報價：由舊 dash_data quotes_slim 還原 quotes 結構（引擎/溫度計只需 last/change_pct/change_bp/prev_close/high/low/mkt_status）
quotes = {k: dict(v) for k, v in old_dd["quotes"].items()}
calendar = old_dd["calendar"]

print(f"[rebuild] cached 新聞 {len(news)} 條、報價 {len(quotes)} 個")

# 2) 事件引擎（重跑，用新規則）
eng = event_engine.run_event_engine(news, now=now)
events, arcs = eng["events"], eng["arcs"]
print(f"[rebuild] 事件 {len(events)} 個、弧線 {len(arcs)} 條；統計：{ {k:v for k,v in eng['counts'].items() if v} }")
for e in events:
    print(f"   {e.get('etype')} @ {e.get('loc_name')} ({e.get('lat')},{e.get('lng')}) sev={e.get('severity')} | {e.get('headline','')[:60]}")

# 3) 溫度計（沿用 cached 分數，報價結構 slim 都夠用）
thermo = thermo_mod.score_thermometer(quotes, fred=bundle_no_news.get("fred"))
print(f"[rebuild] 溫度計 {thermo['total']} 分 {thermo.get('regime_icon','')} {thermo.get('regime_label','')}")

# 4) 持倉合併＋歸因
holdings_doc = run_v2.load_holdings()
holdings = merge_holdings(holdings_doc, quotes)
for h in holdings:
    chg = h.get("change_pct")
    th = 6.0 if h["code"] == "SBTU" else 3.0
    if chg is not None and abs(chg) >= th:
        attrib, hit = brief_builder.attribute_holding(h["code"], news)
        h["attrib"] = attrib
        h["attrib_found"] = hit is not None
    else:
        h["attrib"] = ""
        h["attrib_found"] = False
    h["is_new"] = False

# 5) Brief
brief = brief_builder.build_brief(edition, events, quotes, thermo,
                                  calendar, holdings, news, now=now)
print(f"[rebuild] Brief {len(brief)} 點")

# 6) 組裝
next24 = calendar.get("next24h", [])
next_event = None
if next24:
    e = next24[0]
    dt = datetime.strptime(e["time_hkt"], "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
    next_event = {**e, "iso": dt.isoformat()}

regime_sub_map = {
    "risk-on": "RISK-ON · EA 正常運行，趨勢策略順風",
    "neutral": "NEUTRAL · EA 正常，避開 🔴 事件窗口",
    "risk-off": "RISK-OFF · 建議暫停高 beta EA、收窄倉位",
    "crisis": "CRISIS · 全部 EA 暫停，僅保留觀察",
}

# 6.5) NEWS ⇄ MARKETS 關聯數據：有獨立緩存就讀（news_markets.py 採集），否則帶舊值/空殼
market_corr = {"ok": False, "windows": {}, "topics_meta": [], "markets_meta": [], "generated": ""}
try:
    import news_markets as _nm
    if os.path.exists(_nm.CACHE_PATH):
        with open(_nm.CACHE_PATH, encoding="utf-8") as f:
            market_corr = json.load(f)
        print(f"[rebuild] market_corr ok={market_corr.get('ok')} · {market_corr.get('generated','')}")
except Exception as e:  # noqa
    print(f"[rebuild] market_corr 讀取失敗（唔阻塞）: {type(e).__name__}: {str(e)[:60]}")

dash_data = dict(old_dd)
dash_data.update({
    "market_corr": market_corr,
    "generated_iso": now.isoformat(),
    "date_str": now.strftime("%Y-%m-%d"),
    "date_parts": {"y": now.year, "m": now.month, "d": now.day},
    "weekday": "星期" + WEEKDAY_ZH[now.weekday()],
    "edition": edition,
    "edition_label": edition_label,
    "quotes": old_dd["quotes"],
    "thermo": thermo,
    "regime_sub": regime_sub_map.get(thermo["regime"], old_dd.get("regime_sub", "")),
    "events": events,
    "arcs": arcs,
    "calendar": calendar,
    "next_event": next_event,
    "fed_chip": run_v2.build_fed_chip(calendar, quotes, now),
    "holdings": [{k: h.get(k) for k in
                  ("code", "name_cn", "account_type", "group", "status", "nature",
                   "last", "change_pct", "prev_close", "high", "low", "cost_price",
                   "pnl_cost_pct", "attrib", "attrib_found", "is_new", "notes")}
                 for h in holdings],
    "brief": brief,
    "feed": run_v2.build_feed(news, events),
    "event_counts": eng["counts"],
})

# 7) 存快照（bundle 保留舊嘅非新聞部分）
with open(os.path.join(DATA_DIR, "dashboard_latest.json"), "w", encoding="utf-8") as f:
    json.dump({"bundle": bundle_no_news, "dash_data": dash_data}, f,
              ensure_ascii=False, indent=1, default=str)

# 8) 渲染
stamp = now.strftime("%Y%m%d_%H%M")
out_name = os.path.join(OUT_DIR, f"dashboard_v2_{edition}_{stamp}.html")
render_html(dash_data, out_name)
render_html(dash_data, os.path.join(OUT_DIR, "dashboard_v2_latest.html"))
print(f"[rebuild] ✅ {out_name}")
print(f"[rebuild] ✅ output/dashboard_v2_latest.html")
