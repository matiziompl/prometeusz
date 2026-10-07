import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)


def test_upload_lifecycle_and_management():
    # 1. Upload a file using raw bytes
    test_content = b"test payload content for upload"
    test_filename = "quick_test_upload.txt"

    res = client.post(
        "/api/upload",
        content=test_content,
        headers={"x-filename": test_filename, "content-type": "text/plain"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["filename"] == test_filename
    assert data["size"] == len(test_content)

    # 2. List uploads and verify presence
    res_list = client.get("/api/uploads")
    assert res_list.status_code == 200
    uploads = res_list.json()
    assert isinstance(uploads, list)
    item = next((u for u in uploads if u["filename"] == test_filename), None)
    assert item is not None
    assert item["size"] == len(test_content)
    assert "modified" in item
    assert "path" in item

    # 3. Delete the file
    res_del = client.delete(f"/api/uploads/{test_filename}")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # 4. Verify file is gone from list
    res_list_after = client.get("/api/uploads")
    assert res_list_after.status_code == 200
    uploads_after = res_list_after.json()
    assert not any(u["filename"] == test_filename for u in uploads_after)


def test_upload_json_base64():
    import base64
    content = b"base64 test data"
    b64_str = base64.b64encode(content).decode("ascii")

    res = client.post(
        "/api/upload",
        json={"filename": "test_b64.json", "content_base64": b64_str},
        headers={"content-type": "application/json"}
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Cleanup
    client.delete("/api/uploads/test_b64.json")


def test_delete_upload_nonexistent():
    res = client.delete("/api/uploads/non_existent_file_9999.xyz")
    assert res.status_code == 404


def test_delete_upload_path_traversal_protection():
    # Attempt path traversal
    res = client.delete("/api/uploads/..%2F..%2Fetc%2Fpasswd")
    # Path traversal should be rejected (400 from validate_filename or 403/404/405)
    assert res.status_code in (400, 403, 404, 405)


def test_fs_explorer_list_and_read():
    # 1. List directory /workspace
    res = client.get("/api/fs/list?path=/workspace")
    assert res.status_code == 200
    data = res.json()
    assert "current_path" in data
    assert "items" in data
    assert isinstance(data["items"], list)

    # 2. Read existing file
    res_read = client.get("/api/fs/read?path=/workspace/prometeusz/Dockerfile")
    assert res_read.status_code == 200
    file_info = res_read.json()
    assert file_info["filename"] == "Dockerfile"
    assert "FROM node:22-slim" in file_info["content"]

    # 3. Read non-existent file
    res_notfound = client.get("/api/fs/read?path=/workspace/prometeusz/non_existent_file.xyz")
    assert res_notfound.status_code == 404

