"""투자지표 탭: 상시 노출된 ROE·EPS 성장률·재무안정성 게이지와 업종 비교 블록을 지표 버튼(탭) 체계로 옮김."""
import re, sys, os

METRICS = [('roe', 'ROE', r'ROE \(자기자본이익률\)'),
           ('growth', 'EPS 성장률', r'EPS 성장률[^<]*'),
           ('debt', '재무안정성', r'재무안정성 \(부채비율\)')]


def close_div(s, i):
    """s[i:]가 '<div'로 시작할 때 짝이 맞는 '</div>'의 끝 위치."""
    depth = 0
    for m in re.finditer(r'<div\b|</div>', s[i:]):
        depth += 1 if m.group() == '<div' else -1
        if depth == 0:
            return i + m.end()
    raise ValueError('unbalanced')


def cut_out(s, a, b):
    while b < len(s) and s[b] in '\r\n':
        b += 1
    return s[:a] + s[b:]


def last_line_start(s, lo, pos):
    """pos가 속한 줄의 시작(들여쓰기 앞)."""
    return s.rindex('\n', lo, pos) + 1


def fix(s):
    if 'id="dpMetricNav"' not in s:
        return s, 'no-nav'
    nl = '\r\n' if '\r\n' in s else '\n'
    moved, gauges, peers = [], [], []
    for mid, label, pat in METRICS:
        if f'data-metric="{mid}"' in s:
            continue
        m = re.search(r'[ \t]*<div class="dp-gauge">\s*<div class="dp-gauge-row">\s*<div class="dp-gauge-nm">' + pat + '</div>', s)
        if not m:
            continue
        a = m.start()
        b = close_div(s, s.index('<div', a))
        blk = s[a:b].strip().replace('<div class="dp-gauge">', f'<div class="dp-gauge dp-metric-detail" data-metric="{mid}">', 1)
        s = cut_out(s, a, b)
        gauges.append(blk)
        moved.append((mid, label))
    if moved:
        # 게이지 → dp-metrics-detail-left 안 맨 끝
        li = s.index('<div class="dp-metrics-detail-left">')
        cut = last_line_start(s, li, close_div(s, li) - len('</div>'))
        s = s[:cut] + ''.join(f'        {g}{nl}' for g in gauges) + s[cut:]
        # 버튼 → nav 끝
        ni = s.index('id="dpMetricNav"')
        cut = last_line_start(s, ni, s.index('</nav>', ni))
        s = s[:cut] + ''.join(f'      <button type="button" data-metric="{mid}" onclick="dpShowMetricChart(\'{mid}\',this)">{label}</button>{nl}' for mid, label in moved) + s[cut:]
    # 업종 비교 블록 → dpPeerDataSource 안: 데이터 영역에 같은 지표 블록이 없으면 처음 삽입 때 게이지 바로 뒤에 들어가
    # 화면에 펼쳐진 채 남고 차트도 비었음(크래프톤 등 33개). 일일 스크립트는 문서 앞쪽 블록부터 갱신하므로 바깥 블록이 최신
    if 'id="dpPeerDataSource"' in s:
        for pm in reversed(list(re.finditer(r'[ \t]*<!-- dp-peercmp-(\w+):start -->.*?<!-- dp-peercmp-\1:end -->', s[:s.index('id="dpPeerDataSource"')], re.S))):
            s = cut_out(s, pm.start(), pm.end())
            peers.insert(0, (pm.group(1), pm.group().strip()))
        if peers:
            si = s.rindex('<div', 0, s.index('id="dpPeerDataSource"'))
            for mid, _ in peers:
                old = re.search(r'[ \t]*<!-- dp-peercmp-' + mid + r':start -->.*?<!-- dp-peercmp-' + mid + r':end -->', s[si:], re.S)
                if old:
                    s = cut_out(s, si + old.start(), si + old.end())
            cut = last_line_start(s, si, close_div(s, si) - len('</div>'))
            s = s[:cut] + ''.join(f'      {p}{nl}' for _, p in peers) + s[cut:]
    if not moved and not peers:
        return s, 'ok'
    return s, 'fixed:' + ','.join([m for m, _ in moved] + ['peer-' + m for m, _ in peers])


if __name__ == '__main__':
    args = sys.argv[1:]
    write = bool(args) and args[0] == '--write'
    files = args[1:] if write else args
    stats = {}
    for f in files:
        raw = open(f, 'rb').read()
        bom = raw.startswith(b'\xef\xbb\xbf')
        s = raw.decode('utf-8-sig')
        t, st = fix(s)
        stats.setdefault(st.split(':')[0], []).append((os.path.basename(f), st))
        if write and t != s:
            open(f, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + t.encode('utf-8'))
    for k, v in stats.items():
        print(k, len(v))
        if k in ('fixed', 'no-nav'):
            print('  ', v)
