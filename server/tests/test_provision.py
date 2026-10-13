import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from powerk.api import REPO_ROOT


def args(**changes):
    values = dict(ip="192.0.2.1", ssid="Home WiFi", password="password", host="127.0.0.1", wait=0)
    values.update(changes)
    return SimpleNamespace(**values)


@contextmanager
def setup_service(replies):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(3)
    commands = []
    def serve():
        for reply in replies:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(3)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                if data:
                    commands.append(data)
                if reply is not None:
                    conn.sendall(reply[:5])
                    conn.sendall(reply[5:])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(serve)
        try:
            yield listener.getsockname()[1], commands
            pending.result(timeout=4)
        finally:
            listener.close()


def test_provision_real_setup_socket(provision, monkeypatch, capsys):
    with setup_service([None, b"up:ip:ip_ok\r\n", b"up:connect:connect_ok\r\n"]) as (port, commands):
        monkeypatch.setattr(provision, "SETUP_PORT", port)
        assert provision.cmd_provision(args()) == 0
    assert commands == [b"up:ip:192.0.2.1\r\n", b"up:connect:Home WiFi:password\r\n"]
    assert capsys.readouterr().out == (
        f"Looking for the strip's setup service at 127.0.0.1:{port} ...\n"
        "  up:ip:ip_ok\n  up:connect:connect_ok\n"
        "\nDone. Reconnect this PC to your home Wi-Fi and start `python powerk.py`.\n"
        "The strip will connect to 192.0.2.1:10086 shortly.\n"
    )


def test_setup_reply_validation(provision, monkeypatch):
    with setup_service([b"unexpected\r\n"]) as (port, commands):
        monkeypatch.setattr(provision, "SETUP_PORT", port)
        with pytest.raises(SystemExit, match="strip answered 'unexpected', expected 'up:ip:ip_ok'"):
            provision.setup_command("up:ip:192.0.2.1", "up:ip:ip_ok", "127.0.0.1")
    assert commands == [b"up:ip:192.0.2.1\r\n"]


@pytest.mark.parametrize("field,value", [("ssid", "x:y"), ("ssid", "x\ny"), ("password", "x\ry"), ("password", "x:y")])
def test_rejected_credentials(provision, field, value):
    with pytest.raises(SystemExit, match="cannot use ':' or newlines"):
        provision.cmd_provision(args(**{field: value}))


def test_missing_ip_guidance_matches_legacy(provision, legacy, monkeypatch, capsys):
    for module in (provision, legacy):
        monkeypatch.setattr(module, "local_ipv4s", lambda: ["192.0.2.5", "192.0.2.6"])
    assert legacy.cmd_provision(args(ip=None)) == 2
    expected = capsys.readouterr().out
    assert provision.cmd_provision(args(ip=None)) == 2
    assert capsys.readouterr().out == expected


def test_unreachable_setup_guidance(provision, monkeypatch, capsys):
    def unreachable(*args, **kwargs):
        raise OSError("unreachable")
    monkeypatch.setattr(provision.socket, "create_connection", unreachable)
    clock = iter([0, 1])
    monkeypatch.setattr(provision.time, "monotonic", lambda: next(clock))
    assert provision.cmd_provision(args()) == 1
    output = capsys.readouterr().out
    assert "Not reachable. Do this first:" in output
    assert "TONLY_TAP_XXXXXXX" in output and "LGU_XXXXXXX" in output
    assert "  3. re-run this command\n" in output


@pytest.mark.parametrize("prefix", [[], ["provision"]])
def test_both_cli_forms(provision, prefix):
    result = subprocess.run([sys.executable, str(REPO_ROOT / "tools/provision.py"), *prefix,
                             "--ip", "invalid", "--ssid", "wifi", "--password", "password"],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "--ip must be an IPv4 address (got 'invalid')"
