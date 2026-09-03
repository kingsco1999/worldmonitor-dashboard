# -*- coding: utf-8 -*-
"""
render_v2.py — 模板改造 + 數據驅動渲染
======================================
1. 首次執行把 ui_mockup/dashboard_mockup_v1.html 複製為 pipeline_v2/template.html
2. 將模擬數據區塊換成 id 掛點 + 一個 const DASH_DATA = {...}
3. HTML 結構/CSS/地球邏輯（globe.gl CDN + SVG 降級）保持不變
4. 輸出 output/dashboard_v2_<edition>_YYYYMMDD_HHMM.html + dashboard_v2_latest.html
"""
import os
import re
import json
import shutil
from datetime import datetime, timezone, timedelta

HKT = timezone(timedelta(hours=8))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE = os.path.join(HERE, "template.html")
MOCKUP_SRC = os.path.join(ROOT, "ui_mockup", "dashboard_mockup_v1.html")
OUTPUT_DIR = os.path.join(ROOT, "output")

# ------------------------------------------------------------- 持倉合併報價
def merge_holdings(holdings_doc, quotes):
    """holdings.json + CNBC quotes → 渲染用持倉 list（含今日 change_pct；次軌 cost）。"""
    out = []
    for h in holdings_doc.get("holdings", []):
        q = quotes.get(h.get("quote_key", "")) or {}
        item = dict(h)
        item["code"] = h["ticker"]
        item["last"] = q.get("last")
        item["change_pct"] = q.get("change_pct")
        item["prev_close"] = q.get("prev_close")
        item["high"] = q.get("high")
        item["low"] = q.get("low")
        item["mkt_status"] = q.get("mkt_status", "")
        item["quote_source"] = q.get("source", "CNBC")
        # 次軌：現價 vs 成本價
        if h.get("cost_price") and q.get("last"):
            item["pnl_cost_pct"] = round((q["last"] - h["cost_price"]) / h["cost_price"] * 100, 1)
        else:
            item["pnl_cost_pct"] = None
        out.append(item)
    return out


# ============================================================= JS 生成
def build_js(dash_data):
    """返回注入 HTML 嘅 <script> 內容（DASH_DATA + 渲染函數）。"""
    data_json = json.dumps(dash_data, ensure_ascii=False, separators=(",", ":"))
    return r"""
/* ============================================================
   DASH_DATA（由 pipeline_v2 注入，真實數據驅動）
============================================================ */
const DASH_DATA = __DATA__;
const pad = n => String(n).padStart(2,'0');
const $ = id => document.getElementById(id);
const esc = s => String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmtPx = v => v==null ? '—' : (Math.abs(v)>=1000 ? Number(v).toLocaleString('en-US',{maximumFractionDigits:0}) : (Math.abs(v)>=100 ? v.toFixed(1) : v.toFixed(2)));
const fmtPct = v => v==null ? '—' : (v>=0?'+':'')+v.toFixed(2)+'%';
const clsOf = v => v>0.05 ? 'up' : (v<-0.05 ? 'down' : 'neu');
const arrowOf = v => v>0.05 ? '▲' : (v<-0.05 ? '▼' : '◆');

/* ---------- 時鐘（真實 HKT，由生成時間錨定）---------- */
function initClock(){
  const base = new Date(DASH_DATA.generated_iso).getTime();
  const t0 = performance.now();
  const wk = ['日','一','二','三','四','五','六'];
  function tick(){
    const now = new Date(base + (performance.now()-t0));
    $('hkClock').innerHTML = pad(now.getHours())+':'+pad(now.getMinutes())+':'+pad(now.getSeconds())+'<small>HKT</small>';
    const d = DASH_DATA.date_parts;
    $('dateLine').innerHTML = d.y+'-'+pad(d.m)+'-'+pad(d.d)+' <small>星期'+wk[now.getDay()]+' · '+DASH_DATA.edition_label+'</small>';
    document.title = 'Ernest 每日市觀 Dashboard — '+d.y+'-'+pad(d.m)+'-'+pad(d.d);
    // 倒數至下一個 High 事件
    const ev = DASH_DATA.next_event;
    if(ev){
      let diff = new Date(ev.iso).getTime() - now.getTime();
      if(diff < 0) diff = 0;
      const h=Math.floor(diff/3600000), m=Math.floor(diff%3600000/60000), s=Math.floor(diff%60000/1000);
      $('cd').innerHTML = pad(h)+'<small>時</small>'+pad(m)+'<small>分</small>'+pad(s)+'<small>秒</small>';
    } else {
      $('cd').innerHTML = '—<small></small>';
    }
  }
  tick(); setInterval(tick,1000);
}

/* ---------- 頂欄：溫度計 ---------- */
function renderThermo(){
  const t = DASH_DATA.thermo;
  $('thermoVal').innerHTML = t.total+'<small>'+t.regime_label.toUpperCase()+' /100</small>';
  $('needle').style.left = Math.min(96, Math.max(2,t.total))+'%';
  // 4 段：0-30 / 31-60 / 61-80 / 81-100
  const segs = $('thermoSegs').children;
  const bounds = [30,60,80,100];
  for(let i=0;i<4;i++){ segs[i].classList.toggle('on', t.total>bounds[i]-30 || (i===0&&t.total<=30&&t.total>0) || t.total> (i===0?0:bounds[i-1])); }
  // 簡化：按分數亮段
  for(let i=0;i<4;i++){ segs[i].classList.remove('on'); }
  if(t.total>0) segs[0].classList.add('on');
  if(t.total>30) segs[1].classList.add('on');
  if(t.total>60) segs[2].classList.add('on');
  if(t.total>80) segs[3].classList.add('on');
  const names = $('thermoNames').children;
  for(let i=0;i<4;i++) names[i].classList.remove('cur');
  const ci = t.total<=30?0:t.total<=60?1:t.total<=80?2:3;
  names[ci].classList.add('cur');
  $('regimePill').innerHTML = '<span class="ricon">'+t.regime_icon+'</span>'+
    '<div><b>'+t.regime_label+'</b><small>'+DASH_DATA.regime_sub+'</small></div>';
}

/* ---------- 頂欄：情緒七格 ---------- */
function sentimentTile(k, emo, v, pct, tileCls){
  const c = clsOf(pct);
  return '<div class="sent '+tileCls+'"><div class="k">'+emo+' '+k+'</div>'+
    '<div class="v">'+v+'</div><div class="p '+c+'">'+arrowOf(pct)+' '+fmtPct(pct)+'</div></div>';
}
function renderSentiment(){
  const q = DASH_DATA.quotes;
  const g = (key,label,emo,fmt) => {
    const x = q[key]; if(!x) return '';
    const v = fmt ? fmt(x.last) : fmtPx(x.last);
    const tile = (x.change_pct>0.05) ? 'g-tile' : (x.change_pct<-0.05 ? 'r-tile' : '');
    let pct = x.change_pct;
    let pTxt = fmtPct(pct);
    if(key==='US10Y' && x.change_bp!=null){
      const bp = x.change_bp, bc = bp>0.05?'up':(bp<-0.05?'down':'neu');
      return '<div class="sent '+(bp>0.05?'r-tile':bp<-0.05?'g-tile':'')+'"><div class="k">'+emo+' '+label+'</div>'+
        '<div class="v">'+(x.last==null?'—':x.last.toFixed(2)+'%')+'</div>'+
        '<div class="p '+bc+'">'+(bp>0?'▲':bp<0?'▼':'◆')+' '+(bp>0?'+':'')+bp.toFixed(1)+'bp</div></div>';
    }
    return sentimentTile(label, emo, v, pct, tile);
  };
  $('sentimentBox').innerHTML =
    g('DXY','美元 DXY','💵') +
    g('US10Y','10年債','📈') +
    g('VIX','VIX 恐慌','😱') +
    g('GDX','金礦 GDX','🪙') +
    g('XAU','金價 XAU','🥇') +
    g('WTI','油 WTI','🛢️') +
    g('BTC','BTC','₿', v=>'$'+fmtPx(v)) +
    '';
  // regime pill 由 renderThermo 處理
}

/* ---------- 風險時鐘面板 ---------- */
function renderRiskClock(){
  const ev = DASH_DATA.next_event;
  const chip = $('riskCountChip');
  const n = (DASH_DATA.calendar.next24h||[]).length + (DASH_DATA.calendar.next48h||[]).length;
  chip.textContent = 'EVENT '+pad(Math.min(n,99));
  if(ev){
    $('nextEvent').innerHTML =
      '<div class="t"><span class="blip"></span>🔴 '+esc(ev.time_hm)+' '+esc(ev.title)+'（'+esc(ev.country)+'）</div>'+
      '<div class="m">📍 高影響經濟事件 · 預測 '+esc(ev.forecast||'—')+' · 前值 '+esc(ev.previous||'—')+'</div>';
  } else {
    $('nextEvent').innerHTML =
      '<div class="t"><span class="blip" style="background:var(--cyan);box-shadow:0 0 10px var(--cyan)"></span>🔵 未來 24-48h 無 High 級經濟事件</div>'+
      '<div class="m">📍 ForexFactory 日曆實時監測中</div>';
  }
  $('fedChipLine').innerHTML = DASH_DATA.fed_chip;
  // mini calendar
  const rows = [];
  const all = (DASH_DATA.calendar.next24h||[]).concat(DASH_DATA.calendar.next48h||[]).slice(0,6);
  all.forEach(e=>{
    const cls = e.delta_hours<=24 ? 'hi' : 'mid';
    const tag = e.delta_hours<=24 ? 'HIGH 🔴' : 'MID 🟠';
    rows.push('<div class="row"><span class="tm">'+esc(e.time_hm)+'</span><span class="ev">'+esc(e.title)+' <small style="color:var(--txt-faint)">'+esc(e.country)+'</small></span><span class="impact '+cls+'">'+tag+'</span></div>');
  });
  $('miniCal').innerHTML = rows.join('') || '<div class="row"><span class="ev" style="color:var(--txt-faint)">未來 48h 無高影響事件</span></div>';
}

/* ---------- 事件卡（黑天鵝/突發）---------- */
function renderEventCards(){
  const evs = DASH_DATA.events;
  $('activeCount').textContent = evs.length+' ACTIVE';
  if(!evs.length){
    $('eventCards').innerHTML = '<div style="padding:14px;color:var(--txt-faint);font-size:12px">🔵 過去 24-48h 未偵測到可映射 E1-E12 嘅地緣/宏觀突發事件（RSS+GDELT 持續監測中）。</div>';
    return;
  }
  $('eventCards').innerHTML = evs.map(e=>{
    const tags = e.assets.map(a=>'<span class="tag '+a[3]+'">'+a[0]+' '+esc(a[1])+' <span class="strength">'+a[2]+'</span></span>').join('');
    const flagStyle = e.cls==='cyan'
      ? 'style="color:#04121c;background:linear-gradient(180deg,rgba(45,212,255,.95),rgba(20,150,200,.9));border:1px solid rgba(90,220,255,.55);font-weight:800"'
      : '';
    return '<div class="ev-card '+e.card_cls+'">'+
      '<div class="top"><span class="ev-flag '+(e.flag[1]==='cb'?'':e.flag[1])+'" '+flagStyle+'>'+esc(e.flag[0])+'</span>'+
      '<span class="loc">📍 '+esc(e.name)+'</span></div>'+
      '<div class="headline">'+esc(e.headline)+'</div>'+
      '<div class="tags">'+tags+'</div>'+
      '<div class="if-then"><b>如果</b> '+esc(e.if_then.split('，就 ')[0].replace('如果 ',''))+'，<b>就</b> '+esc(e.if_then.split('，就 ')[1]||'')+'</div>'+
      '<div style="margin-top:6px;font-family:var(--mono);font-size:9px;color:var(--txt-faint)">'+esc(e.etype)+' · '+esc(e.etype_name)+' · '+esc(e.time)+' · <a href="'+esc(e.url)+'" style="color:var(--cyan)" target="_blank" rel="noopener">來源 ↗</a></div>'+
    '</div>';
  }).join('');
}

/* ---------- 地球 chips ---------- */
function renderGlobeChips(){
  const boxes = {'high':[], 'med':[], 'low':[]};
  DASH_DATA.events.forEach(e=>{
    const label = e.name;
    if(e.severity==='high') boxes.high.push('<span class="chip">'+esc(label)+' <b style="color:var(--red)">CRITICAL</b></span>');
    else if(e.severity==='med') boxes.med.push('<span class="chip">'+esc(label)+' <b style="color:var(--amber)">ELEVATED</b></span>');
    else boxes.low.push('<span class="chip">'+esc(label)+' <b style="color:var(--cyan)">WATCH</b></span>');
  });
  if(!DASH_DATA.events.length){
    $('globeChips').innerHTML = '<span class="chip">全球態勢 <b style="color:var(--green)">NOMINAL</b></span>';
  } else {
    $('globeChips').innerHTML = boxes.high.join('')+boxes.med.join('')+boxes.low.join('');
  }
}

/* ---------- 跑馬燈 ---------- */
function renderTicker(){
  const items = [];
  DASH_DATA.events.forEach(e=>{
    const dir = e.assets[0] ? e.assets[0][2] : '';
    items.push(['🟠', esc(e.name)+'：'+esc(e.headline.slice(0,38)), '<b>'+dir+'</b>']);
  });
  const q = DASH_DATA.quotes;
  const add = (key,emo,name,fmt)=>{ const x=q[key]; if(!x||x.last==null) return;
    const v = fmt?fmt(x.last):fmtPx(x.last);
    items.push([emo, esc(name)+' '+v, '<b class="'+clsOf(x.change_pct)+'">'+fmtPct(x.change_pct)+'</b>']); };
  add('VIX','😱','VIX'); add('XAU','🥇','金價'); add('WTI','🛢️','WTI'); add('DXY','💵','DXY');
  add('BTC','₿','BTC',v=>'$'+fmtPx(v));
  DASH_DATA.holdings.forEach(h=>{
    if(h.change_pct==null) return;
    const th = h.code==='SBTU'?6:3;
    if(Math.abs(h.change_pct)>=th){
      items.push(['⚠️', esc(h.code)+' 今日'+(h.change_pct>0?'升':'跌')+Math.abs(h.change_pct).toFixed(1)+'%',
        '<b class="'+clsOf(h.change_pct)+'">'+(h.attrib_found?'':'歸因待查')+'</b>']);
    }
  });
  if(DASH_DATA.next_event){
    items.push(['📅','下一高影響：'+esc(DASH_DATA.next_event.title)+' '+esc(DASH_DATA.next_event.time_hm),'<b>'+esc(DASH_DATA.next_event.country)+'</b>']);
  }
  const html = items.map(i=>'<span class="t-item"><span>'+i[0]+'</span><b>'+i[1]+'</b>'+i[2]+'</span>').join('');
  $('tickerTrack').innerHTML = html + html;
}

/* ---------- 持倉矩陣（三組 + SBTU 獨立區）---------- */
function sparkline(chg){
  // 用今日升跌畫極簡 8 點 polyline
  const up = (chg||0)>=0;
  const col = up ? '#2ee6a8' : '#ff4d6d';
  const pts = up ? '0,13 8,12 16,11 24,10 32,8 40,7 48,5 56,4'
                 : '0,4 8,5 16,4 24,7 32,9 40,12 48,13 56,14';
  const endY = up ? 4 : 14;
  return '<svg class="h-sp" width="56" height="18" viewBox="0 0 56 18"><polyline points="'+pts+'" fill="none" stroke="'+col+'" stroke-width="1.5"/><circle cx="56" cy="'+endY+'" r="2" fill="'+col+'"/></svg>';
}
function holdingRow(h){
  const chg = h.change_pct;
  const c = clsOf(chg);
  const up = (chg||0)>=0;
  const px = h.last==null ? '—' : (h.code.indexOf('USD')>=0 ? '$'+fmtPx(h.last) : '$'+fmtPx(h.last));
  let tag, tagCls;
  if(chg==null){ tag='數據待更新'; tagCls='n'; }
  else if(Math.abs(chg)>= (h.code==='SBTU'?6:3)){ tag=(up?'強利好 ↑↑':'強利空 ↓↓'); tagCls= up?'g':'r'; }
  else if(Math.abs(chg)>=1){ tag=(up?'利好 ↑':'利空 ↓'); tagCls= up?'g':'r'; }
  else { tag='中性 ◆'; tagCls='n'; }
  const th = h.code==='SBTU'?6:3;
  const alert = (chg!=null && Math.abs(chg)>=th);
  const isNew = h.is_new ? '<span style="color:var(--cyan);font-weight:800">🆕</span>' : '';
  // 次軌：成本價
  let costLine = '';
  if(h.cost_price!=null && h.pnl_cost_pct!=null){
    const cc = h.pnl_cost_pct>=0?'up':'down';
    costLine = '<div style="grid-column:1/-1;font-family:var(--mono);font-size:9.5px;color:var(--txt-faint)">開倉成本 $'+fmtPx(h.cost_price)+' · 累計 <span class="'+cc+'">'+(h.pnl_cost_pct>=0?'+':'')+h.pnl_cost_pct+'%</span></div>';
  } else {
    costLine = '<div style="grid-column:1/-1;font-family:var(--mono);font-size:9.5px;color:var(--txt-faint)">成本價未記錄（淨顯示日變動%）</div>';
  }
  let attribLine = '';
  if(alert){
    const a = h.attrib||'';
    const found = h.attrib_found;
    attribLine = '<div class="attrib">歸因：<b>'+(found?'':'⚠️ ')+esc(a.slice(0,70))+'</b></div>';
  }
  return '<div class="hold-row'+(alert?' alert':'')+'">'+
    '<div class="h-nm">'+isNew+' '+esc(h.code)+'<small>'+esc(h.name_cn)+' · '+esc(h.account_type)+'</small></div>'+
    '<div class="h-px '+c+'">'+px+' <span class="'+c+'">'+arrowOf(chg)+' '+(chg==null?'—':fmtPct(chg))+'</span></div>'+
    sparkline(chg)+
    '<div class="h-tag"><span class="h-tag '+tagCls+'">'+tag+'</span>'+(alert?'<span class="alert-badge">⚠️ 異動</span>':'')+'</div>'+
    costLine + attribLine +
  '</div>';
}
function groupHeader(title, sub, color){
  return '<div style="padding:7px 12px;margin-top:2px;font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:'+color+';border-bottom:1px solid var(--line);background:rgba(13,22,39,.5)">'+title+' <span style="color:var(--txt-faint);letter-spacing:.04em">'+sub+'</span></div>';
}
function renderHoldings(){
  const hs = DASH_DATA.holdings;
  const ea = hs.filter(h=>h.group==='mt5_ea' && h.status==='open');
  const sbtu = hs.filter(h=>h.group==='us_demo_special' && h.status==='open');
  const us = hs.filter(h=>h.group==='us_demo' && h.status==='open');
  const closed = hs.filter(h=>h.status==='closed');
  let html = '';
  html += groupHeader('🤖 MT5 EA 倉','全自動策略 · 重點風險管理','var(--cyan)');
  html += ea.map(holdingRow).join('');
  html += groupHeader('🎰 美股 DEMO · 2X 槓桿區','T-REX 單日 2 倍 · 波動極大 · 獨立風控','var(--red)');
  html += sbtu.map(holdingRow).join('');
  html += groupHeader('📈 美股 DEMO 倉','us_demo 模擬倉 · 5 隻','var(--amber)');
  html += us.map(holdingRow).join('');
  const wl = DASH_DATA.watchlist||[];
  if(wl.length){
    html += groupHeader('👀 觀察區 WATCHLIST','資料未齊 · 照報價不計 P&L','var(--txt-faint)');
    html += wl.map(holdingRow).join('');
  }
  if(closed.length){
    html += groupHeader('⏸ 已平倉觀察組','保留報價＋歸因 30 日','var(--txt-faint)');
    html += closed.map(holdingRow).join('');
  }
  // 底部統計
  const openHs = hs.filter(h=>h.status==='open' && h.change_pct!=null);
  const gN = openHs.filter(h=>h.change_pct>0.05).length;
  const rN = openHs.filter(h=>h.change_pct<-0.05).length;
  const nN = openHs.length - gN - rN;
  const avg = openHs.length ? (openHs.reduce((s,h)=>s+h.change_pct,0)/openHs.length) : 0;
  // 金銀比
  const q = DASH_DATA.quotes;
  let foot = '📐 <b>金銀比</b> ';
  if(q.XAU && q.XAG && q.XAU.last && q.XAG.last){
    const ratio = q.XAU.last/q.XAG.last;
    foot += '<span class="gv">'+ratio.toFixed(1)+'</span>（金銀相對強弱）<br>';
  } else foot += '—<br>';
  foot += '🎯 <b>今日持倉平均</b> <span class="'+clsOf(avg)+'">'+fmtPct(avg)+'</span>（'+gN+' 升 / '+nN+' 平 / '+rN+' 跌，僅計日變動）<br>';
  foot += '🛢️ WTI <b>$'+fmtPx(q.WTI?q.WTI.last:null)+'</b> ｜ ₿ <b>$'+fmtPx(q.BTC?q.BTC.last:null)+'</b> ｜ 數據源：CNBC 實時';
  $('holdingsBody').innerHTML = html;
  $('matrixFoot').innerHTML = foot;
}

/* ---------- 倉位速覽 → 倉位動向（組合事件）---------- */
function renderPosition(){
  const logs = DASH_DATA.trade_log||[];
  const hs = DASH_DATA.holdings.filter(h=>h.status==='open' && h.change_pct!=null);
  const gN = hs.filter(h=>h.change_pct>0.05).length;
  const nN = hs.filter(h=>Math.abs(h.change_pct)<=0.05).length;
  const rN = hs.length-gN-nN;
  const avg = hs.length ? hs.reduce((s,h)=>s+h.change_pct,0)/hs.length : 0;
  let html = '<div style="display:flex;justify-content:space-between;font-size:11.5px"><span style="color:var(--txt-dim)">持倉日變動均值（模擬倉）</span><b class="'+clsOf(avg)+'">'+fmtPct(avg)+'</b></div>';
  html += '<div style="height:8px;border-radius:6px;background:#0c1626;overflow:hidden;display:flex;margin-top:6px">'+
    '<div style="width:'+(gN/Math.max(1,hs.length)*100)+'%;background:linear-gradient(90deg,#125c48,var(--green))"></div>'+
    '<div style="width:'+(nN/Math.max(1,hs.length)*100)+'%;background:rgba(126,147,173,.35)"></div>'+
    '<div style="width:'+(rN/Math.max(1,hs.length)*100)+'%;background:linear-gradient(90deg,#7a1f30,var(--red))"></div></div>';
  html += '<div style="display:flex;gap:12px;font-family:var(--mono);font-size:9.5px;color:var(--txt-faint);margin-top:6px">'+
    '<span><i style="display:inline-block;width:7px;height:7px;border-radius:2px;background:var(--green);margin-right:4px"></i>利好 '+gN+'</span>'+
    '<span><i style="display:inline-block;width:7px;height:7px;border-radius:2px;background:rgba(126,147,173,.5);margin-right:4px"></i>中性 '+nN+'</span>'+
    '<span><i style="display:inline-block;width:7px;height:7px;border-radius:2px;background:var(--red);margin-right:4px"></i>利空 '+rN+'</span></div>';
  html += '<div style="border-top:1px dashed var(--line);padding-top:9px;margin-top:9px;font-size:11px;color:var(--txt-dim);line-height:1.7">📋 <b style="color:var(--cyan)">倉位動向</b>（組合事件，非市場事件）：<br>';
  if(logs.length){
    html += logs.slice(-4).map(l=>'· '+esc(l.date)+' '+esc(l.action)+' '+esc(l.ticker)+' @ '+esc(l.price)+' — '+esc(l.reason)).join('<br>');
  } else {
    html += '· 暫無開/平倉記錄（持倉成本價未記錄，P&amp;L 雙軌只顯示日變動%）';
  }
  html += '</div>';
  $('positionBody').innerHTML = html;
}

/* ---------- Brief 5 卡 ---------- */
function renderBrief(){
  $('briefSub').textContent = 'DAILY INTEL · '+DASH_DATA.date_str+' · '+DASH_DATA.edition_label;
  $('briefCards').innerHTML = DASH_DATA.brief.map(b=>{
    const tags = (b.tags||[]).map(t=>'<span class="tag c">'+esc(t)+'</span>').join('');
    const ifParts = (b.ifthen||'').split('，就 ');
    const cond = ifParts[0].replace('如果 ','');
    const act = ifParts[1]||'';
    return '<div class="panel brief-card" style="--bc:'+b.color+'">'+
      '<div class="b-no">'+b.no+'</div>'+
      '<div class="b-txt">'+b.tag+' '+esc(b.txt)+'</div>'+
      '<div class="b-foot">'+tags+'</div>'+
      '<div class="b-if"><b>如果</b> '+esc(cond)+' → <b>就</b> '+esc(act)+'</div>'+
    '</div>';
  }).join('');
}

/* ---------- 新聞 Feed（摺疊）---------- */
function renderFeed(){
  $('feedCount').textContent = '// 24-48H · '+pad(DASH_DATA.feed.length)+' REPORTS';
  $('feedBody').innerHTML = DASH_DATA.feed.slice(0,40).map(f=>{
    let t = f.time_hm;
    let tagMap = {'oil':'🛢️油','gold':'🥇金','semi':'💾半導體','shipping':'🚢航運','crypto':'₿加密','macro':'🏛️宏觀','geo':'🌏地緣','stock':'📈美股'};
    const tag = tagMap[f.theme]||'📰';
    const title = esc(f.title);
    return '<div class="feed-row"><span class="f-time">'+esc(t)+'</span><span class="f-src">'+esc(f.source)+'</span>'+
      '<span class="f-txt"><a href="'+esc(f.url)+'" target="_blank" rel="noopener" style="color:inherit;text-decoration:none">'+title+'</a></span>'+
      '<span class="tag c">'+tag+'</span></div>';
  }).join('');
}

/* ---------- 經濟日曆（摺疊）---------- */
function renderCalendarFold(){
  const all = (DASH_DATA.calendar.next24h||[]).concat(DASH_DATA.calendar.next48h||[]);
  $('calCount').textContent = '// NEXT 48H · '+pad(all.length)+' HIGH EVENTS';
  $('calBody').innerHTML = all.slice(0,12).map(e=>{
    const cls = e.delta_hours<=24?'hi':'mid';
    const lbl = e.delta_hours<=24?'HIGH':'MID+';
    return '<div class="cal-row"><span class="c-time">'+esc(e.time_hm)+'</span>'+
      '<span class="impact '+cls+'" style="justify-self:start">'+lbl+'</span>'+
      '<span class="c-name">'+esc(e.title)+'<small>'+esc(e.country)+' · '+esc(e.date_label)+'</small></span>'+
      '<span class="c-fcst">預測 <b>'+esc(e.forecast||'—')+'</b><br>前值 '+esc(e.previous||'—')+'</span></div>';
  }).join('') || '<div class="cal-row"><span class="c-name">未來 48h 無 High 級事件</span></div>';
}

/* ---------- 傳導矩陣摺疊（取代舊場景推演）---------- */
function renderMatrixFold(){
  const evs = DASH_DATA.events;
  $('matrixFoldCount').textContent = '// ACTIVE · '+pad(evs.length)+' EVENTS';
  if(!evs.length){
    $('matrixFoldBody').innerHTML = '<div style="padding:8px 0;color:var(--txt-faint);font-size:12px">暫無活躍事件；矩陣規則庫 E1-E12 持續待命。</div>';
    return;
  }
  $('matrixFoldBody').innerHTML = evs.map(e=>{
    const p = e.severity==='high'?'bear':(e.severity==='med'?'base':'bull');
    const pLabel = e.severity==='high'?'🔴 高嚴重度':(e.severity==='med'?'🟠 中級':'🔵 參考');
    const sevIcon = e.severity==='high'?'🔴':(e.severity==='med'?'🟠':'🔵');
    const chain = e.chain.map((s,i)=>'<div class="step" style="display:flex;gap:8px;padding:2px 0;font-size:11px;color:var(--txt)"><span style="font-family:var(--mono);width:18px;height:18px;border-radius:50%;border:1px solid rgba(45,212,255,.4);color:var(--cyan);font-size:9.5px;display:flex;align-items:center;justify-content:center;flex:none">'+(i+1)+'</span>'+esc(s)+'</div>').join('');
    return '<div class="scen"><div class="s-h">'+sevIcon+' '+esc(e.etype)+' '+esc(e.etype_name)+'<span class="s-p '+p+'">'+pLabel+'</span></div>'+
      '<div class="s-b" style="margin-bottom:6px">'+esc(e.headline)+'</div>'+
      '<div style="margin:6px 0">'+chain+'</div></div>';
  }).join('');
}

/* ---------- footer 數據源狀態 ---------- */
function renderFooter(){
  const s = DASH_DATA.sources_status||{};
  $('footSources').textContent = Object.entries(s).map(([k,v])=>k+':'+(v.startsWith('OK')?'✓':'⚠')).join(' · ');
}

/* ---------- SVG 降級地圖（數據驅動）---------- */
function projectLL(lat,lng){
  // 等距柱狀投影：lng[-180,180]→x[0,1000]，lat[80,-60]→y[0,500]
  const x = (lng+180)/360*1000;
  const y = (80-lat)/140*500;
  return [x,y];
}
function arcPath(slat,slng,elat,elng){
  const [x1,y1]=projectLL(slat,slng), [x2,y2]=projectLL(elat,elng);
  const mx=(x1+x2)/2, my=Math.min(y1,y2)-Math.abs(x2-x1)*0.18-30;
  return 'M'+x1.toFixed(0)+','+y1.toFixed(0)+' Q'+mx.toFixed(0)+','+my.toFixed(0)+' '+x2.toFixed(0)+','+y2.toFixed(0);
}
function renderFallbackMap(){
  const evs = DASH_DATA.events, arcs = DASH_DATA.arcs;
  let arcsHtml = arcs.map(a=>'<path class="fb-arc" stroke="'+a.color+'" d="'+arcPath(a.startLat,a.startLng,a.endLat,a.endLng)+'" opacity=".45"/>').join('');
  let marks = evs.map(e=>{
    const [x,y]=projectLL(e.lat,e.lng);
    const dur = (2+e.id*0.3).toFixed(1);
    return '<g class="fb-marker" data-ev="'+e.id+'" style="cursor:pointer" transform="translate('+x.toFixed(0)+','+y.toFixed(0)+')">'+
      '<circle r="22" fill="transparent"/>'+
      '<circle r="14" fill="none" stroke="'+e.color+'" stroke-width="1.5" opacity=".8"><animate attributeName="r" values="6;20" dur="'+dur+'s" repeatCount="indefinite"/><animate attributeName="opacity" values=".9;0" dur="'+dur+'s" repeatCount="indefinite"/></circle>'+
      '<circle r="6" fill="'+e.color+'" stroke="#fff" stroke-width="1.5"/>'+
      '<text class="fb-mlabel" x="12" y="-6">'+esc(e.name)+'</text></g>';
  }).join('');
  $('fbMapSvgDynamic').innerHTML = arcsHtml + marks;
  document.querySelectorAll('.fb-marker').forEach(m=>m.addEventListener('click',()=>showPopover(EVENTS[+m.dataset.ev])));
}

/* ============================================================
   Popover（事件傳導鏈卡）
============================================================ */
let world = null;
function showPopover(ev){
  try{ if(world) world.controls().autoRotate=false; }catch(e){}
  const pop = document.getElementById('popover');
  document.getElementById('popTitle').textContent = ev.title;
  document.getElementById('popLoc').textContent = ev.loc;
  document.getElementById('popTime').textContent = ev.time;
  document.getElementById('popChain').innerHTML = ev.chain.map((s,i)=>
    '<div class="step"><span class="n">'+(i+1)+'</span>'+esc(s)+'</div>'+(i<ev.chain.length-1?'<div class="link"></div>':'')
  ).join('');
  const dirTxt = {g:'利好 ↑',r:'利空 ↓',a:'關注 ◆',n:'待定 ?'};
  document.getElementById('popAssets').innerHTML = ev.assets.map(a=>
    '<div class="ah-row"><span class="emo">'+a[0]+'</span><span class="nm">'+esc(a[1])+'</span><span class="dir '+a[3]+'">'+a[2]+' · '+dirTxt[a[3]]+'</span></div>'
  ).join('');
  pop.classList.add('open');
}
document.getElementById('popClose').addEventListener('click',()=>{
  document.getElementById('popover').classList.remove('open');
  try{ if(world) world.controls().autoRotate=true; }catch(e){}
});

/* ============================================================
   3D 地球（globe.gl CDN，失敗降級 SVG）—— 邏輯同模板原版
============================================================ */
function activateFallback(reason){
  const ld = document.getElementById('globeLoading');
  if(ld) ld.style.display='none';
  document.getElementById('fbMap').style.display='block';
  renderFallbackMap();
  console.warn('[Ernest市觀] 3D 地球降級為 SVG 地圖：', reason);
}
function initGlobe(){
  try{
    if(typeof Globe === 'undefined'){ activateFallback('Globe 未定義'); return; }
    const N = window.THREE || null;
    const EVENTS = DASH_DATA.events, ARCS = DASH_DATA.arcs;

    const markerEl = ev => {
      const el = document.createElement('div');
      el.className = 'g-marker '+ev.cls;
      el.innerHTML =
        '<div class="ripple"></div><div class="ripple r2"></div>'+
        '<div class="core"></div>'+
        '<div class="mlabel">'+ev.name+'</div>';
      el.addEventListener('click', e=>{ e.stopPropagation(); showPopover(ev); });
      el.addEventListener('mouseenter', ()=>{ try{ world.controls().autoRotate=false; }catch(e){} });
      el.addEventListener('mouseleave', ()=>{ try{ if(!document.getElementById('popover').classList.contains('open')) world.controls().autoRotate=true; }catch(e){} });
      return el;
    };
    const hexToRgba = (hex,a)=>{
      const n = parseInt(hex.slice(1),16);
      return 'rgba('+((n>>16)&255)+','+((n>>8)&255)+','+(n&255)+','+a+')';
    };

    const vizEl = document.getElementById('globeViz');
    world = Globe()
      .width(vizEl.clientWidth).height(vizEl.clientHeight)
      .backgroundColor('rgba(0,0,0,0)')
      .globeMaterial(new (N.MeshPhoneMaterial || N.MeshPhongMaterial)({color:0x0a1424, emissive:0x06101f, shininess:4}))
      .atmosphereColor('#2dd4ff').atmosphereAltitude(0.22)
      .showGraticules(true)
      .pointsData(EVENTS).pointLat('lat').pointLng('lng').pointColor(d=>d.color)
      .pointAltitude(0.012).pointRadius(0.16)
      .ringsData(EVENTS).ringLat('lat').ringLng('lng')
      .ringColor(d=>()=>d.color).ringMaxRadius(7).ringPropagationSpeed(2.2)
      .ringRepeatPeriod(1400).ringAltitude(0.014)
      .htmlElementsData(EVENTS).htmlElement(d=>markerEl(d))
      .htmlLat('lat').htmlLng('lng').htmlAltitude(0.06).htmlTransitionDuration(900)
      .arcsData(ARCS)
      .arcStartLat('startLat').arcStartLng('startLng').arcEndLat('endLat').arcEndLng('endLng')
      .arcColor(d=>[hexToRgba(d.color,.05), d.color])
      .arcDashLength(0.45).arcDashGap(0.3).arcDashAnimateTime(4200)
      .arcStroke(0.45).arcAltitudeAutoScale(0.32)
      (document.getElementById('globeViz'));

    try{ world.renderer().setPixelRatio(Math.min(window.devicePixelRatio||1,2)); }catch(e){}
    const aspect = vizEl.clientWidth / Math.max(1,vizEl.clientHeight);
    // 鏡頭推近：個球填滿舞台約 80-90% 高度（舊值 2.6 太遠，底部空一大舊）
    const fitAlt = 2.02 + Math.max(0,(aspect-1.5))*0.55;

    (function loadCountryPolygons(){
      const TOPO_SRC='https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js';
      const WORLD_SRC='https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json';
      const HOT={'36':'#ff4d6d','68':'#ffb020','818':'#ffb020','710':'#ff4d6d','392':'#ffb020','410':'#ffb020','156':'#ffb020','840':'#2dd4ff','826':'#2dd4ff','276':'#2dd4ff','702':'#2dd4ff'};
      const loadScript = u => new Promise((res,rej)=>{ const s=document.createElement('script');s.src=u;s.onload=res;s.onerror=rej;document.head.appendChild(s); });
      const hexA=(hex,a)=>{const n=parseInt(hex.slice(1),16);return 'rgba('+((n>>16)&255)+','+((n>>8)&255)+','+(n&255)+','+a+')';};
      loadScript(TOPO_SRC).then(()=>fetch(WORLD_SRC))
        .then(r=>{if(!r.ok)throw new Error('world-atlas '+r.status);return r.json();})
        .then(topo=>{
          const fc = window.topojson.feature(topo, topo.objects.countries);
          const polys = fc.features.map(f=>{ const hot=HOT[String(f.id)];
            return {...f, fill: hot?hexA(hot,0.22):'rgba(46,66,99,0.55)', stroke: hot?hexA(hot,0.95):'rgba(120,175,230,0.4)'}; });
          world.polygonsData(polys).polygonCapColor(d=>d.fill).polygonSideColor(()=>'rgba(28,42,66,0.5)')
            .polygonStrokeColor(d=>d.stroke).polygonAltitude(0.008);
          console.log('[Ernest市觀] 國家邊界載入完成：'+polys.length+' 個國家');
        }).catch(e=>console.warn('[Ernest市觀] 國家邊界載入失敗：',e));
    })();

    world.controls().autoRotate=true; world.controls().autoRotateSpeed=0.55;
    world.controls().enableZoom=false; world.controls().enablePan=false;
    world.pointOfView({lat:20,lng:45,altitude:Math.max(1.95,fitAlt)},1400);

    if(N){ try{
      const starGeo=new N.BufferGeometry(); const n=900, pos=new Float32Array(n*3);
      for(let i=0;i<n;i++){ const r=600+Math.random()*600, th=Math.random()*Math.PI*2, ph=Math.acos(2*Math.random()-1);
        pos[i*3]=r*Math.sin(ph)*Math.cos(th); pos[i*3+1]=r*Math.sin(ph)*Math.sin(th); pos[i*3+2]=r*Math.cos(ph); }
      starGeo.setAttribute('position',new N.BufferAttribute(pos,3));
      world.scene().add(new N.Points(starGeo,new N.PointsMaterial({color:0x9fd8ff,size:1.4,sizeAttenuation:true,transparent:true,opacity:0.75})));
    }catch(e){} }

    const ld=document.getElementById('globeLoading');
    setTimeout(()=>{ if(ld) ld.style.display='none'; },600);
    window.addEventListener('resize',()=>{ const st=document.getElementById('globeViz'); world.width(st.clientWidth).height(st.clientHeight); const a=st.clientWidth/Math.max(1,st.clientHeight); world.pointOfView({altitude:Math.max(1.95,2.02+Math.max(0,(a-1.5))*0.55)},400); });
  }catch(err){ activateFallback(err.message||'init error'); }
}

(function boot(){
  let done=false;
  const fail=(r)=>{ if(done)return; done=true; activateFallback(r); };
  const win=()=>{ if(done)return; done=true; initGlobe(); };
  const s1=document.createElement('script');
  s1.src='https://unpkg.com/three@0.160.0/build/three.min.js';
  s1.onload=()=>{ const s2=document.createElement('script');
    s2.src='https://unpkg.com/globe.gl@2.33.0/dist/globe.gl.min.js';
    s2.onload=()=>setTimeout(win,60); s2.onerror=()=>fail('globe.gl CDN 載入失敗');
    document.head.appendChild(s2); };
  s1.onerror=()=>{ const s2=document.createElement('script');
    s2.src='https://unpkg.com/globe.gl@2.33.0/dist/globe.gl.min.js';
    s2.onload=()=>setTimeout(win,60); s2.onerror=()=>fail('CDN 全部不可達');
    document.head.appendChild(s2); };
  document.head.appendChild(s1);
  setTimeout(()=>fail('CDN 載入逾時'),7000);
})();

/* ============================================================
   即時財經直播 TV（YouTube 官方 24/7 直播嵌入，靜音自動播放；HLS 備援）
============================================================ */
const TV_SOURCES = [
  {id:'bloomberg', name:'BLOOMBERG', zh:'彭博財經',
   embed:'https://www.youtube-nocookie.com/embed/live_stream?channel=UCIALMKvObZNtJ6AmdCLP7Lg',
   yt:'https://www.youtube.com/@markets/live'},
  {id:'quicktake', name:'QUICKTAKE', zh:'彭博快訊',
   embed:'https://www.youtube-nocookie.com/embed/iEpJwprxDdk',
   yt:'https://www.youtube.com/watch?v=iEpJwprxDdk'},
  {id:'sky', name:'SKY NEWS', zh:'天空新聞',
   embed:'https://www.youtube-nocookie.com/embed/live_stream?channel=UCoMdktPbSTixAyNGwb-Ukfw',
   yt:'https://www.youtube.com/@SkyNews/live'},
  {id:'dw', name:'DW NEWS', zh:'德國之聲',
   embed:'https://www.youtube-nocookie.com/embed/live_stream?channel=UCknLrEdhRCp1aegoMqRaCZg',
   yt:'https://www.youtube.com/@dwnews/live'},
  {id:'aljazeera', name:'AL JAZEERA', zh:'半島電視',
   embed:'https://www.youtube-nocookie.com/embed/live_stream?channel=UCNye-wNBqNL5ZzHSJj3l8Bg',
   yt:'https://www.youtube.com/@aljazeeraenglish/live'},
  {id:'cgtn', name:'CGTN', zh:'中國環球電視網',
   hls:'https://live.cgtn.com/1000/prog_index.m3u8',
   yt:'https://news.cgtn.com/tv'},
  {id:'cna', name:'CNA', zh:'亞洲新聞',
   hls:'https://d2e1asnsl7br7b.cloudfront.net/7782e205e72f43aeb4a48ec97f66ebbe/index_5.m3u8',
   yt:'https://www.channelnewsasia.com/watch'}
];
function initTV(){
  const tabs=$('tvTabs'), frame=$('tvFrame'), video=$('tvHls'),
        poster=$('tvPoster'), pName=$('tvPName'),
        fail=$('tvFail'), fLink=$('tvFailLink'),
        yt=$('tvOpenYt'), snd=$('tvSoundBtn');
  if(!tabs||!frame) return;
  let cur=0, muted=true, loadT=null, playing=false, ytBlocked=false, hlsP=null;

  function loadHls(s){
    const win=window;
    if(!win.Hls||!video.canPlayType('application/vnd.apple.mpegurl')){
      showFail(s); return;
    }
    fail.style.display='none'; poster.style.display='none';
    frame.style.display='none'; video.style.display='block';
    if(hlsP){ hlsP.destroy(); hlsP=null; }
    const h=new win.Hls();
    hlsP=h;
    h.loadSource(s.hls);
    h.attachMedia(video);
    h.on(win.Hls.Events.MANIFEST_PARSED,()=>{ video.play().catch(()=>{}); });
    h.on(win.Hls.Events.ERROR,(_,d)=>{
      if(d.fatal) showFail(s);
    });
  }
  function showFail(s){
    fLink.href=s.yt;
    fail.style.display='flex';
    poster.style.display='none';
    frame.style.display='';
    video.style.display='none';
  }
  function play(){
    const s=TV_SOURCES[cur];
    playing=true;
    fail.style.display='none';
    poster.style.display='none';
    if(loadT) clearTimeout(loadT);
    loadT=setTimeout(()=>{ if(playing){ if(!ytBlocked&&s.embed) showFail(s); } }, 8000);
    if(ytBlocked&&s.hls){ loadHls(s); return; }
    if(!s.embed){ loadHls(s); return; }
    frame.style.display=''; video.style.display='none';
    frame.src=s.embed+'?autoplay=1&mute='+(muted?1:0)+'&rel=0';
  }
  function select(i){
    cur=i;
    Array.from(tabs.children).forEach((t,k)=>t.classList.toggle('active',k===i));
    const s=TV_SOURCES[i];
    yt.href=s.yt;
    pName.textContent=s.name;
    fail.style.display='none';
    poster.style.display='flex';
    frame.removeAttribute('src');
    frame.style.display='';
    video.style.display='none';
    if(loadT) clearTimeout(loadT);
    playing=false;
  }
  TV_SOURCES.forEach((s,i)=>{
    const b=document.createElement('button');
    b.className='tv-tab'+(i===0?' active':'');
    b.innerHTML=s.name+' <small style="opacity:.68;font-weight:400">'+s.zh+'</small>';
    b.onclick=()=>{
      if(i!==cur){ muted=true; snd.innerHTML='🔇 已靜音'; select(i); }
    };
    tabs.appendChild(b);
  });
  snd.onclick=()=>{
    muted=!muted;
    snd.innerHTML=muted?' 已靜音':'🔊 開聲';
    if(video.style.display!=='none') video.muted=muted;
    if(playing) play();
  };
  poster.onclick=play;
  frame.onload=()=>{ if(loadT){ clearTimeout(loadT); loadT=null; } fail.style.display='none'; };
  yt.href=TV_SOURCES[0].yt;

  // YouTube 封鎖偵測（試載一張 YouTube thumbnail）
  const probe=new Image();
  probe.onload=()=>{}; // YouTube 通
  probe.onerror=()=>{ ytBlocked=true; };
  probe.src='https://img.youtube.com/vi/dQw4w9WgXcQ/default.jpg';
}

/* ============================================================
   NEWS ⇄ MARKETS 關聯圖（DASH_DATA.market_corr，內聯 SVG 雙軌）
============================================================ */
const NM = (DASH_DATA.market_corr||{windows:{},topics_meta:[],markets_meta:[],generated:''});
function pearson(a,b){
  const n=a.length; if(n<5) return null;
  let ma=0,mb=0; for(let i=0;i<n;i++){ma+=a[i];mb+=b[i];} ma/=n; mb/=n;
  let num=0,da=0,db=0;
  for(let i=0;i<n;i++){const dx=a[i]-ma,dy=b[i]-mb;num+=dx*dy;da+=dx*dx;db+=dy*dy;}
  if(da===0||db===0) return null;
  return num/Math.sqrt(da*db);
}
function nmInterp(r){
  if(r===null) return '數據點不足，未能計算相關係數。';
  const a=Math.abs(r);
  const strength=a<0.2?'幾乎冇':a<0.4?'弱':a<0.7?'中等':'強';
  const dir=r>0?'正相關':'負相關';
  const verb=r>0?'齊上齊落':'背馳';
  return '呢段時間兩條線呈<b>'+strength+dir+'</b>（r = '+r.toFixed(2)+'），即「'+
    $('nmTopic').selectedOptions[0].text+'」新聞熱度同「'+
    $('nmMarket').selectedOptions[0].text+'」走勢大致'+verb+
    '。留意：相關唔等於因果，只反映關注度同價格嘅同步程度。';
}
function nmRender(){
  const box=$('nmChart'), stats=$('nmStats');
  const tk=$('nmTopic').value, mk=$('nmMarket').value, wk=$('nmWindow').value;
  const win=(NM.windows||{})[wk]||{};
  const news=(win.topics||{})[tk], px=(win.markets||{})[mk];
  if(!news||!px||news.length<3){
    box.innerHTML='<div class="nm-empty">⚠️ 呢個組合暫時冇數據（採集時 GDELT/CNBC 超時會留空，下次生成自動重試）</div>';
    stats.innerHTML=''; return;
  }
  const pm=new Map(px.map(p=>[p[0],p[1]]));
  const xs=[],nv=[],pv=[];
  news.forEach(p=>{ if(pm.has(p[0])){ xs.push(p[0]); nv.push(p[1]); pv.push(pm.get(p[0])); } });
  if(xs.length<5){
    box.innerHTML='<div class="nm-empty">⚠️ 對齊後數據點不足（市場休市或時段唔重疊）</div>';
    stats.innerHTML=''; return;
  }
  const W=920,H=340,L=60,R=66,T=18,B=34;
  const nMin=Math.min(...nv),nMax=Math.max(...nv),pMin=Math.min(...pv),pMax=Math.max(...pv);
  const X=i=>L+(W-L-R)*i/(xs.length-1);
  const Yn=v=>T+(H-T-B)*(1-(nMax===nMin?0.5:(v-nMin)/(nMax-nMin)));
  const Yp=v=>T+(H-T-B)*(1-(pMax===pMin?0.5:(v-pMin)/(pMax-pMin)));
  const path=arr=>arr.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+','+v.toFixed(1)).join(' ');
  const fmtV=v=>Math.abs(v)>=1000?Math.round(v).toLocaleString('en-US'):Number(v).toFixed(2);
  let xlab='';
  for(let i=0;i<5;i++){
    const idx=Math.round(i*(xs.length-1)/4);
    const d=new Date(xs[idx]*1000);
    const lab=wk==='1d'?pad(d.getHours())+':'+pad(d.getMinutes()):(d.getMonth()+1)+'/'+d.getDate()+' '+pad(d.getHours())+'h';
    xlab+='<text x="'+X(idx)+'" y="'+(H-10)+'" fill="rgba(126,147,173,.75)" font-size="10" font-family="monospace" text-anchor="middle">'+lab+'</text>';
  }
  const ylab=(y,v,col,anchor,x)=>'<text x="'+x+'" y="'+(y+3)+'" fill="'+col+'" font-size="10" font-family="monospace" text-anchor="'+anchor+'">'+v+'</text>';
  box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'+
    '<line x1="'+L+'" y1="'+T+'" x2="'+L+'" y2="'+(H-B)+'" stroke="rgba(86,156,214,.2)"/>'+
    '<line x1="'+(W-R)+'" y1="'+T+'" x2="'+(W-R)+'" y2="'+(H-B)+'" stroke="rgba(86,156,214,.2)"/>'+
    '<line x1="'+L+'" y1="'+(H-B)+'" x2="'+(W-R)+'" y2="'+(H-B)+'" stroke="rgba(86,156,214,.25)"/>'+
    ylab(T,fmtV(nMax),'#ffb020','end',L-7)+ylab(H-B,fmtV(nMin),'#ffb020','end',L-7)+
    ylab(T,fmtV(pMax),'#2dd4ff','start',W-R+7)+ylab(H-B,fmtV(pMin),'#2dd4ff','start',W-R+7)+
    xlab+
    '<path d="'+path(nv.map(Yn))+'" fill="none" stroke="#ffb020" stroke-width="1.8" opacity=".95"/>'+
    '<path d="'+path(pv.map(Yp))+'" fill="none" stroke="#2dd4ff" stroke-width="1.8" opacity=".95"/>'+
    '</svg>';
  const r=pearson(nv,pv);
  const cls=r===null?'weak':(Math.abs(r)<0.2?'weak':(r>0?'pos':'neg'));
  stats.innerHTML=
    '<div><span class="st">PEARSON r</span><span class="r '+cls+'">'+(r===null?'—':r.toFixed(2))+'</span></div>'+
    '<div><span class="st">對齊樣本 n</span><span class="r weak" style="font-size:18px">'+xs.length+'</span></div>'+
    '<div class="interp">'+nmInterp(r)+'</div>';
}
function initNM(){
  const ov=$('nmOverlay'); if(!ov) return;
  const tSel=$('nmTopic'),mSel=$('nmMarket');
  (NM.topics_meta||[]).forEach(t=>{ const o=document.createElement('option'); o.value=t.key; o.textContent=t.zh; tSel.appendChild(o); });
  (NM.markets_meta||[]).forEach(m=>{ const o=document.createElement('option'); o.value=m.key; o.textContent=m.zh; mSel.appendChild(o); });
  tSel.value='sanctions'; mSel.value='SPX';
  $('nmGen').textContent=NM.generated?('數據快照 '+NM.generated):'';
  [tSel,mSel,$('nmWindow')].forEach(el=>el.addEventListener('change',nmRender));
  $('nmOpenBtn').onclick=()=>{ ov.classList.add('open'); nmRender(); };
  $('nmClose').onclick=()=>ov.classList.remove('open');
  ov.onclick=e=>{ if(e.target===ov) ov.classList.remove('open'); };
  document.addEventListener('keydown',e=>{ if(e.key==='Escape') ov.classList.remove('open'); });
}

/* ============================================================
   啟動
============================================================ */
initClock();
initTV();
initNM();
renderThermo();
renderSentiment();
renderRiskClock();
renderEventCards();
renderGlobeChips();
renderTicker();
renderHoldings();
renderPosition();
renderBrief();
renderFeed();
renderCalendarFold();
renderMatrixFold();
renderFooter();
""".replace("__DATA__", data_json)


# ============================================================= 模板改造
def ensure_template():
    """若 pipeline_v2/template.html 唔存在，從 mockup 複製並改造成掛點版。"""
    if os.path.exists(TEMPLATE):
        return TEMPLATE
    if not os.path.exists(MOCKUP_SRC):
        raise FileNotFoundError(f"找不到 UI 模板：{MOCKUP_SRC}")
    html = open(MOCKUP_SRC, encoding="utf-8").read()

    def repl(start_marker, end_marker, new_block, text):
        i = text.index(start_marker)
        j = text.index(end_marker, i) + len(end_marker)
        return text[:i] + new_block + text[j:]

    # ---- 頂欄日期/時鐘
    html = repl(
        '<div class="clockbox">', '</div>\n    <div class="top-sep"></div>',
        '<div class="clockbox">\n'
        '      <div class="date" id="dateLine">—</div>\n'
        '      <div class="time" id="hkClock">—<small>HKT</small></div>\n'
        '    </div>\n    <div class="top-sep"></div>',
        html)

    # ---- 溫度計
    html = repl('<div class="thermo">', '</div>\n\n    <div class="sentiment">',
        '<div class="thermo">\n'
        '      <div class="thermo-label">風險<br>溫度計</div>\n'
        '      <div class="thermo-bar">\n'
        '        <div class="needle" id="needle" style="left:30%"></div>\n'
        '        <div class="thermo-segs" id="thermoSegs"><i></i><i></i><i></i><i></i></div>\n'
        '        <div class="thermo-names" id="thermoNames"><span>LOW</span><span>MODERATE</span><span>HIGH</span><span>EXTREME</span></div>\n'
        '      </div>\n'
        '      <div class="thermo-val" id="thermoVal">—<small>RISK /100</small></div>\n'
        '    </div>\n\n    <div class="sentiment">',
        html)

    # ---- 情緒七格 + regime pill
    i = html.index('<div class="sentiment">')
    j = html.index('</header>', i)
    html = (html[:i] +
            '<div class="sentiment" id="sentimentBox"></div>\n'
            '    <div class="regime-pill" id="regimePill"></div>\n  ' +
            html[j:])

    # ---- 風險時鐘面板
    html = repl('<div class="clock-hero">', '<div class="mini-cal">',
        '<div class="clock-hero">\n'
        '          <div class="countdown" id="cd">—</div>\n'
        '          <div class="cd-label">距離下一個高影響事件</div>\n'
        '          <div class="event-next" id="nextEvent"></div>\n'
        '          <div class="ea-pause">🤖 <span id="fedChipLine"></span></div>\n'
        '        </div>\n        <div class="mini-cal" id="miniCal">',
        html)
    # mini-cal 舊 row 清到 </div> 之後
    html = repl('<div class="mini-cal" id="miniCal">', '</div>\n      </div>',
        '<div class="mini-cal" id="miniCal"></div>\n      </div>',
        html)
    # EVENT chip
    html = html.replace('<span class="chip">EVENT&nbsp;<b>04</b></span>',
                        '<span class="chip" id="riskCountChip">EVENT&nbsp;<b>—</b></span>')

    # ---- 事件卡面板
    i = html.index('<div class="panel reveal" style="animation-delay:.12s">')
    j = html.index('</section>', i)
    new_panel = ('<div class="panel reveal" style="animation-delay:.12s">\n'
        '        <div class="panel-head"><span class="dot" style="background:var(--red);box-shadow:0 0 8px var(--red)"></span>\n'
        '          <span class="zh">黑天鵝 / 突發事件</span><span class="right"><span class="live-tag"><i></i><span id="activeCount">0 ACTIVE</span></span></span></div>\n'
        '        <div id="eventCards"></div>\n'
        '      </div>\n    </section>\n\n    <!-- ========== 中央地球 ========== -->\n    <section class="col">\n  ')
    html = html[:i] + new_panel + html[j:]

    # ---- 地球 chips
    html = repl('<span class="sub">GLOBAL THREAT MAP · 3D</span>\n          <span class="right">',
                'WATCH</b></span>\n          </span>\n        </div>',
                '<span class="sub">GLOBAL THREAT MAP · 3D</span>\n          <span class="right" id="globeChips"></span>\n        </div>',
                html)

    # ---- SVG fallback：固定 arcs/markers 改為動態 group
    i = html.index('<!-- 傳導弧線（與3D版對應）-->')
    j = html.index('</svg>', i)
    html = (html[:i] +
            '<!-- 傳導弧線＋標記（數據驅動，DASH_DATA）-->\n'
            '<g id="fbMapSvgDynamic"></g>\n          ' +
            html[j:])

    # ---- 持倉面板（由持倉 panel 開頭，到倉位速覽 panel 開頭前）
    pos_start_marker = '<div class="panel reveal" style="animation-delay:.3s">'
    i = html.index('<div class="panel reveal" style="animation-delay:.24s">')
    j = html.index(pos_start_marker, i)
    holdings_panel = ('<div class="panel reveal" style="animation-delay:.24s">\n'
        '        <div class="panel-head"><span class="dot" style="background:var(--amber);box-shadow:0 0 8px var(--amber)"></span>\n'
        '          <span class="zh">持倉影響矩陣</span><span class="sub">PORTFOLIO × TODAY · 模擬倉 DEMO</span>\n'
        '          <span class="right"><span class="chip">模擬倉 DEMO</span></span></div>\n'
        '        <div id="holdingsBody"></div>\n'
        '        <div class="matrix-foot" id="matrixFoot"></div>\n'
        '      </div>\n\n      ')
    html = html[:i] + holdings_panel + html[j:]

    # ---- 倉位速覽（由 position panel 開頭到右欄 </section>）
    i = html.index(pos_start_marker)
    j = html.index('</section>', i)
    pos_panel = ('<div class="panel reveal" style="animation-delay:.3s">\n'
        '        <div class="panel-head"><span class="dot" style="background:var(--violet);box-shadow:0 0 8px var(--violet)"></span>\n'
        '          <span class="zh">倉位速覽 / 動向</span><span class="right"><span class="chip">模擬倉 DEMO</span></span></div>\n'
        '        <div id="positionBody" style="padding:12px"></div>\n'
        '      </div>\n    ')
    html = html[:i] + pos_panel + html[j:]

    # ---- Brief 面板
    i = html.index('<section class="panel reveal" style="margin-top:10px;animation-delay:.34s">')
    j = html.index('</section>', i)
    brief_panel = ('<section class="panel reveal" style="margin-top:10px;animation-delay:.34s">\n'
        '    <div class="panel-head"><span class="dot" style="background:var(--green);box-shadow:0 0 8px var(--green)"></span>\n'
        '      <span class="zh">📋 今日 Brief</span><span class="sub" id="briefSub">DAILY INTEL</span>\n'
        '      <span class="right"><span class="chip">5 重點</span></span></div>\n'
        '    <div style="padding:12px">\n'
        '      <div class="brief-grid" id="briefCards"></div>\n'
        '      <div class="accordion" style="margin-top:12px">\n'
        '        <details class="fold" open>\n'
        '          <summary><span class="caret">▶</span><span class="zh">📰 新聞 Feed</span><span class="cnt" id="feedCount"></span></summary>\n'
        '          <div class="fold-body" id="feedBody"></div>\n'
        '        </details>\n'
        '        <details class="fold">\n'
        '          <summary><span class="caret">▶</span><span class="zh">🗓️ 經濟日曆</span><span class="cnt" id="calCount"></span></summary>\n'
        '          <div class="fold-body" id="calBody"></div>\n'
        '        </details>\n'
        '        <details class="fold">\n'
        '          <summary><span class="caret">▶</span><span class="zh">🔗 事件傳導鏈</span><span class="cnt" id="matrixFoldCount"></span></summary>\n'
        '          <div class="fold-body" id="matrixFoldBody"></div>\n'
        '        </details>\n'
        '      </div>\n'
        '    </div>\n'
        '  ')
    html = html[:i] + brief_panel + html[j:]

    # ---- footer
    i = html.index('<footer class="foot">')
    j = html.index('</footer>', i) + len('</footer>')
    footer = ('<footer class="foot">\n'
        '    <span class="sys">● SYSTEM NOMINAL</span>\n'
        '    <span>ERNEST DAILY MARKET OPS · WorldMonitor v2</span>\n'
        '    <span id="footSources">DATA FEED: —</span>\n'
        '    <span>⚠️ AI 生成內容僅供參考，不構成投資建議；場景分析基於歷史數據同統計概率，唔係預測保證；投資有風險，決策請結合自身情況並咨詢專業人士。</span>\n'
        '  </footer>')
    html = html[:i] + footer + html[j:]

    # ---- 整段 script 換成數據驅動版（由 render 注入 __SCRIPT__）
    i = html.index('<script>')
    j = html.rindex('</script>') + len('</script>')
    html = html[:i] + '<script>\n__SCRIPT__\n</script>' + html[j:]

    os.makedirs(HERE, exist_ok=True)
    with open(TEMPLATE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[render_v2] 模板改造完成 → {TEMPLATE}")
    return TEMPLATE


def render_html(dash_data, out_path):
    """讀 template.html，注入 JS，寫出成品。"""
    ensure_template()
    tpl = open(TEMPLATE, encoding="utf-8").read()
    js = build_js(dash_data)
    html = tpl.replace("__SCRIPT__", js)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
