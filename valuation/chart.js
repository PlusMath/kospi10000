// -- 내재가치 평가: 월간 주가 선 그래프 위에 분기별 내재가치 하단~상단 밴드(분기별 색) 표시, 기간 선택 (valuation/chart.js에서 생성) --
(function () {
  const box = document.getElementById('dpBuffettBox');
  const pEl = document.querySelector(box ? (box.dataset.priceSel || '.dp-price') : '.dp-price');
  if (!box || !pEl) return;
  const price = box.dataset.price ? +box.dataset.price : parseFloat(pEl.textContent.replace(/[^0-9.]/g, ''));
  const low = +box.dataset.ivLow, high = +box.dataset.ivHigh;
  const won = (v) => Math.round(v).toLocaleString() + '원';
  // 한 줄 판단 + 배지(리포트형). 구형 박스(dpbPrice 숫자 칸)도 계속 채움
  let verdict, badge, cls;
  if (box.dataset.hold) { badge = '평가 보류'; cls = 'hold'; verdict = '적자·고성장 단계라 장부가치 기준 참고값만 제시합니다.'; }
  else if (price < low) { badge = '저평가'; cls = 'under'; verdict = `현재가 ${won(price)}은 내재가치 하단 ${won(low)}보다 ${Math.round((1 - price / low) * 100)}% 낮습니다. 보수적으로 잡은 가치보다도 싼 구간입니다.`; }
  else if (price <= high) { badge = '범위 안'; cls = 'fair'; verdict = `현재가 ${won(price)}은 내재가치 범위 ${won(low)}~${won(high)} 안, 하단에서 ${Math.round((price - low) / (high - low) * 100)}% 지점에 있습니다.`; }
  else { badge = '고평가'; cls = 'over'; verdict = `현재가 ${won(price)}은 내재가치 상단 ${won(high)}보다 ${Math.round((price / high - 1) * 100)}% 높습니다. 지금의 이익 수준이 오래 이어진다는 기대가 주가에 들어 있다는 뜻입니다.`; }
  const bEl = document.getElementById('dpbBadge');
  if (bEl) { bEl.textContent = badge; bEl.className = 'dpb-badge ' + cls; }
  document.getElementById('dpbVerdict').textContent = bEl ? verdict : badge + ' — ' + verdict;
  const pOld = document.getElementById('dpbPrice');
  if (pOld) pOld.textContent = won(price);
  // 범위 막대: 초록 = 가중 내재가치 하단~상단, 빨간 선 = 현재가
  const bar = document.getElementById('dpbBar');
  if (bar && low >= 0 && high > 0) {
    const a = Math.min(low, price) * 0.85, b = Math.max(high, price) * 1.08, x = (v) => (v - a) / (b - a) * 100;
    bar.innerHTML = `<div class="ax"></div><div class="band" style="left:${x(low)}%;width:${x(high) - x(low)}%"></div><div class="now" style="left:${x(price)}%"></div>`
      + `<label class="lo"><small>하단</small>${Math.round(low).toLocaleString()}</label>`
      + `<label class="hi"><small>상단</small>${Math.round(high).toLocaleString()}</label>`
      + `<label class="cur"><small>현재가</small>${Math.round(price).toLocaleString()}</label>`;
    // 라벨 배치(px): 각자 기준점 가운데 → 하단·상단이 겹치면 둘 사이 가운데를 기준으로 좌우로 벌림 → 막대 안으로 밀어 넣음
    const place = () => {
      const W = bar.clientWidth;
      if (!W) return;
      const [lo, hi, cur] = ['lo', 'hi', 'cur'].map((c) => bar.querySelector('label.' + c));
      const fit = (l, w) => Math.min(Math.max(l, 0), W - w);
      const wl = lo.offsetWidth, wh = hi.offsetWidth, wc = cur.offsetWidth;
      const pl = x(low) / 100 * W, ph = x(high) / 100 * W;
      let ll = pl - wl / 2, lh = ph - wh / 2;
      if (ll + wl + 8 > lh) { const mid = (pl + ph) / 2; ll = mid - 4 - wl; lh = mid + 4; }
      ll = fit(ll, wl); lh = fit(lh, wh);
      if (ll + wl + 8 > lh) { if (lh + wh >= W) ll = lh - 8 - wl; else lh = ll + wl + 8; }
      lo.style.left = ll + 'px'; hi.style.left = lh + 'px';
      cur.style.left = fit(x(price) / 100 * W - wc / 2, wc) + 'px';
      [lo, hi, cur].forEach((e) => { e.style.transform = 'none'; });
    };
    place();
    window.addEventListener('resize', place);
  } else if (bar) bar.hidden = true;
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
  const bandAt = d => { let b = null; bands.forEach(x => { if (x[0] <= d) b = x; }); return b; };  // 값이 null이면 그 분기는 평가 공백(최근 4분기 적자)
  let state = null;

  function draw(months) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const pts = months ? all.slice(Math.max(0, all.length - months - 1)) : all;
    const n = pts.length, m0 = mNum(pts[0].d), m1 = mNum(pts[n - 1].d);
    const segs = [];
    bands.forEach((b, i) => {
      const s = Math.max(mNum(b[0]), m0), e = Math.min(i + 1 < bands.length ? mNum(bands[i + 1][0]) : m1, m1);
      if (b[1] != null && (e > s || (i === bands.length - 1 && e >= s))) segs.push({ s: s - m0, e: Math.max(e, s) - m0, lo: b[1], hi: b[2], q: b[0] });
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
      txt += ` · <span style="color:oklch(0.5 0.14 ${h});font-weight:700">${b[0].slice(0, 4)}년 ${QNAME[b[0].slice(5, 7)]} 기준</span> ` +
        (b[1] == null ? '최근 4분기 적자로 이익 기반 내재가치 없음' : `내재가치 ${won(b[1])} ~ ${won(b[2])}`);
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
