"""사용: python theme/gen_theme.py  →  css/theme.css 재생성.
css/theme.css 생성: 시안 E(다크 남보라) 토큰 + 기존 인라인 <style>의 밝은 리터럴 색을 다크 토큰으로 덮어쓰는 규칙 자동 생성.
수동 규칙은 theme_manual.css를 앞에 붙인다."""
import re, glob, os, colorsys
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
SP = os.path.dirname(os.path.abspath(__file__))


def lum(c):
    """색 문자열 → (밝기 0~1, 채도 있음 여부). 모르면 None."""
    c = c.strip()
    m = re.match(r'oklch\(\s*([\d.]+)%?\s+([\d.]+)', c)
    if m:
        L = float(m.group(1)); L = L / 100 if L > 1 else L
        return L, float(m.group(2)) > 0.05
    m = re.match(r'#([0-9a-fA-F]{3,8})$', c)
    if m:
        h = m.group(1)
        if len(h) in (3, 4): h = ''.join(x * 2 for x in h[:3])
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
        return 0.2126 * r ** .45 + 0.7152 * g ** .45 + 0.0722 * b ** .45, ss > 0.35 and 0.2 < ll < 0.85
    m = re.match(r'rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)', c)
    if m:
        r, g, b = (float(x) / 255 for x in m.groups())
        hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
        return 0.2126 * r ** .45 + 0.7152 * g ** .45 + 0.0722 * b ** .45, ss > 0.35 and 0.2 < ll < 0.85
    if c == 'white': return 1, False
    if c == 'black': return 0, False
    return None


COL = r'(?:#[0-9a-fA-F]{3,8}\b|oklch\([^)]*\)|rgba?\([^)]*\)|\bwhite\b|\bblack\b)'


def map_decl(prop, val):
    prop = prop.strip().lower()
    cols = re.findall(COL, val)
    if not cols or 'var(' in val and not cols:
        return None
    if prop in ('background', 'background-color', 'background-image'):
        if 'gradient' in val:
            return 'background', 'var(--t-card)'
        L = lum(cols[0])
        if L is None: return None
        l, chroma = L
        if chroma: return None            # 색 있는 배경(배지 등)은 유지
        if l >= 0.985: return 'background', 'var(--t-card)'
        if l >= 0.8: return 'background', 'var(--t-card2)'
        return None
    if prop == 'color':
        L = lum(cols[0])
        if L is None: return None
        l, chroma = L
        if chroma:
            return ('color', 'var(--t-accent)') if l < 0.45 else None   # 진한 남색 링크 등
        if l >= 0.95: return None         # 흰 글자(진한 배지 위)는 유지
        if l < 0.42: return 'color', 'var(--t-fg)'
        if l < 0.75: return 'color', 'var(--t-mute)'
        return None
    if prop.startswith('border') or prop.startswith('outline'):
        L = lum(cols[-1])
        if L and not L[1] and L[0] >= 0.75:
            return prop, re.sub(COL, 'var(--t-line)', val)
        return None
    if prop == 'box-shadow':
        return 'box-shadow', re.sub(COL, 'oklch(0.05 0.02 285 / .5)', val)
    if prop in ('fill', 'stroke'):
        L = lum(cols[0])
        if L and not L[1]:
            return prop, 'var(--t-line)' if L[0] >= 0.75 else 'var(--t-mute)'
    return None


def split_media(st):
    """style 텍스트 → [(media 조건 or '', 규칙 텍스트)]. @media 안 규칙은 같은 @media로 감싸 출력해야
    (평평하게 하면 모바일 전용 배경이 데스크톱에도 걸림)."""
    out, i, top = [], 0, []
    while True:
        j = st.find('@media', i)
        if j < 0:
            top.append(st[i:]); break
        top.append(st[i:j])
        k = st.index('{', j); cond = ' '.join(st[j + 6:k].split())
        depth, q = 1, k + 1
        while depth:
            depth += {'{': 1, '}': -1}.get(st[q], 0); q += 1
        out.append((cond, st[k + 1:q - 1])); i = q
    return [('', ''.join(top))] + out


rules = {}
cards = set()
inline_vals = set()
for p in ['index.html', 'portfolio.html'] + sorted(glob.glob('stocks/*_*.html')) + sorted(glob.glob('indices/*.html')):
    s = open(p, encoding='utf-8-sig').read()
    for st in re.findall(r'<style[^>]*>(.*?)</style>', s, re.S):
        st = re.sub(r'/\*.*?\*/', '', st, flags=re.S)
        for media, chunk in split_media(st):
          for m in re.finditer(r'([^{}@;]+)\{([^{}]*)\}', chunk):
            sel = (media, ' '.join(m.group(1).split()))
            if sel[1].startswith(':root') or not sel[1] or sel[1][0].isdigit():
                continue
            for d in m.group(2).split(';'):
                if ':' not in d: continue
                k, v = d.split(':', 1)
                if k.strip().startswith('--'): continue
                r = map_decl(k, v)
                if r:
                    rules.setdefault(sel, {})[r[0]] = r[1]
            body = m.group(2).replace(' ', '')
            # 강조색 배경 위 흰 글자 → 다크 강조색(밝은 라벤더) 위에선 어두운 글자
            if re.search(r'background(-color)?:var\(--(color|dp)-accent\)', body) and re.search(r'(?<![-\w])color:(#fff(?![0-9a-f])|#ffffff|white)', body):
                rules.setdefault(sel, {})['color'] = 'var(--t-bg)'
            # 카드 배경 요소는 바탕과 구분되게 그림자
            if re.search(r'background(-color)?:var\(--(color-card-bg|dp-card)\)', body) and 'border-radius' in body and not media:
                cards.add(sel[1])
    for m in re.finditer(r'style="([^"]*)"', s):
        for d in m.group(1).split(';'):
            if ':' not in d: continue
            k, v = d.split(':', 1)
            r = map_decl(k, v)
            if r:
                inline_vals.add((k.strip(), v.strip(), r[0], r[1]))

out = [open(os.path.join(SP, 'theme_manual.css'), encoding='utf-8').read(), '\n/* ---- 자동 생성: 기존 밝은 리터럴 색 덮어쓰기 ---- */']
for (media, sel), ds in sorted(rules.items()):
    r = sel + '{' + ';'.join(f'{k}:{v} !important' for k, v in ds.items()) + '}'
    out.append(f'@media {media}{{{r}}}' if media else r)
out.append(',\n'.join(sorted(cards)) + '{box-shadow:var(--t-shadow)}')
for k, v, nk, nv in sorted(inline_vals):
    out.append(f'[style*="{k}:{v}"],[style*="{k}: {v}"]{{{nk}:{nv} !important}}')
# 저장소 작업본은 CRLF(LF로 쓰면 git 경고 → 일일 스크립트가 충돌로 오인한 이력)
open('css/theme.css', 'w', encoding='utf-8', newline='\r\n').write('\n'.join(out) + '\n')
print('rules', len(rules), 'inline', len(inline_vals))
