"""순영업소득(NOI) — 전용률·공실·운영경비로 임대료를 소득으로 바꾼다.

유효임대료는 "1㎡ 를 한 달 빌려주면 얼마"라는 단가일 뿐이다. 건물 한 동이
1년에 버는 돈이 되려면 세 번 깎여야 한다. ① 연면적 전부를 빌려주지는
못하고(전용률), ② 빌려줄 수 있는 면적도 늘 다 차지는 않으며(공실률),
③ 들어온 돈에서 운영경비가 나간다(opex).

    임대면적(NLA) = GFA × 전용률
    PGI = 유효임대료 × 임대면적 × 12          (잠재총수입, 만실 가정)
    EGI = PGI × (1 − 공실률)                  (유효총수입)
    NOI = EGI × (1 − opex_ratio)              (순영업소득)

전부 순수 함수다 — I/O 도 전역 상태도 없다. 표준 라이브러리만 쓴다(`import`
문은 0개다). 앞 모듈(`fin_core`·`effective_rent`)을 부르지 않는다.

규약이 셋 있다.

1. **임대료 단위는 원/㎡·월이고 결과는 원/년이다.** ×12 는 이 안에서 한다.
   연액을 넣으면 열두 배 부풀고, 평당가를 넣으면 3.3배 부푼다. 이 모듈은
   임대료의 물리 범위를 다시 검사하지 않는다 — 그 게이트는 임대료를 만드는
   `effective_rent` 쪽에 있고, 여기서는 부호와 유한성만 본다.
2. **전용률은 GFA 대비 임대면적(rentable/GFA) 비율이다.** 등기부의 전유면적
   비율이 아니다. 임대면적은 공용부 안분을 포함해 잡히므로 전유면적보다
   크다. 서울 오피스 관행 근사가 0.5 라 기본값으로 둔다.
3. **opex_ratio 는 총 운영경비가 아니라 미회수분이다.** 한국 오피스는
   임차인이 관리비를 임대료와 별도로 부담해(net lease 성격) 청소·경비·
   공용 수도광열 같은 운영경비 대부분이 관리비 수입으로 상계된다. 남는 것은
   수선충당·보험·공용부 손실·재산세 일부 같은 미회수분이고, 그 몫의 관행
   수준이 EGI 의 15% 라 기본값으로 둔다. 관리비 수입과 지출을 각각 총액으로
   세우는 정석 대신 상계 후 비율 하나로 뭉갠 단순화다.

NaN·무한대는 도메인 검사가 아니라 별도 가드로 막는다. 크기 비교가 전부
False 라 도메인 검사를 조용히 통과하는데, 그렇게 나온 NaN·inf 는 정상 float
처럼 생겨서 하류(cap rate·가치·대출)까지 그대로 흘러가기 때문이다.
"""

# 조정 가능한 가정의 기본값(골든 상수가 아니다). 시그니처는 다섯 인자를 모두
# 요구하므로 여기서 기본값을 주지 않는다 — 부르는 쪽이 이 상수를 넘긴다.
DEFAULT_EFFICIENCY = 0.5    # GFA 대비 임대면적 — 서울 오피스 NLA 관행 근사
DEFAULT_OPEX_RATIO = 0.15   # 관리비 상계 후 미회수 운영경비 / EGI

_MONTHS_PER_YEAR = 12
_INF = float("inf")


def _require_finite(x: float, what: str) -> None:
    """NaN·무한대를 입력 오류로 잡는다. 자기 자신과 다른 값은 NaN 뿐이다.

    NaN 은 크기 비교가 전부 False 라 도메인 검사(`0 < x <= 1` 따위)를 조용히
    통과한다. inf 는 통과하지는 않지만 GFA·임대료처럼 상한이 없는 인자에서는
    검사 자체가 없어 그대로 지나간다. 둘 다 곱셈을 거치면 NOI 가 NaN/inf 가
    되는데, 그 값은 정상 float 처럼 생겨서 하류가 잡지 못한다.
    """
    if x != x:
        raise ValueError(f"{what} 값이 NaN 이다 — 검사를 조용히 통과하므로 막는다")
    if x == _INF or x == -_INF:
        raise ValueError(f"{what} 값이 무한대다 — 검사를 조용히 통과하므로 막는다")


def noi(
    eff_rent_won_m2_mo: float,
    gfa_m2: float,
    efficiency: float,
    vacancy: float,
    opex_ratio: float,
) -> dict:
    """정상화 순영업소득(원/년)과 그 가정.

    | 단계     | 산식                          | 예(G-NOI-001)                  |
    |----------|-------------------------------|--------------------------------|
    | 임대면적 | GFA × 전용률                  | 100,000 × 0.5 = 50,000㎡       |
    | PGI      | 유효임대료 × 임대면적 × 12    | 25,000 × 50,000 × 12 = 150억   |
    | EGI      | PGI × (1 − 공실률)            | 150억 × 0.95 = 142.5억         |
    | NOI      | EGI × (1 − opex_ratio)        | 142.5억 × 0.85 = 121.125억     |

    도메인: 전용률 ∈ (0, 1] · 공실률 ∈ [0, 1] · opex_ratio ∈ [0, 1) ·
    유효임대료와 GFA 는 양수. 밖이면 `ValueError` 다(공실 100% 는 허용 —
    소득이 0 인 건물은 있어도 임대면적이 0 이거나 운영경비가 수입 전부인
    건물은 입력이 틀린 것이다).

    반환: `{"noi_won_y", "egi_won_y", "assumptions": {...}}`. `assumptions` 에
    임대면적·PGI 와 함께 전용률·관리비 상계·opex 가정의 뜻과 유보(`caveats`)를
    실어 보낸다. NOI 숫자만 떼어 인용하면 안 된다 — 세 가정이 바뀌면 값도
    바뀐다.
    """
    _require_finite(eff_rent_won_m2_mo, "유효임대료")
    if eff_rent_won_m2_mo <= 0:
        raise ValueError(f"유효임대료는 양수여야 한다: {eff_rent_won_m2_mo}")
    _require_finite(gfa_m2, "연면적")
    if gfa_m2 <= 0:
        raise ValueError(f"연면적은 양수여야 한다: {gfa_m2}")
    _require_finite(efficiency, "전용률")
    if not 0 < efficiency <= 1:
        raise ValueError(f"전용률은 (0, 1] 이어야 한다: {efficiency}")
    _require_finite(vacancy, "공실률")
    if not 0 <= vacancy <= 1:
        raise ValueError(f"공실률은 [0, 1] 이어야 한다: {vacancy}")
    _require_finite(opex_ratio, "운영경비율")
    if not 0 <= opex_ratio < 1:
        raise ValueError(f"운영경비율은 [0, 1) 이어야 한다: {opex_ratio}")

    nla_m2 = gfa_m2 * efficiency
    pgi_won_y = eff_rent_won_m2_mo * nla_m2 * _MONTHS_PER_YEAR
    egi_won_y = pgi_won_y * (1 - vacancy)
    noi_won_y = egi_won_y * (1 - opex_ratio)

    return {
        "noi_won_y": noi_won_y,
        "egi_won_y": egi_won_y,
        "assumptions": {
            "eff_rent_won_m2_mo": eff_rent_won_m2_mo,
            "gfa_m2": gfa_m2,
            "efficiency": efficiency,
            "vacancy": vacancy,
            "opex_ratio": opex_ratio,
            "nla_m2": nla_m2,
            "pgi_won_y": pgi_won_y,
            "notes": [
                f"임대면적 = GFA {gfa_m2:,.0f}㎡ × 전용률 {efficiency} "
                f"= {nla_m2:,.0f}㎡ (전유면적이 아니라 공용부 안분을 포함한 "
                f"임대면적/GFA 비율. 관행 근사 {DEFAULT_EFFICIENCY})",
                f"EGI = 유효임대료 {eff_rent_won_m2_mo:,.0f}원/㎡·월 × 임대면적 "
                f"× 12개월 × (1 − 공실 {vacancy})",
                f"NOI = EGI × (1 − 운영경비율 {opex_ratio}) — 운영경비율은 총 "
                f"운영경비가 아니라 **관리비 상계 후 미회수분**이다. 임차인이 "
                f"관리비를 별도 부담해 청소·경비·공용 수도광열은 대부분 "
                f"회수되고, 수선충당·보험·공용부 손실·재산세 일부만 남는다는 "
                f"가정(관행 근사 {DEFAULT_OPEX_RATIO}).",
            ],
            "caveats": [
                "전용률·공실률·운영경비율 셋 다 관행 수준의 가정값이며 회귀로 "
                "추정한 값이 아니다. 셋 중 하나만 흔들려도 NOI 가 두 자릿수 "
                "퍼센트로 움직인다.",
                "관리비 수입과 지출을 각각 총액으로 세우지 않고 상계 후 비율 "
                "하나로 뭉갰다. 관리비를 임대인이 부담하는 gross lease 건물은 "
                "이 가정이 맞지 않아 opex_ratio 를 크게 올려야 한다.",
                "NOI 관행대로 자본적 지출(CapEx)·임대차 수수료(TI/LC)·감가상각·"
                "이자·법인세는 빼지 않았다. 보증금 운용수익도 넣지 않았다 — "
                "성격이 달라 현금흐름 쪽에서 따로 다룬다.",
                "공실률을 연중 상수로 봤다. 리스업 기간·임차인 교체 공백의 "
                "시점 분포는 반영하지 않은 정상화(stabilized) 한 해다.",
            ],
        },
    }
