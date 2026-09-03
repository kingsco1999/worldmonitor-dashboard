# -*- coding: utf-8 -*-
"""
thermometer.py — 風險溫度計（嚴格照 投資內容規格 §3.2 七格評分表）
================================================================
權重：VIX 25 / US10Y 15 / DXY 15 / BTC 15 / GDX 10 / 金 10 / 油 10（總分 100）
Regime：0-30 🟢進攻 / 31-60 ⚪中性 / 61-80 🟠避險 / 81+ 🔴危機
金同油為 context-aware（要睇 VIX/DXY 方向）。
"""


def _pct(quote):
    """安全取 change_pct（%）。"""
    if not quote:
        return None
    return quote.get("change_pct")


def _last(quote):
    return quote.get("last") if quote else None


def score_thermometer(quotes, fred=None):
    """quotes: collectors 嘅 quotes dict（key: VIX/DXY/US10Y/GDX/XAU/WTI/BTC...）
    返回 {total, regime, cells:[...]}"""
    vix_q = quotes.get("VIX")
    dxy_q = quotes.get("DXY")
    us10_q = quotes.get("US10Y")
    gdx_q = quotes.get("GDX")
    xau_q = quotes.get("XAU") or quotes.get("GOLD_FUT")
    wti_q = quotes.get("WTI")
    btc_q = quotes.get("BTC")

    vix = _last(vix_q)
    vix_chg = _pct(vix_q) or 0.0
    dxy_chg = _pct(dxy_q) or 0.0
    btc_chg = _pct(btc_q) or 0.0
    gdx_chg = _pct(gdx_q) or 0.0
    gold_chg = _pct(xau_q) or 0.0
    oil_chg = _pct(wti_q) or 0.0

    # US10Y bp：CNBC 實時優先，否則 FRED 每日收盤
    bp = None
    us10_src = "CNBC"
    if us10_q and us10_q.get("change_bp") is not None:
        bp = us10_q["change_bp"]
    elif fred and fred.get("US10Y_FRED"):
        bp = fred["US10Y_FRED"].get("change_bp")
        us10_src = "FRED"
    abs_bp = abs(bp) if bp is not None else 0.0

    cells = []

    # ---------- VIX（25 分）----------
    if vix is not None and (vix < 13 or vix_chg < 0):
        s, note = 0, "VIX 低位或單日下跌，風險情緒平穩"
    elif vix is not None and (vix > 30 or vix_chg >= 20):
        s, note = 25, "VIX 極高或單日 +20% 以上，恐慌爆發"
    elif vix is not None and vix >= 25:
        s, note = 20, "VIX 25-30，避險升溫"
    elif vix is not None and vix >= 18:
        s, note = 15, "VIX 18-25，警覺區"
    else:
        s, note = 8, "VIX 13-18，溫和"
    cells.append({"key": "VIX", "label": "VIX 恐慌", "weight": 25,
                  "value": vix, "chg": vix_chg, "chg_unit": "%",
                  "score": s, "note": note})

    # ---------- US10Y（15 分）----------
    if abs_bp >= 15:
        s, note = 15, f"美債10Y 單日變幅 {abs_bp:.1f}bp 急動"
    elif abs_bp >= 10 and vix_chg > 0:
        s, note = 12, f"美債10Y 變幅 {abs_bp:.1f}bp 且 VIX 同日上升"
    elif abs_bp >= 5:
        s, note = 7, f"美債10Y 變幅 {abs_bp:.1f}bp（5-10bp）"
    else:
        s, note = 3, f"美債10Y 變幅 {abs_bp:.1f}bp <5bp，平穩"
    cells.append({"key": "US10Y", "label": "美債 10Y", "weight": 15,
                  "value": _last(us10_q), "chg": bp, "chg_unit": "bp",
                  "score": s, "note": note + f"（{us10_src}）"})

    # ---------- DXY（15 分）----------
    if dxy_chg < -0.3:
        s, note = 0, "美元單日跌 >0.3%，流動性寬鬆"
    elif dxy_chg > 1.2:
        s, note = 15, "美元單日漲 >1.2%，流動性緊縮"
    elif dxy_chg > 0.7:
        s, note = 13, "美元單日漲 0.7-1.2%，明顯走強"
    elif dxy_chg > 0.3:
        s, note = 10, "美元單日漲 0.3-0.7%，溫和走強"
    else:
        s, note = 5, "美元 ±0.3% 以內，平穩"
    cells.append({"key": "DXY", "label": "美元 DXY", "weight": 15,
                  "value": _last(dxy_q), "chg": dxy_chg, "chg_unit": "%",
                  "score": s, "note": note})

    # ---------- BTC（15 分）----------
    if btc_chg > 1:
        s, note = 0, "BTC 單日漲 >1%，高 beta 風險偏好強"
    elif btc_chg < -6:
        s, note = 15, "BTC 單日跌 >6%，風險資產急挫"
    elif btc_chg < -3:
        s, note = 13, "BTC 單日跌 3-6%"
    elif btc_chg < -1:
        s, note = 10, "BTC 單日跌 1-3%"
    else:
        s, note = 5, "BTC ±1% 以內，橫行"
    cells.append({"key": "BTC", "label": "比特幣", "weight": 15,
                  "value": _last(btc_q), "chg": btc_chg, "chg_unit": "%",
                  "score": s, "note": note})

    # ---------- GDX（10 分）----------
    if gdx_chg > 1:
        s, note = 0, "金礦股漲 >1%，金牛市獲風險確認"
    elif gdx_chg < -2.5:
        s, note = 10, "金礦股跌 >2.5%，金缺風險確認"
    elif gdx_chg < -1:
        s, note = 6, "金礦股跌 1-2.5%"
    elif abs(gdx_chg) <= 1:
        s, note = 3, "金礦股 ±1% 以內"
    else:
        s, note = 3, "金礦股平穩"
    cells.append({"key": "GDX", "label": "金礦 GDX", "weight": 10,
                  "value": _last(gdx_q), "chg": gdx_chg, "chg_unit": "%",
                  "score": s, "note": note})

    # ---------- 金（10 分，context-aware）----------
    if gold_chg < -2 and dxy_chg > 0.7:
        s, note = 10, "金急跌 >2% 且美元急升，流動性緊縮拋售"
    elif gold_chg < -1 and vix_chg < 0:
        s, note = 0, "金跌 >1% 且 VIX 跌，risk-on 回吐"
    elif gold_chg > 1 and vix_chg > 0:
        s, note = 9, "金漲 >1% 且 VIX 升，真避險需求"
    elif gold_chg > 1 and vix_chg <= 0:
        s, note = 3, "金漲 >1% 但 VIX 跌，金獨立牛市非避險"
    elif abs(gold_chg) <= 1:
        s, note = 4, "金 ±1% 以內"
    else:
        s, note = 4, "金波動但信號混合"
    cells.append({"key": "XAU", "label": "黃金 XAU", "weight": 10,
                  "value": _last(xau_q), "chg": gold_chg, "chg_unit": "%",
                  "score": s, "note": note})

    # ---------- 油（10 分，兩端皆風險）----------
    if oil_chg > 3:
        s, note = 9, "油漲 >3%，供應衝擊/滯脹風險"
    elif oil_chg < -3 and vix_chg > 0:
        s, note = 9, "油跌 >3% 且 VIX 升，需求崩塌/衰退交易"
    elif oil_chg < -3 and vix_chg <= 0:
        s, note = 2, "油跌 >3% 但 VIX 跌，風險偏好"
    elif oil_chg > 1.5:
        s, note = 5, "油漲 1.5-3%，溫和通脹"
    elif abs(oil_chg) <= 1.5:
        s, note = 3, "油 ±1.5% 以內"
    else:
        s, note = 3, "油溫和波動"
    cells.append({"key": "WTI", "label": "WTI 原油", "weight": 10,
                  "value": _last(wti_q), "chg": oil_chg, "chg_unit": "%",
                  "score": s, "note": note})

    total = sum(c["score"] for c in cells)
    if total <= 30:
        regime, icon, label = "risk-on", "🟢", "進攻模式"
    elif total <= 60:
        regime, icon, label = "neutral", "⚪", "中性"
    elif total <= 80:
        regime, icon, label = "risk-off", "🟠", "避險模式"
    else:
        regime, icon, label = "crisis", "🔴", "極端避險/危機"

    return {
        "total": total,
        "regime": regime,
        "regime_icon": icon,
        "regime_label": label,
        "cells": cells,
        "needle_pct": min(100, total),
    }


if __name__ == "__main__":
    # 用 spike 樣本數據自測
    import json, os
    sample = os.path.join(os.path.dirname(__file__), "..", "data_spike", "samples", "cnbc_quotes.json")
    d = json.load(open(sample))
    qres = d["FormattedQuoteResult"]["FormattedQuote"]
    from collectors import CNBC_SYMBOLS, _num
    quotes = {}
    for q in qres:
        key = CNBC_SYMBOLS.get(q.get("symbol"))
        if not key:
            continue
        quotes[key] = {"last": _num(q.get("last")), "change_pct": _num(q.get("change_pct")),
                       "change_bp": (round((_num(q["last"]) - _num(q["previous_day_closing"])) * 100, 1)
                                     if key in ("US10Y", "US2Y") and _num(q.get("last")) and _num(q.get("previous_day_closing")) else None)}
    r = score_thermometer(quotes)
    print(f"總分 {r['total']} {r['regime_icon']} {r['regime_label']}")
    for c in r["cells"]:
        print(f"  {c['label']:8s} 值 {c['value']}  變 {c['chg']}{c['chg_unit']:>3} → {c['score']:>2}/{c['weight']}  {c['note']}")
