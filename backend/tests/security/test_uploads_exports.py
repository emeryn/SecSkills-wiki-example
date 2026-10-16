"""Upload and export cases of the security matrix."""

import io
import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.context import AppContext
from app.models import AuditEvent, AuthSession
from tests.helpers import TestUser, make_space, make_user, sign_in, write

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def editor(ctx: AppContext) -> TestUser:
    return make_user(ctx, "erin")


@pytest.fixture
def space(ctx: AppContext, editor: TestUser) -> str:
    return make_space(ctx, "Docs", make_user(ctx, "owner"), members={"erin": (editor, "editor")})


@pytest.fixture
def page_id(client: TestClient, editor: TestUser, space: str) -> Iterator[str]:
    sign_in(client, editor)
    page = write(
        client,
        "POST",
        f"/api/v1/spaces/{space}/pages",
        json={"title": "Guide", "body": "See [[Docs]]."},
    )
    yield page.json()["id"]


def upload(client: TestClient, space: str, page_id: str, name: str, data: bytes) -> object:
    return write(
        client,
        "POST",
        f"/api/v1/spaces/{space}/pages/{page_id}/attachments",
        files={"file": (name, data)},
    )


def jpeg_with_exif() -> bytes:
    exif = Image.Exif()
    exif[0x010E] = "secret-location-description"
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def office_file(extra: dict[str, bytes] | None = None, content_types: bytes = b"<Types/>") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", b"<w:document/>")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_image_is_reencoded_and_served_inline_safely(
    client: TestClient, space: str, page_id: str
) -> None:
    original = jpeg_with_exif()
    assert b"secret-location" in original
    created = upload(client, space, page_id, "photo.jpg", original)
    assert created.status_code == 201, created.text  # type: ignore[attr-defined]
    url = created.json()["url"]  # type: ignore[attr-defined]
    response = client.get(url)
    assert response.status_code == 200
    assert b"secret-location" not in response.content
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


def test_polyglot_payload_is_removed(client: TestClient, space: str, page_id: str) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    polyglot = buffer.getvalue() + b"<script>alert(1)</script>"
    url = upload(client, space, page_id, "logo.png", polyglot).json()["url"]  # type: ignore[attr-defined]
    content = client.get(url).content
    assert content.startswith(PNG_MAGIC)
    assert b"<script>" not in content


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("evil.png", b"this is not an image"),
        ("drawing.svg", b"<svg onload=alert(1)></svg>"),
        ("page.html", b"<script>alert(1)</script>"),
        ("tool.exe", b"MZ\x90\x00"),
        ("notes.txt", b"binary\x00content"),
        ("latin1.txt", "café".encode("latin-1")),
        ("report.pdf", b"<html>not a pdf</html>"),
        ("macro.docx", office_file({"word/vbaProject.bin": b"VBA"})),
        (
            "macro.docx",
            office_file(content_types=b"application/vnd.ms-word.document.macroEnabled.main+xml"),
        ),
        ("bomb.docx", office_file({"word/media/zeros.bin": b"\x00" * 20_000_000})),
        ("slip.docx", office_file({"../../evil.sh": b"x"})),
        ("empty.pdf", b""),
    ],
)
def test_refused_files(
    client: TestClient, space: str, page_id: str, name: str, data: bytes
) -> None:
    response = upload(client, space, page_id, name, data)
    assert response.status_code == 422, (name, response.text)  # type: ignore[attr-defined]


def test_documents_are_downloaded_never_rendered(
    client: TestClient, space: str, page_id: str
) -> None:
    created = upload(client, space, page_id, "spec.docx", office_file())
    assert created.status_code == 201, created.text  # type: ignore[attr-defined]
    response = client.get(created.json()["url"])  # type: ignore[attr-defined]
    assert response.headers["content-disposition"].startswith("attachment;")


def test_path_in_filename_is_discarded(client: TestClient, space: str, page_id: str) -> None:
    created = upload(client, space, page_id, "../../etc/pass\x00wd\r\n.txt", b"hello")
    name = created.json()["filename"]  # type: ignore[attr-defined]
    assert name.startswith("pass") and name.endswith(".txt")
    assert not any(char in name for char in ("/", "\\", "\x00", "\r", "\n", "%"))


def test_oversized_upload_is_rejected(
    client: TestClient, space: str, page_id: str, settings: Settings
) -> None:
    response = upload(client, space, page_id, "big.txt", b"a" * (settings.max_attachment_bytes + 1))
    assert response.status_code == 413  # type: ignore[attr-defined]


def test_attachment_access_follows_the_page(
    client: TestClient, ctx: AppContext, space: str, page_id: str
) -> None:
    url = upload(client, space, page_id, "a.txt", b"hello").json()["url"]  # type: ignore[attr-defined]
    viewer = make_user(ctx, "vera")
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        sign_in(other, make_user(ctx, "mallory"))
        assert other.get(url).status_code == 404
    from app.models import SpaceMember  # noqa: PLC0415
    from app.repositories import spaces as space_repo  # noqa: PLC0415

    with ctx.sessions() as db:
        found = space_repo.get_by_key(db, space)
        assert found is not None
        db.add(
            SpaceMember(
                space_id=found.id, principal_type="user", principal_id=viewer.id, role="viewer"
            )
        )
        db.commit()
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        sign_in(other, viewer)
        assert other.get(url).status_code == 200
        assert write(other, "DELETE", url).status_code == 403
    write(client, "DELETE", f"/api/v1/spaces/{space}/pages/{page_id}")
    assert client.get(url).status_code == 404


def test_delete_removes_the_file(
    client: TestClient, space: str, page_id: str, settings: Settings
) -> None:
    upload(client, space, page_id, "a.txt", b"hello")
    assert len(list(settings.attachments_dir.iterdir())) == 1
    attachment = client.get(f"/api/v1/spaces/{space}/pages/{page_id}/attachments").json()[0]
    assert write(client, "DELETE", attachment["url"]).status_code == 204
    assert list(settings.attachments_dir.iterdir()) == []


def test_page_export_is_safe_and_rewrites_links(
    client: TestClient, ctx: AppContext, space: str, page_id: str
) -> None:
    attachment = upload(client, space, page_id, "../diagram.png", _png()).json()  # type: ignore[attr-defined]
    page = client.get(f"/api/v1/spaces/{space}/pages/{page_id}").json()
    write(
        client,
        "PUT",
        f"/api/v1/spaces/{space}/pages/{page_id}",
        json={
            "title": "Guide",
            "body": f"See [[Docs]] and ![d]({attachment['url']}) and [[Missing]].",
        },
        headers={"If-Match": f'"{page["revision_id"]}"'},
    )
    response = client.get(f"/api/v1/spaces/{space}/export", params={"page": page_id})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        body = archive.read("guide.md").decode()
    assert all(re.fullmatch(r"[a-z0-9/_.() -]+", n) and ".." not in n.split("/") for n in names), (
        names
    )
    assert any(n.startswith("_attachments/") and n.endswith("diagram.png") for n in names)
    assert "../" not in body.replace("_attachments", "")
    assert "](_attachments/" in body
    assert "Missing" in body and "[[" not in body
    with ctx.sessions() as db:
        assert "page.exported" in db.scalars(select(AuditEvent.action)).all()


def test_space_export_requires_recent_authentication(
    client: TestClient, ctx: AppContext, space: str, page_id: str
) -> None:
    response = client.get(f"/api/v1/spaces/{space}/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"docs.md", "guide.md"}
    with ctx.sessions() as db:
        db.execute(update(AuthSession).values(reauth_at=datetime.now(UTC) - timedelta(hours=1)))
        db.commit()
    assert client.get(f"/api/v1/spaces/{space}/export").status_code == 401


def test_outsiders_cannot_export(
    client: TestClient, ctx: AppContext, space: str, page_id: str
) -> None:
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        sign_in(other, make_user(ctx, "mallory"))
        assert other.get(f"/api/v1/spaces/{space}/export").status_code == 404
        assert (
            other.get(f"/api/v1/spaces/{space}/export", params={"page": page_id}).status_code == 404
        )


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, "PNG")
    return buffer.getvalue()
