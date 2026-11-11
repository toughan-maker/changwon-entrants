"""
교차경주 관리 (Streamlit 없이 동작)

kyocha (설정 1행, 수정만)
    kyocha_ground    교차 경기장
    kyocha_raceno    교차경주 수
    ground_racecount 광명경주 수
    kyocha_pageno    교차1경주 짝수페이지번호
    ground_pageno    광명1경주 짝수페이지번호

tbl_raceorder (경주 순서표)
    raceorder  경주순서 (1, 2, 3 …)
    ground     경기장 (교차 경기장 / 잠실)
    racecount  경주번호
    pageno     = kyocha_pageno + 2 × (raceorder − 1)   ← 자동 계산
    playtime   건드리지 않음 (backup_on 도 건드리지 않음)
행 추가·삭제 가능: 저장 때 경주순서별로 수정 / 새 순서는 추가 / 사라진 순서는 삭제

열 형식(숫자/문자)은 DB 에서 읽은 값의 형식을 따라 저장 (예: 경주번호가 '01' 이면 두 자리 문자)
"""
import pandas as pd

from common import db

KYOCHA = "kyocha"
ORDER = "tbl_raceorder"
TOP = ["kyocha_ground", "kyocha_raceno", "ground_racecount", "kyocha_pageno", "ground_pageno"]
TOP_LABEL = {"kyocha_ground": "교차 경기장", "kyocha_raceno": "교차경주",
             "ground_racecount": "광명경주수", "kyocha_pageno": "교차1경주 짝수페이지번호",
             "ground_pageno": "광명1경주 짝수페이지번호"}
HOME_GROUND = "잠실"          # 광명 경주의 경기장 표기
KYOCHA_GROUNDS = ["창원", "부산"]   # 교차 경기장으로 고를 수 있는 값
GROUNDS = ["부산", "창원", "잠실"]  # 순서표 경기장
SMALLINT = (-32768, 32767)
VARCHAR_MAX = 10                     # ground, racecount: varchar(10) → 바이트 기준


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def load() -> tuple[dict, dict, pd.DataFrame, dict]:
    """→ (상단 값, 상단 원래 형식, 순서표[raceorder, ground, racecount], 순서표 형식 샘플)"""
    _, krows = db.query(f"SELECT {', '.join(TOP)} FROM {KYOCHA}")
    if len(krows) != 1:
        raise ValueError(f"{KYOCHA} 테이블에 행이 {len(krows)}개 있습니다. (1개여야 수정할 수 있습니다)")
    raw = dict(zip(TOP, krows[0]))
    top = {k: (_s(v) if k == "kyocha_ground" else _int(v)) for k, v in raw.items()}
    _, orows = db.query(f"SELECT raceorder, ground, racecount FROM {ORDER} ORDER BY raceorder")
    df = pd.DataFrame([(int(r[0]), _s(r[1]), _s(r[2])) for r in orows],
                      columns=["raceorder", "ground", "racecount"])
    sample = {"racecount": orows[0][2] if orows else "01", "raceorder": orows[0][0] if orows else 1}
    return top, raw, df, sample


def _int(v) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _like(value: int | str, sample, width: int = 2):
    """DB 에서 읽은 값과 같은 형식으로: 숫자면 int, 문자면 (숫자일 때) 두 자리 문자"""
    if isinstance(sample, (int, float)) and not isinstance(sample, bool):
        return int(value)
    s = str(value).strip()
    if s.isdigit() and isinstance(sample, str) and len(sample.strip()) >= width:
        return s.zfill(width)
    return s


def build_order(top: dict) -> pd.DataFrame:
    """상단 값으로 순서표 새로 만들기: 교차 경주 → 광명(잠실) 경주"""
    rows, n = [], 0
    for i in range(int(top["kyocha_raceno"] or 0)):
        n += 1
        rows.append((n, top["kyocha_ground"], f"{i + 1:02d}"))
    for i in range(int(top["ground_racecount"] or 0)):
        n += 1
        rows.append((n, HOME_GROUND, f"{i + 1:02d}"))
    return pd.DataFrame(rows, columns=["raceorder", "ground", "racecount"])


def pageno(top: dict, raceorder: int) -> int:
    return int(top["kyocha_pageno"]) + 2 * (int(raceorder) - 1)


def _bytes(v) -> int:
    return len(_s(v).encode("cp949", errors="replace"))


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or _s(v) == ""


def normalize(order: pd.DataFrame) -> pd.DataFrame:
    """빈 줄 제거 + 경주순서 정렬 (경주순서가 비었으면 그대로 두고 check 에서 알림)"""
    o = order.copy()
    o = o[~o.apply(lambda r: all(_blank(r[c]) for c in ("raceorder", "ground", "racecount")), axis=1)]
    o["_n"] = pd.to_numeric(o["raceorder"], errors="coerce")
    return o.sort_values("_n", kind="stable").drop(columns="_n").reset_index(drop=True)


def check(top: dict, order: pd.DataFrame) -> tuple[list[str], list[str]]:
    """→ (오류: 저장 안 함, 참고: 저장은 함). order 는 normalize 한 값"""
    errors, notes = [], []
    if top["kyocha_ground"] not in KYOCHA_GROUNDS:
        errors.append("교차 경기장은 창원 또는 부산이어야 합니다.")
    for k in TOP[1:]:
        if top[k] is None or not 0 <= int(top[k]) <= SMALLINT[1]:
            errors.append(f"{TOP_LABEL[k]}: 0~{SMALLINT[1]} 사이 숫자를 넣어 주세요.")
    seen = set()
    for i, r in order.iterrows():
        n = pd.to_numeric(r["raceorder"], errors="coerce")
        where = f"{i + 1}번째 줄"
        if pd.isna(n) or int(n) != n or not 1 <= n <= SMALLINT[1]:
            errors.append(f"{where}: 경주순서는 1 이상의 정수여야 합니다 ('{_s(r['raceorder'])}')")
            continue
        n = int(n)
        if n in seen:
            errors.append(f"경주순서 {n}: 중복입니다.")
        seen.add(n)
        for c, label in (("ground", "경기장을"), ("racecount", "경주번호를")):
            if _blank(r[c]):
                errors.append(f"경주순서 {n}: {label} 비울 수 없습니다.")
            elif _bytes(r[c]) > VARCHAR_MAX:
                errors.append(f"경주순서 {n}: {label[:-1]} '{_s(r[c])}' 가 너무 깁니다 (최대 {VARCHAR_MAX}바이트, 한글 1자 2바이트)")
        if pageno(top, n) > SMALLINT[1]:
            errors.append(f"경주순서 {n}: 페이지번호가 너무 큽니다.")
    total = int(top["kyocha_raceno"] or 0) + int(top["ground_racecount"] or 0)
    if len(order) != total:
        notes.append(f"순서표는 {len(order)}줄이고, 교차경주 + 광명경주수 = {total} 입니다. 맞게 바꾸려면 '상단 값으로 다시 만들기'를 누르세요.")
    if seen and sorted(seen) != list(range(1, len(seen) + 1)):
        notes.append("경주순서가 1부터 빠짐없이 이어지지 않습니다: " + ", ".join(map(str, sorted(seen))))
    expect = int(top["kyocha_pageno"] or 0) + 2 * int(top["kyocha_raceno"] or 0)
    if int(top["ground_pageno"] or 0) != expect:
        notes.append(f"광명1경주 짝수페이지번호가 {top['ground_pageno']} 입니다. 순서표 계산대로라면 {expect} 입니다.")
    return errors, notes


def save(top: dict, raw_top: dict, order: pd.DataFrame, sample: dict) -> dict:
    """kyocha 수정 + tbl_raceorder 경주순서별 수정/추가, 사라진 순서 삭제 — 한 트랜잭션"""
    vals = [top["kyocha_ground"]] + [_like(top[k], raw_top[k]) if raw_top[k] is not None else int(top[k])
                                     for k in TOP[1:]]
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(f"UPDATE {KYOCHA} SET " + ", ".join(f"[{k}] = %s" for k in TOP), tuple(vals))
            cur.execute(f"SELECT raceorder FROM {ORDER}")
            existing = {int(r[0]) for r in cur.fetchall()}
            upd = ins = 0
            new = set()
            for _, r in order.iterrows():
                n = int(r["raceorder"])
                new.add(n)
                params = (_s(r["ground"]), _like(r["racecount"], sample["racecount"]), pageno(top, n))
                if n in existing:
                    cur.execute(f"UPDATE {ORDER} SET ground = %s, racecount = %s, pageno = %s "
                                "WHERE raceorder = %s", params + (_like(n, sample["raceorder"]),))
                    upd += 1
                else:
                    cur.execute(f"INSERT INTO {ORDER} (raceorder, ground, racecount, pageno) "
                                "VALUES (%s, %s, %s, %s)", (_like(n, sample["raceorder"]),) + params)
                    ins += 1
            extra = sorted(existing - new)
            for n in extra:
                cur.execute(f"DELETE FROM {ORDER} WHERE raceorder = %s", (_like(n, sample["raceorder"]),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"update": upd, "insert": ins, "delete": len(extra)}
