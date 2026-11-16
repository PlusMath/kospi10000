"""종목 상세 리포트형 헤더: 각 종목 페이지에 css/report.css 링크를 넣고, 종목명 줄(.dp-title-row)과
가격 줄(.dp-price-row)을 <header class="dp-head">로 감싼다. 이미 적용된 페이지는 건너뜀.
일일 스크립트의 가격 갱신 패턴은 .dp-price-row 안쪽만 보므로 감싸도 영향 없음.
사용: python theme/report_head.py"""
import glob, os, re
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

LINK = '<link rel="stylesheet" href="../css/report.css">'
THEME = '<link rel="stylesheet" href="../css/theme.css">'
HEAD = re.compile(r'(<div class="dp-title-row">(?:(?!</div>).)*</div>)(\s*)'
                  r'(<div class="dp-price-row">\s*<div class="dp-price">[^<]*</div>\s*<div class="dp-chg[^"]*">[^<]*</div>\s*<div class="dp-date">[^<]*</div>\s*</div>)', re.S)
n_link = n_head = 0
for p in sorted(glob.glob('stocks/*_*.html')):
    raw = open(p, 'rb').read(); bom = raw.startswith(b'\xef\xbb\xbf'); s = raw.decode('utf-8-sig')
    o = s
    nl = '\r\n' if '\r\n' in s else '\n'
    if LINK not in s and THEME in s:
        s = s.replace(THEME, THEME + nl + LINK, 1); n_link += 1
    if 'class="dp-head"' not in s:
        m = HEAD.search(s)
        if m:
            s = s[:m.start()] + f'<header class="dp-head">{nl}' + m.group(1) + nl + m.group(3) + f'{nl}</header>' + s[m.end():]
            n_head += 1
    if s != o:
        open(p, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + s.encode('utf-8'))
print('link', n_link, 'head', n_head)
