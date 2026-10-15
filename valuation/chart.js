// -- 내재가치 평가: 월간 주가 선 그래프 위에 분기별 내재가치 하단~상단 밴드(분기별 색) 표시, 기간 선택 (valuation/chart.js에서 생성) --
(function () {
  const box = document.getElementById('dpBuffettBox');
  const pEl = document.querySelector(box ? (box.dataset.priceSel || '.dp-price') : '.dp-price');
  if (!box || !pEl) return;
  const price = box.dataset.price ? +box.dataset.price : parseFloat(pEl.textContent.replace(/[^0-9.]/g, ''));
  const low = +box.dataset.ivLow, high = +box.dataset.ivHigh;
  document.getElementById('dpbPrice').textContent = price.toLocaleString() + '원';
  let verdict, color;
  if (price < low) { verdict = '내재가치 하단 아래 — 저평가'; color = 'var(--dp-up)'; }
  else if (price <= high) { verdict = '내재가치 범위 안 — 적정 가치 수준'; color = 'var(--dp-text2)'; }
  else { verdict = '내재가치 상단 초과 — 고평가'; color = 'var(--dp-down)'; }
  if (box.dataset.hold) { verdict = '평가 보류 — 적자·고성장 단계라 장부가치 기준 참고값만 제시'; color = 'var(--dp-text3)'; }
  const vEl = document.getElementById('dpbVerdict');
  vEl.textContent = verdict; vEl.style.color = color;
  const svg = document.getElementById('dpbChart');
  const readout = document.getElementById('dpbReadout');
  const all = JSON.parse(box.dataset.hist).map(h => ({ d: h[0], c: h[1] }));
  const bands = JSON.parse(box.dataset.bands); // [quarter-end 'YYYY-MM', low, high]
  const today = new Date().toISOString().slice(0, 7);
  if (today > all[all.length - 1].d) all.push({ d: today, c: price }); else all[all.length - 1].c = price;
  // 분기별 색: 1Q 초록 · 2Q 청록 · 3Q 보라 · 4Q(사업보고서) 주황
  const QHUE = { '03': 150, '06': 195, '09': 300, '12': 60 };
  const QNAME = { '03': '1분기', '06': '반기', '09': '3분기', '12': '사업보고서' };
  const mNum = d => (+d.slice(0, 4)) * 12 + (+d.slice(5, 7)) - 1;
  const NS = 'http://www.w3.org/2000/svg';
  const fmtK = v => v >= 10000 ? (+(v / 10000).toFixed(1)).toLocaleString() + '만' : Math.round(v).toLocaleString();
  const won = v => Math.round(v).toLocaleString() + '원';
  const bandAt = d => { let b = null; bands.forEach(x => { if (x[0] <= d) b = x; }); return b; };
  let state = null;

  function draw(months) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const pts = months ? all.slice(Math.max(0, all.length - months - 1)) : all;
    const n = pts.length, m0 = mNum(pts[0].d), m1 = mNum(pts[n - 1].d);
    const segs = [];
    bands.forEach((b, i) => {
      const s = Math.max(mNum(b[0]), m0), e = Math.min(i + 1 < bands.length ? mNum(bands[i + 1][0]) : m1, m1);
      if (e > s || (i === bands.length - 1 && e >= s)) segs.push({ s: s - m0, e: Math.max(e, s) - m0, lo: b[1], hi: b[2], q: b[0] });
    });
    const W = Math.max(300, Math.min(760, Math.round(svg.getBoundingClientRect().width) || 600));
    const H = W < 480 ? 230 : 250, pL = 40, pR = 92, pT = 34, pB = 24, cW = W - pL - pR, cH = H - pT - pB;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    const vals = pts.map(p => p.c).concat(segs.map(s => s.lo), segs.map(s => s.hi));
    const vMin = Math.min(...vals) * 0.92, vMax = Math.max(...vals) * 1.06;
    const x = i => pL + cW * i / (n - 1);
    const y = v => pT + cH * (1 - (v - vMin) / (vMax - vMin));
    function el(tag, attrs, text) {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      if (text != null) e.textContent = text;
      svg.appendChild(e); return e;
    }
    const step = Math.pow(10, Math.floor(Math.log10((vMax - vMin) / 4)));
    const tick = [1, 2, 2.5, 5, 10].map(m => m * step).find(s => (vMax - vMin) / s <= 5);
    for (let v = Math.ceil(vMin / tick) * tick; v <= vMax; v += tick) {
      el('line', { x1: pL, x2: W - pR, y1: y(v), y2: y(v), style: 'stroke:var(--dp-border)', 'stroke-width': 1 });
      el('text', { x: pL - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, style: 'fill:var(--dp-text4)' }, fmtK(v));
    }
    segs.forEach(s => {
      const h = QHUE[s.q.slice(5, 7)], x0 = x(s.s), x1 = Math.max(x(s.e), x0 + 3);
      el('rect', { x: x0, y: y(s.hi), width: x1 - x0, height: Math.max(1, y(s.lo) - y(s.hi)), style: `fill:oklch(0.68 0.13 ${h} / 0.28)` });
      [s.hi, s.lo].forEach(v => el('line', { x1: x0, x2: x1, y1: y(v), y2: y(v), style: `stroke:oklch(0.55 0.14 ${h})`, 'stroke-width': 1.5 }));
    });
    const last = segs[segs.length - 1];
    [[last.hi, '상단', -2], [last.lo, '하단', 11]].forEach(([v, lab, dy]) =>
      el('text', { x: W - pR + 6, y: y(v) + dy, 'font-size': 11, 'font-weight': 700, style: 'fill:oklch(0.5 0.13 150)' }, lab + ' ' + Math.round(v).toLocaleString()));
    const short = n <= 14;
    pts.forEach((p, i) => {
      const mm = p.d.slice(5, 7);
      const yearMark = mm === '01';
      if (short ? ['01', '04', '07', '10'].includes(mm) : yearMark) {
        el('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, style: 'fill:var(--dp-text4)' }, short ? p.d.slice(2, 4) + '.' + mm : p.d.slice(0, 4));
        el('line', { x1: x(i), x2: x(i), y1: pT, y2: pT + cH, style: 'stroke:var(--dp-border)', 'stroke-width': 1, 'stroke-dasharray': '2 3' });
      }
    });
    el('polyline', { points: pts.map((p, i) => x(i) + ',' + y(p.c)).join(' '), fill: 'none', style: 'stroke:var(--dp-accent)', 'stroke-width': 2, 'stroke-linejoin': 'round' });
    const lx = x(n - 1), ly = y(price);
    el('circle', { cx: lx, cy: ly, r: 4, style: 'fill:var(--dp-accent)' });
    const near = Math.abs(ly - y(last.hi)) < 14 || Math.abs(ly - y(last.lo)) < 14;
    el('text', { x: lx + 6, y: near ? ly + (ly < y(last.hi) ? -10 : 18) : ly + 4, 'font-size': 11, 'font-weight': 800, style: 'fill:var(--dp-accent)' }, '현재 ' + Math.round(price).toLocaleString());
    const cross = el('line', { x1: 0, x2: 0, y1: pT, y2: pT + cH, style: 'stroke:var(--dp-text4);visibility:hidden', 'stroke-width': 1 });
    const dot = el('circle', { r: 3.5, style: 'fill:var(--dp-accent);visibility:hidden' });
    state = { pts, n, x, y, cW, pL, W, cross, dot };
  }

  function show(i) {
    const s = state, p = s.pts[i], b = bandAt(p.d);
    s.cross.setAttribute('x1', s.x(i)); s.cross.setAttribute('x2', s.x(i)); s.cross.style.visibility = 'visible';
    s.dot.setAttribute('cx', s.x(i)); s.dot.setAttribute('cy', s.y(p.c)); s.dot.style.visibility = 'visible';
    let txt = `<b>${p.d.replace('-', '.')}</b> 주가 ${won(p.c)}`;
    if (b) {
      const h = QHUE[b[0].slice(5, 7)];
      txt += ` · <span style="color:oklch(0.5 0.14 ${h});font-weight:700">${b[0].slice(0, 4)}년 ${QNAME[b[0].slice(5, 7)]} 기준</span> 내재가치 ${won(b[1])} ~ ${won(b[2])}`;
    }
    readout.innerHTML = txt;
  }
  function onMove(ev) {
    const r = svg.getBoundingClientRect(), s = state;
    const vx = (ev.clientX - r.left) * (s.W / r.width);
    const i = Math.max(0, Math.min(s.n - 1, Math.round((vx - s.pL) / s.cW * (s.n - 1))));
    show(i);
  }
  svg.addEventListener('pointermove', onMove);
  svg.addEventListener('pointerdown', onMove);
  svg.addEventListener('pointerleave', () => { state.cross.style.visibility = 'hidden'; state.dot.style.visibility = 'hidden'; show(state.n - 1); state.cross.style.visibility = 'hidden'; state.dot.style.visibility = 'hidden'; });

  const btns = box.querySelectorAll('.dpb-rng button');
  btns.forEach(btn => btn.addEventListener('click', () => {
    btns.forEach(b => b.classList.toggle('on', b === btn));
    draw(+btn.dataset.m || 0);
    show(state.n - 1); state.cross.style.visibility = 'hidden'; state.dot.style.visibility = 'hidden';
  }));
  draw(0);
  show(state.n - 1); state.cross.style.visibility = 'hidden'; state.dot.style.visibility = 'hidden';
  if (typeof addChartExpandButton === 'function') addChartExpandButton(svg);
})();
