"""Process-wide services built once at startup and shared by requests, CLI and worker."""

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.crypto import FieldCipher, decode_key
from app.core.ip_blocklist import IpBlocklist
from app.core.mailer import Mailer
from app.core.runtime_settings import RuntimeSettings
from app.core.secrets import SecretsProvider
from app.core.security import PasswordHasher
from app.core.sso_env import SsoEnvironment
from app.core.sso_env import load as load_sso_environment


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    engine: Engine
    sessions: sessionmaker[Session]
    cipher: FieldCipher
    hasher: PasswordHasher
    csrf_key: bytes
    mailer: Mailer
    runtime: RuntimeSettings
    blocklist: IpBlocklist
    sso_env: SsoEnvironment


def build_context(settings: Settings, engine: Engine, secrets: SecretsProvider) -> AppContext:
    # Invalid BACKEND_OIDC_* / BACKEND_LDAP_* variables stop every process here.
    sso_env = load_sso_environment()
    sessions = sessionmaker(engine, expire_on_commit=False)
    cipher = FieldCipher(decode_key(secrets.read("app/master.key")))
    runtime = RuntimeSettings(sessions, cipher)
    return AppContext(
        settings=settings,
        engine=engine,
        sessions=sessions,
        cipher=cipher,
        hasher=PasswordHasher(settings.password_hash_profile),
        csrf_key=decode_key(secrets.read("app/csrf.key")),
        mailer=Mailer(settings, runtime),
        runtime=runtime,
        blocklist=IpBlocklist(sessions),
        sso_env=sso_env,
    )
