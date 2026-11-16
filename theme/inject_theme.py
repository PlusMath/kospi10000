"""사용: python theme/inject_theme.py [--remove]
각 페이지 </head> 앞에 theme.css 링크 추가(이미 있으면 건너뜀). --remove로 제거."""
import glob, os, sys
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
n = 0
for p in ['index.html', 'portfolio.html'] + sorted(glob.glob('stocks/*.html')) + sorted(glob.glob('indices/*.html')):
    raw = open(p, 'rb').read(); bom = raw.startswith(b'\xef\xbb\xbf'); s = raw.decode('utf-8-sig')
    href = ('../' if p.startswith(('stocks', 'indices')) else '') + 'css/theme.css'
    tag = f'<link rel="stylesheet" href="{href}">'
    if '--remove' in sys.argv:
        if tag not in s: continue
        s = s.replace(tag + ('\r\n' if tag + '\r\n' in s else '\n'), '', 1).replace(tag, '')
    else:
        if tag in s: continue
        nl = '\r\n' if '\r\n' in s else '\n'
        if '</head>' in s:
            s = s.replace('</head>', tag + nl + '</head>', 1)
        elif '</style>' in s:   # 종목 페이지는 head 태그 없음 → 첫 <style> 블록 뒤
            s = s.replace('</style>', '</style>' + nl + tag, 1)
        else:
            continue
    open(p, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + s.encode('utf-8')); n += 1
print('changed', n)
