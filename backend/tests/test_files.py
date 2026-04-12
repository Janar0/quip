"""Tests for file upload, download, and delete endpoints."""
import io
import pytest
from io import BytesIO
from unittest.mock import patch, AsyncMock

from quip.services.config import set_setting


def _png_bytes():
    """Create a minimal 1x1 PNG."""
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (1, 1), "red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_image(client, auth_headers, tmp_upload_dir):
    """Upload PNG → response has file_type=image, file exists on disk."""
    set_setting("rag_enabled", "false")
    png = _png_bytes()

    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("test.png", png, "image/png"))],
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["files"]) == 1
    f = data["files"][0]
    assert f["file_type"] == "image"
    assert f["filename"] == "test.png"
    assert f["content_type"] == "image/png"
    assert f["size"] > 0

    # Verify file written to disk
    user_dirs = list(tmp_upload_dir.iterdir())
    assert len(user_dirs) == 1


@pytest.mark.asyncio
async def test_upload_document(client, auth_headers, tmp_upload_dir):
    """Upload text file → classified as document."""
    set_setting("rag_enabled", "false")

    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("notes.txt", b"Hello world", "text/plain"))],
    )
    assert res.status_code == 200
    f = res.json()["files"][0]
    assert f["file_type"] == "document"
    assert f["filename"] == "notes.txt"


@pytest.mark.asyncio
async def test_upload_multiple_files(client, auth_headers, tmp_upload_dir):
    """Upload image + document at once → both returned."""
    set_setting("rag_enabled", "false")

    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[
            ("files", ("a.png", _png_bytes(), "image/png")),
            ("files", ("b.txt", b"some text", "text/plain")),
        ],
    )
    assert res.status_code == 200
    files = res.json()["files"]
    assert len(files) == 2
    assert {f["file_type"] for f in files} == {"image", "document"}


@pytest.mark.asyncio
async def test_download_file(client, auth_headers, tmp_upload_dir):
    """Upload then download via token query param."""
    set_setting("rag_enabled", "false")
    png = _png_bytes()

    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("photo.png", png, "image/png"))],
    )
    file_id = res.json()["files"][0]["id"]
    token = auth_headers["Authorization"].removeprefix("Bearer ")

    res = await client.get(f"/api/files/{file_id}?token={token}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert len(res.content) == len(png)


@pytest.mark.asyncio
async def test_delete_file(client, auth_headers, tmp_upload_dir):
    """Upload then delete → 204, file no longer accessible."""
    set_setting("rag_enabled", "false")

    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("temp.txt", b"delete me", "text/plain"))],
    )
    file_id = res.json()["files"][0]["id"]

    res = await client.delete(f"/api/files/{file_id}", headers=auth_headers)
    assert res.status_code == 204

    # Can't download anymore
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    res = await client.get(f"/api/files/{file_id}?token={token}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_upload_requires_auth(client, tmp_upload_dir):
    """Upload without auth → 403."""
    res = await client.post(
        "/api/files/upload",
        files=[("files", ("x.png", b"fake", "image/png"))],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_document_upload_triggers_background_processing(client, auth_headers, tmp_upload_dir):
    """RAG enabled + document → background embedding task is spawned."""
    set_setting("rag_enabled", "true")

    with patch("quip.routers.files._process_file_background", new_callable=AsyncMock) as mock_bg:
        res = await client.post(
            "/api/files/upload",
            headers=auth_headers,
            files=[("files", ("doc.txt", b"Embed this text", "text/plain"))],
        )
    assert res.status_code == 200
    mock_bg.assert_called_once()


@pytest.mark.asyncio
async def test_image_upload_skips_embedding(client, auth_headers, tmp_upload_dir):
    """Image uploads should not trigger background embedding."""
    set_setting("rag_enabled", "true")

    with patch("quip.routers.files._process_file_background", new_callable=AsyncMock) as mock_bg:
        res = await client.post(
            "/api/files/upload",
            headers=auth_headers,
            files=[("files", ("img.png", _png_bytes(), "image/png"))],
        )
    assert res.status_code == 200
    mock_bg.assert_not_called()


def _jpeg_with_exif_orientation(width=2, height=1, orientation=6):
    """Create a JPEG with EXIF orientation tag (6 = 90° CW → stored WxH displays as HxW)."""
    from PIL import Image
    import io
    import struct

    img = Image.new("RGB", (width, height), "blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_data = buf.getvalue()

    # Build minimal EXIF with orientation tag
    # EXIF structure: APP1 marker + Tiff header + IFD with orientation
    ifd_entry = struct.pack(">HHII", 0x0112, 3, 1, (orientation << 16))  # Tag, SHORT, count=1, value
    ifd = struct.pack(">H", 1) + ifd_entry + struct.pack(">I", 0)  # 1 entry + next IFD offset
    tiff = b"MM" + struct.pack(">HI", 42, 8) + ifd  # Big-endian TIFF header + IFD
    exif_payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif_payload) + 2) + exif_payload

    # Insert APP1 after SOI marker (first 2 bytes)
    return jpeg_data[:2] + app1 + jpeg_data[2:]


@pytest.mark.asyncio
async def test_upload_applies_exif_orientation(client, auth_headers, tmp_upload_dir):
    """JPEG with EXIF orientation 6 (90° CW) → stored file has swapped dimensions."""
    set_setting("rag_enabled", "false")

    # Create 2x1 JPEG with orientation=6 → should become 1x2 after transpose
    jpeg_data = _jpeg_with_exif_orientation(width=2, height=1, orientation=6)

    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("rotated.jpg", jpeg_data, "image/jpeg"))],
    )
    assert res.status_code == 200
    file_id = res.json()["files"][0]["id"]

    # Download and check dimensions
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    res = await client.get(f"/api/files/{file_id}?token={token}")
    assert res.status_code == 200

    from PIL import Image
    img = Image.open(io.BytesIO(res.content))
    # After EXIF transpose of orientation 6: width and height should be swapped
    assert img.size[0] == 1, f"Expected width=1 after 90° rotation, got {img.size[0]}"
    assert img.size[1] == 2, f"Expected height=2 after 90° rotation, got {img.size[1]}"
