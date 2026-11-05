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


def _download_issuer(cert: x509.Certificate):
    """인증서에 적힌 발급기관 주소(AIA)에서 발급자 인증서 받기. 서명이 맞는 것만 반환."""
    for url in _issuer_urls(cert):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException:
            continue
        for cand in _load_certs(resp.content):
            try:
                cert.verify_directly_issued_by(cand)
                return cand
            except Exception:
                continue
    return None


def _issued_by_trusted_root(cert: x509.Certificate, roots) -> bool:
    for root in roots:
        if root.subject == cert.issuer:
            try:
                cert.verify_directly_issued_by(root)
                return True
            except Exception:
                continue
    return False


def build_chain(leaf: x509.Certificate, roots, max_depth: int = 4):
    """서버 인증서에서 시작해 발급기관 주소를 따라가다가, 신뢰 목록(certifi)의 루트가
    서명한 인증서에 닿으면 바로 멈춤. → 그때까지 받은 중간 인증서 목록.
    루트까지 서명이 이어지지 않으면 None (받아온 인증서를 그냥 믿지 않음)."""
    chain, cert = [], leaf
    for _ in range(max_depth + 1):
        if _issued_by_trusted_root(cert, roots):
            return chain
        nxt = _download_issuer(cert)
        if nxt is None or nxt.issuer == nxt.subject:   # 더 못 가거나, 신뢰 목록에 없는 루트
            return None
        chain.append(nxt)
        cert = nxt
    return None


def bundle_for(url: str) -> str | None:
    """해당 사이트용 검증 파일(certifi + 받아온 중간 인증서) 경로. 보완할 수 없으면 None."""
    p = urlparse(url)
    host, port = p.hostname, p.port or 443
    key = f"{host}:{port}"
    with _lock:
        if key in _bundles:
            return _bundles[key]
        with open(certifi.where(), "rb") as f:
            base = f.read()
        roots = x509.load_pem_x509_certificates(base)
        try:
            extra = build_chain(_server_leaf(host, port), roots)
        except (OSError, ValueError):
            return None
        if not extra:
            return None
        fd, path = tempfile.mkstemp(prefix=f"ca_{host}_", suffix=".pem")
        with os.fdopen(fd, "wb") as f:
            f.write(base + b"\n" + b"".join(c.public_bytes(Encoding.PEM) for c in extra))
        _bundles[key] = path
        return path


def is_cert_error(exc: Exception) -> bool:
    return "CERTIFICATE_VERIFY_FAILED" in str(exc) or "certificate verify failed" in str(exc)
