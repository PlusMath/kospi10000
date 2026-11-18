"""QRI 통합 매력도 — 순수 계산 모듈(파일·네트워크 입출력 없음).

입력은 run_daily.py가 data/fundamental_score.json·data/intrinsic_value.json에서 만들어 넘기는 종목별 dict.
기술적 점수(technical_score)는 어디에서도 읽거나 쓰지 않는다 — 산식·모집단·게시 조건·동점 정렬 모두 무관.
"""
from __future__ import annotations

import math

from . import config as C

OBSERVED = {'valid', 'zero_dividend', 'loss', 'turnaround'}
NOT_APPLICABLE = 'designed_not_applicable'

ITEM_LABEL = {'roe': 'ROE', 'growth': 'EPS 성장률', 'safety': '재무안전성(부채비율)',
              'fpe': 'Forward PER', 'pbr': 'PBR', 'div': '배당수익률'}
STATUS_TEXT = {
    'missing': '데이터 없음', 'parse_error': '읽기 실패', 'insufficient_peers': '업종 비교 표본 부족',
    'stale': '비교 데이터 기한 경과', 'invalid': '정상 평가 불가(자본잠식 등)', NOT_APPLICABLE: '설계상 미적용',
}


# ── 항목 점수(0~100) ─────────────────────────────────────────────────────────

def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def finite_pos(*vals) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in vals)


def score_roe(roe: float, median: float) -> float:
    """업종 중앙값과 같으면 50, +10%p면 100, −10%p면 0. 단위 %·%p."""
    return clamp(50 + 5 * (roe - median))


def score_growth(cns_eps: float, eps_last: float) -> float:
    """로그 척도: 예상/직전 EPS 비율 1/3배=0, 1배=50, 3배=100 (2026-11-17 결정 — 스펙 초안의 선형 −50%~+100% 대체)."""
    return clamp(50 + 50 * math.log(cns_eps / eps_last) / math.log(3))


def score_multiple(rel: float) -> float:
    """업종 중앙값 대비 상대배수: 1/3배 이하 100, 1배 50, 3배 이상 0 (로그 대칭)."""
    return clamp(100 * (0.5 - math.log(rel) / (2 * math.log(3))))


def score_intrinsic(price: float, low: float, high: float) -> dict:
    """V = √(L·H), x = ln(V/P). 주가/가치 0.5배=100, 1배=50, 2배=25, 4배=0. 반올림하지 않음."""
    v = math.sqrt(low * high)
    x = math.log(v / price)
    raw = clamp(50 + 50 * x / (math.log(2) if x >= 0 else math.log(4)))
    return {
        'raw': raw, 'midpoint': v, 'price_to_value': price / v,
        'margin_of_safety_mid': 1 - price / v, 'margin_of_safety_low': 1 - price / low,
        'upside_to_mid': v / price - 1, 'range_ratio': high / low,
    }


# ── 항목 구성 ────────────────────────────────────────────────────────────────

def _item(key, weight, status, score=None, value=None, reason=None, **extra):
    d = {'key': key, 'label': ITEM_LABEL[key], 'weight': weight, 'status': status,
         'score': score, 'value': value, 'reason': reason or STATUS_TEXT.get(status)}
    d.update(extra)
    return d


def _relative_item(key, weight, m, adj=1.0):
    """Forward PER·PBR 공통: status/value/median/peer_n → 상대배수 점수. adj는 우선주 할인율 보정(현재/평균 비율)."""
    m = m or {}
    st = m.get('status', 'missing')
    if st == 'loss' and key == 'fpe':
        return _item(key, weight, 'loss', 0.0, None, '컨센서스 예상 적자 — Forward PER 성립 안 함(0점 관측)')
    if st != 'valid':
        return _item(key, weight, st if st in STATUS_TEXT else 'missing', peer_n=m.get('peer_n'))
    val, med, n = m.get('value'), m.get('median'), m.get('peer_n')
    if not finite_pos(val):
        return _item(key, weight, 'invalid', value=val)
    if not finite_pos(med) or (n is not None and n < C.MIN_PEERS_MULTIPLE):
        return _item(key, weight, 'insufficient_peers', value=val, peer_n=n)
    rel = val / med * adj
    return _item(key, weight, 'valid', score_multiple(rel), val,
                 f'업종 중앙값 {med:.2f}배 대비 {rel:.2f}배' + (f' (우선주 평소 할인 대비 보정 ×{adj:.2f})' if adj != 1.0 else ''),
                 median=med, peer_n=n, rel=rel)


def build_q_items(m: dict, financial: bool) -> list:
    """m: {'roe': {...}, 'growth': {...}, 'safety': {...}}. 금융업은 재무안전성(일반 부채비율) 설계상 미적용."""
    W = C.Q_WEIGHTS
    out = []
    r = m.get('roe') or {}
    st = r.get('status', 'missing')
    if st == 'valid':
        if not isinstance(r.get('value'), (int, float)) or not math.isfinite(r['value']):
            out.append(_item('roe', W['roe'], 'missing'))
        elif not isinstance(r.get('median'), (int, float)) or (r.get('peer_n') is not None and r['peer_n'] < C.MIN_PEERS_MULTIPLE):
            out.append(_item('roe', W['roe'], 'insufficient_peers', value=r.get('value'), peer_n=r.get('peer_n')))
        else:
            diff = r['value'] - r['median']
            out.append(_item('roe', W['roe'], 'valid', score_roe(r['value'], r['median']), r['value'],
                             f"ROE 추정치(EPS/BPS) {r['value']:.1f}% · 업종 중앙값 {r['median']:.1f}% 대비 {diff:+.1f}%p",
                             median=r['median'], peer_n=r.get('peer_n')))
    else:
        out.append(_item('roe', W['roe'], st if st in STATUS_TEXT else 'missing'))

    g = m.get('growth') or {}
    st = g.get('status', 'missing')
    cns, last = g.get('cns_eps'), g.get('eps_last')
    if st == 'turnaround' and finite_pos(cns):
        out.append(_item('growth', W['growth'], 'turnaround', 50.0, None,
                         f"흑자전환 (직전 EPS {last:,.0f}원 → 올해 컨센서스 {cns:,.0f}원)" if isinstance(last, (int, float)) else '흑자전환',
                         cns_eps=cns, eps_last=last, eps_last_year=g.get('eps_last_year')))
    elif st == 'loss':
        out.append(_item('growth', W['growth'], 'loss', 0.0, None, '올해 컨센서스 적자 전망(0점 관측)',
                         cns_eps=cns, eps_last=last, eps_last_year=g.get('eps_last_year')))
    elif st == 'valid' and finite_pos(cns, last):
        gp = (cns / last - 1) * 100
        out.append(_item('growth', W['growth'], 'valid', score_growth(cns, last), gp,
                         f"올해 컨센서스 EPS {cns:,.0f}원 vs {g.get('eps_last_year') or '직전'}년 {last:,.0f}원 ({gp:+.0f}%)",
                         cns_eps=cns, eps_last=last, eps_last_year=g.get('eps_last_year')))
    elif st == 'valid' and isinstance(g.get('growth_pct'), (int, float)) and g['growth_pct'] > -100:
        # 구 스키마(EPS 원값 없이 성장률만 저장) 호환: 비율 = 1 + g/100. 직전·예상 EPS 모두 양수일 때만 기록되던 값
        gp = g['growth_pct']
        out.append(_item('growth', W['growth'], 'valid', score_growth(1 + gp / 100, 1.0), gp, f'올해 컨센서스 EPS 성장률 {gp:+.0f}%'))
    else:
        out.append(_item('growth', W['growth'], 'missing' if st in ('valid', 'turnaround') else (st if st in STATUS_TEXT else 'missing'),
                         reason='컨센서스 EPS 없음' if st in ('missing', 'valid', 'turnaround') else None))

    s = m.get('safety') or {}
    if financial:
        out.append(_item('safety', W['safety'], NOT_APPLICABLE, reason='금융업은 일반 부채비율을 쓰지 않음(금융업 건전성 지표 미반영)'))
    else:
        st = s.get('status', 'missing')
        if st == 'valid':
            if not isinstance(s.get('value'), (int, float)) or s['value'] < 0:
                out.append(_item('safety', W['safety'], 'invalid', value=s.get('value'), reason='부채비율 음수·자본잠식은 낮아서 좋은 값으로 보지 않음'))
            elif s.get('percentile') is None or (s.get('peer_n') is not None and s['peer_n'] < C.MIN_PEERS_RANK):
                out.append(_item('safety', W['safety'], 'insufficient_peers', value=s.get('value'), peer_n=s.get('peer_n')))
            else:
                out.append(_item('safety', W['safety'], 'valid', s['percentile'] * 100, s['value'],
                                 (f"부채비율 {s['value']:.0f}% · 업종 {s['peer_n']}개 중 낮을수록 좋은 백분위" if s.get('peer_n') else f"부채비율 {s['value']:.0f}% · 업종 내 낮을수록 좋은 백분위"), peer_n=s.get('peer_n')))
        else:
            out.append(_item('safety', W['safety'], st if st in STATUS_TEXT else 'missing'))
    return out


def build_r_items(m: dict, div: dict, adj: float = 1.0) -> list:
    """m: {'fpe', 'pbr'} (우선주는 보통주 값 + adj), div: 이 종목 자체의 배당 항목."""
    W = C.R_WEIGHTS
    out = [_relative_item('fpe', W['fpe'], m.get('fpe'), adj), _relative_item('pbr', W['pbr'], m.get('pbr'), adj)]
    d = div or {}
    st = d.get('status', 'missing')
    if st == 'zero_dividend':
        out.append(_item('div', W['div'], 'zero_dividend', 0.0, 0.0, '무배당(0점 관측)'))
    elif st == 'valid':
        if d.get('percentile') is None or (d.get('peer_n') is not None and d['peer_n'] < C.MIN_PEERS_RANK):
            out.append(_item('div', W['div'], 'insufficient_peers', value=d.get('value'), peer_n=d.get('peer_n')))
        elif not isinstance(d.get('value'), (int, float)) or d['value'] <= 0:
            out.append(_item('div', W['div'], 'invalid', value=d.get('value')))
        else:
            out.append(_item('div', W['div'], 'valid', d['percentile'] * 100, d['value'],
                             f"배당수익률 {d['value']:.2f}% · 전 종목(무배당 포함) 백분위", peer_n=d.get('peer_n')))
    else:
        out.append(_item('div', W['div'], st if st in STATUS_TEXT else 'missing', reason='배당 데이터 없음(무배당으로 추정하지 않음)'))
    return out


# ── 축 원점수 ────────────────────────────────────────────────────────────────

def axis_summary(items: list) -> dict:
    elig = sum(i['weight'] for i in items if i['status'] != NOT_APPLICABLE)
    obs_items = [i for i in items if i['status'] in OBSERVED]
    obs = sum(i['weight'] for i in obs_items)
    cov = obs / elig if elig else 0.0
    raw = sum(i['weight'] * i['score'] for i in obs_items) / obs if obs else None
    for i in items:
        i['effective_weight'] = (i['weight'] / obs) if (i['status'] in OBSERVED and obs) else 0.0
    return {'eligible_weight': elig, 'observed_weight': obs, 'coverage': cov,
            'observed_count': len(obs_items), 'raw_candidate': raw}


def _axis_reasons(axis, items, required):
    out = []
    for i in items:
        if i['key'] in required and i['status'] not in OBSERVED:
            out.append((f"{axis}_{i['key']}_{i['status']}".upper(), f"{ITEM_LABEL[i['key']]}: {i['reason'] or STATUS_TEXT.get(i['status'], i['status'])}"))
    return out


def q_axis(items: list, financial: bool) -> dict:
    s = axis_summary(items)
    obs = {i['key'] for i in items if i['status'] in OBSERVED}
    required = {'roe', 'growth'} if financial else {'roe'}
    reasons = _axis_reasons('Q', items, required)
    if s['observed_count'] < 2 and not reasons:
        reasons.append(('Q_TOO_FEW', '기업체력 관측 항목 2개 미만'))
    if s['coverage'] < C.AXIS_MIN_COVERAGE and not reasons:
        miss = [i for i in items if i['status'] not in OBSERVED and i['status'] != NOT_APPLICABLE]
        reasons.append(('Q_LOW_COVERAGE', '기업체력 자료 부족(' + ', '.join(f"{ITEM_LABEL[i['key']]} {i['reason'] or i['status']}" for i in miss) + ')'))
    ok = not reasons and required <= obs
    return dict(s, raw=s['raw_candidate'] if ok else None, published=ok, reasons=reasons, items=items)


def r_axis(items: list) -> dict:
    s = axis_summary(items)
    reasons = _axis_reasons('R', items, {'fpe', 'pbr'})
    if s['observed_count'] < 2 and not reasons:
        reasons.append(('R_TOO_FEW', '상대가치 관측 항목 2개 미만'))
    if s['coverage'] < C.AXIS_MIN_COVERAGE and not reasons:
        reasons.append(('R_LOW_COVERAGE', '상대가치 자료 부족'))
    ok = not reasons
    return dict(s, raw=s['raw_candidate'] if ok else None, published=ok, reasons=reasons, items=items)


def i_axis(entry: dict | None, price) -> dict:
    """entry: intrinsic_value.json의 종목 항목(+detail). price: Q/R과 같은 기준일 종가."""
    base = {'raw': None, 'published': False, 'reasons': [], 'warnings': []}
    if not entry:
        base['reasons'].append(('I_MISSING', '내재가치 평가 없음'))
        return base
    d = entry.get('detail') or {}
    if 'error' in entry or 'error' in d:
        err = entry.get('error') or d.get('error')
        base['reasons'].append(('I_EXCLUDED' if (entry.get('excluded') or d.get('excluded')) else 'I_ERROR', f'내재가치 평가 불가: {err}'))
        return base
    base.update(model_type=d.get('model_type'), required_return=d.get('required_return'), financial_period=d.get('financial_period') or entry.get('q'),
                method_weights=d.get('method_weights'), methods=d.get('methods_ok'), missing_methods=d.get('missing_methods'),
                method_coverage=d.get('method_coverage'), spread=d.get('spread'), calc_date=d.get('calc_date'))
    if entry.get('hold'):
        base['reasons'].append(('I_HOLD', '내재가치 평가 보류(적자·고성장 단계 참고값)'))
        return base
    if not d:
        base['reasons'].append(('I_NO_METHOD_INFO', '평가방법 정보 없음(숫자 두 개만으로는 신뢰도 판단 불가)'))
        return base
    if d.get('period_mismatch'):
        base['reasons'].append(('I_PERIOD_MISMATCH', '내재가치 박스와 평가 엔진의 기준 분기가 다름'))
        return base
    lo, hi = entry.get('low'), entry.get('high')
    if not finite_pos(lo, hi) or lo > hi:
        base['reasons'].append(('I_BAD_RANGE', '내재가치 상하단이 유효하지 않음(0 이하·역전·비유한값)'))
        return base
    if not finite_pos(price):
        base['reasons'].append(('I_NO_PRICE', '기준일 종가 없음'))
        return base
    mc = d.get('method_coverage')
    if not isinstance(mc, (int, float)) or mc < C.IV_MIN_METHOD_COVERAGE:
        base['reasons'].append(('I_LOW_METHOD_COVERAGE', f"평가방법 커버리지 {mc if mc is None else round(mc * 100)}% (최소 {round(C.IV_MIN_METHOD_COVERAGE * 100)}%)"))
        return base
    n_ok = len(d.get('methods_ok') or [])
    if not d.get('single_method_design') and n_ok < 2:
        base['reasons'].append(('I_SINGLE_BY_MISSING', '복수 평가방법 모델인데 성공한 방법이 1개'))
        return base
    base.update(score_intrinsic(price, lo, hi), low=lo, high=hi, price=price, published=True)
    w = base['warnings']
    if d.get('single_method_design'): w.append('단일 평가방법')
    if d.get('missing_methods'): w.append('일부 평가방법 누락(' + ', '.join(d['missing_methods']) + ')')
    if isinstance(d.get('spread'), (int, float)) and d['spread'] > C.IV_SPREAD_WARN: w.append('평가방법 간 차이 큼')
    if base['price_to_value'] > 1: w.append('내재가치 중간값보다 비쌈')
    if base['margin_of_safety_low'] < 0: w.append('하단 안전마진 음수')
    if d.get('detail_carried'): w.append('평가방법 정보는 직전 실행 결과')
    return base


# ── 정규화·통합 ──────────────────────────────────────────────────────────────

def midrank_percentiles(values: dict) -> dict:
    """{code: raw} → {code: 0~100}. 100×(less + (equal−1)/2)/(n−1). 동점(허용오차 TIE_EPS)은 같은 값, 전원 동점이면 50."""
    codes = list(values)
    n = len(codes)
    if n == 0:
        return {}
    if n == 1:
        return {codes[0]: 50.0}
    out = {}
    for c in codes:
        a = values[c]
        less = sum(1 for b in values.values() if b < a - C.TIE_EPS)
        equal = sum(1 for b in values.values() if abs(b - a) <= C.TIE_EPS)
        out[c] = 100.0 * (less + (equal - 1) / 2) / (n - 1)
    return out


def round1(x: float) -> float:
    """소수 첫째 자리 반올림(사사오입). 표시·등급용 — 순위는 반올림 전 값 사용."""
    return math.floor(x * 10 + 0.5) / 10


def grade(score) -> str:
    if score is None:
        return C.HOLD_GRADE
    for cut, label in C.GRADES:
        if score >= cut:
            return label
    return C.GRADES[-1][1]


def compute(stocks: list, as_of_date: str, weights: dict | None = None) -> dict:
    """stocks: [{code, name, industry, issuer_code, financial, preferred, price, price_date,
                 q_metrics, r_metrics, div_metric, pref_adj, iv_entry, warnings}]
    반환: {'universe': [...], 'stocks': {code: 결과}} — 정규화 모집단 U는 세 축 모두 유효 + 기준일 일치 종목 전체."""
    W = weights or C.WEIGHTS
    res = {}
    for s in stocks:
        code = s['code']
        reasons, warns = [], list(s.get('warnings') or [])
        stale = s.get('price_date') != as_of_date
        q = q_axis(build_q_items(s.get('q_metrics') or {}, s.get('financial', False)), s.get('financial', False))
        r = r_axis(build_r_items(s.get('r_metrics') or {}, s.get('div_metric') or {}, s.get('pref_adj') or 1.0))
        i = i_axis(s.get('iv_entry'), s.get('price'))
        if stale:
            reasons.append(('PRICE_DATE_MISMATCH', f"가격 기준일 {s.get('price_date')}이 전체 기준일 {as_of_date}와 다름"))
        for ax in (q, r, i):
            reasons += ax['reasons']
        if s.get('financial'):
            warns.append('금융업 건전성 지표 미반영')
        warns += i.get('warnings', [])
        res[code] = {'input': s, 'q': q, 'r': r, 'i': i, 'reasons': reasons, 'warnings': warns,
                     'eligible': not stale and q['raw'] is not None and r['raw'] is not None and i['raw'] is not None}

    U = sorted(c for c, x in res.items() if x['eligible'])
    small = len(U) < C.UNIVERSE_MIN
    pct = {ax: midrank_percentiles({c: res[c][ax]['raw'] for c in U}) for ax in 'qri'}
    for c, x in res.items():
        if x['eligible'] and not small:
            for ax in 'qri':
                x[ax]['normalized'] = pct[ax][c]
                x[ax]['contribution'] = W[ax] * pct[ax][c]
            x['score_unrounded'] = sum(x[ax]['contribution'] for ax in 'qri')
        else:
            for ax in 'qri':
                x[ax]['normalized'] = None
                x[ax]['contribution'] = None
            x['score_unrounded'] = None
            if x['eligible'] and small:
                x['reasons'].append(('UNIVERSE_TOO_SMALL', f'비교 표본 부족(정규화 모집단 {len(U)}개 < {C.UNIVERSE_MIN})'))
    ranked = sorted((c for c in res if res[c]['score_unrounded'] is not None), key=lambda c: (-res[c]['score_unrounded'], c))
    for k, c in enumerate(ranked, 1):
        res[c]['rank'] = k
    for c, x in res.items():
        x.setdefault('rank', None)
        x['score'] = round1(x['score_unrounded']) if x['score_unrounded'] is not None else None
        x['grade'] = grade(x['score'])
        x['published'] = x['score'] is not None
    return {'universe': U, 'universe_too_small': small, 'stocks': res, 'weights': W}
