# -*- coding: utf-8 -*-
"""
event_engine.py — 事件分類器 + 傳導矩陣 + 弧線生成
==================================================
規則來源：content_spec/投資內容規格_v1.0.md §1（12 事件型 E1-E12 × 13 資產傳導矩陣）

功能：
  1. 關鍵詞分類器：新聞標題/摘要 → E1-E12（映射唔到唔顯示）
  2. 嚴重度三級：🔴高(sw/red) / 🟠中(hot/amber) / 🔵參考(cb/cyan)
  3. 位置經緯度字典 → 地球標記
  4. 24h 同事件去重、>48h 下架
  5. 查矩陣 → 受影響資產＋方向強度 → 傳導鏈 chain（3 步）＋ assets 標籤
  6. 弧線：事件 → 市場樞紐（8-18 條，事件上限 6 個）
"""
import re
from datetime import datetime, timezone, timedelta

HKT = timezone(timedelta(hours=8))
UTC = timezone.utc

# ============================================================ 1. 傳導矩陣（§1.2）
# 方向：'↑↑' '↓↓' 強烈；'↑' '↓' 溫和；'—' 中性
MATRIX = {
    "E1": {"name": "中東武裝衝突升級",
           "dirs": {"gold": "↑", "silver": "↑", "oil": "↑↑", "natgas": "↑", "usd": "↑",
                    "us10y": "↑", "vix": "↑", "usstock": "↓", "hkstock": "↓", "semi": "↓",
                    "shipping": "↑", "btc": "↓"}},
    "E2": {"name": "霍爾木茲/海灣航道封鎖",
           "dirs": {"gold": "↑", "silver": "—", "oil": "↑↑", "natgas": "↑↑", "usd": "↑",
                    "us10y": "↑", "vix": "↑", "usstock": "↓", "hkstock": "↓", "semi": "↓",
                    "shipping": "↑↑", "btc": "↓"}},
    "E3": {"name": "紅海/蘇伊士航道中斷",
           "dirs": {"gold": "—", "silver": "—", "oil": "↑", "natgas": "—", "usd": "—",
                    "us10y": "—", "vix": "—", "usstock": "—", "hkstock": "—", "semi": "—",
                    "shipping": "↑", "btc": "—"}},
    "E4": {"name": "台海/東海地緣升溫",
           "dirs": {"gold": "↑", "silver": "—", "oil": "—", "natgas": "—", "usd": "—",
                    "us10y": "↓", "vix": "↑", "usstock": "↓", "hkstock": "↓↓", "semi": "↓↓",
                    "shipping": "—", "btc": "↓"}},
    "E5": {"name": "俄烏戰事升級",
           "dirs": {"gold": "↑", "silver": "—", "oil": "↑", "natgas": "↑↑", "usd": "↑",
                    "us10y": "—", "vix": "↑", "usstock": "↓", "hkstock": "—", "semi": "—",
                    "shipping": "—", "btc": "↓"}},
    "E6": {"name": "中美關稅升級",
           "dirs": {"gold": "↑", "silver": "↓", "oil": "↓", "natgas": "—", "usd": "↑",
                    "us10y": "↑", "vix": "↑", "usstock": "↓", "hkstock": "↓↓", "semi": "↓↓",
                    "shipping": "↓", "btc": "↓"}},
    "E7": {"name": "出口管制/金融制裁",
           "dirs": {"gold": "↑", "silver": "—", "oil": "—", "natgas": "—", "usd": "↑",
                    "us10y": "—", "vix": "↑", "usstock": "—", "hkstock": "↓", "semi": "↓",
                    "shipping": "—", "btc": "—"}},
    "E8": {"name": "央行意外鷹派（加息/縮表）",
           "dirs": {"gold": "↓", "silver": "↓", "oil": "—", "natgas": "—", "usd": "↑",
                    "us10y": "↑↑", "vix": "↑", "usstock": "↓", "hkstock": "↓", "semi": "↓↓",
                    "shipping": "—", "btc": "↓"}},
    "E9": {"name": "央行意外鴿派（減息/放水）",
           "dirs": {"gold": "↑", "silver": "↑", "oil": "↑", "natgas": "—", "usd": "↓",
                    "us10y": "↓", "vix": "↓", "usstock": "↑", "hkstock": "↑", "semi": "↑",
                    "shipping": "—", "btc": "↑"}},
    "E10": {"name": "衰退型數據爆冷",
            "dirs": {"gold": "↑", "silver": "↓", "oil": "↓↓", "natgas": "↓", "usd": "↓",
                     "us10y": "↓↓", "vix": "↑", "usstock": "↓", "hkstock": "↓", "semi": "↓",
                     "shipping": "↓", "btc": "↓"}},
    "E11": {"name": "金融機構爆煲/信用事件",
            "dirs": {"gold": "↑", "silver": "—", "oil": "↓", "natgas": "—", "usd": "↑",
                     "us10y": "↓", "vix": "↑↑", "usstock": "↓↓", "hkstock": "↓", "semi": "↓",
                     "shipping": "—", "btc": "↓↓"}},
    "E12": {"name": "停火/地緣降級",
            "dirs": {"gold": "↓", "silver": "—", "oil": "↓", "natgas": "↓", "usd": "—",
                     "us10y": "—", "vix": "↓", "usstock": "↑", "hkstock": "↑", "semi": "—",
                     "shipping": "↓", "btc": "↑"}},
}

# 資產顯示 meta：key → (emoji, 顯示名)
ASSET_META = {
    "gold": ("🥇", "黃金 XAU"), "silver": ("🥈", "白銀 XAG"),
    "oil": ("🛢️", "WTI 原油"), "natgas": ("⛽", "天然氣"),
    "usd": ("💵", "美元 DXY"), "us10y": ("📈", "美債 10Y"),
    "vix": ("😱", "VIX 恐慌"), "usstock": ("🇺🇸", "美股"),
    "hkstock": ("🇭🇰", "港股"), "semi": ("💾", "半導體"),
    "shipping": ("🚢", "航運"), "btc": ("₿", "BTC"),
}

# ============================================================ 2. 傳導鏈（3 步，§1.3）
CHAINS = {
    "E1": ["中東交火升級 → 原油供應中斷風險定價",
           "油價急升 → 通脹預期升溫、美債息升",
           "避險資金湧入金銀，VIX 抬頭"],
    "E2": ["霍爾木茲通行受阻 → 全球約 20% 石油海運受威脅",
           "供應休克 → 油價↑↑、航運保險費飆升",
           "滯脹交易 → 新興市場貨幣貶、風險資產跌"],
    "E3": ["紅海船隻遇襲 → 航運繞道好望角（+10-14 日）",
           "集裝箱運價攀升 → 供應鏈成本轉嫁",
           "原油影響溫和，主要衝擊航運同零售"],
    "E4": ["台海軍演/越線 → 地緣風險溢價急升",
           "全球 90%+ 先進半導體產能受威脅 → 科技股↓↓",
           "避險買金、日元升值，VIX 抬頭"],
    "E5": ["俄烏戰事升級 → 歐洲天然氣/糧食通道受擾",
           "TTF 天然氣↑↑、小麥供應憂慮",
           "核威脅言論 → 黃金避險需求升"],
    "E6": ["中美關稅升級 → 成本稅推升物價、壓縮企業利潤",
           "港股/科技/供應鏈 ↓↓；鋁鋼關稅推工業機械成本",
           "美元走強，黃金避險受惠"],
    "E7": ["出口管制/金融制裁 → 被制裁板塊↓↓",
           "國產替代受惠；貨幣體系受動搖",
           "黃金中長線受惠（儲備多元化）"],
    "E8": ["央行意外鷹派（加息/縮表）→ 實際利率升",
           "金/成長股估值受壓、美元走強",
           "⚠️ 日央行加息可觸發套息拆倉跨市場連鎖急跌"],
    "E9": ["央行意外鴿派（減息/放水）→ 流動性預期改善",
           "美元走弱、美債息回落",
           "金、成長股、BTC 齊升"],
    "E10": ["衰退型數據爆冷 → 需求崩塌預期",
            "油暴跌↓↓、資金湧入美債（息急降）",
            "VIX 升，防禦板塊（醫藥/公用）相對抗跌"],
    "E11": ["金融機構爆煲/信用事件 → 交易對手風險蔓延",
            "SOFR 隔夜利率 spike、銀行 CDS 急升",
            "初期美元因流動性需求反升，BTC↓↓"],
    "E12": ["停火/地緣降級 → 避險溢價回吐",
            "油金回落、航運風險降",
            "風險資產反彈、BTC 回升"],
}

# 「如果…就…」句式（事件卡 if-then）
IF_THEN = {
    "E1": "如果 72h 內進一步升級，就 油價風險溢價擴大、XAU 加倉；否則溢價通常回吐一半以上",
    "E2": "如果 海峽 48h 內未恢復通行，就 WTI 見 $90 並帶動金銀破位，收緊風險倉",
    "E3": "如果 繞道持續逾兩週，就 航運股續強、零售成本壓力浮現，TEX 留意出貨指引",
    "E4": "如果 演訓升級為實彈封鎖，就 半導體供應鏈溢價急升，VEEV/ILMN 等科技股先減一半",
    "E5": "如果 斷供或核威脅升級，就 天然氣/金價急升，歐洲資產避險",
    "E6": "如果 關稅正式落地，就 港股/科技/供應鏈 ↓↓，TEX 成本端受壓、FND 審慎",
    "E7": "如果 制裁名單擴大，就 被制裁板塊急跌、國產替代受惠，金中長線受惠",
    "E8": "如果 鷹派落地，就 金/成長股受壓、美元強；留意日央行加息引發拆倉",
    "E9": "如果 減息信號確認，就 美元弱、金衝關，VEEV 等利率敏感股反彈",
    "E10": "如果 數據連續爆冷，就 衰退交易主導：油跌、美債升、UHS 等防禦相對抗跌",
    "E11": "如果 傳染確認（SOFR/CDS 急升），就 全部高 beta EA 暫停，BTC 止損",
    "E12": "如果 停火破裂再升級，就 強度升一級，避險交易重啟",
}

# ============================================================ 3. 關鍵詞分類規則
# 順序敏感：每條為 (事件型, 權重, [關鍵詞])；命中加分，最高分勝出
# 設計原則（§1.3）：blockade/seal/tanker seized→E2；Houthi/Red Sea shipping→E3；
# drill/exercise/Taiwan Strait→E4；tariff→E6；hike/hawkish surprise→E8；cut/dovish→E9；
# bank failure/default→E11；ceasefire→E12
KEYWORD_RULES = [
    # --- E2 航道封鎖（最具體，優先）---
    ("E2", 5, ["hormuz", "strait of hormuz", "霍爾木茲", "海峽封鎖", "海灣航道"]),
    ("E2", 4, ["blockade", "seal the strait", "tanker seized", "tanker detained",
               "ship seized", "shipping lane closed", "航道封鎖", "封鎖海峽", "油輪被扣", "油輪遇襲"]),
    # --- E3 紅海 ---
    ("E3", 5, ["red sea", "houthi", "yemen", "bab el-mandeb", "suez", "紅海", "胡塞", "也門", "蘇彝士", "曼德"]),
    ("E3", 2, ["cape of good hope", "好望角", "container ship attack", "貨櫃船遇襲"]),
    # --- E4 台海 ---
    ("E4", 5, ["taiwan strait", "台海", "台灣海峽", "環台", "聯合利劍"]),
    ("E4", 4, ["taiwan", "台灣", "臺灣"]),
    ("E4", 3, ["pla drill", "military drill", "military exercise", "war games",
               "軍演", "演訓", "演習", "東部戰區", "越中線", "admiral"]),
    # --- E5 俄烏 ---
    ("E5", 5, ["ukraine", "kyiv", "russia strikes", "moscow", "俄烏", "烏克蘭", "基輔", "俄羅斯"]),
    ("E5", 3, ["nord stream explosion", "nord stream sabotage",
               "russia cuts gas", "russia gas halt", "ukraine gas pipeline",
               "natural gas pipeline explosion", "核威脅", "nuclear threat"]),
    # --- E1 中東武裝（通用，地緣關鍵詞優先於關稅/制裁）。
    # 注意：純「伊朗」一詞太闊（央行/外匯官員講話都會講伊朗），改用地緣動詞/名詞搭配 ---
    ("E1", 5, ["israel", "gaza", "iran attack", "iranian strike", "irgc", "hezbollah",
               "iran escalation", "iran tension", "iran hostilit", "iran conflict",
               "iran strikes", "iran fires", "iran missile",
               "以色列", "加沙", "革命衛隊", "真主黨", "中東衝突",
               "伊朗襲擊", "伊朗打擊", "伊朗導彈", "伊朗軍方", "伊朗無人機", "伊朗空襲",
               "中東局勢", "中東升級"]),
    ("E1", 3, ["missile strike", "airstrike", "air strike", "drone attack", "middle east tension",
               "空襲", "導彈", "無人機襲擊"]),
    # --- E12 停火降級 ---
    ("E12", 6, ["ceasefire", "truce", "peace deal", "peace agreement", "de-escalation",
                "停火", "和平協議", "降級", "復航"]),
    # --- E11 金融爆煲（必須係爆煲/違約本身；銀行股併購/研報唔算）---
    ("E11", 5, ["bank failure", "bank collapses", "bank collapsed", "credit event",
                "sovereign default", "liquidity crisis", "bank run", "bank seized",
                "bank shut down", "fdic seizure",
                "爆煲", "違約", "破產", "銀行倒閉", "信用事件", "銀行被接管"]),
    ("E11", 3, ["cds spike", "sofr spike", "hedge fund collapse", "contagion risk"]),
    # --- E10 衰退數據 ---
    ("E10", 5, ["recession", "jobs report miss", "payrolls miss", "contraction",
                "衰退", "失業率升", "經濟收縮"]),
    ("E10", 3, ["factory orders plunge", "consumer confidence plunge", "ism below 45"]),
    # --- E8 鷹派（rate hike 改成 fed/央行搭配，避免「XRP rate hike」之類加密投機文誤判）---
    ("E8", 5, ["fed rate hike", "fed hikes", "rate hike would", "hike rates", "hawkish surprise",
               "surprise hike", "tightening cycle", "balance sheet shrink",
               "boj hike", "boj hikes", "bank of japan hike", "boj raises",
               "加息", "鷹派", "縮表", "意外加息", "央行加息", "日銀加息"]),
    ("E8", 3, ["higher for longer", "no rate cut", "pushes back cut", "hawkish fed", "hawkish powell",
               "pushed for boj hike", "pushed for rate hike", "calls for rate hike", "urges hike"]),
    # --- E9 鴿派 ---
    ("E9", 5, ["rate cut", "rate cuts", "dovish", "quantitative easing",
               "減息", "降息", "鴿派", "放水", "寬鬆"]),
    ("E9", 3, ["fed pivot", "cut odds rise", "pause hikes"]),
    # --- E6 關稅 ---
    ("E6", 5, ["tariff", "tariffs", "trade war", "import duty", "關稅", "貿易戰", "加徵關稅"]),
    ("E6", 3, ["trade tension", "retaliatory", "貿易摩擦"]),
    # --- E7 制裁/出口管制 ---
    ("E7", 5, ["new sanctions", "fresh sanctions", "export control", "entity list", "blacklist",
               "制裁", "出口管制", "實體清單", "貿易管制"]),
    ("E7", 3, ["asset freeze", "swift", "金融制裁", "國產替代"]),
]

# 噪音黑名單：意見/行情技術分析/投機內容，唔係突發事件（肥F規格：過濾「專家預測/行情評論」）
# 命中任一條 → 唔入事件流（除非同時命中強升級詞）
NOISE_BLACKLIST = [
    # 行情技術分析（「WTI Price Forecast」「X Forecast」之類）
    "price forecast", "price analysis", "forecast:", "technical outlook", "sma breakout",
    "technical analysis:", "here's why", "5 reasons", "what a september", "what would",
    "we asked ai", "ai predicts", "chatgpt", "could hit", "could reach",
    # 投機觀點/評論/研報/併購閒話（分析師/大行評論，唔係突發事件）
    "opinion:", "column:", "analysts say", "experts predict", "could be next",
    "commerzbank", "mufg", "ing bank", "goldman says", "analyst:", "proactive ecb",
    "room to buy", "have room to", "stock of the week", "etf flows",
    "as headwinds", "flags ", "warns ", "cites ", "cautious on", "bullish on",
    "wells fargo", "jpmorgan says", "morgan stanley says", "goldman sachs ceo",
    # 純行情描述冇事件
    "climbs above", "slips below", "rallies as", "falls as", "rises as", "drops as",
    "extends retreat", "extends gain", "extends rally", "jumps 5%", "jump 5%",
    "shares rise", "shares fall", "shares drop",
]
# 地區詞（用於非美國事件定位，避免統一落到華盛頓）
REGION_WORDS = {
    "spain": "馬德里 · 西班牙", "germany": "柏林 · 德國", "french ": "巴黎 · 法國",
    "uk ": "倫敦 · 英國", "britain": "倫敦 · 英國", "eurozone": "布魯塞爾 · 歐盟",
    "euro area": "布魯塞爾 · 歐盟", "china ": "北京", "beijing": "北京",
    "japan": "東京 · 日銀", "boj": "東京 · 日銀", "bank of japan": "東京 · 日銀",
    "canada": "渥太華 · 加拿大", "mexico": "墨西哥城", "india": "新德里 · 印度",
    "brazil": "巴西利亞", "australia": "悉尼 · 澳洲", "korea": "首爾 · 韓國",
    "ecb": "布魯塞爾 · 歐央行", "european central bank": "布魯塞爾 · 歐央行",
}
REGION_COORDS = {
    "馬德里 · 西班牙": (40.4, -3.7), "柏林 · 德國": (52.5, 13.4), "巴黎 · 法國": (48.9, 2.35),
    "倫敦 · 英國": (51.5, -0.1), "布魯塞爾 · 歐盟": (50.85, 4.35), "布魯塞爾 · 歐央行": (50.85, 4.35),
    "北京": (39.9, 116.4), "東京 · 日銀": (35.7, 139.7), "渥太華 · 加拿大": (45.4, -75.7),
    "墨西哥城": (19.4, -99.1), "新德里 · 印度": (28.6, 77.2), "巴西利亞": (-15.8, -47.9),
    "悉尼 · 澳洲": (-33.9, 151.2), "首爾 · 韓國": (37.6, 127.0),
}

# 強升級詞（命中 → 嚴重度升 high）
ESCALATION_WORDS = ["blockade", "invasion", "ground war", "declares war", "nuclear",
                    "實彈", "開戰", "封鎖", "導彈襲擊", "explosion", "strikes kill",
                    "tanker hit", "mine", "seized", "detained"]
# 參考/預警詞（純演講/預告 → 降 ref）
REFERENCE_WORDS = ["speech", "speaks", "to speak", "preview", "jackson hole",
                   "symposium", "annual dinner", "testimony", "演講", "講話", "年會"]

# ============================================================ 4. 位置字典
LOCATIONS = [
    # (key, 顯示名, lat, lng, [關鍵詞])
    ("hormuz", "霍爾木茲海峽", 26.6, 56.3,
     ["hormuz", "霍爾木茲", "strait", "海峽", "gulf of oman", "阿曼灣"]),
    ("redsea", "紅海 · 曼德海峽", 14.7, 42.5,
     ["red sea", "紅海", "houthi", "胡塞", "yemen", "也門", "suez", "蘇彝士", "bab el", "曼德"]),
    ("taiwan", "台海", 23.7, 121.0,
     ["taiwan", "台海", "台灣", "臺灣", "taipei", "台北"]),
    ("ukraine", "烏克蘭 · 基輔", 50.5, 30.5,
     ["ukraine", "kyiv", "kiev", "烏克蘭", "基輔", "moscow", "莫斯科", "russia", "俄羅斯"]),
    ("mideast", "中東 · 伊朗/以色列", 31.5, 34.5,
     ["iran", "irgc", "tehran", "德黑蘭", "伊朗", "israel", "gaza", "tel aviv",
      "以色列", "加沙", "hezbollah", "hormuz", "霍爾木茲"]),
    # 東京放華府之前：BOJ/日本新聞 snippet 常含 "the fed"（policy divergence 語境），
    # 否則會被華府搶走定位
    ("tokyo", "東京 · 日銀", 35.7, 139.7,
     ["tokyo", "boj", "bank of japan", "東京", "日本央行", "日銀"]),
    ("beijing", "北京", 39.9, 116.4,
     ["beijing", "北京", "china ministry", "商務部", "外交部"]),
    ("brussels", "布魯塞爾 · 歐央行", 50.85, 4.35,
     ["brussels", "ecb", "european central bank", "布魯塞爾", "歐央行", "歐盟", "eu tariff"]),
    ("washington", "華盛頓 · 聯儲局", 38.9, -77.0,
     ["washington", "federal reserve", "fomc", "powell", "the fed ", "fed chair",
      "聯儲", "聯準", "白宮", "white house", "treasury secretary bessent visits",
      "美國財政部", "財長貝森特訪"]),
    ("venezuela", "委內瑞拉", 10.5, -66.9,
     ["venezuela", "委內瑞拉", "caracas"]),
]

# 事件型預設位置（分類命中但位置詞唔明確時）
DEFAULT_LOC = {
    "E1": "mideast", "E2": "hormuz", "E3": "redsea", "E4": "taiwan", "E5": "ukraine",
    "E8": "washington", "E9": "washington", "E10": "washington", "E11": "washington",
    "E6": "washington", "E7": "washington", "E12": "mideast",
}

# 嚴重度預設（§1.3：封鎖/爆煲/衰退為高等）
SEV_BY_TYPE = {
    "E1": "med", "E2": "high", "E3": "med", "E4": "med", "E5": "med", "E6": "med",
    "E7": "med", "E8": "med", "E9": "ref", "E10": "high", "E11": "high", "E12": "ref",
}
SEV_STYLE = {
    "high": {"cls": "red", "color": "#ff4d6d", "icon": "🔴", "card_cls": "sw",
             "flag": ["🦢 BLACK SWAN", "sw"]},
    "med": {"cls": "amber", "color": "#ffb020", "icon": "🟠", "card_cls": "hot",
            "flag": ["⚡ SIGNAL EVENT", "hot"]},
    "ref": {"cls": "cyan", "color": "#2dd4ff", "icon": "🔵", "card_cls": "cb",
            "flag": ["🏛️ WATCH", "cb"]},
}
SEV_ORDER = {"high": 0, "med": 1, "ref": 2}

# ============================================================ 5. 市場樞紐 + 弧線規則
HUBS = {
    "newyork": (40.7, -74.0), "london": (51.5, -0.1), "tokyo": (35.7, 139.7),
    "hk": (22.3, 114.2), "singapore": (1.35, 103.8), "sf": (37.6, -122.4),
    "seoul": (36.6, 128.0), "frankfurt": (50.1, 8.7), "shanghai": (31.2, 121.5),
}
# 事件型 → 弧線目標樞紐（照任務指定：油/能源強→東京+新加坡+法蘭克福；
# 航運↑↑→倫敦+新加坡；半導體↓↓→東京+三藩市+首爾+上海；央行/美元→紐約+倫敦+香港+新加坡）
ARC_RULES = {
    "E1": ["tokyo", "singapore", "frankfurt", "london"],
    "E2": ["tokyo", "singapore", "frankfurt"],
    "E3": ["london", "singapore"],
    "E4": ["tokyo", "sf", "seoul", "shanghai"],
    "E5": ["frankfurt", "london"],
    "E6": ["hk", "shanghai", "tokyo", "newyork"],
    "E7": ["newyork", "london", "hk"],
    "E8": ["newyork", "london", "hk", "singapore"],
    "E9": ["newyork", "london", "hk", "singapore"],
    "E10": ["newyork", "london", "tokyo"],
    "E11": ["newyork", "london", "hk", "singapore"],
    "E12": ["london", "newyork"],
}


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def classify_text(text):
    """返回 (etype, score) 或 (None, 0)。先過濾行情評論/投機噪音，再做關鍵詞評分。"""
    t = text.lower()
    # 噪音過濾：命中黑名單且唔含強升級詞 → 唔係事件（肥F規格：過濾專家預測/行情評論）
    if any(w in t for w in NOISE_BLACKLIST) and not any(w in t for w in ESCALATION_WORDS):
        return None, 0
    scores = {}
    for etype, weight, kws in KEYWORD_RULES:
        for kw in kws:
            if kw.lower() in t:
                scores[etype] = scores.get(etype, 0) + weight
    if not scores:
        return None, 0
    etype = max(scores.items(), key=lambda kv: kv[1])[0]
    return etype, scores[etype]


def detect_location(text, etype):
    """返回 (loc_key, lat, lng, loc_name)。優先明確地點詞；其次非美地區詞；最後用事件型預設。"""
    t = text.lower()
    # 1) 明確地點字典
    for key, name, lat, lng, kws in LOCATIONS:
        for kw in kws:
            if kw.lower() in t:
                return key, lat, lng, name
    # 2) 非美地區詞（防止西班牙 PMI 之類落到華盛頓）
    for rk, rname in REGION_WORDS.items():
        if rk in t:
            lat, lng = REGION_COORDS.get(rname, (38.9, -77.0))
            return rk.replace(" ", "_"), lat, lng, rname
    # 3) 事件型預設
    key = DEFAULT_LOC.get(etype, "washington")
    for k, name, lat, lng, _ in LOCATIONS:
        if k == key:
            return key, lat, lng, name
    return "washington", 38.9, -77.0, "華盛頓"


def _severity(etype, text):
    sev = SEV_BY_TYPE.get(etype, "med")
    t = text.lower()
    # 純演講/預告（央行事件未發生）→ 參考級
    if any(w in t for w in REFERENCE_WORDS) and not any(w in t for w in ESCALATION_WORDS):
        sev = "ref"
    # 強升級詞 → 高
    if any(w in t for w in ESCALATION_WORDS):
        if etype in ("E1", "E3", "E4", "E5", "E6", "E7", "E8"):
            sev = "high"
    return sev


def build_assets(etype):
    """查矩陣 → assets 陣列 [[emoji, name, dir, cls], ...]（過濾中性，最多 6 項）。"""
    dirs = MATRIX[etype]["dirs"]
    out = []
    for key, d in dirs.items():
        if d == "—":
            continue
        emo, name = ASSET_META[key]
        cls = "g" if d.startswith("↑") else "r"
        out.append([emo, name, d, cls])
    # 排序：↑↑/↓↓ 行先
    out.sort(key=lambda a: 0 if a[2] in ("↑↑", "↓↓") else 1)
    return out[:6]


def run_event_engine(news, now=None, max_events=6):
    """新聞 list → events + arcs。返回 {'events': [...], 'arcs': [...], 'classified_news': [...]}"""
    now = now or datetime.now(HKT)
    cutoff_48h = now - timedelta(hours=48)
    events = []
    classified = []

    for item in news:
        text = f"{item.get('title','')} {item.get('snippet','')}"
        etype, score = classify_text(text)
        if not etype:
            continue
        pub = _parse_dt(item.get("published"))
        if pub:
            pub_hkt = pub.astimezone(HKT)
            if pub_hkt < cutoff_48h:
                continue  # >48h 下架
        else:
            pub_hkt = now
        loc_key, lat, lng, loc_name = detect_location(text, etype)
        sev = _severity(etype, text)
        classified.append({**item, "etype": etype, "etype_name": MATRIX[etype]["name"],
                           "severity": sev, "loc_key": loc_key})
        events.append({
            "etype": etype, "score": score, "severity": sev,
            "loc_key": loc_key, "lat": lat, "lng": lng, "loc_name": loc_name,
            "news_title": item.get("title", ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "published": item.get("published"),
            "pub_hkt": pub_hkt.strftime("%H:%M HKT"),
            "pub_date": pub_hkt.strftime("%m/%d"),
        })

    # 24h 去重：同 (etype, loc_key) 保留分數最高/最新一條
    dedup = {}
    for ev in events:
        k = (ev["etype"], ev["loc_key"])
        if k not in dedup or (ev["score"], ev["published"] or "") > (dedup[k]["score"], dedup[k]["published"] or ""):
            dedup[k] = ev
    events = list(dedup.values())

    # 排序：嚴重度 → 分數 → 時間，取 max_events
    events.sort(key=lambda e: (SEV_ORDER[e["severity"]], -e["score"], e["published"] or ""),
                reverse=False)
    events = sorted(events, key=lambda e: (SEV_ORDER[e["severity"]], -(e["score"])))
    events = events[:max_events]

    # 組裝輸出事件（照模板 EVENTS 結構）
    out_events, arcs = [], []
    arc_pairs = set()
    for i, ev in enumerate(events):
        style = SEV_STYLE[ev["severity"]]
        etype = ev["etype"]
        title = f"{style['icon']} {ev['loc_name']} · {MATRIX[etype]['name']}"
        headline = ev["news_title"][:90]
        out_events.append({
            "id": i,
            "etype": etype,
            "etype_name": MATRIX[etype]["name"],
            "color": style["color"], "cls": style["cls"],
            "card_cls": style["card_cls"],
            "flag": style["flag"],
            "severity": ev["severity"],
            "lat": ev["lat"], "lng": ev["lng"], "name": ev["loc_name"],
            "title": title,
            "loc": f"📍 {ev['loc_name']}",
            "time": f"{ev['pub_date']} {ev['pub_hkt']} · {ev['source']}",
            "headline": headline,
            "chain": CHAINS[etype],
            "if_then": IF_THEN[etype],
            "assets": build_assets(etype),
            "source": ev["source"], "url": ev["url"],
        })
        # 弧線
        for hub in ARC_RULES.get(etype, []):
            hlat, hlng = HUBS[hub]
            pair = (round(ev["lat"], 2), round(ev["lng"], 2), round(hlat, 2), round(hlng, 2))
            if pair in arc_pairs:
                continue
            arc_pairs.add(pair)
            arcs.append({"startLat": ev["lat"], "startLng": ev["lng"],
                         "endLat": hlat, "endLng": hlng,
                         "color": style["color"], "etype": etype})

    # 弧線總數控制 8-18：太多就裁（先裁 ref 事件嘅弧），太少就由 med 事件補紐約/倫敦
    if len(arcs) > 18:
        arcs = arcs[:18]
    if len(arcs) < 8 and out_events:
        for ev in out_events:
            if len(arcs) >= 8:
                break
            for hub in ("newyork", "london"):
                hlat, hlng = HUBS[hub]
                pair = (round(ev["lat"], 2), round(ev["lng"], 2), round(hlat, 2), round(hlng, 2))
                if pair not in arc_pairs:
                    arc_pairs.add(pair)
                    arcs.append({"startLat": ev["lat"], "startLng": ev["lng"],
                                 "endLat": hlat, "endLng": hlng,
                                 "color": ev["color"], "etype": ev["etype"]})
                    if len(arcs) >= 8:
                        break

    return {"events": out_events, "arcs": arcs,
            "classified_news": classified[:60],
            "counts": {e: sum(1 for c in classified if c["etype"] == e)
                       for e in MATRIX}}


if __name__ == "__main__":
    import json, sys
    # 簡單自測
    test = [
        {"title": "Iranian navy seizes oil tanker in Strait of Hormuz, shipping halted",
         "snippet": "", "source": "test", "url": "u1",
         "published": datetime.now(UTC).isoformat()},
        {"title": "Houthi militants attack container ship in Red Sea, Maersk diverts",
         "snippet": "", "source": "test", "url": "u2",
         "published": datetime.now(UTC).isoformat()},
        {"title": "PLA launches Joint Sword military drill around Taiwan",
         "snippet": "", "source": "test", "url": "u3",
         "published": datetime.now(UTC).isoformat()},
        {"title": "Trump announces 25% tariff on Chinese imports",
         "snippet": "", "source": "test", "url": "u4",
         "published": datetime.now(UTC).isoformat()},
        {"title": "Fed's Powell signals rate cut could come in September",
         "snippet": "", "source": "test", "url": "u5",
         "published": datetime.now(UTC).isoformat()},
        {"title": "Regional bank failure sparks contagion fears, CDS spikes",
         "snippet": "", "source": "test", "url": "u6",
         "published": datetime.now(UTC).isoformat()},
        {"title": "Ceasefire agreement reached in Gaza, peace deal signed",
         "snippet": "", "source": "test", "url": "u7",
         "published": datetime.now(UTC).isoformat()},
        {"title": "Local bakery wins award for best croissant",
         "snippet": "", "source": "test", "url": "u8",
         "published": datetime.now(UTC).isoformat()},
    ]
    r = run_event_engine(test)
    print(f"事件數: {len(r['events'])}，弧線數: {len(r['arcs'])}")
    for e in r["events"]:
        print(f"  {e['etype']} [{e['severity']}] {e['name']} — {e['headline'][:50]}")
        print(f"    assets: {[a[1]+a[2] for a in e['assets']]}")
    print("分類統計:", {k: v for k, v in r["counts"].items() if v})
