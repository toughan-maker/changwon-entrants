"""경기장 이름 → 정보를 가져오는 모듈 (load_entrant / load_counsel / load_result 를 가짐)"""
from common import site_kcycle, site_lepopark, site_spo1

SITES = {
    "창원": site_lepopark,
    "광명": site_kcycle,
    "부산": site_spo1,
}
