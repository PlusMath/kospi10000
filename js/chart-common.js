// 임의의 SVG(연간/분기 막대그래프 등, 캔들차트 전용 로직이 필요 없는 단순 차트)에
// "크게 보기" 버튼을 붙여주는 범용 헬퍼. 각 종목 파일의 drawAnnualChart()/drawQtrChart()
// 끝에서 자기 자신의 svg 변수를 넘겨 호출한다. 캔들차트(renderCandleChart)는 자체적으로
// 이 로직을 내장하고 있어 별도 호출이 필요 없음.
function addChartExpandButton(svg) {
  if (!svg) return;
  let wrap = svg.closest('.kc-chart-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.className = 'kc-chart-wrap';
    svg.parentNode.insertBefore(wrap, svg);
    wrap.appendChild(svg);
  }
  if (wrap.querySelector('.kc-expand-btn')) return;
  const expandBtn = document.createElement('button');
  expandBtn.type = 'button';
  expandBtn.className = 'kc-expand-btn';
  expandBtn.setAttribute('aria-label', '차트 크게 보기');
  expandBtn.textContent = '⤢ 크게 보기';
  expandBtn.addEventListener('click', function () { openChartFullscreen(wrap, null); });
  wrap.appendChild(expandBtn);
}

// 차트를 화면 전체 너비로 크게 보여주는 오버레이 — 모바일에서 좁은 폭에 눌린 캔들/글씨를
// 뷰포트 전체 폭으로 확대해서 보기 위함. wrap(.kc-chart-wrap)과 controls(.kc-controls)를
// 그대로 옮겨서(재렌더링 없이) 보여주고, 닫으면 원래 위치로 복원.
// 지원되는 브라우저(주로 안드로이드 크롬 계열)에서는 전체화면 + 가로모드 강제 전환도 시도.
// iOS Safari는 정책상 자동 가로 회전을 지원하지 않아 실패해도 조용히 무시하고 세로로 그대로 표시.
function openChartFullscreen(wrap, controls) {
  if (document.querySelector('.kc-fullscreen-overlay')) return;
  const parent = wrap.parentNode;
  const beforeNode = wrap.nextSibling;
  const expandBtn = wrap.querySelector('.kc-expand-btn');

  const overlay = document.createElement('div');
  overlay.className = 'kc-fullscreen-overlay';
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'kc-fullscreen-close';
  closeBtn.setAttribute('aria-label', '닫기');
  closeBtn.textContent = '✕';
  overlay.appendChild(closeBtn);

  if (expandBtn) expandBtn.style.display = 'none';
  if (controls) overlay.appendChild(controls);
  overlay.appendChild(wrap);
  document.body.appendChild(overlay);
  document.body.classList.add('kc-fullscreen-open');

  const reqFullscreen = overlay.requestFullscreen || overlay.webkitRequestFullscreen;
  if (reqFullscreen) {
    Promise.resolve(reqFullscreen.call(overlay)).then(function () {
      if (screen.orientation && screen.orientation.lock) {
        screen.orientation.lock('landscape').catch(function () {});
      }
    }).catch(function () {});
  }

  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    if (screen.orientation && screen.orientation.unlock) {
      try { screen.orientation.unlock(); } catch (e) {}
    }
    const exitFullscreen = document.exitFullscreen || document.webkitExitFullscreen;
    if (exitFullscreen && (document.fullscreenElement || document.webkitFullscreenElement)) {
      Promise.resolve(exitFullscreen.call(document)).catch(function () {});
    }
    if (controls) parent.insertBefore(controls, beforeNode);
    parent.insertBefore(wrap, beforeNode);
    if (expandBtn) expandBtn.style.display = '';
    overlay.remove();
    document.body.classList.remove('kc-fullscreen-open');
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('fullscreenchange', onFsChange);
  }
  function onKey(e) { if (e.key === 'Escape') close(); }
  function onFsChange() { if (!document.fullscreenElement) close(); }
  document.addEventListener('keydown', onKey);
  document.addEventListener('fullscreenchange', onFsChange);
  closeBtn.addEventListener('click', close);
  overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
}

// "7. Daily 주요 뉴스" 날짜별 아카이브 뷰어 — PlusMath/finnews의 날짜 선택 UI를 종목
// 페이지에 맞게 이식. data/news/{code}.json을 fetch로 한 번만 읽어 캐시해두고,
// <select> 날짜 변경 시 재요청 없이 즉시 다시 그린다. 종목 파일 자체는 정적이라
// 매일 갱신되는 아카이브 JSON만 새로 받아오면 페이지 코드 수정 없이 최신 상태 반영.
function initDpNews(code) {
  const holder = document.getElementById('dpNewsBody');
  const toolbar = document.getElementById('dpNewsToolbar');
  if (!holder) return;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const PAGE_SIZE = 5;
  let page = 1;
  let query = '';
  let allItems = [];

  function filteredItems() {
    if (!query) return allItems;
    const q = query.toLowerCase();
    return allItems.filter(n =>
      n.title.toLowerCase().includes(q) || (n.source && n.source.toLowerCase().includes(q))
    );
  }

  function updateCount() {
    const label = document.getElementById('dpNewsCountLabel');
    if (label) label.textContent = `총 ${filteredItems().length}건`;
  }

  function renderList() {
    const items = filteredItems();
    if (items.length === 0) {
      holder.innerHTML = `<p class="dp-news-empty">${query ? '검색 결과가 없습니다.' : '최근 뉴스 데이터가 없습니다.'}</p>`;
      return;
    }
    const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    if (page > totalPages) page = totalPages;
    const start = (page - 1) * PAGE_SIZE;
    const pageItems = items.slice(start, start + PAGE_SIZE);

    const listHtml = '<div class="dp-news-list">' + pageItems.map(n => `
      <a class="dp-news-item" href="${esc(n.link)}" target="_blank" rel="noopener">
        <div class="dp-news-title">${esc(n.title)}</div>
        <div class="dp-news-meta"><span class="dp-news-source">${esc(n.source)}</span><span class="dp-news-time">${esc(n.time)}</span></div>
      </a>
    `).join('') + '</div>';

    let pagerHtml = '';
    if (totalPages > 1) {
      const btnStyle = 'border:1px solid var(--dp-border2);background:var(--dp-card);border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer;color:var(--dp-text2);font-family:inherit;';
      const disabledStyle = 'opacity:.4;cursor:default;';
      pagerHtml = `
        <div style="display:flex;align-items:center;justify-content:center;gap:10px;margin-top:14px;">
          <button type="button" data-act="prev" ${page <= 1 ? 'disabled' : ''} style="${btnStyle}${page <= 1 ? disabledStyle : ''}">이전</button>
          <span style="font-size:12px;color:var(--dp-text3);">${page} / ${totalPages}</span>
          <button type="button" data-act="next" ${page >= totalPages ? 'disabled' : ''} style="${btnStyle}${page >= totalPages ? disabledStyle : ''}">다음</button>
        </div>`;
    }

    holder.innerHTML = listHtml + pagerHtml;

    const prevBtn = holder.querySelector('[data-act="prev"]');
    const nextBtn = holder.querySelector('[data-act="next"]');
    if (prevBtn) prevBtn.addEventListener('click', () => {
      if (page > 1) { page--; renderList(); holder.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
    });
    if (nextBtn) nextBtn.addEventListener('click', () => {
      if (page < totalPages) { page++; renderList(); holder.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
    });
  }

  if (toolbar) {
    toolbar.innerHTML = `
      <input type="search" id="dpNewsSearchInput" placeholder="뉴스 제목·언론사 검색" style="flex:1;min-width:0;font-size:12.5px;padding:6px 10px;border:1px solid var(--dp-border2);border-radius:6px;background:var(--dp-card);color:inherit;font-family:inherit;">
      <span id="dpNewsCountLabel" style="font-size:11px;color:var(--dp-text4);white-space:nowrap;"></span>
    `;
    const input = document.getElementById('dpNewsSearchInput');
    input.addEventListener('input', () => {
      query = input.value.trim();
      page = 1;
      updateCount();
      renderList();
    });
  }

  fetch(`../data/news/${code}.json?v=${Date.now()}`, { cache: 'no-store' })
    .then(res => { if (!res.ok) throw new Error('no data'); return res.json(); })
    .then(archive => {
      allItems = [];
      Object.keys(archive).forEach(dateKey => {
        (archive[dateKey] || []).forEach(n => allItems.push(n));
      });
      // n.time은 "MM-dd HH:mm" 형식이라 문자열 내림차순 정렬만으로도 최신순이 됨(연도 경계 근처 예외는 무시).
      allItems.sort((a, b) => (a.time < b.time ? 1 : (a.time > b.time ? -1 : 0)));

      if (allItems.length === 0) {
        holder.innerHTML = '<p class="dp-news-empty">최근 뉴스 데이터가 없습니다.</p>';
        if (toolbar) toolbar.style.display = 'none';
        return;
      }
      updateCount();
      renderList();
    })
    .catch(() => {
      holder.innerHTML = '<p class="dp-news-empty">뉴스 데이터를 불러오지 못했습니다.</p>';
      if (toolbar) toolbar.style.display = 'none';
    });
}

// "1. 기술적 분석" 상단 — 눌림목매매 기준 기술적 매력도 점수 카드(2026-09-07 개편,
// 이전 Minervini SEPA/Trend Template 기반에서 교체).
// data/technical_score.json(전 종목 통합, PowerShell과 무관한 별도 Python 배치가 매일
// 갱신)을 fetch해서 렌더링. 100점 본점수와 별도 트랙인 돌파신호(10점)·수급점수(10점)도
// 함께 표시.
function initTechnicalScore(code) {
  const holder = document.getElementById('dpTscoreBody');
  if (!holder) return;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  fetch(`../data/technical_score.json?v=${Date.now()}`, { cache: 'no-store' })
    .then(res => { if (!res.ok) throw new Error('no data'); return res.json(); })
    .then(all => {
      const r = all[code];
      if (!r || r.data_status !== 'ok' || r.technical_score === null || r.technical_score === undefined) {
        const reason = (r && r.error_message) || '기술적 매력도 데이터가 없습니다.';
        holder.innerHTML = `<p class="dp-tscore-empty">${esc(reason)}</p>`;
        return;
      }

      const score = r.technical_score;
      const items = [];
      if (r.setup_score) items.push(['눌림목 셋업 적격성 (40점)', r.setup_score.score]);
      if (r.entry_score) items.push(['진입 타이밍 매력도 (60점)', r.entry_score.score]);
      if (r.risk_penalty) items.push(['위험 감점', r.risk_penalty.score]);
      if (r.breakout_signal) items.push(['돌파 신호 (별도10점)', r.breakout_signal.score]);
      if (r.supply_demand_score && r.supply_demand_score.computable) items.push(['수급 점수 (별도10점)', r.supply_demand_score.score]);

      const itemsHtml = items.map(([label, val]) => {
        const style = val < 0 ? ' style="color:var(--dp-down);"' : '';
        const sign = val > 0 && label.indexOf('위험') >= 0 ? '+' : '';
        return `<div class="dp-tscore-item"><span class="l">${esc(label)}</span><span class="v"${style}>${sign}${val.toFixed(1)}</span></div>`;
      }).join('');

      const warning = r.setup_score && r.setup_score.warning;
      const warningHtml = warning ? ` · <span style="color:var(--dp-down);font-weight:700;">${esc(warning)}</span>` : '';
      const summaryHtml = (r.summary || []).map(s => `<li>${esc(s)}</li>`).join('');

      holder.innerHTML = `
        <div class="dp-tscore">
          <div class="dp-tscore-top">
            <div class="dp-tscore-num">${Math.round(score)}<span>/100</span></div>
            <div class="dp-tscore-grade">${esc(r.grade)}</div>
          </div>
          <div class="dp-tscore-track"><div class="dp-tscore-fill" style="width:${Math.max(0, Math.min(100, score))}%;"></div></div>
          <div class="dp-tscore-sub">기술적 매력도(눌림목매매 기준)${warningHtml} · 투자 권고 아님</div>
          <div class="dp-tscore-grid">${itemsHtml}</div>
          ${summaryHtml ? `<ul class="dp-tscore-summary">${summaryHtml}</ul>` : ''}
        </div>
      `;
    })
    .catch(() => {
      holder.innerHTML = '<p class="dp-tscore-empty">기술적 매력도 데이터를 불러오지 못했습니다.</p>';
    });
}

// 공통 캔들차트 렌더러 — 기간 전환(1개월/3개월/6개월/1년) + 마우스 호버 툴팁
// data: [{d:'YYYY-MM-DD', o,h,l,c}, ...] (오름차순, 만원 단위), 외부 CDN 없이 순수 SVG로 렌더링
function renderCandleChart(cfg) {
  const svg = document.getElementById(cfg.svgId);
  if (!svg) return;
  const data = cfg.data;
  const controls = cfg.controlsId ? document.getElementById(cfg.controlsId) : null;
  const W = 720, H = 240, pL = 64, pR = 12, pT = 14, pB = 24;
  const cW = W - pL - pR, cH = H - pT - pB;

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function svgEl(tag, attrs) {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function calcMA(arr, n) {
    return arr.map((_, i) => i < n - 1 ? null : arr.slice(i - n + 1, i + 1).reduce((s, x) => s + x.c, 0) / n);
  }
  function fmtMD(dateStr) { const p = dateStr.split('-'); return p[1] + '/' + p[2]; }
  function won(v) { return Math.round(v * 10000).toLocaleString(); }
  // cfg.fmtValue/cfg.unit: 지수·환율 페이지처럼 만원 단위 변환(*10000)이 맞지 않는 값을
  // 그리는 경우를 위한 오버라이드(2026-09-07). 둘 다 생략하면 기존 종목 차트와 완전히 동일.
  const fmtValue = cfg.fmtValue || won;
  const unit = cfg.unit !== undefined ? cfg.unit : '원';

  const ma5Full = calcMA(data, 5), ma20Full = calcMA(data, 20), ma60Full = calcMA(data, 60), ma120Full = calcMA(data, 120);

  // 차트를 감싸는 wrap(툴팁 절대위치 기준) 준비
  let wrap = svg.closest('.kc-chart-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.className = 'kc-chart-wrap';
    svg.parentNode.insertBefore(wrap, svg);
    wrap.appendChild(svg);
  }
  let tip = wrap.querySelector('.kc-tooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'kc-tooltip';
    wrap.appendChild(tip);
  }
  let expandBtn = wrap.querySelector('.kc-expand-btn');
  if (!expandBtn) {
    expandBtn = document.createElement('button');
    expandBtn.type = 'button';
    expandBtn.className = 'kc-expand-btn';
    expandBtn.setAttribute('aria-label', '차트 크게 보기');
    expandBtn.textContent = '⤢ 크게 보기';
    expandBtn.addEventListener('click', function () { openChartFullscreen(wrap, controls); });
    wrap.appendChild(expandBtn);
  }

  function render(periodDays) {
    const n = data.length;
    const startIdx = periodDays >= n ? 0 : n - periodDays;
    const slice = data.slice(startIdx);
    const ma5 = ma5Full.slice(startIdx), ma20 = ma20Full.slice(startIdx), ma60 = ma60Full.slice(startIdx), ma120 = ma120Full.slice(startIdx);

    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const prices = slice.flatMap(d => [d.h, d.l]);
    const maxP = Math.max(...prices) * 1.02, minP = Math.min(...prices) * 0.98;
    const rng = (maxP - minP) || 1;
    function py(v) { return pT + cH * (1 - (v - minP) / rng); }
    const colW = cW / slice.length, cw = Math.max(colW * 0.62, 1.2);
    const gridCol = cssVar('--color-text-tertiary');

    for (let i = 0; i <= 4; i++) {
      const v = minP + rng * i / 4;
      const y = py(v);
      svg.appendChild(svgEl('line', { x1: pL, x2: pL + cW, y1: y, y2: y, stroke: gridCol, opacity: 0.15, 'stroke-width': 1 }));
      const t = svgEl('text', { x: pL - 4, y: y + 3, 'text-anchor': 'end', 'font-size': 9, fill: gridCol, opacity: 0.85 });
      t.textContent = fmtValue(v);
      svg.appendChild(t);
    }

    function drawLine(arr, col, w) {
      let pts = [];
      arr.forEach((v, i) => { if (v === null) return; pts.push(`${pL + (i + 0.5) * colW},${py(v)}`); });
      if (pts.length < 2) return;
      svg.appendChild(svgEl('polyline', { points: pts.join(' '), fill: 'none', stroke: col, 'stroke-width': w || 1.3 }));
    }

    slice.forEach((d, i) => {
      const cx = pL + (i + 0.5) * colW, isUp = d.c >= d.o, col = isUp ? '#D85A30' : '#185FA5';
      svg.appendChild(svgEl('line', { x1: cx, x2: cx, y1: py(d.h), y2: py(d.l), stroke: col, 'stroke-width': 1 }));
      const bT = py(Math.max(d.o, d.c)), bB = py(Math.min(d.o, d.c));
      svg.appendChild(svgEl('rect', { x: cx - cw / 2, y: bT, width: cw, height: Math.max(bB - bT, 1), fill: col, rx: 0.6 }));
    });

    drawLine(ma5, '#FF69B4', 1.3);
    drawLine(ma20, '#9370DB', 1.3);
    drawLine(ma60, '#DAA520', 1.6);
    drawLine(ma120, '#2E8B57', 1.6);

    let hiIdx = 0, loIdx = 0;
    slice.forEach((d, i) => { if (d.h > slice[hiIdx].h) hiIdx = i; if (d.l < slice[loIdx].l) loIdx = i; });
    const hi = slice[hiIdx], lo = slice[loIdx];
    const mkLabel = (idx, val, dateStr, isLow, col) => {
      const cx = pL + (idx + 0.5) * colW, cy = isLow ? py(val) + 12 : py(val) - 8;
      const t = svgEl('text', { x: cx, y: cy, 'text-anchor': 'middle', 'font-size': 9, fill: col, 'font-weight': 600 });
      t.textContent = (isLow ? '저 ' : '고 ') + fmtValue(val) + ' (' + fmtMD(dateStr) + ')';
      svg.appendChild(t);
    };
    mkLabel(hiIdx, hi.h, hi.d, false, '#B02E3C');
    mkLabel(loIdx, lo.l, lo.d, true, '#185FA5');

    const lastIdx = slice.length - 1, last = slice[lastIdx];
    const curCx = pL + (lastIdx + 0.5) * colW, curCy = py(last.h) - 8;
    const curT = svgEl('text', { x: curCx - 4, y: curCy, 'text-anchor': 'end', 'font-size': 9, fill: cssVar('--color-text-primary'), 'font-weight': 600 });
    curT.textContent = '현재 ' + fmtValue(last.c);
    svg.appendChild(curT);

    const tickCount = Math.min(7, slice.length);
    for (let k = 0; k < tickCount; k++) {
      const idx = Math.round(k * (slice.length - 1) / (tickCount - 1 || 1));
      const cx = pL + (idx + 0.5) * colW;
      const t = svgEl('text', { x: cx, y: H - 4, 'text-anchor': 'middle', 'font-size': 9, fill: gridCol });
      t.textContent = fmtMD(slice[idx].d);
      svg.appendChild(t);
    }

    const legend = [['#D85A30', '양봉'], ['#185FA5', '음봉'], ['#FF69B4', 'MA5'], ['#9370DB', 'MA20'], ['#DAA520', 'MA60'], ['#2E8B57', 'MA120']];
    legend.forEach((l, i) => {
      const gx = pL + i * 74;
      svg.appendChild(svgEl('rect', { x: gx, y: 2, width: 9, height: 9, fill: l[0], rx: 2 }));
      const t = svgEl('text', { x: gx + 12, y: 10, 'font-size': 8.5, fill: gridCol });
      t.textContent = l[1]; svg.appendChild(t);
    });

    // 호버 오버레이 + 크로스헤어
    const overlay = svgEl('rect', { x: pL, y: pT, width: cW, height: cH, fill: 'transparent', style: 'cursor:crosshair;' });
    svg.appendChild(overlay);
    const crosshair = svgEl('line', { y1: pT, y2: pT + cH, stroke: gridCol, 'stroke-width': 1, 'stroke-dasharray': '3,3', visibility: 'hidden' });
    svg.appendChild(crosshair);

    overlay.addEventListener('mousemove', function (evt) {
      const rect = svg.getBoundingClientRect();
      const scale = rect.width / W;
      const mx = (evt.clientX - rect.left) / scale;
      let idx = Math.floor((mx - pL) / colW);
      idx = Math.max(0, Math.min(slice.length - 1, idx));
      const d = slice[idx];
      const cx = pL + (idx + 0.5) * colW;
      crosshair.setAttribute('x1', cx); crosshair.setAttribute('x2', cx);
      crosshair.setAttribute('visibility', 'visible');
      const prev = idx > 0 ? slice[idx - 1] : null;
      const chg = prev ? (d.c - prev.c) / prev.c * 100 : null;
      let chgHtml = '';
      if (chg !== null) {
        const chgCol = chg >= 0 ? '#D85A30' : '#185FA5';
        chgHtml = ' <span style="color:' + chgCol + ';font-weight:600;">' + (chg >= 0 ? '▲' : '▼') + Math.abs(chg).toFixed(2) + '%</span>';
      }
      tip.innerHTML =
        '<b>' + d.d + '</b><br>' +
        '시가 ' + fmtValue(d.o) + unit + ' · 고가 ' + fmtValue(d.h) + unit + '<br>' +
        '저가 ' + fmtValue(d.l) + unit + ' · 종가 ' + fmtValue(d.c) + unit + chgHtml;
      tip.style.visibility = 'visible';
      const wrapRect = wrap.getBoundingClientRect();
      let left = (evt.clientX - wrapRect.left) + 14;
      let top = (evt.clientY - wrapRect.top) - 12;
      if (left + 165 > wrapRect.width) left = (evt.clientX - wrapRect.left) - 175;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, top) + 'px';
    });
    overlay.addEventListener('mouseleave', function () {
      crosshair.setAttribute('visibility', 'hidden');
      tip.style.visibility = 'hidden';
    });
  }

  // cfg.periods/cfg.defaultPeriodDays: 지수·환율 페이지처럼 수집 가능한 최대기간(수십 년치
  // 일봉)을 그대로 저장하는 경우, 기존 종목 차트의 "1년=9999(=전체)"라는 눌림목 전제가
  // 더는 성립하지 않아 실제 거래일수 기준 값과 "전체" 버튼을 분리해야 한다(2026-09-07).
  // 둘 다 생략하면 기존 종목 차트와 완전히 동일하게 동작.
  const defaultPeriodDays = cfg.defaultPeriodDays || 9999;
  if (controls) {
    const periods = cfg.periods || [['1개월', 21], ['3개월', 63], ['6개월', 126], ['1년', 9999]];
    controls.innerHTML = '';
    periods.forEach(([label, days]) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = label;
      btn.className = 'kc-period-btn' + (days === defaultPeriodDays ? ' active' : '');
      btn.addEventListener('click', function () {
        Array.from(controls.children).forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        render(days);
        if (cfg.onPeriodChange) cfg.onPeriodChange(days);
      });
      controls.appendChild(btn);
    });
  }

  render(defaultPeriodDays);
}

// ── 지수/환율 상세페이지 공용 로직 (2026-09-07 신규, indices/*.html 7개 페이지가 공유) ──
// 종목 상세페이지와 달리 PER/PBR/재무제표가 없는 대신, 캔들 데이터(data) 배열 하나만
// 있으면 RSI·변동성·기간별 수익률·월별 등락률을 전부 클라이언트에서 계산해 그린다.
// PowerShell 쪽은 하루 한 번 OHLCV 배열(만원 단위 변환 없이 실제 지수·환율 값 그대로)만
// 구워 넣으면 되고, 헤더(현재값·등락률·52주 최고/최저)만 기존 종목 페이지와 동일하게
// 정적 텍스트로 굽는다(계산 로직을 PowerShell/JS 두 곳에 이중 구현하지 않기 위함).

// Wilder's smoothing 방식 RSI(14) 시계열 — data.length와 동일한 길이 배열(초기 n개는 null).
function calcRsiSeries(closes, n) {
  n = n || 14;
  const out = new Array(closes.length).fill(null);
  if (closes.length < n + 1) return out;
  let gains = 0, losses = 0;
  for (let i = 1; i <= n; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gains += diff; else losses -= diff;
  }
  let avgGain = gains / n, avgLoss = losses / n;
  out[n] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = n + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff >= 0 ? diff : 0, loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (n - 1) + gain) / n;
    avgLoss = (avgLoss * (n - 1) + loss) / n;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

function computeIndexStats(data) {
  if (!data || data.length < 2) return null;
  const closes = data.map(d => d.c);
  const last = data[data.length - 1];
  const prev = data[data.length - 2];
  const changePct = ((last.c - prev.c) / prev.c) * 100;

  const win = data.slice(-252); // 52주(거래일 기준) 최고/최저
  let hi = win[0], lo = win[0];
  win.forEach(d => { if (d.h > hi.h) hi = d; if (d.l < lo.l) lo = d; });

  function barNTradingDaysAgo(n) {
    const idx = data.length - 1 - n;
    return idx >= 0 ? data[idx] : null;
  }
  function pctFrom(pastBar) {
    return pastBar ? ((last.c - pastBar.c) / pastBar.c) * 100 : null;
  }
  const ytdKey = last.d.slice(0, 4) + '-01-01';
  const ytdBar = data.find(d => d.d >= ytdKey) || null;

  const periodReturns = {
    w1: pctFrom(barNTradingDaysAgo(5)),
    m1: pctFrom(barNTradingDaysAgo(21)),
    m3: pctFrom(barNTradingDaysAgo(63)),
    m6: pctFrom(barNTradingDaysAgo(126)),
    y1: pctFrom(barNTradingDaysAgo(252)),
    ytd: pctFrom(ytdBar),
  };

  const byMonth = {};
  data.forEach(d => {
    const mk = d.d.slice(0, 7);
    (byMonth[mk] = byMonth[mk] || []).push(d);
  });
  const monthly = Object.keys(byMonth).sort().map(mk => {
    const bars = byMonth[mk];
    const open = bars[0].o, close = bars[bars.length - 1].c;
    const high = Math.max(...bars.map(b => b.h)), low = Math.min(...bars.map(b => b.l));
    return { month: mk, open, high, low, close, changePct: ((close - open) / open) * 100 };
  });

  // 최근 20거래일 일간수익률 표준편차의 연환산(%) — 단순 실현변동성 근사치.
  const recent = data.slice(-21);
  const rets = [];
  for (let i = 1; i < recent.length; i++) rets.push((recent[i].c - recent[i - 1].c) / recent[i - 1].c);
  const mean = rets.reduce((s, x) => s + x, 0) / (rets.length || 1);
  const variance = rets.reduce((s, x) => s + (x - mean) * (x - mean), 0) / (rets.length || 1);
  const vol20d = rets.length ? Math.sqrt(variance) * Math.sqrt(252) * 100 : null;

  function sma(n) {
    if (closes.length < n) return null;
    const slice = closes.slice(-n);
    return slice.reduce((s, x) => s + x, 0) / n;
  }

  const rsiSeries = calcRsiSeries(closes, 14);

  return {
    last, prev, changePct, high52w: hi, low52w: lo, periodReturns, monthly,
    vol20d, rsi14: rsiSeries[rsiSeries.length - 1],
    ma5: sma(5), ma20: sma(20), ma60: sma(60), ma120: sma(120),
  };
}

// 반환값(draw 함수): 캔들차트의 기간 버튼과 같은 구간을 보도록 외부에서 다시 호출할 수
// 있게 노출한다(2026-09-07). 지수·환율 페이지는 데이터가 수십 년치 일봉이라, 캔들차트가
// "1년"으로 좁혀졌는데 RSI만 전체 기간을 그리면 두 차트의 x축 구간이 안 맞게 되기 때문.
function renderRsiChart(cfg) {
  const svg = document.getElementById(cfg.svgId);
  if (!svg) return function () {};
  const data = cfg.data;
  const closes = data.map(d => d.c);
  const rsiFull = calcRsiSeries(closes, 14);
  const W = 720, H = 90, pL = 40, pR = 12, pT = 8, pB = 16;
  const cW = W - pL - pR, cH = H - pT - pB;
  function svgEl(tag, attrs) {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function draw(periodDays) {
    const n = data.length;
    const startIdx = periodDays >= n ? 0 : n - periodDays;
    const rsi = rsiFull.slice(startIdx);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    function py(v) { return pT + cH * (1 - v / 100); }
    const colW = cW / rsi.length;
    [30, 50, 70].forEach((v) => {
      svg.appendChild(svgEl('line', { x1: pL, x2: pL + cW, y1: py(v), y2: py(v), stroke: 'oklch(0.85 0.005 90)', 'stroke-width': 1, 'stroke-dasharray': v === 50 ? '2,2' : 'none' }));
      const t = svgEl('text', { x: pL - 4, y: py(v) + 3, 'text-anchor': 'end', 'font-size': 8, fill: 'oklch(0.55 0.02 260)' });
      t.textContent = v;
      svg.appendChild(t);
    });
    const pts = [];
    rsi.forEach((v, i) => { if (v === null) return; pts.push(`${pL + (i + 0.5) * colW},${py(v)}`); });
    if (pts.length >= 2) {
      svg.appendChild(svgEl('polyline', { points: pts.join(' '), fill: 'none', stroke: '#9370DB', 'stroke-width': 1.5 }));
    }
    const lastRsi = rsi[rsi.length - 1];
    if (lastRsi !== null && lastRsi !== undefined) {
      const t = svgEl('text', { x: W - pR, y: pT + 8, 'text-anchor': 'end', 'font-size': 10, 'font-weight': 700, fill: '#9370DB' });
      t.textContent = 'RSI(14) ' + lastRsi.toFixed(1);
      svg.appendChild(t);
    }
  }
  draw(cfg.defaultPeriodDays || 9999);
  return draw;
}

function renderIndexMaStatus(containerId, stats) {
  const el = document.getElementById(containerId);
  if (!el || !stats) return;
  const rows = [['5일선', stats.ma5], ['20일선', stats.ma20], ['60일선', stats.ma60], ['120일선', stats.ma120]];
  el.innerHTML = rows.map(([label, ma]) => {
    if (ma === null) return `<div class="dp-row2"><span class="l">${label}</span><span class="v">데이터 부족</span></div>`;
    const above = stats.last.c >= ma;
    return `<div class="dp-row2"><span class="l">${label}</span><span class="v${above ? ' up' : ''}"${above ? '' : ' style="color:var(--dp-down);"'}>${above ? '가격 상회' : '가격 하회'}</span></div>`;
  }).join('');
}

function renderIndexPeriodReturns(containerId, stats) {
  const el = document.getElementById(containerId);
  if (!el || !stats) return;
  const items = [
    ['1주', stats.periodReturns.w1], ['1개월', stats.periodReturns.m1], ['3개월', stats.periodReturns.m3],
    ['6개월', stats.periodReturns.m6], ['1년', stats.periodReturns.y1], ['YTD', stats.periodReturns.ytd],
  ];
  el.innerHTML = items.map(([label, pct]) => {
    if (pct === null || pct === undefined || isNaN(pct)) {
      return `<div class="idx-ret-item"><div class="idx-ret-l">${label}</div><div class="idx-ret-v">-</div></div>`;
    }
    const sign = pct >= 0 ? '+' : '';
    const color = pct >= 0 ? 'var(--dp-up)' : 'var(--dp-down)';
    return `<div class="idx-ret-item"><div class="idx-ret-l">${label}</div><div class="idx-ret-v" style="color:${color};">${sign}${pct.toFixed(2)}%</div></div>`;
  }).join('');
}

function renderIndexMonthlyTable(tbodyId, stats, fmtValue) {
  const el = document.getElementById(tbodyId);
  if (!el || !stats) return;
  const rows = stats.monthly.slice(-12).slice().reverse();
  el.innerHTML = rows.map((m) => {
    const sign = m.changePct >= 0 ? '+' : '';
    const color = m.changePct >= 0 ? 'var(--dp-up)' : 'var(--dp-down)';
    return `<tr>
      <td>${m.month}</td>
      <td style="text-align:right;">${fmtValue(m.open)}</td>
      <td style="text-align:right;">${fmtValue(m.high)}</td>
      <td style="text-align:right;">${fmtValue(m.low)}</td>
      <td style="text-align:right;">${fmtValue(m.close)}</td>
      <td style="text-align:right;color:${color};font-weight:700;">${sign}${m.changePct.toFixed(2)}%</td>
    </tr>`;
  }).join('');
}

// 홈페이지 index-grid와 동일한 7개 지수/환율을 상세페이지 안에서도 보여주는 위젯.
// indices/*.html은 서로 형제 파일이라 링크는 파일명만("kospi.html")으로 충분.
const IDX_ORDER = ['KOSPI', 'SP500', 'DOW', 'RUSSELL2000', 'NIKKEI', 'USDKRW', 'JPYKRW'];
const IDX_PAGE_MAP = {
  KOSPI: 'kospi.html', SP500: 'sp500.html', DOW: 'dow.html', RUSSELL2000: 'russell2000.html',
  NIKKEI: 'nikkei.html', USDKRW: 'usdkrw.html', JPYKRW: 'jpykrw.html',
};
function renderIndexCompareGrid(containerId, marketIndices, currentKey) {
  const el = document.getElementById(containerId);
  if (!el || !marketIndices) return;
  el.innerHTML = IDX_ORDER.map((key) => {
    const idx = marketIndices[key];
    if (!idx || typeof idx.value !== 'number') return '';
    const isSelf = key === currentKey;
    const changeCls = idx.change > 0 ? 'up' : (idx.change < 0 ? 'down' : '');
    const sign = idx.change > 0 ? '+' : '';
    const valueStr = idx.value.toLocaleString('ko-KR', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
    const changeStr = typeof idx.change === 'number' ? `${sign}${idx.change.toFixed(2)}%` : '-';
    const inner = `<span class="idx-cmp-label">${idx.name}${isSelf ? ' · 현재' : ''}</span>` +
      `<span class="idx-cmp-value">${valueStr}</span>` +
      `<span class="idx-cmp-change ${changeCls}">${changeStr}</span>`;
    return isSelf
      ? `<div class="idx-cmp-card self">${inner}</div>`
      : `<a class="idx-cmp-card" href="${IDX_PAGE_MAP[key]}">${inner}</a>`;
  }).join('');
}

// 코스피 페이지 전용: 이미 계산된 dailyMovers(±5% 변동, kospi10000 Top100 대상)를
// 상승/하락으로 나눠 각각 상위 10개만 보여준다. indices/kospi.html에서 한 단계 아래
// stocks/*.html로 링크해야 하므로 경로 앞에 '../'를 붙인다.
function renderIndexMovers(dailyMovers) {
  const upEl = document.getElementById('idxMoversUp');
  const downEl = document.getElementById('idxMoversDown');
  if (!upEl && !downEl) return;
  const gainers = dailyMovers.filter((m) => m.change > 0).sort((a, b) => b.change - a.change).slice(0, 10);
  const losers = dailyMovers.filter((m) => m.change < 0).sort((a, b) => a.change - b.change).slice(0, 10);
  function rowHtml(m) {
    const cls = m.change >= 0 ? 'up' : 'down';
    const sign = m.change >= 0 ? '+' : '';
    return `<a class="idx-mover-row" href="../${m.page}">
      <span class="idx-mover-name">${m.name}</span>
      <span class="idx-mover-close">${m.close}</span>
      <span class="idx-mover-chg ${cls}">${sign}${m.change.toFixed(2)}%</span>
    </a>`;
  }
  if (upEl) upEl.innerHTML = gainers.length ? gainers.map(rowHtml).join('') : '<p class="idx-mover-empty">오늘 +5% 이상 상승 종목 없음</p>';
  if (downEl) downEl.innerHTML = losers.length ? losers.map(rowHtml).join('') : '<p class="idx-mover-empty">오늘 -5% 이상 하락 종목 없음</p>';
}

// "시계열 주요 뉴스" — "Daily 주요 뉴스"(최근 30일 실제 기사 스크랩)와는 성격이 완전히
// 다르다(2026-09-08, 사용자 명확화). data/news/{code}.json을 그대로 재포장하는 게 아니라,
// data/index_events/{code}.json — 수집 가능한 최대기간(수십 년치 일봉) 전체에서 실제 가격
// 데이터로 감지한 급등락·사상 최고/최저 이벤트에 claude가 그 실제 수치를 근거로 한 문장씩
// 설명을 붙인 아카이브 — 를 읽어 타임라인으로 보여준다. 감지·설명 생성은 update_daily_charts.ps1
// 쪽(Get-DpIndexMajorEvents/Get-DpIndexEventDescriptions)에서 이미 끝난 상태이고, 여기서는
// 그 결과를 그대로 시간순으로 나열만 한다.
function renderIndexEventsTimeline(code) {
  const holder = document.getElementById('idxNewsTimeline');
  if (!holder) return;
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function typeLabel(e) {
    if (e.type === 'big_move') return (typeof e.changePct === 'number' && e.changePct < 0) ? '급락' : '급등';
    if (e.type === 'new_high') return '사상 최고';
    if (e.type === 'new_low') return '사상 최저';
    return '';
  }
  fetch(`../data/index_events/${code}.json?v=${Date.now()}`, { cache: 'no-store' })
    .then(res => { if (!res.ok) throw new Error('no data'); return res.json(); })
    .then(archive => {
      const events = archive.events || [];
      if (events.length === 0) {
        holder.innerHTML = '<p class="dp-news-empty">아직 감지된 주요 사건이 없습니다.</p>';
        return;
      }
      const sorted = events.slice().sort((a, b) => (a.date < b.date ? 1 : (a.date > b.date ? -1 : 0)));
      holder.innerHTML = sorted.map(e => {
        const closeStr = (typeof e.close === 'number') ? e.close.toLocaleString('ko-KR', { maximumFractionDigits: 2 }) : '-';
        const chgStr = (typeof e.changePct === 'number') ? ` · 전일대비 ${e.changePct >= 0 ? '+' : ''}${e.changePct.toFixed(2)}%` : '';
        return `
        <div class="dp-tl-item">
          <span class="dp-tl-dot"></span>
          <div class="dp-tl-date">${esc(e.date)} <span class="dp-tl-badge">${esc(typeLabel(e))}</span></div>
          <div class="dp-tl-title">${esc(e.description || '')}</div>
          <div class="dp-tl-body">종가 ${closeStr}${chgStr}</div>
        </div>
      `;
      }).join('');
    })
    .catch(() => {
      holder.innerHTML = '<p class="dp-news-empty">주요 사건 데이터를 불러오지 못했습니다.</p>';
    });
}

// 7개 indices/*.html 페이지가 공통으로 호출하는 진입점.
// cfg: { code, data, fmtValue?, unit?, marketIndices?, dailyMovers? }
function initIndexDetailPage(cfg) {
  const data = cfg.data;
  if (!data || data.length < 2) return;
  const fmtValue = cfg.fmtValue || function (v) { return v.toLocaleString('ko-KR', { maximumFractionDigits: 2, minimumFractionDigits: 2 }); };
  const unit = cfg.unit || '';

  // 지수·환율 데이터는 수집 가능한 최대기간(수십 년치 일봉)을 통째로 담고 있으므로,
  // 종목 차트의 "1개월/3개월/6개월/1년(=전체)" 구성 대신 실제 연 단위 구간 + "전체" 버튼을
  // 쓰고, 기본값도 최근 1년으로 좁혀 첫 렌더링이 무겁지 않게 한다(2026-09-07).
  const INDEX_CHART_PERIODS = [['1년', 252], ['3년', 756], ['5년', 1260], ['10년', 2520], ['전체', 9999]];
  const rsiDraw = renderRsiChart({ svgId: 'idxRsiSvg', data: data, defaultPeriodDays: 252 });
  renderCandleChart({
    svgId: 'idxSvg', controlsId: 'idxChartControls', data: data, fmtValue: fmtValue, unit: unit,
    periods: INDEX_CHART_PERIODS, defaultPeriodDays: 252,
    onPeriodChange: function (days) { rsiDraw(days); },
  });

  const stats = computeIndexStats(data);
  if (stats) {
    renderIndexMaStatus('idxMaStatus', stats);
    const volEl = document.getElementById('idxVolStat');
    if (volEl) volEl.textContent = (stats.vol20d === null || isNaN(stats.vol20d)) ? '-' : stats.vol20d.toFixed(1) + '%';
    renderIndexPeriodReturns('idxPeriodReturns', stats);
    renderIndexMonthlyTable('idxMonthlyBody', stats, fmtValue);
  }

  if (cfg.marketIndices) renderIndexCompareGrid('idxCompareGrid', cfg.marketIndices, cfg.code);
  if (cfg.dailyMovers) renderIndexMovers(cfg.dailyMovers);

  renderIndexEventsTimeline(cfg.code);
  initDpNews(cfg.code);
}

// ── QRI 통합 매력도 카드(2026-11-17) — data/integrated_score.json(integrated_score/run_daily.py가 매일 생성)을 읽어
// 종목 상단 수치(.dp-stats) 바로 아래에 대표 점수로 표시. 점수·등급·순위는 백엔드 값 그대로(여기서 재계산하지 않음).
// 카드가 그려지면 <html>에 qri-on 클래스 → 예전 '기본적 매력도' 카드(.dp-vscore)는 대표 점수로 겹치지 않게 숨김(report.css).
// 기술적 매력도와 무관하며 기술 카드는 '1. 기술적 분석' 섹션에 그대로 둔다.
(function () {
  const m = location.pathname.match(/\/\d{3}_([0-9A-Z]{6})\.html$/);
  if (!m) return;
  const code = m[1];
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const f1 = (v) => (v == null ? '—' : Number(v).toFixed(1));
  const pct = (v) => (v == null ? '—' : `${v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(1)}%`);
  const AX = { q: ['Q', '기업체력'], r: ['R', '상대가치'], i: ['I', '내재가치'] };
  const ST = { valid: '관측', zero_dividend: '무배당', loss: '적자 확인', turnaround: '흑자전환', missing: '데이터 없음', parse_error: '읽기 실패',
    insufficient_peers: '비교 표본 부족', stale: '기한 경과', designed_not_applicable: '설계상 미적용', invalid: '평가 불가' };
  const OBS = ['valid', 'zero_dividend', 'loss', 'turnaround'];

  function itemsTable(items) {
    return `<div class="qri-tbl"><table class="qri-items"><thead><tr><th>항목</th><th>상태</th><th>점수</th><th>적용 가중치</th><th>근거</th></tr></thead><tbody>${items.map(it => `
      <tr class="${OBS.includes(it.status) ? '' : 'off'}"><td>${esc(it.label)}<small>기본 ${it.weight}</small></td><td>${esc(ST[it.status] || it.status)}</td>
      <td>${it.score == null ? '—' : f1(it.score)}</td><td>${it.effective_weight ? (it.effective_weight * 100).toFixed(0) + '%' : '—'}</td><td>${esc(it.reason || '')}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function render(data, holder) {
    const e = data.stocks && data.stocks[code];
    if (!e) { holder.innerHTML = '<p class="qri-empty">이 종목은 통합 매력도 산출 대상에 없습니다.</p>'; return; }
    const pageDate = (document.querySelector('.dp-date') || {}).textContent || '';
    const pd = pageDate.match(/(\d{4})\.(\d{2})\.(\d{2})/);
    const stale = pd && data.as_of_date < `${pd[1]}-${pd[2]}-${pd[3]}`;
    const n = data.normalization || {};
    const W = data.weights || {};
    const head = e.published
      ? `<div class="qri-top"><div class="qri-num">${f1(e.score)}<span>/100</span></div><div class="qri-grade">${esc(e.grade)}</div>
         <div class="qri-rank">비교 가능 ${n.universe_count}개 종목 중 ${e.rank}위</div></div>`
      : `<div class="qri-top"><div class="qri-num hold">평가 보류</div></div><ul class="qri-reasons">${(e.reasons || []).map(r => `<li>${esc(r)}</li>`).join('')}</ul>`;
    const axes = ['q', 'r', 'i'].map(a => {
      const x = e[a] || {};
      return `<div class="qri-ax"><div class="qri-ax-h"><b>${AX[a][0]}</b> ${AX[a][1]} <small>× ${Math.round((W[a] || 0) * 100)}%</small></div>
        <div class="qri-ax-v">${x.normalized != null ? `${Math.round(x.normalized)}<small>백분위</small>` : '<small>통합 비교 제외</small>'}</div>
        <div class="qri-ax-bar"><i style="width:${x.normalized != null ? x.normalized : 0}%"></i></div>
        <div class="qri-ax-s">원점수 ${f1(x.raw)}${x.contribution != null ? ` · 기여 ${f1(x.contribution)}` : ''}${x.coverage != null && a !== 'i' ? ` · 자료 ${Math.round(x.coverage * 100)}%` : ''}</div></div>`;
    }).join('');
    const iv = e.i || {};
    const sd = e.source_dates || {};
    const facts = [
      iv.price_to_value != null ? `주가/가치 ${iv.price_to_value.toFixed(2)}배` : null,
      iv.margin_of_safety_low != null ? `하단 안전마진 ${pct(iv.margin_of_safety_low)}` : null,
      iv.upside_to_mid != null ? `중간값까지 ${pct(iv.upside_to_mid)}` : null,
      `가격 기준일 ${esc(sd.price || data.as_of_date)}`,
      sd.intrinsic_period ? `재무 기준 ${esc(sd.intrinsic_period)}` : null,
    ].filter(Boolean).join(' · ');
    const warns = (e.warnings || []).filter(w => !/구 형식|메인 페이지 시세/.test(w)).map(w => `<span class="qri-badge">${esc(w)}</span>`).join('');
    const contrib = e.published ? `<p class="qri-calc">기여도 ${f1(e.q.contribution)} + ${f1(e.r.contribution)} + ${f1(e.i.contribution)} = ${f1(e.score_unrounded)} → 표시 ${f1(e.score)}</p>` : '';
    const ivInfo = iv.model_type ? `<p class="qri-calc">내재가치: ${esc(iv.model_type)}형 · 요구수익률 ${Math.round((iv.required_return || 0) * 100)}% · 평가방법 ${esc((iv.methods || []).join(', '))}${(iv.missing_methods || []).length ? ` (누락: ${esc(iv.missing_methods.join(', '))})` : ''} · 방법 커버리지 ${iv.method_coverage != null ? Math.round(iv.method_coverage * 100) + '%' : '—'}${iv.spread != null ? ` · 방법 간 차이 ${iv.spread.toFixed(2)}배` : ''}</p>` : '';
    holder.innerHTML = `${head}<div class="qri-axes">${axes}</div>
      ${facts ? `<p class="qri-facts">${facts}</p>` : ''}${warns ? `<div class="qri-badges">${warns}</div>` : ''}
      ${stale ? '<p class="qri-stale">이전 기준일 자료 — 오늘 통합 매력도 갱신이 아직 반영되지 않았습니다.</p>' : ''}
      <details class="qri-more"><summary>계산 근거 펼치기 (원점수 → 백분위 → 기여도)</summary>
        ${contrib}
        <p class="qri-calc">각 축은 항목 점수(0~100)를 관측된 항목 가중치로 평균한 원점수이고, 이를 통합 비교 가능한 ${n.universe_count}개 종목 안에서 평균 동순위 백분위로 바꾼 값이 Q·R·I입니다.</p>
        <h4>Q 기업체력 · 원점수 ${f1(e.q.raw)}</h4>${itemsTable(e.q.metrics || [])}
        <h4>R 상대가치 · 원점수 ${f1(e.r.raw)}${e.r.pref_adjustment ? ` · 우선주 평소 할인 대비 보정 ×${e.r.pref_adjustment.toFixed(2)}` : ''}</h4>${itemsTable(e.r.metrics || [])}
        <h4>I 내재가치 · 원점수 ${f1(iv.raw)}</h4>${ivInfo}
        <p class="qri-calc">I 원점수는 주가가 가치 중간값(하단·상단의 기하평균)의 0.5배면 100, 1배면 50, 2배면 25, 4배면 0입니다. 50점이 '주가 = 가치'를 뜻하는 건 I 원점수에만 해당합니다.</p>
      </details>
      <p class="qri-help">${esc(data.help || '')}</p>`;
    document.documentElement.classList.add('qri-on');
  }

  function init() {
    const anchor = document.querySelector('.dp-head + .dp-stats') || document.querySelector('.dp-stats');
    if (!anchor || document.getElementById('dpQri')) return;
    const box = document.createElement('section');
    box.className = 'dp-qri';
    box.id = 'dpQri';
    box.setAttribute('aria-label', '통합 매력도');
    box.innerHTML = '<div class="dp-qri-h">통합 매력도 <small>기업체력·상대가치·내재가치 · 기술적 분석 제외</small></div><div class="dp-qri-body"><p class="qri-empty">불러오는 중...</p></div>';
    anchor.insertAdjacentElement('afterend', box);
    const holder = box.querySelector('.dp-qri-body');
    fetch(`../data/integrated_score.json?v=${Date.now()}`, { cache: 'no-store' })
      .then(res => { if (!res.ok) throw new Error('no data'); return res.json(); })
      .then(data => render(data, holder))
      .catch(() => { holder.innerHTML = '<p class="qri-empty">통합 매력도 데이터를 불러오지 못했습니다(점수가 낮다는 뜻이 아닙니다).</p>'; });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
