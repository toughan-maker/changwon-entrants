"""
출주표(chuljuRec) 관리: 조회 / 수정 / 경주 삭제 (Streamlit 없이 동작)

- 한 경주(raceNo)의 선수 행들을 불러와서
- 공통 필드(playDate, playTime, ground, grade)는 모든 행에 같은 값으로,
- 선수별 필드는 행마다 저장
- 저장은 한 트랜잭션: 바뀐 행 UPDATE, 새 행 INSERT, 지운 행 DELETE
"""
import re
from datetime import date, datetime

import pandas as pd

from common import db
from common.db_upload import CHULJU, Col

TABLE = CHULJU.table
COMMON = ["playDate", "playTime", "ground", "grade"]               # 표 위에 한 번만 표시
COLS = {c.db: c for c in CHULJU.cols}
GRID = [c.db for c in CHULJU.cols if c.db != "raceNo" and c.db not in COMMON]   # 표에 표시
SMALLINT = (-32768, 32767)


def list_races(prefix: str, d: date) -> list[str]:
    """그날 해당 경기장(raceNo 앞 글자)의 경주번호 목록"""
    _, rows = db.query(f"SELECT DISTINCT raceNo FROM {TABLE} "
                       "WHERE CAST(playDate AS date) = %s AND raceNo LIKE %s ORDER BY raceNo",
                       (d, f"{prefix}%"))
    return [str(r[0]).strip() for r in rows]


def find_race(prefix: str, d: date, no: int) -> str | None:
    """경주일자 + 경기장 + 경주번호 → raceNo (없으면 None)"""
    for rn in list_races(prefix, d):
        if rn[-2:].isdigit() and int(rn[-2:]) == no:
            return rn
    return None


def load_race(raceno: str) -> tuple[dict, pd.DataFrame]:
    """→ (공통 필드 dict, 선수 표 DataFrame[GRID 열, 선수번호 순])"""
    cols = ["raceNo"] + COMMON + GRID
    names, rows = db.query(f"SELECT {', '.join(f'[{c}]' for c in cols)} FROM {TABLE} "
                           "WHERE raceNo = %s ORDER BY playerNumber", (raceno,))
    df = pd.DataFrame(rows, columns=names)
    if df.empty:
        return {}, pd.DataFrame(columns=GRID)
    first = df.iloc[0]
    pd_val = first["playDate"]
    common = {
        "playDate": pd_val.date() if isinstance(pd_val, datetime) else pd_val,
        "playTime": _s(first["playTime"]), "ground": _s(first["ground"]), "grade": _s(first["grade"]),
    }
    grid = df[GRID].copy()
    for c in GRID:
        if COLS[c].kind == "str":
            grid[c] = grid[c].map(_s)
    return common, grid.reset_index(drop=True)


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _value(v, col: Col, where: str, errors: list):
    """화면 값 → DB 값 (형식·범위·길이 검사)"""
    if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == ""):
        return None
    if col.kind == "int":
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            errors.append(f"{where} {col.db}: 숫자가 아닙니다 ('{v}')")
            return None
        if not SMALLINT[0] <= n <= SMALLINT[1]:
            errors.append(f"{where} {col.db}: 범위를 벗어났습니다 ({n})")
        return n
    if col.kind == "float":
        try:
            return float(v)
        except (TypeError, ValueError):
            errors.append(f"{where} {col.db}: 숫자가 아닙니다 ('{v}')")
            return None
    if col.kind == "date":
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(v))
        if not m:
            errors.append(f"{where} {col.db}: 날짜 형식이 아닙니다 ('{v}')")
            return None
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    s = str(v).strip()
    if col.size and len(s) > col.size:
        errors.append(f"{where} {col.db}: {col.size}자를 넘습니다 ('{s}')")
    return s


def plan_save(raceno: str, common_before: dict, common: dict, before: pd.DataFrame, after: pd.DataFrame):
    """저장할 내용 계산 → (작업 dict, 오류 목록). 오류가 있으면 저장하지 않음.
    작업: {'update': [행], 'insert': [행], 'delete': [선수번호], 'unchanged': n}
    공통 필드가 바뀌면 남아 있는 모든 행을 UPDATE"""
    errors = []
    com = {}
    for c in COMMON:
        com[c] = _value(common.get(c), COLS[c], "공통", errors)
    if com["playDate"] is None:
        errors.append("공통 playDate(경주일)는 비울 수 없습니다.")

    new_rows, seen = [], set()
    for i, r in after.reset_index(drop=True).iterrows():
        if all(_s(r.get(c)) == "" for c in GRID):
            continue                                   # 완전히 빈 행은 무시
        where = f"{i + 1}번째 행"
        rec = {"raceNo": raceno, **com}
        for c in GRID:
            rec[c] = _value(r.get(c), COLS[c], where, errors)
        if rec["playerNumber"] is None:
            errors.append(f"{where}: playerNumber(선수번호)가 비어 있습니다.")
            continue
        if rec["playerNumber"] in seen:
            errors.append(f"{where}: playerNumber {rec['playerNumber']} 가 중복입니다.")
        seen.add(rec["playerNumber"])
        new_rows.append(rec)

    old = {}
    for _, r in before.iterrows():
        n = _value(r.get("playerNumber"), COLS["playerNumber"], "", [])
        if n is not None:
            old[n] = {c: _value(r.get(c), COLS[c], "", []) for c in GRID}
    common_changed = any(com[c] != _value(common_before.get(c), COLS[c], "", []) for c in COMMON)
    ops = {"update": [], "insert": [], "delete": sorted(set(old) - seen), "unchanged": 0}
    for rec in new_rows:
        n = rec["playerNumber"]
        if n in old:
            changed = common_changed or any(rec[c] != old[n][c] for c in GRID)
            if changed:
                ops["update"].append(rec)
            else:
                ops["unchanged"] += 1
        else:
            ops["insert"].append(rec)
    return ops, errors


def save(raceno: str, ops: dict) -> dict:
    """plan_save 결과를 한 트랜잭션으로 반영"""
    sets = [c for c in COMMON + GRID if c != "playerNumber"]
    cols = ["raceNo"] + COMMON + GRID
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            for n in ops["delete"]:
                cur.execute(f"DELETE FROM {TABLE} WHERE raceNo = %s AND playerNumber = %s", (raceno, n))
            for r in ops["update"]:
                cur.execute(f"UPDATE {TABLE} SET " + ", ".join(f"[{c}] = %s" for c in sets)
                            + " WHERE raceNo = %s AND playerNumber = %s",
                            tuple(r[c] for c in sets) + (raceno, r["playerNumber"]))
            for r in ops["insert"]:
                cur.execute(f"INSERT INTO {TABLE} ({', '.join(f'[{c}]' for c in cols)}) "
                            f"VALUES ({', '.join(['%s'] * len(cols))})", tuple(r[c] for c in cols))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {k: (len(v) if isinstance(v, list) else v) for k, v in ops.items()}


def delete_race(raceno: str) -> int:
    """해당 raceNo 의 모든 행 삭제 → 삭제한 행 수"""
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE raceNo = %s", (raceno,))
            n = cur.fetchall()[0][0]
            cur.execute(f"DELETE FROM {TABLE} WHERE raceNo = %s", (raceno,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return int(n)
