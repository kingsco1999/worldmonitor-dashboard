# WorldMonitor 風格每日市觀 Dashboard — Phase 1 Pipeline（pipeline_v2）

真數據驅動嘅每日市場態勢感知 dashboard。UI 鎖定 `ui_mockup/dashboard_mockup_v1.html`（v1.4.1 已驗收）嘅 WorldMonitor 視覺：3D 地球、國家邊界、事件→市場傳導弧線、風險溫度計、持倉矩陣、晨/晚 Brief。

## 一鍵跑

```bash
python3 pipeline_v2/run_v2.py              # 自動按 HKT：<14:00 晨版 / >=14:00 晚版
python3 pipeline_v2/run_v2.py --morning    # 強制晨版
python3 pipeline_v2/run_v2.py --evening    # 強制晚版
python3 pipeline_v2/run_v2.py --no-gdelt   # 跳過 GDELT（快 ~3 分鐘；地緣事件由 RSS 補頂）
```

- 數據快照：`data_v2/dashboard_latest.json`、`data_v2/news_latest.json`
- 成品：`output/dashboard_v2_<morning|evening>_YYYYMMDD_HHMM.html` + `dashboard_v2_latest.html`
- 雙擊 HTML 即開，單一檔案、CDN 失效自動降級 SVG 地球、全繁體中文

## 模塊

| 檔案 | 職責 |
|---|---|
| `collectors.py` | 數據採集：CNBC Quote API（17 符號行情主源，免 key 批量）、FRED CSV（US10Y/US2Y/DXY，備援）、新浪 hq（金銀油備援，需 Referer）、ForexFactory 日曆 JSON、GDELT DOC 2.0（串行 sleep 5.5s、超時 120s）、7 英文 RSS + 新浪 7x24 |
| `event_engine.py` | 新聞 → E1-E12 事件分類（關鍵詞評分）、噪音黑名單過濾行情評論/投機文、地點定位（明確地點→非美地區詞→事件型預設）、嚴重度、弧線生成 |
| `thermometer.py` | 風險溫度計：VIX25 / US10Y15 / DXY15 / BTC15 / GDX10 / 金10 / 油10 → 0-100 分，🟢進攻/⚪中性/🟠避險/🔴危機 |
| `brief_builder.py` | 5 點 Brief（風險事件/持倉異動/金油/溫度/關注），「如果…就…」句式；持倉歸因搜索（SBTU 搜 SBET/SHARPLINK），搵唔到如實標「⚠️ 未尋獲明確歸因，需人工查證」，**禁止編造** |
| `render_v2.py` | 數據 → HTML（持倉合併、矩陣、卡片、地球 markers/arcs JS 注入） |
| `template.html` | UI 模板（globe.gl + Three.js + topojson 國家邊界，CDN 失敗降級 SVG） |
| `run_v2.py` | 主編排：採集→事件→溫度計→持倉→Brief→快照→渲染 |

## 數據源（全部免費、免 key）

- **行情**：CNBC Quote API（`.VIX` `.DXY` `US10Y` `US2Y` `@GC.1` `@CL.1` `@SI.1` `XAU=` `GDX` `BTC.CM=` + 持倉股），pipe 批量 ~1s
- **利率/美元**：FRED CSV（DGS10/DGS2/DTWEXBGS）；沙盒大陸 IP 偶發超時，CNBC US10Y/US2Y 可頂上
- **日曆**：ForexFactory `ff_calendar_thisweek.json`
- **地緣事件**：GDELT DOC 2.0（4 組查詢：Hormuz/Red Sea/Taiwan/Fed；TLS 握手慢、限速 5s/請求，必須串行）+ RSS 補頂
- **新聞**：CNBC×5、MarketWatch×2、FXStreet、ForexLive、Mining.com、OilPrice、CoinTelegraph、新浪 7x24
- **已封不可用**：Yahoo Finance（403）、Google News RSS、CME FedWatch、stooq、investing.com（沙盒大陸 IP）

## 持倉（全部模擬倉 DEMO）

持倉名單用 **chat 式手動更新** `data_v2/holdings.json`（同 Ernest 講「買咗/平咗 XXX」，肥IT 改檔）；價格、歸因、溫度計、Brief 全自動。

- schema：ticker / quote_key / name_cn / account_type(us_demo|mt5_ea) / nature(long|short|leveraged2x|ea) / open_date / cost_price / shares / open_reason / status(open|closed) / close_* / notes + watchlist[] + trade_log[]
- 三組渲染：🥇 EA 倉（XAU/XAG）、🎰 2X 槓桿區（SBTU，閾值 6%/12%）、📈 美股 DEMO 倉；平倉轉 ⏸ 觀察組保留 30 日；新倉 🆕 標 3 個交易日
- 升跌雙軌：主軌＝今日 vs 昨收（歸因/Brief/溫度計用）；次軌＝現價 vs cost_price（未記錄顯示「成本價未記錄」）；已廢除 8/12 基準價
- 開倉四件齊（ticker/日期/成本價/股數＋原因），唔齊入 watchlist；每次改動 append trade_log

## 規格依據

- 投資內容規則：`content_spec/投資內容規格_v1.0.md`（肥F叔叔著：12 事件型 × 13 資產傳導矩陣、Brief 模板、溫度計 regime 表）
- 數據源測試：`data_spike/數據源測試報告.md` + `data_spike/samples/`
- 舊 pipeline（唯讀參考）：`scripts/`（run_dashboard.py 編排，ntfy.sh 推送）

## 已知限制 / Phase 2 方向

- GDELT 慢且唔穩定（~3 分鐘、超時常見），RSS 補頂後事件分類已夠用；FedWatch 概率抓唔到 → EA chip 改顯示 US10Y bp 實時變化＋事件倒數
- 事件分類係關鍵詞規則引擎，會持續按誤判案例迭代 NOISE_BLACKLIST / KEYWORD_RULES / LOCATIONS
- Phase 2：sector 輪動熱力圖、ETF 資金流、FedWatch 概率 RSS 文字萃取、週度主線
