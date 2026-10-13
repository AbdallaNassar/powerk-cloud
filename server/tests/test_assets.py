import base64
import re

import pytest

from powerk.api import DEFAULT_APK, REPO_ROOT, WEB_ROOT


@pytest.mark.parametrize("path", ["/", "/index.html"])
def test_page_bytes(client_factory, path):
    with client_factory(token="") as (_, client):
        response = client.get(path)
        assert response.status_code == 200
        assert response.content == (WEB_ROOT / "index.html").read_bytes()
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "cache-control" not in response.headers
        assert "set-cookie" not in response.headers


def test_every_legacy_font_is_bundled_and_served(client_factory, legacy):
    wanted = set(re.findall(r"url\(fonts/([\w.-]+)\)", legacy.PAGE))
    assert wanted == set(legacy.FONT_FILES), wanted ^ set(legacy.FONT_FILES)
    assert all(base64.b64decode(v)[:4] == b"wOF2" for v in legacy.FONT_FILES.values())
    assert {p.name for p in (WEB_ROOT / "fonts").glob("*.woff2")} == wanted
    with client_factory() as (_, client):
        for name, data in legacy.FONT_FILES.items():
            response = client.get("/fonts/" + name)
            expected = base64.b64decode(data)
            assert response.status_code == 200 and response.content == expected
            assert (WEB_ROOT / "fonts" / name).read_bytes() == expected
            assert response.headers["content-type"] == "font/woff2"
            assert response.headers["cache-control"] == "max-age=31536000, immutable"
            assert int(response.headers["content-length"]) == len(expected)


def test_public_downloads_and_apk_override(client_factory, tmp_path):
    assert DEFAULT_APK == REPO_ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    apk = tmp_path / "custom.apk"
    apk.write_bytes(b"test APK bytes")
    with client_factory(token="secret", apk=apk) as (_, client):
        response = client.get("/powerk.py")
        assert response.status_code == 200
        assert response.content == (REPO_ROOT / "tools/provision.py").read_bytes()
        assert response.headers["content-type"] == "text/x-python"
        assert response.headers["content-disposition"] == 'attachment; filename="powerk.py"'
        assert response.headers["cache-control"] == "no-store"  # downloads must not be edge-cached
        response = client.get("/powerk.apk")
        assert response.status_code == 200 and response.content == apk.read_bytes()
        assert response.headers["content-type"] == "application/vnd.android.package-archive"
        assert response.headers["content-disposition"] == 'attachment; filename="powerk.apk"'
        assert response.headers["cache-control"] == "no-store"
    with client_factory(token="secret") as (_, client):
        response = client.get("/powerk.apk")
        assert response.status_code == 404
        assert response.content == b'{"error": "no APK built yet: cd android && gradlew assembleDebug"}'
        assert response.headers["cache-control"] == "no-store"
