"""
DB 업로드 (카페24 MSSQL) — 출주표 → chuljuRec

- 키: raceNo + playerNumber. 있으면 UPDATE, 없으면 INSERT
- 출주표 결과 파일 + 추가 파일(kia, badpoint_2/1/n/r)을 한 행으로 함께 반영
- 전체를 한 트랜잭션으로 처리 → 중간에 오류가 나면 모두 취소(이전 상태 유지)
"""
import re
from datetime import date

import pandas as pd

from common import db

TABLE = "chuljuRec"
KEYS = ["raceNo", "playerNumber"]

# (DB 열, 출주표 DataFrame 열, 형식, 최대 길이)
CHULJU_MAP = [
    ("raceNo", "경주번호", "str", 11),
    ("playDate", "경주일", "date", None),
    ("playTime", "경주시간", "str", 10),
    ("playerNumber", "선수번호", "int", None),
    ("playerName", "선수명", "str", 10),
    ("kisu", "기수", "int", None),
    ("age", "나이", "int", None),
    ("kia", "기어배수", "str", 10),
    ("grade", "등급", "str", 10),
    ("winPercent", "승률", "int", None),
    ("savePercent", "연대율", "int", None),
    ("rap200", "200미터기록", "str", 10),
    ("training", "훈련지", "str", 20),
    ("jamsilPoint", "경기장점수", "float", None),
    ("totPoint", "종합점수", "float", None),
    ("ground", "경기장", "str", 10),
    ("money_rank", "상금순위", "int", None),
    # 추가 파일 항목 (값1~3 은 파일과 같이 0, 잔여점수)
    ("badpoint_2", "값1", "int", None),
    ("badpoint_1", "값2", "int", None),
    ("badpoint_n", "값3", "int", None),
    ("badpoint_r", "잔여점수", "int", None),
]


def _conv(v, kind: str):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s == "":
        return None
    if kind == "int":
        m = re.match(r"-?\d+", s)
        return int(m.group(0)) if m else None
    if kind == "float":
        try:
            return float(s)
        except ValueError:
            return None
    if kind == "date":   # '26-11-01' → 2026-11-01
        m = re.match(r"(\d{2,4})-(\d{1,2})-(\d{1,2})", s)
        if not m:
            return None
        y = int(m.group(1))
        return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(3)))
    return s


def chulju_records(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    """출주표 DataFrame(값1~3·잔여점수 포함) → (DB 행 목록, 경고 목록)"""
    rows, warns = [], []
    for _, r in df.iterrows():
        rec = {}
        for col, src, kind, size in CHULJU_MAP:
            v = _conv(r.get(src), kind)
            if kind == "str" and v is not None and size and len(v) > size:
                if col == "raceNo":
                    warns.append(f"경주번호 {v} 가 {size}자를 넘어 이 행은 올리지 않습니다.")
                    rec = None
                    break
                warns.append(f"{r.get('경주번호')} {r.get('선수명')}: {col} '{v}' 가 {size}자를 넘어 잘랐습니다.")
                v = v[:size]
            rec[col] = v
        if rec is None:
            continue
        if rec["raceNo"] is None or rec["playerNumber"] is None or rec["playDate"] is None:
            warns.append(f"필수값(경주번호·선수번호·경주일)이 없어 건너뜀: {r.get('경주번호')} {r.get('선수명')}")
            continue
        rows.append(rec)
    return rows, warns


def upsert_chulju(rows: list[dict]) -> dict:
    """chuljuRec 에 반영 → {'inserted': n, 'updated': m}. 오류 시 전부 취소하고 예외 발생."""
    if not rows:
        return {"inserted": 0, "updated": 0}
    cols = [c for c, *_ in CHULJU_MAP]
    sets = [c for c in cols if c not in KEYS]
    update_sql = (f"UPDATE {TABLE} SET " + ", ".join(f"{c} = %s" for c in sets)
                  + " WHERE raceNo = %s AND playerNumber = %s")
    insert_sql = f"INSERT INTO {TABLE} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"

    race_nos = sorted({r["raceNo"] for r in rows})
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT raceNo, playerNumber FROM {TABLE} WITH (UPDLOCK, HOLDLOCK) "
                        f"WHERE raceNo IN ({', '.join(['%s'] * len(race_nos))})", tuple(race_nos))
            existing = {(str(a).strip(), int(b)) for a, b in cur.fetchall()}
            ins = upd = 0
            for r in rows:
                if (r["raceNo"], r["playerNumber"]) in existing:
                    cur.execute(update_sql, tuple(r[c] for c in sets) + (r["raceNo"], r["playerNumber"]))
                    upd += 1
                else:
                    cur.execute(insert_sql, tuple(r[c] for c in cols))
                    ins += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"inserted": ins, "updated": upd}
