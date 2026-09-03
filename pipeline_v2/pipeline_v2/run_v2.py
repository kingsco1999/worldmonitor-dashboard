# -*- coding: utf-8 -*-
"""
run_v2.py — WorldMonitor Phase 1 主編排
=======================================
用法：
  python3 run_v2.py                # 自動按 HKT 判斷晨版(<14:00)/晚版(>=14:00)
  python3 run_v2.py --morning      # 強制晨版
  python3 run_v2.py --evening      # 強制晚版
  python3 run_v2.py --no-gdelt     # 跳過 GDELT（快，地緣由 RSS 補頂）

產出：
  data_v2/dashboard_latest.json    （完整數據快照）
  output/dashboard_v2_<edition>_YYYYMMDD_HHMM.html
  output/dashboard_v2_latest.html
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collectors
import event_engine
import thermometer as thermo_mod
import brief_builder
from render_v2 import render_html, merge_holdings

HKT = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data_v2")
OUT_DIR = os.path.join(ROOT, "output")

WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]

# 新聞 feed 主題標籤
THEME_RULES = [
    ("oil", ["oil", "crude", "wti", "opec", "brent", "油", "原油"]),
    ("gold", ["gold", "xau", "bullion", "金價", "黃金", "白银", "silver", "銀價"]),
    ("semi", ["semiconductor", "chip", "tsmc", "nvidia", "asml", "半導體", "芯片", "台積電"]),
    ("shipping", ["shipping", "tanker", "maersk", "freight", "航運", "貨櫃", "油輪"]),
    ("crypto", ["bitcoin", "btc", "ethereum", "eth", "crypto", "比特幣", "加密"]),
    ("geo", ["iran", "hormuz", "houthi", "red sea", "taiwan", "ukraine", "russia",
             "ceasefire", "war", "strike", "伊朗", "紅海", "台海", "烏克蘭", "俄", "停火"]),
    ("macro", ["fed", "powell", "fomc", "rate", "cpi", "pce", "payroll", "ecb",
               "聯儲", "減息", "加息", "通脹", "失業"]),
]


def theme_of(title):
    t = title.lower()
    for theme, kws in THEME_RULES:
        if any(k in t for k in kws):
            return theme
    return "stock"


def load_holdings():
    p = os.path.join(DATA_DIR, "holdings.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def build_fed_chip(calendar, quotes, now_hkt):
    """FedWatch 模擬 chip 替換：US10Y 實時 bp / 下一 FOMC 倒數。"""
    us10 = quotes.get("US10Y")
    bp_txt = ""
    if us10 and us10.get("change_bp") is not None:
        bp = us10["change_bp"]
        bp_txt = f"US10Y 今日 <b>{'+' if bp >= 0 else ''}{bp:.1f}bp</b>（CNBC 實時）"
    # 搵 FOMC/利率事件
    fomc = None
    for e in calendar.get("all_high", []):
        t = e["title"].lower()
        if any(k in t for k in ["fomc", "rate decision", "rate statement", "interest rate",
                                "monetary policy", "cash rate"]):
            if e["delta_hours"] > -1:
                fomc = e
                break
    if fomc:
        # 「今日」必須按日期判斷，唔可以淨係睇 delta<24h（夜晚跑、聽朝事件會誤判）
        ev_date = fomc.get("time_hkt", "")[:10]
        today_str = now_hkt.strftime("%Y-%m-%d")
        tomorrow_str = (now_hkt + timedelta(days=1)).strftime("%Y-%m-%d")
        if ev_date == today_str:
            when = "今日"
        elif ev_date == tomorrow_str:
            when = "明日"
        elif fomc.get("date_label"):
            when = fomc["date_label"]
        else:
            when = ev_date[5:].replace("-", "/")
        return (f"🤖 <span><b>EA 暫停提示：</b>{when} {fomc['time_hm']} {fomc['title']}"
                f"（{fomc['country']}）｜事件前 30 分鐘＋後 60 分鐘暫停 EA。{bp_txt}</span>")
    if bp_txt:
        return f"🤖 <span><b>EA 暫停提示：</b>🔴 高影響事件窗口前 30 分鐘＋後 60 分鐘一律暫停 EA；{bp_txt}。</span>"
    return "🤖 <span><b>EA 暫停提示：</b>🔴 高影響事件窗口前 30 分鐘＋後 60 分鐘一律暫停 EA。</span>"


def build_feed(news, events, limit=40):
    """新聞 feed：優先顯示已分類事件新聞，其餘按時間。"""
    event_urls = {e.get("url") for e in events}
    rows = []
    for it in news:
        pub = it.get("published")
        try:
            dt = datetime.fromisoformat(pub).astimezone(HKT) if pub else datetime.now(HKT)
        except Exception:
            dt = datetime.now(HKT)
        rows.append({
            "time_hm": dt.strftime("%m/%d %H:%M"),
            "source": it.get("source", "")[:14],
            "title": it.get("title", "")[:120],
            "url": it.get("url", ""),
            "theme": theme_of(it.get("title", "")),
            "is_event": it.get("url") in event_urls,
        })
    rows.sort(key=lambda r: (not r["is_event"], r["time_hm"]), reverse=False)
    rows.sort(key=lambda r: r["is_event"], reverse=True)
    return rows[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--morning", action="store_true")
    ap.add_argument("--evening", action="store_true")
    ap.add_argument("--no-gdelt", action="store_true")
    args = ap.parse_args()

    now = datetime.now(HKT)
    if args.morning:
        edition = "morning"
    elif args.evening:
        edition = "evening"
    else:
        edition = "morning" if now.hour < 14 else "evening"
    edition_label = "晨間版" if edition == "morning" else "晚間版"
    print(f"[run_v2] {now.strftime('%Y-%m-%d %H:%M HKT')} → {edition_label}")

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1) 採集
    bundle = collectors.collect_all(use_gdelt=(not args.no_gdelt))
    quotes = bundle["quotes"]

    # 2) 事件引擎
    eng = event_engine.run_event_engine(bundle["news"], now=now)
    events, arcs = eng["events"], eng["arcs"]
    print(f"[run_v2] 事件 {len(events)} 個、弧線 {len(arcs)} 條；"
          f"分類統計：{ {k:v for k,v in eng['counts'].items() if v} }")

    # 3) 溫度計
    thermo = thermo_mod.score_thermometer(quotes, fred=bundle.get("fred"))
    print(f"[run_v2] 溫度計 {thermo['total']} 分 {thermo['regime_icon']} {thermo['regime_label']}")

    # 4) 持倉合併＋歸因
    holdings_doc = load_holdings()
    holdings = merge_holdings(holdings_doc, quotes)
    # 歸因搜索（異動持倉）
    for h in holdings:
        chg = h.get("change_pct")
        th = 6.0 if h["code"] == "SBTU" else 3.0
        if chg is not None and abs(chg) >= th:
            attrib, hit = brief_builder.attribute_holding(h["code"], bundle["news"])
            h["attrib"] = attrib
            h["attrib_found"] = hit is not None
        else:
            h["attrib"] = ""
            h["attrib_found"] = False
        # 🆕 新開倉首 3 個交易日（open_date 記錄後先生效）
        h["is_new"] = False

    # 5) Brief
    brief = brief_builder.build_brief(edition, events, quotes, thermo,
                                      bundle["calendar"], holdings, bundle["news"], now=now)
    print(f"[run_v2] Brief {len(brief)} 點")
    for b in brief:
        print(f"   {b['tag']} ({b['txt'][:34]}…) 中文字數={brief_builder._zh_len(b['txt'])}")

    # 6) 組裝 DASH_DATA
    cal = bundle["calendar"]
    next24 = cal.get("next24h", [])
    next_event = None
    if next24:
        e = next24[0]
        dt = datetime.strptime(e["time_hkt"], "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
        next_event = {**e, "iso": dt.isoformat()}

    quotes_slim = {}
    for k, q in quotes.items():
        quotes_slim[k] = {
            "last": q.get("last"), "change_pct": q.get("change_pct"),
            "change_bp": q.get("change_bp"), "prev_close": q.get("prev_close"),
            "high": q.get("high"), "low": q.get("low"),
            "mkt_status": q.get("mkt_status"),
        }

    regime_sub_map = {
        "risk-on": "RISK-ON · EA 正常運行，趨勢策略順風",
        "neutral": "NEUTRAL · EA 正常，避開 🔴 事件窗口",
        "risk-off": "RISK-OFF · 建議暫停高 beta EA、收窄倉位",
        "crisis": "CRISIS · 全部 EA 暫停，僅保留觀察",
    }

    dash_data = {
        "generated_iso": now.isoformat(),
        "date_str": now.strftime("%Y-%m-%d"),
        "date_parts": {"y": now.year, "m": now.month, "d": now.day},
        "weekday": "星期" + WEEKDAY_ZH[now.weekday()],
        "edition": edition,
        "edition_label": edition_label,
        "quotes": quotes_slim,
        "thermo": thermo,
        "regime_sub": regime_sub_map[thermo["regime"]],
        "events": events,
        "arcs": arcs,
        "calendar": cal,
        "next_event": next_event,
        "fed_chip": build_fed_chip(cal, quotes, now),
        "holdings": [{k: h.get(k) for k in
                      ("code", "name_cn", "account_type", "group", "status", "nature",
                       "last", "change_pct", "prev_close", "high", "low", "cost_price",
                       "pnl_cost_pct", "attrib", "attrib_found", "is_new", "notes")}
                     for h in holdings],
        "watchlist": holdings_doc.get("watchlist", []),
        "trade_log": holdings_doc.get("trade_log", []),
        "brief": brief,
        "feed": build_feed(bundle["news"], events),
        "sources_status": bundle["sources_status"],
        "event_counts": eng["counts"],
    }

    # 6.5) NEWS ⇄ MARKETS 關聯數據（GDELT 慢，預設用緩存；--fresh-corr 先強制重抓）
    try:
        import news_markets
        dash_data["market_corr"] = news_markets.build_market_corr(
            use_cache="--fresh-corr" not in sys.argv)
        print(f"[run_v2] market_corr ok={dash_data['market_corr'].get('ok')}")
    except Exception as e:  # noqa
        print(f"[run_v2] market_corr 失敗（唔阻塞）: {type(e).__name__}: {str(e)[:80]}")
        dash_data["market_corr"] = {"ok": False, "windows": {}, "topics_meta": [],
                                    "markets_meta": [], "generated": ""}

    # 7) 存數據快照
    snap = os.path.join(DATA_DIR, "dashboard_latest.json")
    with open(snap, "w", encoding="utf-8") as f:
        json.dump({"bundle": {k: v for k, v in bundle.items() if k != "news"},
                   "dash_data": dash_data}, f, ensure_ascii=False, indent=1, default=str)
    # 也獨立存新聞快照
    with open(os.path.join(DATA_DIR, "news_latest.json"), "w", encoding="utf-8") as f:
        json.dump(bundle["news"], f, ensure_ascii=False, default=str)

    # 8) 渲染 HTML
    stamp = now.strftime("%Y%m%d_%H%M")
    out_name = os.path.join(OUT_DIR, f"dashboard_v2_{edition}_{stamp}.html")
    render_html(dash_data, out_name)
    latest = os.path.join(OUT_DIR, "dashboard_v2_latest.html")
    render_html(dash_data, latest)
    print(f"[run_v2] ✅ 成品：{out_name}")
    print(f"[run_v2] ✅ 最新：{latest}")


if __name__ == "__main__":
    main()
