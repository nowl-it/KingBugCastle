"""Deployment launchers must preserve operator-owned OAuth configuration."""
import importlib.util
import sys
from pathlib import Path

import preflight


_SERVER = Path(__file__).resolve().parent.parent


def test_public_launcher_does_not_override_glogin_public_url_from_server_env():
    script = (_SERVER / "serve_public.sh").read_text(encoding="utf-8")
    assert 'export GLOGIN_PUBLIC_URL="${GLOGIN_PUBLIC_URL:-https://kingbugcastle.id.vn}"' in script
    assert 'export GLOGIN_PUBLIC_URL="https://kingbugcastle.id.vn"' not in script


def test_preflight_refuses_the_google_dev_login_bypass(monkeypatch):
    monkeypatch.setenv("GLOGIN_DEV", "1")
    monkeypatch.delenv("KGC_ADOPT_LONE_SAVE", raising=False)
    monkeypatch.delenv("KGC_MULTIPLAYER", raising=False)
    previous = preflight._results[:]
    try:
        preflight._results.clear()
        preflight.check_dev_backdoors()
        assert (preflight.FAIL, "GLOGIN_DEV=1") == tuple(preflight._results[0][:2])
    finally:
        preflight._results[:] = previous


def test_preflight_reads_an_explicit_deployment_env_without_executing_shell(tmp_path, monkeypatch):
    config = tmp_path / "server.env"
    marker = tmp_path / "must-not-run"
    config.write_text(
        f"GLOGIN_STATE_SECRET=local-secret\n"
        f"PREFLIGHT_SHELL_FRAGMENT=$(touch {marker})\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KGC_ENV_FILE", str(config))
    monkeypatch.setenv("GLOGIN_STATE_SECRET", "stale-shell-value")
    monkeypatch.delenv("PREFLIGHT_SHELL_FRAGMENT", raising=False)
    preflight.load_deployment_env()
    assert preflight._env("GLOGIN_STATE_SECRET") == "local-secret"
    assert preflight._env("PREFLIGHT_SHELL_FRAGMENT") == f"$(touch {marker})"
    assert not marker.exists()


def _development_launcher():
    spec = importlib.util.spec_from_file_location("kgc_dev_launcher", _SERVER / "run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_development_launcher_binds_loopback_unless_lan_access_is_explicit(monkeypatch):
    launcher = _development_launcher()
    monkeypatch.delenv("KGC_DEV_BIND_HOST", raising=False)
    services = launcher.build_services()
    assert not (_SERVER / "run.sh").exists()
    assert len(services) == 4
    assert all(isinstance(service.command, list) for service in services)
    for service in services[:3]:
        host = service.command.index("--host")
        assert service.command[host + 1] == "127.0.0.1"
    assert "--config.verify-deps-before-run=false" in services[3].command
    host = services[3].command.index("--hostname")
    assert services[3].command[host + 1] == "127.0.0.1"

    monkeypatch.setenv("KGC_DEV_BIND_HOST", "0.0.0.0")
    services = launcher.build_services()
    for service in services[:3]:
        host = service.command.index("--host")
        assert service.command[host + 1] == "0.0.0.0"
    host = services[3].command.index("--hostname")
    assert services[3].command[host + 1] == "0.0.0.0"


def test_development_launcher_stops_the_process_group_it_started(tmp_path):
    launcher = _development_launcher()
    service = launcher.Service(
        "Probe", 0, [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path, tmp_path / "probe.log", "",
    )
    service.start()
    try:
        assert service.running
    finally:
        service.stop()
    assert not service.running


def test_development_launcher_uses_windows_process_groups(monkeypatch):
    launcher = _development_launcher()
    monkeypatch.setattr(launcher, "IS_WINDOWS", False)
    assert launcher._process_group_options() == {"start_new_session": True}

    monkeypatch.setattr(launcher, "IS_WINDOWS", True)
    assert launcher._process_group_options() == {
        "creationflags": launcher.CREATE_NEW_PROCESS_GROUP,
    }

    class Process:
        pid = 123
        sent_signal = None

        def send_signal(self, value):
            self.sent_signal = value

    process = Process()
    launcher._signal_process_group(process)
    assert process.sent_signal == launcher.CTRL_BREAK_EVENT

    calls = []

    def taskkill(command, **_kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(launcher.subprocess, "run", taskkill)
    launcher._signal_process_group(process, force=True)
    assert calls == [["taskkill", "/PID", "123", "/T", "/F"]]


def test_windows_runtime_dependencies_are_conditional():
    requirements = (_SERVER.parent / "requirements.txt").read_text(encoding="utf-8")
    assert 'windows-curses>=2.4.1; sys_platform == "win32"' in requirements
    assert 'gunicorn>=21.2.0; sys_platform != "win32"' in requirements


def test_public_caddy_serves_the_game_through_domain_and_origin_ip_safely():
    caddy = (_SERVER.parent / "systemd" / "kgc-public.Caddyfile").read_text(encoding="utf-8")
    assert "http://213.35.110.245" in caddy
    assert "https://213.35.110.245" in caddy
    assert "@from_cloudflared remote_ip private_ranges" in caddy
    assert "header_up -CF-Connecting-IP" in caddy
    assert "header_up X-Forwarded-For {remote_host}" in caddy


def test_public_xapk_polls_origin_caddy_port_80_while_local_builder_keeps_8080_default():
    workflow = (_SERVER.parent / ".github" / "workflows" / "build-xapk.yml").read_text(encoding="utf-8")
    builder = (_SERVER / "builders" / "build_private.py").read_text(encoding="utf-8")
    assert 'default: "80"' in workflow
    assert "GLOGIN_POLL_PORT: ${{ github.event.inputs.glogin_poll_port }}" in workflow
    assert 'GLOGIN_POLL_PORT = os.environ.get("GLOGIN_POLL_PORT", "8080")' in builder


def test_native_poll_port_is_patched_relative_to_the_browser_host_buffer():
    builder = (_SERVER / "builders" / "build_private.py").read_text(encoding="utf-8")
    stub = (_SERVER / "xigncode_stub" / "arm64" / "libxigncode.so").read_bytes()
    host = stub.find(b"127.0.0.1\0")
    assert host >= 0
    assert stub[host + 64:host + 80].split(b"\0", 1)[0] == b"8080"
    # The binary also contains an unrelated `8080`; a global find would corrupt it.
    assert stub.count(b"8080\0") > 1
    assert "port_start = idx + 64" in builder
    assert "stub_padded.find(old_port_pattern)" not in builder
