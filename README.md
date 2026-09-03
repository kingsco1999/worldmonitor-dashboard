# Ernest 每日市觀 Dashboard

WorldMonitor 風格即時態勢感知 Dashboard，專為投資者設計。

## 🚀 線上版本

👉 **https://kingsco1999.github.io/worldmonitor-dashboard**

## 📊 功能

- 🌍 3D 地球即時顯示全球熱點
- 📺 即時財經直播（Bloomberg / Sky / DW / Al Jazeera / CGTN / CNA）
- 📈 NEWS ⇄ MARKETS 新聞話題量 × 資產價格關聯圖
- 🌡️ 地緣政治溫度計
- 📋 每日 Brief（5 點摘要）
- 💼 模擬倉持倉歸因（Demo）

## 🔧 技術棧

- **Frontend**: 純 HTML + CSS + Vanilla JS（單一 HTML，雙擊即開）
- **Pipeline**: Python 3（collectors + event_engine + thermometer + brief_builder + render_v2）
- **數據源**: 免費公開 API（CNBC、GDELT、RSS feeds）
- **部署**: GitHub Pages + GitHub Actions（自動每日更新）

## 📦 本機運行

```bash
# 完整採集 + 生成
python3 pipeline_v2/run_v2.py --evening

# 快速重渲（讀緩存，秒級）
python3 pipeline_v2/rebuild_cached.py evening
```

## 🔄 自動更新

GitHub Actions 每日自動執行：
- 🌅 晨版 07:57 HKT
- 🌃 晚版 21:09 HKT

## 📄 License

Private - Ernest Wong
