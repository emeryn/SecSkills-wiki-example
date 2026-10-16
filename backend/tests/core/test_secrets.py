from pathlib import Path

import pytest

from app.core.secrets import FileSecretsProvider


def test_reads_and_strips(tmp_path: Path) -> None:
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "pw").write_text("s3cret\n")
    assert FileSecretsProvider(tmp_path).read("db/pw") == "s3cret"


def test_path_traversal_is_refused(tmp_path: Path) -> None:
    provider = FileSecretsProvider(tmp_path / "secrets")
    with pytest.raises(ValueError, match="escapes"):
        provider.read("../etc/passwd")
