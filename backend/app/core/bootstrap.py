"""One-shot secret bootstrap, run by the ``init`` service before anything else starts.

Creates missing secrets only; existing ones are never overwritten, except certificates that are
missing or expire within ``RENEW_BEFORE``, which are regenerated together with their internal CA.
File modes rely on group ownership: the init user belongs to the database and web server groups.
"""

import base64
import ipaddress
import logging
import os
import re
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

DB_GID = 70
WEB_GID = 101
CA_VALIDITY = timedelta(days=3650)
DB_CERT_VALIDITY = timedelta(days=3650)
TLS_CERT_VALIDITY = timedelta(days=397)
RENEW_BEFORE = timedelta(days=30)

_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)

_RANDOM_KEYS = (
    "app/master.key",
    "app/session.key",
    "app/csrf.key",
    "app/bootstrap_admin_password",
    # Encrypts backups; stored apart from the backups volume and never inside a backup.
    "app/backup.key",
)
CUSTOM_TLS_MARKER = "tls/.custom"
_CERT_FILES = ("db/ca.crt", "db/server.crt", "db/server.key", "tls/tls.crt", "tls/tls.key")


def _write(path: Path, data: bytes, mode: int, gid: int | None = None) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
        if gid is not None and gid != os.getegid():
            os.fchown(fd, -1, gid)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _ensure_dir(path: Path, mode: int, gid: int | None = None) -> None:
    path.mkdir(exist_ok=True)
    if gid is not None and gid != os.getegid():
        os.chown(path, -1, gid)
    path.chmod(mode)


def _random_secret() -> bytes:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=")


def _subject_alt_names(hostnames: list[str]) -> list[x509.GeneralName]:
    names: list[x509.GeneralName] = []
    for host in hostnames:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            if not _DNS_NAME.match(host):
                raise ValueError(f"Invalid TLS host name: {host!r}") from None
            names.append(x509.DNSName(host))
    return names


def _issue(
    common_name: str,
    hostnames: list[str],
    ca_key: ec.EllipticCurvePrivateKey,
    ca_cert: x509.Certificate,
    validity: timedelta,
) -> tuple[bytes, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + validity)
        .add_extension(x509.SubjectAlternativeName(_subject_alt_names(hostnames)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem


def _certificates_need_renewal(base: Path) -> bool:
    custom_tls = (base / CUSTOM_TLS_MARKER).exists()
    checked = [n for n in _CERT_FILES if not (custom_tls and n.startswith("tls/"))]
    if not all((base / name).exists() for name in checked):
        return True
    deadline = datetime.now(UTC) + RENEW_BEFORE
    for name in [n for n in checked if n.endswith(".crt")]:
        cert = x509.load_pem_x509_certificate((base / name).read_bytes())
        if cert.not_valid_after_utc < deadline or not _has_key_identifiers(cert):
            return True
    return False


def _has_key_identifiers(cert: x509.Certificate) -> bool:
    """Strict X.509 verification (e.g. Python 3.13+ clients) requires both identifiers."""
    try:
        cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
        cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    except x509.ExtensionNotFound:
        return False
    return True


def _generate_certificates(base: Path, tls_hostnames: list[str], db_gid: int, web_gid: int) -> None:
    # The CA key only lives in memory: certificates are re-issued together when renewed.
    ca_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Wiki internal CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + CA_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    db_cert, db_key = _issue("db", ["db"], ca_key, ca_cert, DB_CERT_VALIDITY)
    tls_cert, tls_key = _issue(tls_hostnames[0], tls_hostnames, ca_key, ca_cert, TLS_CERT_VALIDITY)

    _write(base / "db/ca.crt", ca_cert.public_bytes(serialization.Encoding.PEM), 0o444)
    _write(base / "db/server.crt", db_cert, 0o444)
    _write(base / "db/server.key", db_key, 0o040, db_gid)
    if not (base / CUSTOM_TLS_MARKER).exists():
        _write(
            base / "tls/tls.crt", tls_cert + ca_cert.public_bytes(serialization.Encoding.PEM), 0o444
        )
        _write(base / "tls/tls.key", tls_key, 0o040, web_gid)
    logger.info("Certificates generated", extra={"tls_hostnames": tls_hostnames})


def import_tls(base: Path, cert_pem: bytes, key_pem: bytes, web_gid: int = WEB_GID) -> None:
    """Install an operator-provided certificate chain and key for the reverse proxy.

    The certificate is kept across restarts (no automatic renewal); delete ``tls/.custom`` from
    the volume to return to a generated certificate.
    """
    chain = x509.load_pem_x509_certificates(cert_pem)
    key = serialization.load_pem_private_key(key_pem, password=None)
    leaf_public = (
        chain[0]
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    key_public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if leaf_public != key_public:
        raise ValueError("The private key does not match the certificate")
    if chain[0].not_valid_after_utc <= datetime.now(UTC):
        raise ValueError("The certificate has expired")
    _ensure_dir(base / "tls", 0o750, web_gid)
    _write(base / "tls/tls.crt", cert_pem, 0o444)
    _write(base / "tls/tls.key", key_pem, 0o040, web_gid)
    _write(base / CUSTOM_TLS_MARKER, b"", 0o444)
    logger.info("TLS certificate imported", extra={"subject": chain[0].subject.rfc4514_string()})


def bootstrap(
    base: Path, tls_hostnames: list[str], db_gid: int = DB_GID, web_gid: int = WEB_GID
) -> list[str]:
    """Create every missing secret under ``base`` and return the names created."""
    if not tls_hostnames:
        raise ValueError("At least one TLS host name is required")
    _ensure_dir(base / "app", 0o700)
    _ensure_dir(base / "db", 0o750, db_gid)
    _ensure_dir(base / "tls", 0o750, web_gid)

    created: list[str] = []
    for name in _RANDOM_KEYS:
        if not (base / name).exists():
            _write(base / name, _random_secret(), 0o400)
            created.append(name)
    # Superuser password: readable by the database group only, not by the application user.
    db_passwords = (
        ("db/superuser_password", 0o040),
        ("db/owner_password", 0o440),
        ("db/runtime_password", 0o440),
    )
    for name, mode in db_passwords:
        if not (base / name).exists():
            _write(base / name, _random_secret(), mode, db_gid)
            created.append(name)
    if _certificates_need_renewal(base):
        _generate_certificates(base, tls_hostnames, db_gid, web_gid)
        created.extend(_CERT_FILES)
    return created


def main() -> int:
    """Entry point of the ``init`` service."""
    settings = get_settings()
    configure_logging(settings.log_level)
    hostnames = [h.strip().lower() for h in settings.tls_hostnames.split(",") if h.strip()]
    created = bootstrap(settings.secrets_dir, hostnames)
    logger.info("Secret bootstrap complete", extra={"secrets_created": created})
    return 0


if __name__ == "__main__":
    sys.exit(main())
