"""
출주표·상담결과 출력 형식 (세 경기장 공용, Streamlit 없이 동작)

경기장마다 사이트 모양은 달라도 아래 함수로 한 줄씩 만들면 txt 형식이 같아집니다.
"""
import re

from common.tracks import TRACK_FIELD, TRACK_PREFIX


def format_name(name: str) -> str:
    """선수명 정리. 외자(두 글자) 이름은 성과 이름 사이에 공백 두 칸: '김현' / '김 현' → '김  현'.
    그 외 이름은 안쪽 공백을 모두 없앰."""
    n = re.sub(r"\s+", "", name or "")
    return f"{n[0]}  {n[1]}" if len(n) == 2 else n


# ───────────────────────── 출주표 ─────────────────────────
# 결과 파일 열 순서 (창원에서 쓰던 순서 그대로. '경기장점수' = 해당 경기장 최근3회 평균득점)
ENTRANT_COLUMNS = [
    "경주번호", "경주일", "경주시간", "선수번호", "선수명", "기수", "나이",
    "기어배수", "등급", "승률", "연대율", "200미터기록", "훈련지",
    "경기장점수", "종합점수", "경기장", "상금순위",
]
# 추가 파일 열: 경주번호(회차·일차까지), 이름, 기어배수, 0, 0, 0, 잔여점수
EXTRA_COLUMNS = ["경주번호", "선수명", "기어배수", "값1", "값2", "값3", "잔여점수"]

# 예: "(43회 3일) 11월 01일", "2026년 40회 3일차"
ROUND_RE = re.compile(r"(\d{4})\s*년\s*(?:[가-힣]+\s*)?(\d+)([A-Za-z]?)\s*회\s*(\d+)\s*일차")


def normalize_record(text: str) -> str:
    """200m 기록 11”29 / 11″29 / 11.29 -> 11"29 (일반 큰따옴표로 통일)"""
    return re.sub(r"[”″.]", '"', text or "").strip()


def first_number(text: str) -> str:
    """'14 (0)' / '14\\n(0)' → '14',  '407/574' → '407'"""
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return m.group(0) if m else ""


def race_id(track: str, year: str, round_no: str, day_no: str, race_no) -> str:
    """c2026400301 형식. round_no 는 '40' 또는 '41A' 같은 문자열."""
    rnd = str(round_no).upper()
    if rnd.isdigit():
        rnd = f"{int(rnd):02d}"
    return f"{TRACK_PREFIX[track]}{year}{rnd}{int(day_no):02d}{int(race_no):02d}"


def yy_mm_dd(year, month, day) -> str:
    """경주일 YY-MM-DD (예: 26-11-01)"""
    return f"{str(year)[2:]}-{int(month):02d}-{int(day):02d}"


def entrant_row(*, track, race_no_id, race_date, race_time, grade, player_no, name,
                kisu, age, gear, win, quinella, rec200, train, track_score, total_score,
                rank, residual="") -> dict:
    return {
        "경주번호": race_no_id, "경주일": race_date, "경주시간": race_time,
        "선수번호": str(player_no), "선수명": format_name(name),
        "기수": first_number(kisu), "나이": first_number(age),
        "기어배수": (gear or "").strip(), "등급": grade,
        "승률": first_number(win), "연대율": first_number(quinella),
        "200미터기록": normalize_record(rec200), "훈련지": (train or "").strip(),
        "경기장점수": first_number(track_score), "종합점수": first_number(total_score),
        "경기장": TRACK_FIELD[track], "상금순위": first_number(rank),
        "잔여점수": first_number(residual),
    }


def round_label(year, round_no, day_no) -> str:
    return f"{year}년 {str(round_no).lstrip('0') or '0'}회 {int(day_no)}일차"


# ───────────────────────── 상담결과 ─────────────────────────
COUNSEL_COLUMNS = ["회차", "경주일", "성명", "기수", "체중", "200미터", "333미터", "500미터",
                   "도로", "트랙", "훈련일수", "훈련지", "훈련동참자", "전회출전", "훈련내용", "참고사항"]


def counsel_values(cells: list[str]) -> list[str]:
    """[성명, 기수, 체중, 200, 333, 500, 도로, 트랙, 훈련일수, 훈련지, 동참자, 전회출전, 내용, 참고]
    → 정리된 14개 값. '-' 는 빈칸, '(후보)' 표시는 지움."""
    vals = [("" if c.strip() in {"-", "－"} else c.strip()) for c in cells[:14]]
    vals += [""] * (14 - len(vals))
    vals[0] = format_name(re.sub(r"\s*\(.*?\)\s*", "", vals[0]))  # '심상훈 (후보)' → '심상훈', '김현' → '김  현'
    vals[1] = first_number(vals[1])                              # '25기' → '25'
    w = re.findall(r"\d+(?:\.\d+)?", vals[2])                    # 체중 '75->74' → '74' (바뀐 뒤 체중)
    vals[2] = w[-1] if w else vals[2]
    return vals


def counsel_code(track: str, year, times) -> str:
    """회차 코드: c202641 / j202643 / b202638"""
    return f"{TRACK_PREFIX[track]}{year}{int(times):02d}"
