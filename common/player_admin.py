"""
선수정보 관리 (player_info + player_jisu) — Streamlit 없이 동작

- 두 테이블은 playerName 으로 연결
- player_info.playerName 은 기본키: 상세화면에서는 바꾸지 않음 (다른 테이블들도 이름으로 연결되어 있음)
- player_jisu 는 선수당 1행으로 다룸 (여러 행이면 idx 가 가장 큰 행, 없으면 새로 만듦)
- retire_yn(은퇴여부, char(1), 기본값 'n') 열이 없으면 has_retire()=False → 모두 현역으로 취급
"""
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from common import db

INFO, JISU = "player_info", "player_jisu"
ENC = "cp949"
RANGE = {"tinyint": (0, 255), "smallint": (-32768, 32767), "int": (-2147483648, 2147483647)}


@dataclass(frozen=True)
class F:
    db: str
    label: str
    kind: str              # vstr(varchar·바이트) / char(고정·바이트) / text / tinyint / smallint / int / date
    size: int | None = None
    required: bool = False
    section: str = "기본"
    wide: bool = False      # 여러 줄 입력칸


# player_info — 화면 이름은 이 표만 고치면 바뀝니다
INFO_FIELDS = [
    F("playerName", "선수명", "vstr", 10, True),
    F("reg_code", "선수번호", "vstr", 8, True),
    F("kisu", "기수", "tinyint", required=True),
    F("birth", "생년월일", "date", required=True),
    F("marriage", "결혼 (Y/N)", "char", 1, True),
    F("height", "키", "char", 3, True),
    F("weight", "체중", "char", 3, True),
    F("bloodtype", "혈액형", "char", 2),
    F("land", "연고", "vstr", 20),
    F("upper_leg", "대퇴", "vstr", 5),
    F("lower_leg", "하퇴", "vstr", 5),
    F("mainStyle", "주전법", "vstr", 10),
    F("rap200m", "200M", "vstr", 5, section="기록·등급"),
    F("rap1000m", "1000M", "vstr", 5, section="기록·등급"),
    F("rank", "순위", "char", 2, section="기록·등급"),
    F("oldGrade", "등급 (전전)", "char", 2, section="기록·등급"),
    F("prevGrade", "등급 (이전)", "char", 2, section="기록·등급"),
    F("curGrade", "등급 (현재)", "char", 2, section="기록·등급"),
    F("camp_move", "훈련지 이동", "vstr", 50, section="기록·등급"),
    F("camp_rank", "훈련지 순위", "tinyint", section="기록·등급"),
    F("school", "학교", "vstr", 50, section="학력·경력"),
    F("middleschool", "중학교", "vstr", 50, section="학력·경력"),
    F("highschool", "고등학교", "vstr", 50, section="학력·경력"),
    F("univ", "대학교", "vstr", 50, section="학력·경력"),
    F("team", "실업팀", "vstr", 50, section="학력·경력"),
    F("univsilup", "대학·실업", "vstr", 50, section="학력·경력"),
    F("silup", "경력", "vstr", 100, section="학력·경력"),
    F("description", "설명", "text", section="학력·경력", wide=True),
    F("jigu", "지구력", "smallint", section="능력치 (player_info)"),
    F("sunbal", "순발력", "smallint", section="능력치 (player_info)"),
    F("danspeed", "단속력", "smallint", section="능력치 (player_info)"),
    F("judo", "주도력", "smallint", section="능력치 (player_info)"),
    F("mark", "마크", "smallint", section="능력치 (player_info)"),
    F("jojong", "조종력", "smallint", section="능력치 (player_info)"),
    F("woonyoung", "운영력", "smallint", section="능력치 (player_info)"),
    F("distance", "거리감", "smallint", section="능력치 (player_info)"),
    F("friend_info", "친분 선수", "vstr", 2000, section="친분 선수", wide=True),
    F("friend_info2", "친분 선수 2", "vstr", 500, section="친분 선수", wide=True),
    F("friend_info3", "친분 선수 3", "vstr", 500, section="친분 선수", wide=True),
    F("friend_info4", "친분 선수 4", "vstr", 500, section="친분 선수", wide=True),
    F("friend_info5", "친분 선수 5", "vstr", 500, section="친분 선수", wide=True),
]
RETIRE = F("retire_yn", "은퇴여부", "char", 1, section="기본")
JISU_FIELDS = [F(c, f.label, "int", section="지수 (player_jisu)")
               for c, f in ((x.db, x) for x in INFO_FIELDS if x.section.startswith("능력치"))]
BY_DB = {f.db: f for f in INFO_FIELDS + [RETIRE]}


# ───────────────────────── 구조 확인 ─────────────────────────
def has_retire() -> bool:
    _, rows = db.query(f"SELECT COL_LENGTH('{INFO}', 'retire_yn')")
    return rows[0][0] is not None


ADD_RETIRE_SQL = (f"ALTER TABLE {INFO} ADD retire_yn char(1) NOT NULL "
                  f"CONSTRAINT DF_{INFO}_retire_yn DEFAULT 'n'")


def add_retire_column():
    """retire_yn 열 추가 (기존 선수는 모두 'n')"""
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(ADD_RETIRE_SQL)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ───────────────────────── 조회 ─────────────────────────
def options() -> tuple[list[int], list[str]]:
    """검색 선택지: (기수 목록, 등급 목록)"""
    _, k = db.query(f"SELECT DISTINCT kisu FROM {INFO} WHERE kisu IS NOT NULL ORDER BY kisu")
    _, g = db.query(f"SELECT DISTINCT RTRIM(curGrade) FROM {INFO} WHERE curGrade IS NOT NULL AND RTRIM(curGrade) <> '' "
                    "ORDER BY 1")
    return [int(r[0]) for r in k], [str(r[0]) for r in g]


def search(status: str, grade: str | None, kisu: int | None, name: str, retire_col: bool) -> pd.DataFrame:
    """status: 전체 / 현역 / 은퇴 → [선수명, 기수, 등급, 현역여부]"""
    where, params = [], []
    if retire_col and status == "현역":
        where.append("ISNULL(retire_yn, 'n') <> 'y'")
    elif retire_col and status == "은퇴":
        where.append("retire_yn = 'y'")
    if grade:
        where.append("RTRIM(curGrade) = %s"); params.append(grade)
    if kisu is not None:
        where.append("kisu = %s"); params.append(int(kisu))
    if name.strip():
        where.append("playerName LIKE %s"); params.append(f"%{name.strip()}%")
    ret = "ISNULL(retire_yn, 'n')" if retire_col else "'n'"
    sql = (f"SELECT playerName, kisu, RTRIM(curGrade), {ret} FROM {INFO}"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY kisu, playerName")
    _, rows = db.query(sql, tuple(params) or None)
    return pd.DataFrame([(str(r[0]).rstrip(), r[1], r[2] or "", "은퇴" if str(r[3]).lower() == "y" else "현역")
                         for r in rows], columns=["선수명", "기수", "등급", "현역여부"])


def load(name: str, retire_col: bool) -> tuple[dict, dict, int | None]:
    """→ (player_info 값, player_jisu 값, jisu idx 또는 None)"""
    cols = [f.db for f in INFO_FIELDS] + (["retire_yn"] if retire_col else [])
    names, rows = db.query(f"SELECT {', '.join(f'[{c}]' for c in cols)} FROM {INFO} WHERE playerName = %s", (name,))
    if not rows:
        return {}, {}, None
    info = {c: _clean(v) for c, v in zip(names, rows[0])}
    if not retire_col:
        info["retire_yn"] = "n"
    jcols = [f.db for f in JISU_FIELDS]
    _, jrows = db.query(f"SELECT TOP 1 idx, {', '.join(f'[{c}]' for c in jcols)} FROM {JISU} "
                        "WHERE playerName = %s ORDER BY idx DESC", (name,))
    if not jrows:
        return info, {c: None for c in jcols}, None
    return info, dict(zip(jcols, jrows[0][1:])), int(jrows[0][0])


def _clean(v):
    if isinstance(v, str):
        return v.rstrip()
    if isinstance(v, datetime):
        return v.date()
    return v


# ───────────────────────── 검사·변환 ─────────────────────────
def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == "")


def convert(values: dict, fields: list[F], errors: list) -> dict:
    out = {}
    for f in fields:
        v = values.get(f.db)
        if _blank(v):
            if f.required:
                errors.append(f"{f.label}: 꼭 입력해야 합니다.")
            out[f.db] = None
            continue
        if f.kind in RANGE:
            try:
                n = int(float(v))
            except (TypeError, ValueError):
                errors.append(f"{f.label}: 숫자가 아닙니다 ('{v}')")
                n = None
            if n is not None:
                lo, hi = RANGE[f.kind]
                if not lo <= n <= hi:
                    errors.append(f"{f.label}: {lo}~{hi} 사이여야 합니다 ({n})")
            out[f.db] = n
        elif f.kind == "date":
            out[f.db] = v if isinstance(v, date) else pd.to_datetime(str(v), errors="coerce")
            if out[f.db] is pd.NaT or out[f.db] is None:
                errors.append(f"{f.label}: 날짜 형식이 아닙니다 ('{v}')")
            elif not isinstance(out[f.db], date):
                out[f.db] = out[f.db].date()
        else:
            s = str(v).strip()
            if f.size and len(s.encode(ENC, errors="replace")) > f.size:
                errors.append(f"{f.label}: 너무 깁니다 ({len(s.encode(ENC, errors='replace'))}바이트, 최대 {f.size}바이트 · 한글 1자 2바이트)")
            out[f.db] = s
    if out.get("marriage") and out["marriage"].upper() not in ("Y", "N"):
        errors.append("결혼: Y 또는 N 으로 입력하세요.")
    elif out.get("marriage"):
        out["marriage"] = out["marriage"].upper()
    if "retire_yn" in out and out["retire_yn"] not in (None, "y", "n"):
        errors.append("은퇴여부: y 또는 n 이어야 합니다.")
    return out


def _jisu_values(jisu: dict, errors: list) -> dict | None:
    """player_jisu 는 모든 지수가 NOT NULL → 빈칸은 0. 하나도 입력하지 않았으면 None (행을 만들지 않음)"""
    vals = convert(jisu, JISU_FIELDS, errors)
    if all(v is None for v in vals.values()):
        return None
    return {k: (0 if v is None else v) for k, v in vals.items()}


# ───────────────────────── 저장 ─────────────────────────
def _jisu_identity(cur) -> bool:
    cur.execute(f"SELECT COLUMNPROPERTY(OBJECT_ID('{JISU}'), 'idx', 'IsIdentity')")
    return (cur.fetchall()[0][0] or 0) == 1


def _write_jisu(cur, name: str, vals: dict | None, idx: int | None):
    if vals is None:
        if idx is None:
            return                 # 지수가 없던 선수에 아무것도 입력하지 않음 → 만들지 않음
        vals = {f.db: 0 for f in JISU_FIELDS}   # 있던 지수를 모두 비우면 0 으로
    cols = list(vals)
    if idx is not None:
        cur.execute(f"UPDATE {JISU} SET " + ", ".join(f"[{c}] = %s" for c in cols) + " WHERE idx = %s",
                    tuple(vals[c] for c in cols) + (idx,))
        return
    if _jisu_identity(cur):
        cur.execute(f"INSERT INTO {JISU} (playerName, {', '.join(cols)}) VALUES (%s, {', '.join(['%s'] * len(cols))})",
                    (name, *(vals[c] for c in cols)))
    else:
        cur.execute(f"SELECT ISNULL(MAX(idx), 0) + 1 FROM {JISU} WITH (UPDLOCK, HOLDLOCK)")
        new_idx = cur.fetchall()[0][0]
        cur.execute(f"INSERT INTO {JISU} (idx, playerName, {', '.join(cols)}) "
                    f"VALUES (%s, %s, {', '.join(['%s'] * len(cols))})", (new_idx, name, *(vals[c] for c in cols)))


def save(name: str, info: dict, jisu: dict, idx: int | None, retire_col: bool) -> list[str]:
    """기존 선수 수정 → 오류 목록 (오류가 있으면 저장 안 함)"""
    errors = []
    fields = [f for f in INFO_FIELDS if f.db != "playerName"] + ([RETIRE] if retire_col else [])
    iv = convert(info, fields, errors)
    jv = _jisu_values(jisu, errors)
    if errors:
        return errors
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(f"UPDATE {INFO} SET " + ", ".join(f"[{c}] = %s" for c in iv) + " WHERE playerName = %s",
                        tuple(iv.values()) + (name,))
            _write_jisu(cur, name, jv, idx)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return []


def create(info: dict, jisu: dict, retire_col: bool) -> list[str]:
    """새 선수 추가 → 오류 목록"""
    errors = []
    fields = INFO_FIELDS + ([RETIRE] if retire_col else [])
    iv = convert(info, fields, errors)
    if retire_col and iv.get("retire_yn") is None:
        iv["retire_yn"] = "n"
    jv = _jisu_values(jisu, errors)
    if errors:
        return errors
    name = iv["playerName"]
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {INFO} WHERE playerName = %s", (name,))
            if cur.fetchall()[0][0]:
                conn.rollback()
                return [f"선수명 '{name}' 은 이미 있습니다."]
            cur.execute(f"INSERT INTO {INFO} ({', '.join(f'[{c}]' for c in iv)}) VALUES ({', '.join(['%s'] * len(iv))})",
                        tuple(iv.values()))
            _write_jisu(cur, name, jv, None)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return []


def delete(name: str) -> tuple[int, int]:
    """player_info·player_jisu 에서 해당 선수 삭제 → (info 행 수, jisu 행 수)"""
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {JISU} WHERE playerName = %s", (name,))
            nj = cur.fetchall()[0][0]
            cur.execute(f"DELETE FROM {JISU} WHERE playerName = %s", (name,))
            cur.execute(f"SELECT COUNT(*) FROM {INFO} WHERE playerName = %s", (name,))
            ni = cur.fetchall()[0][0]
            cur.execute(f"DELETE FROM {INFO} WHERE playerName = %s", (name,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return int(ni), int(nj)
