import os
import ssl
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.bootstrap import _certificates_need_renewal, bootstrap, import_tls

GID = os.getegid()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def secrets_dir(tmp_path: Path) -> Path:
    bootstrap(tmp_path, ["wiki.example.com", "127.0.0.1"], db_gid=GID, web_gid=GID)
    return tmp_path


def test_creates_every_secret_with_restrictive_modes(secrets_dir: Path) -> None:
    expected = {
        "app/master.key": 0o400,
        "app/session.key": 0o400,
        "app/csrf.key": 0o400,
        "app/bootstrap_admin_password": 0o400,
        "app/backup.key": 0o400,
        "db/superuser_password": 0o040,
        "db/owner_password": 0o440,
        "db/runtime_password": 0o440,
        "db/server.key": 0o040,
        "db/ca.crt": 0o444,
        "tls/tls.key": 0o040,
        "tls/tls.crt": 0o444,
    }
    for name, mode in expected.items():
        assert _mode(secrets_dir / name) == mode, name
    assert _mode(secrets_dir / "app") == 0o700


def test_is_idempotent(secrets_dir: Path) -> None:
    before = {p: p.read_bytes() for p in secrets_dir.rglob("*") if p.is_file()}
    created = bootstrap(secrets_dir, ["wiki.example.com"], db_gid=GID, web_gid=GID)
    assert created == []
    assert {p: p.read_bytes() for p in secrets_dir.rglob("*") if p.is_file()} == before


def test_random_secrets_are_unique_and_long(secrets_dir: Path) -> None:
    os.chmod(secrets_dir / "db/superuser_password", 0o600)
    values = [
        (secrets_dir / name).read_text()
        for name in ("app/master.key", "app/session.key", "db/superuser_password")
    ]
    assert len(set(values)) == 3
    assert all(len(v) >= 43 for v in values)


def test_tls_certificate_names_and_validity(secrets_dir: Path) -> None:
    cert = x509.load_pem_x509_certificate((secrets_dir / "tls/tls.crt").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["wiki.example.com"]
    assert [str(ip) for ip in san.get_values_for_type(x509.IPAddress)] == ["127.0.0.1"]
    assert cert.not_valid_after_utc - datetime.now(UTC) <= timedelta(days=398)


def test_db_certificate_matches_service_name(secrets_dir: Path) -> None:
    cert = x509.load_pem_x509_certificate((secrets_dir / "db/server.crt").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["db"]


def test_invalid_host_name_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid TLS host name"):
        bootstrap(tmp_path, ["bad host;rm"], db_gid=GID, web_gid=GID)


def test_imported_certificate_is_kept_across_restarts(secrets_dir: Path) -> None:
    generated = (secrets_dir / "db/server.crt").read_bytes()
    cert_pem = (secrets_dir / "db/server.crt").read_bytes()
    os.chmod(secrets_dir / "db/server.key", 0o600)
    key_pem = (secrets_dir / "db/server.key").read_bytes()
    import_tls(secrets_dir, cert_pem, key_pem, web_gid=GID)
    assert (secrets_dir / "tls/tls.crt").read_bytes() == generated
    bootstrap(secrets_dir, ["wiki.example.com"], db_gid=GID, web_gid=GID)
    assert (secrets_dir / "tls/tls.crt").read_bytes() == generated


def test_import_refuses_mismatched_key(secrets_dir: Path) -> None:
    other_key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    with pytest.raises(ValueError, match="does not match"):
        import_tls(secrets_dir, (secrets_dir / "tls/tls.crt").read_bytes(), other_key, web_gid=GID)


def test_certificates_pass_strict_verification(secrets_dir: Path) -> None:
    """Strict clients (Python 3.13+ default) need key identifiers on CA and server certificates."""
    for name in ("db/ca.crt", "db/server.crt", "tls/tls.crt"):
        cert = x509.load_pem_x509_certificate((secrets_dir / name).read_bytes())
        cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
        cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    context = ssl.create_default_context(cafile=str(secrets_dir / "db/ca.crt"))
    context.verify_flags |= ssl.VERIFY_X509_STRICT
    assert context.cert_store_stats()["x509_ca"] == 1


def test_certificates_without_key_identifiers_are_renewed(secrets_dir: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "legacy")])
    now = datetime.now(UTC)
    legacy = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    (secrets_dir / "db/ca.crt").chmod(0o644)
    (secrets_dir / "db/ca.crt").write_bytes(legacy.public_bytes(serialization.Encoding.PEM))
    assert _certificates_need_renewal(secrets_dir)
