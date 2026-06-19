"""Build a self-contained HTML clinical report from the exported JSON dataset.

Reads dataset/_embed.json (compact, produced by the analysis step) and writes
docs/bao-cao-suc-khoe-18062026.html with inline SVG charts (no external libs,
works offline). Re-run after refreshing the JSON to regenerate the report.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "dataset" / "_embed.json").read_text(encoding="utf-8"))
OUT = ROOT / "docs" / "bao-cao-suc-khoe-18062026.html"

HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Báo cáo sức khỏe — polar_h10 — 18/06/2026</title>
<style>
  :root{
    --bg:#0f1419; --panel:#171e26; --panel2:#1e2730; --line:#2a3540;
    --txt:#e6edf3; --muted:#8b98a5; --accent:#4aa8ff;
    --green:#3fb950; --yellow:#d29922; --orange:#f0883e; --red:#f85149; --purple:#bc8cff;
    --shadow:0 1px 3px rgba(0,0,0,.4);
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.55;font-size:15px}
  .wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
  header{border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:26px}
  h1{font-size:26px;margin:0 0 6px;font-weight:700}
  .sub{color:var(--muted);font-size:14px}
  h2{font-size:19px;margin:38px 0 14px;display:flex;align-items:center;gap:9px}
  h2 .dot{width:9px;height:9px;border-radius:50%;background:var(--accent)}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:18px 20px;box-shadow:var(--shadow);margin-bottom:18px}
  .grid{display:grid;gap:14px}
  .kpis{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
  .kpi{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .kpi .lbl{color:var(--muted);font-size:12.5px;margin-bottom:4px}
  .kpi .val{font-size:26px;font-weight:700;line-height:1.1}
  .kpi .unit{font-size:13px;color:var(--muted);font-weight:400}
  .kpi .note{font-size:12px;margin-top:3px}
  .b-green{color:var(--green)} .b-yellow{color:var(--yellow)} .b-orange{color:var(--orange)}
  .b-red{color:var(--red)} .b-purple{color:var(--purple)} .b-accent{color:var(--accent)}
  .two{grid-template-columns:1fr 1fr}
  @media(max-width:760px){.two{grid-template-columns:1fr}}
  .chart-title{font-size:15px;font-weight:600;margin-bottom:2px}
  .chart-sub{font-size:12.5px;color:var(--muted);margin-bottom:12px}
  svg{display:block;width:100%;height:auto;overflow:visible}
  .legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;font-size:12.5px;color:var(--muted)}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .legend i{width:11px;height:11px;border-radius:3px;display:inline-block}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-weight:600;font-size:12.5px}
  td.hr{font-weight:600}
  .scrollx{overflow-x:auto}
  .alert-box{border-left:4px solid var(--red);background:rgba(248,81,73,.08);
    border-radius:8px;padding:14px 18px;margin-bottom:16px}
  .alert-box.warn{border-left-color:var(--orange);background:rgba(240,136,62,.08)}
  .alert-box h3{margin:0 0 6px;font-size:16px}
  .alert-box.warn h3{color:var(--orange)}
  .alert-box h3{color:var(--red)}
  ul.find{margin:8px 0 0;padding-left:20px}
  ul.find li{margin-bottom:7px}
  .tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;font-weight:600}
  .tag.crit{background:rgba(248,81,73,.18);color:var(--red)}
  .tag.high{background:rgba(240,136,62,.18);color:var(--orange)}
  .footer{color:var(--muted);font-size:12.5px;margin-top:34px;border-top:1px solid var(--line);padding-top:16px}
  .disclaimer{background:var(--panel2);border:1px dashed var(--line);border-radius:10px;
    padding:14px 18px;font-size:13px;color:var(--muted)}
  .pill{font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Báo cáo phân tích sức khỏe tim mạch</h1>
    <div class="sub">Bệnh nhân <b>polar_h10</b> · Thiết bị Polar H10 (ECG ngực) · Ngày theo dõi <b>18/06/2026</b> · Nguồn: MongoDB Atlas <code>elderly_care</code></div>
  </header>

  <!-- ALERT SUMMARY -->
  <div class="alert-box">
    <h3>⚠️ Phát hiện chính: Nhịp nhanh lúc nghỉ kéo dài, nặng dần về đêm</h3>
    <div>Nhịp tim nghỉ trung bình <b>109 bpm</b> (bình thường 60–100), tăng vọt buổi tối lên <b>148–182 bpm</b> khi bệnh nhân đang bất động. Kèm <b>nghi ngờ rung nhĩ</b>, <b>gánh nặng ngoại tâm thu cao (~32%)</b> và <b>26 sự kiện nguy kịch</b>. Xu hướng xấu đi rõ qua 3 ngày liên tiếp.</div>
  </div>

  <!-- KPI -->
  <div class="grid kpis" id="kpis"></div>

  <!-- HR TIMELINE -->
  <h2><span class="dot"></span>Diễn biến nhịp tim trong ngày</h2>
  <div class="panel">
    <div class="chart-title">Nhịp tim theo thời gian (trung vị mỗi phút, chỉ tín hiệu good/fair)</div>
    <div class="chart-sub">Vùng xanh: bình thường (&lt;100) · vàng: hơi nhanh (100–130) · đỏ: nhịp nhanh (&gt;130). Đường đứt là ngưỡng 100 và 130 bpm.</div>
    <div id="timeline"></div>
    <div class="legend">
      <span><i style="background:var(--accent)"></i>Nhịp tim (bpm)</span>
      <span><i style="background:var(--red)"></i>Sự kiện nguy kịch</span>
    </div>
  </div>

  <!-- HOURLY + BANDS -->
  <div class="grid two">
    <div class="panel">
      <div class="chart-title">Phân bố nhịp tim theo giờ</div>
      <div class="chart-sub">Thanh = khoảng min–max · hộp đậm = p25–p75 · vạch trắng = trung bình</div>
      <div id="hourly"></div>
    </div>
    <div class="panel">
      <div class="chart-title">Tỷ lệ thời gian theo dải nhịp tim</div>
      <div class="chart-sub">n = 4.227 cửa sổ tín hiệu tin cậy</div>
      <div id="bands"></div>
    </div>
  </div>

  <!-- STRESS -->
  <h2><span class="dot" style="background:var(--purple)"></span>Mức độ stress trong ngày</h2>
  <div class="alert-box warn">
    <h3>Diễn giải: tỷ lệ stress cao cần đọc cùng nhịp tim</h3>
    <div>Mô hình stress phân loại <b>46,3%</b> số cửa sổ tin cậy là "stress". Tuy nhiên các khung <b>19h–21h là 100% stress</b> — <b>trùng khít</b> với giai đoạn nhịp nhanh. Mô hình suy ra stress chủ yếu từ đặc trưng nhịp tim/HRV, nên nhãn "stress" ở đây nhiều khả năng phản ánh <b>kích hoạt giao cảm do nhịp nhanh</b> hơn là stress tâm lý đơn thuần — tức bị nhiễu bởi chính tình trạng rối loạn nhịp.</div>
  </div>
  <div class="grid two">
    <div class="panel">
      <div class="chart-title">Tỷ lệ stress / không stress (cả ngày)</div>
      <div class="chart-sub">n = 3.918 cửa sổ có kết quả hợp lệ (good/fair). 309 cửa sổ không xác định.</div>
      <div id="stressbar"></div>
    </div>
    <div class="panel">
      <div class="chart-title">Tỷ lệ % stress theo giờ</div>
      <div class="chart-sub">Cao điểm 19h–21h trùng với giai đoạn nhịp nhanh</div>
      <div id="stresshour"></div>
    </div>
  </div>

  <!-- 3-DAY TREND -->
  <h2><span class="dot" style="background:var(--red)"></span>Xu hướng nhịp tim nghỉ qua các ngày</h2>
  <div class="panel">
    <div class="chart-title">Nhịp tim lúc nghỉ trung bình — 17 → 18 → 19/06 (tăng dần đáng lo ngại)</div>
    <div class="chart-sub">Chỉ tính cửa sổ REST + tín hiệu good/fair. Ngày 19/6 mới ghi một phần nhưng mức tăng đã rất rõ.</div>
    <div id="days"></div>
  </div>

  <!-- EVENTS + RHYTHM -->
  <div class="grid two">
    <div class="panel">
      <div class="chart-title">Sự kiện theo loại (tổng 6.801)</div>
      <div class="chart-sub">Hệ thống tự phát hiện trong ngày</div>
      <div id="events"></div>
    </div>
    <div class="panel">
      <div class="chart-title">Phân loại nhịp & ngoại tâm thu</div>
      <div class="chart-sub">Trên tín hiệu good/fair</div>
      <div id="rhythm"></div>
    </div>
  </div>

  <!-- CRITICAL EVENTS TABLE -->
  <h2><span class="dot" style="background:var(--red)"></span>Danh sách sự kiện nguy kịch (26)</h2>
  <div class="panel scrollx">
    <table id="crit"></table>
  </div>

  <!-- CONCLUSION -->
  <h2><span class="dot" style="background:var(--purple)"></span>Kết luận & khuyến nghị</h2>
  <div class="panel">
    <p>Trong ngày 18/06/2026, bệnh nhân <b>polar_h10</b> có <b>nhịp nhanh lúc nghỉ kéo dài</b> (trung bình ngày 109 bpm), <b>tăng mạnh về đêm</b> (22h–23h trung bình ~148 bpm, đỉnh 182 bpm) trong khi <b>99% thời gian đang bất động</b> — đã được kiểm chứng không phải do vận động hay nhiễu tín hiệu (95% cửa sổ đạt chất lượng good/fair).</p>
    <p>Đồng thời ghi nhận bộ dấu hiệu rối loạn nhịp:</p>
    <ul class="find">
      <li><b>Nghi ngờ rung nhĩ (AF):</b> 49 cửa sổ <code>possible_afib</code>, 101 cửa sổ có xác suất AFib &gt; 0,3 (đỉnh 0,79), tổng 687 cảnh báo.</li>
      <li><b>Ngoại tâm thu nhiều:</b> 687 PAC + 627 PVC + 17 hỗn hợp ≈ <b>32%</b> số cửa sổ tin cậy.</li>
      <li><b>26 sự kiện nguy kịch</b> (HR 136–171 bpm khi bất động) và 32 sự kiện nhịp nhanh kéo dài.</li>
      <li><b>3 lần nghi ngã</b>, đáng chú ý lúc <b>21:21</b> độ tin cậy 0,95.</li>
      <li><b>Stress 46,3%</b> số cửa sổ, cao điểm 19h–21h (100%) — nhưng trùng giai đoạn nhịp nhanh nên nhãn này nhiều khả năng phản ánh kích hoạt giao cảm do tim, không phải stress tâm lý thuần túy.</li>
    </ul>
    <p style="margin-top:14px">Bộ dấu hiệu này (nhịp nhanh dai dẳng khi nghỉ + nghi AF + nhiều ngoại tâm thu, xu hướng xấu dần) gợi ý <b>khả năng rối loạn nhịp nhanh</b> (rung nhĩ/cuồng nhĩ đáp ứng thất nhanh, nhịp nhanh trên thất, hoặc nhịp nhanh xoang bệnh lý). <b>Khuyến nghị bác sĩ tim mạch đánh giá sớm</b> bằng ECG 12 chuyển đạo / Holter, đồng thời xác minh sự kiện nghi ngã lúc 21:21.</p>
  </div>

  <div class="disclaimer">
    <b>Lưu ý:</b> Đây là thiết bị <b>sàng lọc</b>, không thay thế chẩn đoán lâm sàng. Các nhãn AF / ngoại tâm thu là <i>nghi ngờ</i> do mô hình AI đưa ra, cần ECG chuẩn xác nhận. Nhịp nhanh có thể do nguyên nhân ngoài tim (sốt, thiếu máu, cường giáp, mất nước, lo âu, thuốc / caffeine) — cần khai thác thêm bệnh sử.
  </div>

  <div class="footer">
    Báo cáo tạo tự động từ dữ liệu cloud · Khoảng theo dõi: 08:00 → 23:59 (giờ VN, +07:00) · 4.448 cửa sổ phân tích (~10s/cửa sổ) · Hệ thống Elderly Care Edge AI.
  </div>
</div>

<script id="DATA" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('DATA').textContent);
const NS='http://www.w3.org/2000/svg';
function el(tag,attrs){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);return e;}
function svg(w,h){const s=el('svg',{viewBox:`0 0 ${w} ${h}`,preserveAspectRatio:'xMidYMid meet'});s.setAttribute('width','100%');return s;}
function txt(x,y,s,attrs={}){const t=el('text',{x,y,fill:'var(--muted)','font-size':12,...attrs});t.textContent=s;return t;}
const C={green:'#3fb950',yellow:'#d29922',orange:'#f0883e',red:'#f85149',accent:'#4aa8ff',purple:'#bc8cff',muted:'#8b98a5',line:'#2a3540'};

// ---------- KPI ----------
(function(){
  const s=D.hr_stats, ev=D.event_types;
  const cards=[
    {lbl:'Nhịp tim TB (ngày)',val:Math.round(s.mean),unit:'bpm',cls:'b-orange',note:'Bình thường 60–100'},
    {lbl:'Nhịp tim cao nhất',val:Math.round(s.max),unit:'bpm',cls:'b-red',note:'Lúc 23h'},
    {lbl:'Nhịp tim nghỉ tối (22-23h)',val:148,unit:'bpm',cls:'b-red',note:'99% đang bất động'},
    {lbl:'% thời gian >120 bpm',val:33,unit:'%',cls:'b-orange',note:'1.414 / 4.227 cửa sổ'},
    {lbl:'Sự kiện nguy kịch',val:D.event_severity.critical,unit:'',cls:'b-red',note:'critical_hr + ngã'},
    {lbl:'Nghi rung nhĩ (AF)',val:ev.af_suspicion,unit:'lần',cls:'b-purple',note:'đỉnh xác suất 0,79'},
    {lbl:'Ngoại tâm thu',val:(D.ectopy.pac+D.ectopy.pvc+D.ectopy.mixed_ectopic),unit:'cửa sổ',cls:'b-yellow',note:'~32% PAC+PVC'},
    {lbl:'Tỷ lệ stress (ngày)',val:Math.round(D.stress_stats.pct_stress),unit:'%',cls:'b-purple',note:'cao điểm 19-21h: 100%'},
    {lbl:'Chất lượng tín hiệu',val:95,unit:'%',cls:'b-green',note:'good + fair'},
  ];
  const wrap=document.getElementById('kpis');
  cards.forEach(c=>{
    const d=document.createElement('div');d.className='kpi';
    d.innerHTML=`<div class="lbl">${c.lbl}</div><div class="val ${c.cls}">${c.val}<span class="unit"> ${c.unit}</span></div><div class="note ${c.cls}">${c.note}</div>`;
    wrap.appendChild(d);
  });
})();

// ---------- HR TIMELINE ----------
(function(){
  const W=1040,H=340,padL=44,padR=14,padT=16,padB=34;
  const x0=8*60, x1=24*60; // minutes of day
  const yMin=60,yMax=190;
  const X=m=>padL+(m-x0)/(x1-x0)*(W-padL-padR);
  const Y=v=>padT+(yMax-v)/(yMax-yMin)*(H-padT-padB);
  const s=svg(W,H);
  // zones
  const zones=[[60,100,C.green],[100,130,C.yellow],[130,190,C.red]];
  zones.forEach(([a,b,col])=>{
    s.appendChild(el('rect',{x:padL,y:Y(b),width:W-padL-padR,height:Y(a)-Y(b),fill:col,opacity:0.07}));
  });
  // gridlines + y labels
  [60,80,100,120,140,160,180].forEach(v=>{
    s.appendChild(el('line',{x1:padL,y1:Y(v),x2:W-padR,y2:Y(v),stroke:C.line,'stroke-width':1}));
    s.appendChild(txt(padL-8,Y(v)+4,v,{ 'text-anchor':'end'}));
  });
  // threshold dashed
  [100,130].forEach((v,i)=>{
    s.appendChild(el('line',{x1:padL,y1:Y(v),x2:W-padR,y2:Y(v),stroke:i?C.red:C.yellow,'stroke-width':1.5,'stroke-dasharray':'5 4',opacity:.8}));
  });
  // x labels (hours)
  for(let h=8;h<=23;h++){
    s.appendChild(txt(X(h*60),H-padB+18,h+'h',{'text-anchor':'middle','font-size':11}));
  }
  // line with gap breaks
  const toMin=t=>{const[a,b]=t.split(':').map(Number);return a*60+b;};
  let dpath='';let prev=null;
  D.series.forEach(p=>{
    const m=toMin(p.t);const X_=X(m).toFixed(1);const Y_=Y(Math.max(yMin,Math.min(yMax,p.hr))).toFixed(1);
    if(prev===null||m-prev>8){dpath+=`M${X_} ${Y_}`;}else{dpath+=`L${X_} ${Y_}`;}
    prev=m;
  });
  s.appendChild(el('path',{d:dpath,fill:'none',stroke:C.accent,'stroke-width':1.8,'stroke-linejoin':'round','stroke-linecap':'round'}));
  // critical event markers (along bottom)
  D.critical_events.forEach(e=>{
    const m=toMin(e.t.slice(0,5));
    s.appendChild(el('line',{x1:X(m),y1:padT,x2:X(m),y2:H-padB,stroke:C.red,'stroke-width':1,opacity:.18}));
    s.appendChild(el('circle',{cx:X(m),cy:H-padB+6,r:3,fill:C.red,opacity:.85}));
  });
  document.getElementById('timeline').appendChild(s);
})();

// ---------- HOURLY RANGE ----------
(function(){
  const hh=D.hourly;const W=520,H=300,padL=40,padR=10,padT=14,padB=30;
  const yMin=60,yMax=190;
  const Y=v=>padT+(yMax-v)/(yMax-yMin)*(H-padT-padB);
  const bw=(W-padL-padR)/hh.length;
  const s=svg(W,H);
  [60,90,120,150,180].forEach(v=>{
    s.appendChild(el('line',{x1:padL,y1:Y(v),x2:W-padR,y2:Y(v),stroke:C.line}));
    s.appendChild(txt(padL-7,Y(v)+4,v,{'text-anchor':'end','font-size':11}));
  });
  s.appendChild(el('line',{x1:padL,y1:Y(100),x2:W-padR,y2:Y(100),stroke:C.yellow,'stroke-dasharray':'4 3',opacity:.7}));
  s.appendChild(el('line',{x1:padL,y1:Y(130),x2:W-padR,y2:Y(130),stroke:C.red,'stroke-dasharray':'4 3',opacity:.7}));
  hh.forEach((d,i)=>{
    const cx=padL+bw*i+bw/2;
    const col=d.mean>=130?C.red:(d.mean>=100?C.yellow:C.green);
    // range line
    s.appendChild(el('line',{x1:cx,y1:Y(d.max),x2:cx,y2:Y(d.min),stroke:col,'stroke-width':2,opacity:.45}));
    // IQR box
    s.appendChild(el('rect',{x:cx-bw*0.28,y:Y(d.p75),width:bw*0.56,height:Math.max(2,Y(d.p25)-Y(d.p75)),fill:col,opacity:.55,rx:2}));
    // mean tick
    s.appendChild(el('line',{x1:cx-bw*0.3,y1:Y(d.mean),x2:cx+bw*0.3,y2:Y(d.mean),stroke:'#fff','stroke-width':2}));
    if(i%2===0)s.appendChild(txt(cx,H-padB+16,d.hour,{'text-anchor':'middle','font-size':10}));
  });
  document.getElementById('hourly').appendChild(s);
})();

// ---------- BANDS ----------
(function(){
  const b=D.hr_bands;const total=Object.values(b).reduce((a,c)=>a+c,0);
  const rows=[['60–99 (bình thường)',b['60-99'],C.green],['100–119 (hơi nhanh)',b['100-119'],C.yellow],
    ['120–149 (nhanh)',b['120-149'],C.orange],['≥150 (rất nhanh)',b['>=150'],C.red]];
  const W=520,H=300,padL=10,padT=10,rowH=58;
  const s=svg(W,H);
  rows.forEach((r,i)=>{
    const y=padT+i*rowH;const pct=r[1]/total*100;
    const barW=(W-padL-60)*(pct/100);
    s.appendChild(txt(padL,y+14,r[0],{fill:'var(--txt)','font-size':13}));
    s.appendChild(el('rect',{x:padL,y:y+20,width:W-padL-60,height:18,fill:C.line,rx:5}));
    s.appendChild(el('rect',{x:padL,y:y+20,width:Math.max(2,barW),height:18,fill:r[2],rx:5}));
    s.appendChild(txt(padL+Math.max(2,barW)+8,y+34,pct.toFixed(1)+'%',{fill:'var(--txt)','font-size':13,'font-weight':600}));
  });
  document.getElementById('bands').appendChild(s);
})();

// ---------- 3-DAY ----------
(function(){
  const days=D.days;const labels={'20260617':'17/06','20260618':'18/06','20260619':'19/06*'};
  const W=1040,H=260,padL=46,padR=16,padT=18,padB=40;
  const yMax=160;
  const Y=v=>padT+(yMax-v)/yMax*(H-padT-padB);
  const bw=(W-padL-padR)/days.length;
  const s=svg(W,H);
  [0,40,80,100,120,160].forEach(v=>{
    s.appendChild(el('line',{x1:padL,y1:Y(v),x2:W-padR,y2:Y(v),stroke:C.line}));
    s.appendChild(txt(padL-8,Y(v)+4,v,{'text-anchor':'end','font-size':11}));
  });
  s.appendChild(el('line',{x1:padL,y1:Y(100),x2:W-padR,y2:Y(100),stroke:C.red,'stroke-dasharray':'5 4',opacity:.7}));
  s.appendChild(txt(W-padR,Y(100)-6,'ngưỡng 100 bpm',{'text-anchor':'end',fill:C.red,'font-size':11}));
  days.forEach((d,i)=>{
    const cx=padL+bw*i+bw/2;const col=d.mean>=130?C.red:(d.mean>=100?C.orange:C.yellow);
    const w=bw*0.42;
    s.appendChild(el('rect',{x:cx-w/2,y:Y(d.mean),width:w,height:Y(0)-Y(d.mean),fill:col,rx:5}));
    s.appendChild(txt(cx,Y(d.mean)-9,Math.round(d.mean)+' bpm',{'text-anchor':'middle',fill:'var(--txt)','font-size':15,'font-weight':700}));
    s.appendChild(txt(cx,H-padB+20,labels[d.day],{'text-anchor':'middle',fill:'var(--txt)','font-size':13}));
    s.appendChild(txt(cx,H-padB+36,d.pct_over100.toFixed(0)+'% >100bpm',{'text-anchor':'middle','font-size':11}));
  });
  document.getElementById('days').appendChild(s);
})();

// ---------- EVENTS ----------
(function(){
  const labelMap={hr_context:'Cảnh báo HR theo ngữ cảnh',stress_suspicion:'Nghi stress',
    ectopy_suspicion:'Nghi ngoại tâm thu',af_suspicion:'Nghi rung nhĩ (AF)',poor_signal:'Tín hiệu kém',
    sustained_tachycardia_immobile:'Nhịp nhanh kéo dài',critical_hr_immobile:'HR nguy kịch',fall_candidate:'Nghi ngã'};
  const colMap={hr_context:C.accent,stress_suspicion:C.purple,ectopy_suspicion:C.yellow,
    af_suspicion:C.orange,poor_signal:C.muted,sustained_tachycardia_immobile:C.orange,
    critical_hr_immobile:C.red,fall_candidate:C.red};
  const ev=Object.entries(D.event_types).sort((a,b)=>b[1]-a[1]);
  const max=ev[0][1];const W=520,padL=10,rowH=34,padT=8;const H=padT+ev.length*rowH+6;
  const s=svg(W,H);
  ev.forEach((e,i)=>{
    const y=padT+i*rowH;const barW=(W-padL-205)*(e[1]/max);
    s.appendChild(txt(padL,y+15,labelMap[e[0]]||e[0],{fill:'var(--txt)','font-size':12.5}));
    s.appendChild(el('rect',{x:200,y:y+4,width:Math.max(2,barW),height:16,fill:colMap[e[0]]||C.accent,rx:4}));
    s.appendChild(txt(200+Math.max(2,barW)+7,y+16,e[1].toLocaleString(),{fill:'var(--txt)','font-size':12.5,'font-weight':600}));
  });
  document.getElementById('events').appendChild(s);
})();

// ---------- RHYTHM + ECTOPY stacked ----------
(function(){
  function stack(id,title,obj,map,colors,y0){
    const total=Object.values(obj).reduce((a,c)=>a+c,0);
    return {title,obj,map,colors,total};
  }
  const rmap={normal:'Bình thường',other_rhythm:'Nhịp khác',noise:'Nhiễu',possible_afib:'Nghi AF'};
  const rcol={normal:C.green,other_rhythm:C.accent,noise:C.muted,possible_afib:C.red};
  const emap={normal:'Bình thường',pac:'PAC (ngoại tâm thu nhĩ)',pvc:'PVC (ngoại tâm thu thất)',mixed_ectopic:'Hỗn hợp',other:'Khác'};
  const ecol={normal:C.green,pac:C.yellow,pvc:C.orange,mixed_ectopic:C.red,other:C.muted};
  const W=520,H=300,padL=10;
  const s=svg(W,H);
  function drawBar(obj,map,col,y,label){
    const total=Object.values(obj).reduce((a,c)=>a+c,0);
    s.appendChild(txt(padL,y-8,label,{fill:'var(--txt)','font-size':13,'font-weight':600}));
    let x=padL;const bw=W-padL-10;
    Object.entries(obj).sort((a,b)=>b[1]-a[1]).forEach(([k,v])=>{
      const w=bw*(v/total);
      s.appendChild(el('rect',{x,y,width:Math.max(0.5,w),height:26,fill:col[k]||C.muted}));
      if(w>42){const t=txt(x+w/2,y+17,(v/total*100).toFixed(0)+'%',{'text-anchor':'middle',fill:'#0b0e12','font-size':11,'font-weight':700});s.appendChild(t);}
      x+=w;
    });
    // legend
    let lx=padL;const ly=y+44;
    Object.entries(obj).sort((a,b)=>b[1]-a[1]).forEach(([k,v])=>{
      s.appendChild(el('rect',{x:lx,y:ly-9,width:10,height:10,fill:col[k]||C.muted,rx:2}));
      const lab=(map[k]||k)+' ('+v+')';
      const t=txt(lx+14,ly,lab,{'font-size':11});s.appendChild(t);
      lx+=14+lab.length*6.0+14;
      if(lx>W-90){lx=padL;y+=0;} // simple wrap guard (kept single line where possible)
    });
  }
  drawBar(D.rhythm,rmap,rcol,40,'Phân loại nhịp (rhythm)');
  drawBar(D.ectopy,emap,ecol,150,'Phân loại ngoại tâm thu (ectopy)');
  document.getElementById('rhythm').appendChild(s);
})();

// ---------- STRESS BAR ----------
(function(){
  const ss=D.stress_stats;const W=520,H=150,padL=10;
  const s=svg(W,H);
  const total=ss.stress+ss.non_stress;
  const segs=[['Stress',ss.stress,C.purple],['Không stress',ss.non_stress,C.green]];
  let x=padL;const bw=W-padL-10,y=24;
  segs.forEach(([lab,v,col])=>{
    const w=bw*(v/total);
    s.appendChild(el('rect',{x,y,width:Math.max(1,w),height:34,fill:col,rx:3}));
    if(w>50)s.appendChild(txt(x+w/2,y+22,(v/total*100).toFixed(1)+'%',{'text-anchor':'middle',fill:'#0b0e12','font-size':14,'font-weight':700}));
    x+=w;
  });
  let lx=padL;const ly=84;
  segs.forEach(([lab,v,col])=>{
    s.appendChild(el('rect',{x:lx,y:ly-10,width:12,height:12,fill:col,rx:2}));
    const t=txt(lx+17,ly,lab+' ('+v.toLocaleString()+' cửa sổ)',{'font-size':12.5});s.appendChild(t);
    lx+=17+(lab.length+18)*6.6;
  });
  s.appendChild(txt(padL,118,'Xác suất stress trung bình: '+(ss.mean_prob).toFixed(2)+' · cao nhất: '+(ss.max_prob).toFixed(2),{'font-size':12}));
  document.getElementById('stressbar').appendChild(s);
})();

// ---------- STRESS BY HOUR ----------
(function(){
  const hh=D.stress_stats.hourly;const W=520,H=260,padL=36,padR=10,padT=14,padB=28;
  const Y=v=>padT+(100-v)/100*(H-padT-padB);
  const bw=(W-padL-padR)/hh.length;
  const s=svg(W,H);
  [0,25,50,75,100].forEach(v=>{
    s.appendChild(el('line',{x1:padL,y1:Y(v),x2:W-padR,y2:Y(v),stroke:C.line}));
    s.appendChild(txt(padL-7,Y(v)+4,v+'%',{'text-anchor':'end','font-size':10}));
  });
  hh.forEach((d,i)=>{
    const cx=padL+bw*i+bw/2;const col=d.pct>=80?C.red:(d.pct>=40?C.orange:C.purple);
    const w=bw*0.6;
    s.appendChild(el('rect',{x:cx-w/2,y:Y(d.pct),width:w,height:Y(0)-Y(d.pct),fill:col,opacity:.85,rx:2}));
    if(i%2===0)s.appendChild(txt(cx,H-padB+15,d.hour,{'text-anchor':'middle','font-size':10}));
  });
  document.getElementById('stresshour').appendChild(s);
})();

// ---------- CRITICAL TABLE ----------
(function(){
  const t=document.getElementById('crit');
  t.innerHTML='<thead><tr><th>Thời gian</th><th>Loại</th><th>Nhịp tim</th><th>Mức</th></tr></thead>';
  const tb=document.createElement('tbody');
  const typeLabel={critical_hr_immobile:'HR nguy kịch khi bất động',fall_candidate:'Nghi ngã'};
  D.critical_events.forEach(e=>{
    const tr=document.createElement('tr');
    const hr=e.hr!=null?Math.round(e.hr)+' bpm':'—';
    tr.innerHTML=`<td>${e.t}</td><td>${typeLabel[e.type]||e.type}</td><td class="hr" style="color:${e.hr>=150?'#f85149':'#f0883e'}">${hr}</td><td><span class="tag crit">critical</span></td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
})();
</script>
</body>
</html>
"""

html = HTML.replace("__DATA__", json.dumps(DATA, ensure_ascii=False, separators=(",", ":")))
OUT.write_text(html, encoding="utf-8")
print("Wrote", OUT, "(", len(html), "bytes )")
