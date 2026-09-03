# -*- coding: utf-8 -*-
"""
brief_builder.py — 每日 Brief 規則生成器（照 投資內容規格 §2）
=============================================================
- 晨版（HKT<14:00）/ 晚版（HKT≥14:00），5 點為上限，每點 ≤40 個中文字
- 排序：🔴風險 > 💼持倉 > 🥇核心資產 > 📊溫度 > 🌏地緣
- 每點格式：[標籤] 事實一句｜如果…就…
- 持倉單日 ≥3% 強制入選（SBTU ≥6% 先入）；歸因＝新聞標題搜 ticker/SBET，
  搵唔到寫「⚠️ 未尋獲明確歸因，需人工查證」，禁止編造
"""
import re
from datetime import datetime, timezone, timedelta

HKT = timezone(timedelta(hours=8))

BRIEF_COLORS = {"risk": "#ff4d6d", "hold": "#ffb020", "core": "#ffd24a",
                "temp": "#9d8cff", "geo": "#2dd4ff"}
BRIEF_TAG = {"risk": "🔴", "hold": "💼", "core": "🥇", "temp": "📊", "geo": "🌏"}


def _zh_len(s):
    """中文字數（CJK 統一表意文字），英文/數字/符號不計。"""
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def _trim_zh(s, limit=40):
    """超長就硬截（保留完整標點為止）。"""
    if _zh_len(s) <= limit:
        return s
    out = ""
    n = 0
    for ch in s:
        if "\u4e00" <= ch <= "\u9fff":
            n += 1
        out += ch
        if n >= limit:
            break
    return out.rstrip("，。；、 ") + "…"


def _fmt_price(v, dec=2):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.{dec}f}"


def attribute_holding(ticker, news):
    """在新聞標題/摘要搜 ticker；SBTU 改搜 SBET。返回 (attribution_text, hit_title|None)。"""
    keys = [ticker.upper()]
    if ticker.upper() == "SBTU":
        keys = ["SBET", "SHARPLINK", "SHARP LINK"]
    if ticker.upper() == "XAUUSD":
        keys = ["GOLD", "XAU", "黃金", "金價"]
    if ticker.upper() == "XAGUSD":
        keys = ["SILVER", "XAG", "白銀", "銀價"]
    for it in news[:200]:
        text = f"{it.get('title','')} {it.get('snippet','')}".upper()
        for k in keys:
            if k.upper() in text:
                return it.get("title", "")[:80], it
    return "⚠️ 未尋獲明確歸因，需人工查證", None


def build_brief(edition, events, quotes, thermo, calendar, holdings, news, now=None):
    """生成 5 點 Brief。
    holdings: holdings.json 合併報價後嘅 list（dict 含 code/last/change_pct...）
    返回 list[5]：{no, cat, tag, color, txt, ifthen, tags:[...]}"""
    now = now or datetime.now(HKT)
    points = []  # (rank, dict)，rank 越細越前

    high_events = [e for e in events if e["severity"] == "high"]
    med_events = [e for e in events if e["severity"] == "med"]

    # ---------- 1) 🔴 風險事件（最高排序）----------
    n24 = calendar.get("next24h", []) if calendar else []
    if n24:
        ev = n24[0]
        when = f"{ev['time_hm']}"
        txt = _trim_zh(f"{ev['title']}（{ev['country']}）{when} 公佈，高影響事件臨近")
        ift = _trim_zh(f"如果 數據偏離預期，就 事件窗口前30分鐘暫停 EA、收窄倉位")
        points.append((1, {"cat": "risk", "txt": txt, "ifthen": ift,
                           "tags": ["📅 高影響", ev["title"][:12]]}))
    elif high_events:
        e = high_events[0]
        txt = _trim_zh(f"{e['name']}{e['etype_name']}：{e['headline'][:40]}")
        ift = _trim_zh(e["if_then"].replace("如果 ", "").replace("，就 ", "→")[:44])
        ift = "如果 " + e["if_then"].split("如果 ", 1)[-1]
        points.append((1, {"cat": "risk", "txt": txt,
                           "ifthen": _trim_zh(e["if_then"]),
                           "tags": [f"{a[0]}{a[1][-3:] if len(a[1])>3 else a[1]} {a[2]}" for a in e["assets"][:3]]}))

    # ---------- 2) 💼 持倉異動（≥3% 強制；SBTU ≥6%）----------
    movers = []
    for h in holdings:
        chg = h.get("change_pct")
        if chg is None:
            continue
        threshold = 6.0 if h["code"] == "SBTU" else 3.0
        if abs(chg) >= threshold:
            movers.append((abs(chg), h))
    movers.sort(key=lambda x: -x[0])
    for _, h in movers[:2]:
        chg = h["change_pct"]
        direction = "升" if chg > 0 else "跌"
        attrib, hit = attribute_holding(h["code"], news)
        txt = _trim_zh(f"{h['code']} 今日{direction}{abs(chg):.1f}%（{h.get('name_cn','')}）")
        if hit is None:
            ift = _trim_zh("如果 未尋獲明確歸因，就 人工查證後先決定操作（勿單靠價動作倉）")
        else:
            short = attrib[:24]
            ift = _trim_zh(f"如果 歸因「{short}」持續發酵，就 按板塊邏輯處理持倉")
        tags = [f"{'⚠️' if abs(chg)>=6 else ''}{h['code']} {'↑' if chg>0 else '↓'}{abs(chg):.1f}%"]
        points.append((2, {"cat": "hold", "txt": txt, "ifthen": ift,
                           "tags": tags, "attrib": attrib, "attrib_found": hit is not None}))

    # ---------- 3) 🥇 核心資產（金/油/BTC）----------
    xau = quotes.get("XAU")
    wti = quotes.get("WTI")
    btc = quotes.get("BTC")
    if edition == "morning":
        if xau and xau.get("last"):
            chg = xau.get("change_pct") or 0
            d = "升" if chg >= 0 else "跌"
            txt = _trim_zh(f"金價 ${_fmt_price(xau['last'],0)} 日內{d}{abs(chg):.1f}%，白銀聯動")
            ift = _trim_zh("如果 美元轉弱或避險升溫，就 金大概率試高位，XAU EA 順勢")
            points.append((3, {"cat": "core", "txt": txt, "ifthen": ift,
                               "tags": [f"🥇金 {'↑' if chg>=0 else '↓'}{abs(chg):.1f}%"]}))
    else:
        # 晚版：金銀油收盤 + 金銀比
        xag = quotes.get("XAG")
        ratio = None
        if xau and xag and xau.get("last") and xag.get("last"):
            ratio = xau["last"] / xag["last"]
        if xau and xau.get("last"):
            chg = xau.get("change_pct") or 0
            rt = f"金 ${_fmt_price(xau['last'],0)}"
            if ratio:
                rt += f"、金銀比 {ratio:.1f}"
            txt = _trim_zh(f"{rt}，油 ${_fmt_price(wti['last'],1) if wti else '—'}")
            ift = _trim_zh("如果 金銀比跌穿長期中位，就 白銀轉強，XAG EA 留意加倉")
            points.append((3, {"cat": "core", "txt": txt, "ifthen": ift,
                               "tags": [f"🥇金 {'↑' if chg>=0 else '↓'}{abs(chg):.1f}%"]}))
    if wti and wti.get("last") and len([p for p in points if p[1]["cat"] == "core"]) == 0:
        chg = wti.get("change_pct") or 0
        d = "升" if chg >= 0 else "跌"
        txt = _trim_zh(f"WTI 原油 ${_fmt_price(wti['last'],1)} 日內{d}{abs(chg):.1f}%")
        ift = _trim_zh("如果 中東無新升級，就 油維持區間；供應中斷則見高位")
        points.append((3, {"cat": "core", "txt": txt, "ifthen": ift,
                           "tags": [f"🛢️油 {'↑' if chg>=0 else '↓'}{abs(chg):.1f}%"]}))

    # ---------- 4) 📊 風險溫度 ----------
    if thermo:
        txt = _trim_zh(f"風險溫度 {thermo['total']} 分{thermo['regime_icon']}{thermo['regime_label']}")
        vix = quotes.get("VIX")
        vix_v = vix.get("last") if vix else None
        ift = _trim_zh(f"如果 VIX（{vix_v:.1f}）升穿 20，就 暫停高 beta 持倉；分數>80 即時全停 EA"
                       if vix_v else "如果 溫度越過閾值連續兩次，就 正式切換 regime")
        points.append((4, {"cat": "temp", "txt": txt, "ifthen": ift,
                           "tags": [f"{thermo['regime_icon']} {thermo['total']}/100"]}))

    # ---------- 5) 🌏 地緣（其餘中級事件 / 板塊關注）----------
    used_locs = {high_events[0]["name"]} if high_events else set()
    geo_added = False
    for e in med_events:
        if e["name"] in used_locs:
            continue
        txt = _trim_zh(f"{e['name']}：{e['headline'][:42]}")
        ift = _trim_zh(e["if_then"])
        points.append((5, {"cat": "geo", "txt": txt, "ifthen": ift,
                           "tags": [f"{a[0]} {a[2]}" for a in e["assets"][:2]]}))
        geo_added = True
        break
    if not geo_added and btc and btc.get("last"):
        chg = btc.get("change_pct") or 0
        txt = _trim_zh(f"₿ BTC ${_fmt_price(btc['last'],0)} 日內{'升' if chg>=0 else '跌'}{abs(chg):.1f}%，高 beta 風向標")
        ift = _trim_zh("如果 美股回落，就 留意 BTC 會否同步走資，SBTU 聯動 SBET")
        points.append((5, {"cat": "geo", "txt": txt, "ifthen": ift,
                           "tags": [f"₿ {'↑' if chg>=0 else '↓'}{abs(chg):.1f}%"]}))

    # 排序 + 截 5 點
    points.sort(key=lambda p: p[0])
    out = []
    for i, (_, p) in enumerate(points[:5]):
        p["no"] = f"BRIEF // {i+1:02d}"
        p["color"] = BRIEF_COLORS[p["cat"]]
        p["tag"] = BRIEF_TAG[p["cat"]]
        out.append(p)
    return out


if __name__ == "__main__":
    print("brief_builder 模塊自測：請透過 run_v2.py 整合測試")
