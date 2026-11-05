"""
중간 인증서를 빠뜨린 사이트 접속 보완 (Streamlit 없이 동작)

일부 사이트(예: 스포원 www.spo1.or.kr)는 서버가 '중간 인증서'를 보내지 않습니다.
브라우저는 빠진 인증서를 스스로 받아오지만 파이썬 requests 는 그러지 않아
'CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate' 오류가 납니다.

여기서는 브라우저와 같은 방식으로,
  1) 서버 인증서를 받아서
  2) 인증서에 적힌 발급기관 주소(AIA: CA Issuers)에서 중간 인증서를 내려받고
  3) 기본 신뢰 목록(certifi) + 중간 인증서로 만든 파일로 다시 '정상 검증'합니다.
인증서 검사를 끄는 것이 아니므로 보안상 안전합니다.
"""
import os
import socket
import ssl
import tempfile
import threading
from urllib.parse import urlparse

import certifi
import requests
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

_lock = threading.Lock()
_bundles: dict[str, str] = {}       # 'host:port' → 검증용 인증서 묶음 파일 경로


def _server_leaf(host: str, port: int) -> x509.Certificate:
    """검증 없이 서버 인증서(맨 앞 1장)만 받아오기 — 발급기관 주소를 읽기 위한 용도"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))


def _issuer_urls(cert: x509.Certificate) -> list[str]:
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return []
    return [d.access_location.value for d in aia
            if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS]


def _load_certs(data: bytes) -> list[x509.Certificate]:
    """발급기관 주소에서 받은 파일 (DER / PEM / PKCS#7) → 인증서 목록"""
    for loader in (lambda d: [x509.load_der_x509_certificate(d)],
                   lambda d: x509.load_pem_x509_certificates(d),
                   pkcs7.load_der_pkcs7_certificates,
                   pkcs7.load_pem_pkcs7_certificates):
        try:
            certs = loader(data)
            if certs:
                return certs
        except Exception:
            continue
    return []


def _fetch_intermediates(leaf: x509.Certificate, max_depth: int = 4) -> list[x509.Certificate]:
    """서버 인증서에서 시작해 발급기관 주소를 따라가며 중간 인증서 수집"""
    found, cert = [], leaf
    for _ in range(max_depth):
        if cert.issuer == cert.subject:          # 루트(자체 서명)까지 도달
            break
        nxt = None
        for url in _issuer_urls(cert):
            try:
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException:
                continue
            certs = _load_certs(resp.content)
            if certs:
                nxt = certs[0]
                found.extend(certs)
                break
        if nxt is None:
            break
        cert = nxt
    return found


def _chains_to_trusted_root(leaf, intermediates, roots) -> bool:
    """서버 인증서 → 받아온 중간 인증서들 → 신뢰 목록(certifi)의 루트까지
    서명이 한 단계씩 실제로 이어지는지 확인. (받아온 인증서를 그냥 믿지 않기 위함)"""
    chain = [leaf] + intermediates
    try:
        for child, parent in zip(chain, chain[1:]):
            child.verify_directly_issued_by(parent)
    except Exception:
        return False
    last = chain[-1]
    for root in roots:
        if root.subject == last.issuer:
            try:
                last.verify_directly_issued_by(root)
                return True
            except Exception:
                continue
    return any(last == r for r in roots)


def bundle_for(url: str) -> str | None:
    """해당 사이트용 검증 파일(certifi + 받아온 중간 인증서) 경로. 받을 게 없으면 None."""
    p = urlparse(url)
    host, port = p.hostname, p.port or 443
    key = f"{host}:{port}"
    with _lock:
        if key in _bundles:
            return _bundles[key]
        try:
            leaf = _server_leaf(host, port)
            extra = _fetch_intermediates(leaf)
        except (OSError, ValueError):
            return None
        with open(certifi.where(), "rb") as f:
            base = f.read()
        roots = x509.load_pem_x509_certificates(base)
        extra = [c for c in extra if c.issuer != c.subject]          # 루트는 신뢰 목록에 있는 것만 사용
        if not extra or not _chains_to_trusted_root(leaf, extra, roots):
            return None
        fd, path = tempfile.mkstemp(prefix=f"ca_{host}_", suffix=".pem")
        with os.fdopen(fd, "wb") as f:
            f.write(base + b"\n" + b"".join(c.public_bytes(Encoding.PEM) for c in extra))
        _bundles[key] = path
        return path


def is_cert_error(exc: Exception) -> bool:
    return "CERTIFICATE_VERIFY_FAILED" in str(exc) or "certificate verify failed" in str(exc)
