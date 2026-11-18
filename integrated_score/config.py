"""QRI 통합 매력도 설정값.

설계 문서: docs/qri-integrated-score.md. 가중치·임계값은 초기 설계값이며 수익률 백테스트로 검증한 최적값이 아니다.
"""

SCHEMA_VERSION = 1
MODEL_VERSION = 'qri-1.0'

# 최종 통합 가중치. 스펙 초안은 40/20/40이었으나, R(상대가치)과 I(내재가치)의 순위상관이 약 0.65라
# 40/20/40에선 R이 Q보다 최종 순위에 더 크게 작용 → 세 축의 실효 영향이 비슷해지는 45/15/40으로 결정(2026-11-17).
WEIGHTS = {'q': 0.45, 'r': 0.15, 'i': 0.40}

# 축 내부 가중치
Q_WEIGHTS = {'roe': 15, 'growth': 15, 'safety': 10}
R_WEIGHTS = {'fpe': 25, 'pbr': 20, 'div': 15}

AXIS_MIN_COVERAGE = 0.75
MIN_PEERS_MULTIPLE = 5      # Forward PER·PBR·ROE 업종 중앙값 최소 표본
MIN_PEERS_RANK = 3          # 부채비율·배당 백분위 최소 표본
IV_MIN_METHOD_COVERAGE = 0.70
IV_SPREAD_WARN = 2.0
UNIVERSE_MIN = 30           # 통합점수 게시 최소 정규화 모집단(검증된 통계적 안전선이 아닌 설정값)
PEER_CACHE_MAX_AGE_DAYS = 7 # 사이트 밖 업종 비교군(peer_universe.json) 허용 나이 — 일일 스크립트 정책과 동일
TIE_EPS = 1e-9              # 원점수 동점 판정 허용오차(부동소수 연산 잔차만 흡수, 표시 반올림과 무관)

# 이 단계(백분위 평균)를 거친 Q/R/I는 0~100. 등급은 표시 score(소수 첫째 자리 반올림)로 판정.
GRADES = [(80, '통합 매력 매우 높음'), (65, '통합 매력 높음'), (45, '통합 매력 보통'), (30, '통합 매력 낮음'), (0, '통합 매력 매우 낮음')]
HOLD_GRADE = '평가 보류'

HELP_TEXT = ('통합 매력도는 기업체력 45%, 상대가치 15%, 내재가치 40%를 반영한 상대 비교 점수입니다. '
             '기술적 분석은 포함하지 않습니다. 점수는 상승 확률이나 절대 저평가를 뜻하지 않습니다.')
