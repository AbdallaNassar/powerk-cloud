import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest

from powerk.devices import parse_macs
from powerk.security import parse_trusted_proxies

runner = importlib.import_module("powerk.main")


@pytest.mark.parametrize("argv", [[], ["serve"]])
def test_cli_defaults(monkeypatch, argv):
    monkeypatch.delenv('POWERK_FCM_SERVICE_ACCOUNT', raising=False)
    observed = []
    async def serve(args):
        observed.append(vars(args))
        return 0
    monkeypatch.setattr(runner, "cmd_serve", serve)
    monkeypatch.setattr(sys, "argv", ["powerk", *argv])
    assert runner.main() == 0
    assert {k: v for k, v in observed[0].items() if k != "cmd"} == {
        "port": 10086, "web_port": 8080, "ip": None, "token": "", "mac": [], "data": None, "apk": None,
        "secure_cookies": False, "open_registration": True, "trusted_proxy": [], "fcm_service_account": None,
    }


def test_cli_options_and_mac_forms(monkeypatch):
    async def serve(args):
        assert (args.port, args.web_port, args.ip, args.token, args.data, args.apk) == (18086, 18080, "192.0.2.1", "secret", "data", "custom.apk")
        assert parse_macs(args.mac) == {"AABBCCDDEEFF", "112233445566", "778899AABBCC"}
        assert args.secure_cookies is True and args.open_registration is False
        assert len(parse_trusted_proxies(args.trusted_proxy)) == 3
        return 0
    monkeypatch.setattr(runner, "cmd_serve", serve)
    monkeypatch.setattr(sys, "argv", ["powerk", "serve", "--port", "18086", "--web-port", "18080", "--ip", "192.0.2.1",
                                      "--token", "secret", "--data", "data", "--apk", "custom.apk",
                                      "--mac", "aa:bb:cc:dd:ee:ff,112233445566", "--mac", "77-88-99-aa-bb-cc",
                                      "--secure-cookies", "--no-open-registration",
                                      "--trusted-proxy", "10.0.0.0/8,::1/128", "--trusted-proxy", "192.0.2.0/24"])
    assert runner.main() == 0
    with pytest.raises(SystemExit, match="--mac needs 12 hex digits"):
        parse_macs(["invalid"])


@pytest.mark.parametrize('argv,expected', [([], 'env.json'), (['serve'], 'env.json'),
                                         (['serve', '--fcm-service-account', 'cli.json'], 'cli.json')])
def test_fcm_cli_environment_and_override(monkeypatch, argv, expected):
    async def serve(args):
        assert args.fcm_service_account == expected
        return 0
    monkeypatch.setenv('POWERK_FCM_SERVICE_ACCOUNT', 'env.json')
    monkeypatch.setattr(runner, 'cmd_serve', serve)
    monkeypatch.setattr(sys, 'argv', ['powerk', *argv])
    assert runner.main() == 0


@pytest.mark.parametrize("open_registration", [False, True])
def test_runner_shares_loop_and_closes_connected_clients(monkeypatch, tmp_path, capsys, open_registration):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "local_ipv4s", lambda: ["192.0.2.1"])
    observed, loops, stopped = {}, {}, set()
    start_server = asyncio.start_server
    async def tcp_server(*args, **kwargs):
        observed["server"] = await start_server(*args, **kwargs)
        loops["tcp"] = asyncio.get_running_loop()
        return observed["server"]
    monkeypatch.setattr(runner.asyncio, "start_server", tcp_server)

    def background(name):
        async def run(self):
            loops[name] = asyncio.get_running_loop()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.add(name)
        return run
    monkeypatch.setattr(runner.Hub, "poll_loop", background("poll"))
    monkeypatch.setattr(runner.Engine, "loop", background("engine"))

    class HTTPServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            assert config.app.state.open_registration is open_registration
            assert config.app.state.secure_cookies is True
            assert config.proxy_headers is False and config.server_header is False
        async def serve(self):
            loops["http"] = asyncio.get_running_loop()
            port = observed["server"].sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            observed["reader"], observed["writer"] = reader, writer
            writer.write(b"up:bootinfo:lgutap;AABBCCDDEEFF;001122334455;1;connect\r\n")
            await writer.drain()
            assert await reader.readline() == b"up:getinfo:all\r\n"
            self.should_exit = True
    monkeypatch.setattr(runner.uvicorn, "Server", HTTPServer)

    async def check():
        args = SimpleNamespace(data=None, port=0, web_port=0, mac=[], token="", ip=None, apk=None,
                               secure_cookies=True, open_registration=open_registration)
        assert await asyncio.wait_for(runner.cmd_serve(args), 3) == 0
        assert len(loops) == 4 and len(set(loops.values())) == 1
        assert stopped == {"poll", "engine"}
        assert await asyncio.wait_for(observed["reader"].read(), 1) == b""
        observed["writer"].close()
        await observed["writer"].wait_closed()
    asyncio.run(check())
    assert (tmp_path / "powerk.db").is_file()
    assert (tmp_path / "powerk.json").is_file()
    output = capsys.readouterr().out
    assert f"  data               {tmp_path}" in output
    assert "accounts: every account can control every strip until step 3" not in output
    assert "physical-button claims" in output
    assert "NONE" not in output
