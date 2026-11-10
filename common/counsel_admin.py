"""
상담결과(councel) 관리 — 출주표(chuljuRec)의 한 경주 선수들과 조인해서 조회·수정·삭제 (Streamlit 없이 동작)

조인: councel.racenoofweek = LEFT(chuljuRec.raceNo, 7)  (예: j2026430301 → j202643)
      councel.playerName   = chuljuRec.playerName
- 출주표는 읽기만 하고 절대 바꾸지 않음
- 저장(한 트랜잭션): 상담결과가 있는 선수 → UPDATE, 없던 선수에 값을 넣으면 → INSERT,
  삭제 체크한 선수 → councel 레코드만 DELETE
"""
import pandas as pd

from common import db
from common.db_upload import COUNSEL, VARCHAR_ENCODING

TABLE = COUNSEL.table
COLS = {c.db: c for c in COUNSEL.cols}
# 표에 보여주는 순서 (배번·선수명은 출주표에서, 수정 불가)
EDIT = ["curTrain", "withTrain", "weight", "outside", "pista",
        "interval200", "interval300", "interval500", "traindate", "description", "kija_desc"]
LABEL = {
    "playerNumber": "배번", "playerName": "선수명", "curTrain": "금주훈련지", "withTrain": "동반훈련자",
    "weight": "체중", "outside": "도로", "pista": "피스타", "interval200": "200M", "interval300": "300M",
    "interval500": "500M", "traindate": "훈련일수", "description": "훈련내용", "kija_desc": "참고사항",
    "_delete": "삭제",
}
LIMIT = {"tinyint": (0, 255), "smallint": (-32768, 32767)}
INT_TYPE = {"interval200": "tinyint", "interval300": "tinyint", "interval500": "tinyint", "traindate": "tinyint",
            "weight": "smallint", "outside": "smallint", "pista": "smallint"}
_COLLATE = "COLLATE DATABASE_DEFAULT"   # nvarchar(출주표) ↔ varchar(상담결과) 비교 시 정렬 규칙 충돌 방지


def week_of(raceno: str) -> str:
    return raceno[:7]


def load(raceno: str) -> tuple[dict, pd.DataFrame]:
    """→ (공통 필드, 선수별 표[배번, 선수명, EDIT..., _has])"""
    _, crow = db.query("SELECT TOP 1 raceNo, playDate, playTime, ground, grade FROM chuljuRec WHERE raceNo = %s",
                       (raceno,))
    if not crow:
        return {}, pd.DataFrame()
    r = crow[0]
    common = {"경주번호": str(r[0]).strip(), "경주일": str(r[1])[:10], "경주시간": _s(r[2]),
              "경기장": _s(r[3]), "등급": _s(r[4])}
    sel = ", ".join(f"co.[{c}]" for c in EDIT)
    names, rows = db.query(
        f"SELECT c.playerNumber, c.playerName, {sel}, "
        f"CASE WHEN co.playerName IS NULL THEN 0 ELSE 1 END AS _has "
        f"FROM chuljuRec c LEFT JOIN {TABLE} co "
        f"  ON co.racenoofweek {_COLLATE} = LEFT(c.raceNo, 7) {_COLLATE} "
        f" AND co.playerName {_COLLATE} = c.playerName {_COLLATE} "
        f"WHERE c.raceNo = %s ORDER BY c.playerNumber", (raceno,))
    df = pd.DataFrame(rows, columns=["playerNumber", "playerName", *EDIT, "_has"])
    for c in EDIT:
        if COLS[c].kind == "vstr":
            df[c] = df[c].map(_s)
    df["playerName"] = df["playerName"].map(_s)
    df["_has"] = df["_has"].astype(int).astype(bool)
    df["_delete"] = False
    return common, df


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).rstrip()


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == "")


def _value(v, c: str, where: str, errors: list):
    if _blank(v):
        return None
    col = COLS[c]
    if col.kind == "int":
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            errors.append(f"{where} {LABEL[c]}: 숫자가 아닙니다 ('{v}')")
            return None
        lo, hi = LIMIT[INT_TYPE[c]]
        if not lo <= n <= hi:
            errors.append(f"{where} {LABEL[c]}: {lo}~{hi} 사이여야 합니다 ({n})")
        return n
    s = str(v).strip()
    size = len(s.encode(VARCHAR_ENCODING, errors="replace"))
    if col.size and size > col.size:
        errors.append(f"{where} {LABEL[c]}: 너무 깁니다 ({size}바이트, 최대 {col.size}바이트 · 한글은 1자 2바이트)")
    return s


def plan_save(raceno: str, before: pd.DataFrame, after: pd.DataFrame):
    """→ (작업 {'update','insert','delete'}, 오류 목록)"""
    errors, ops = [], {"update": [], "insert": [], "delete": []}
    week = week_of(raceno)
    b = before.set_index("playerNumber")
    for _, r in after.iterrows():
        n, name = r["playerNumber"], _s(r["playerName"])
        where = f"{n}번 {name}"
        has = bool(b.loc[n, "_has"]) if n in b.index else False
        if bool(r.get("_delete")):
            if has:
                ops["delete"].append({"racenoofweek": week, "playerName": name})
            continue
        vals = {c: _value(r.get(c), c, where, errors) for c in EDIT}
        old = {c: _value(b.loc[n, c], c, "", []) if n in b.index else None for c in EDIT}
        if has:
            if vals != old:
                ops["update"].append({"racenoofweek": week, "playerName": name, **vals})
        elif any(v is not None for v in vals.values()):
            ops["insert"].append({"racenoofweek": week, "playerName": name, **vals})
    return ops, errors


def save(raceno: str, ops: dict) -> dict:
    week = week_of(raceno)
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            for r in ops["delete"]:
                cur.execute(f"DELETE FROM {TABLE} WHERE racenoofweek = %s AND playerName = %s",
                            (r["racenoofweek"], r["playerName"]))
            for r in ops["update"]:
                cur.execute(f"UPDATE {TABLE} SET " + ", ".join(f"[{c}] = %s" for c in EDIT)
                            + " WHERE racenoofweek = %s AND playerName = %s",
                            tuple(r[c] for c in EDIT) + (r["racenoofweek"], r["playerName"]))
            if ops["insert"]:
                # 새 상담결과의 경주일 = 그 회차 출주표의 첫 경주일
                cur.execute("SELECT MIN(playDate) FROM chuljuRec WHERE LEFT(raceNo, 7) = %s", (week,))
                first_day = cur.fetchall()[0][0]
                cols = ["racenoofweek", "playdate", "playerName", *EDIT]
                for r in ops["insert"]:
                    cur.execute(f"INSERT INTO {TABLE} ({', '.join(f'[{c}]' for c in cols)}) "
                                f"VALUES ({', '.join(['%s'] * len(cols))})",
                                (r["racenoofweek"], first_day, r["playerName"], *(r[c] for c in EDIT)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {k: len(v) for k, v in ops.items()}
