#!/usr/bin/env python3
"""Interactive development stack supervisor for KGC."""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

try:
    import curses
except ImportError:  # Windows gets curses from the conditional runtime dependency.
    curses = None


ROOT = Path(__file__).resolve().parent
TEMP_DIR = Path(tempfile.gettempdir())
LOG_LIMIT_BYTES = 256_000
IS_WINDOWS = os.name == "nt"
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
CTRL_BREAK_EVENT = getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM)


def _executable(name: str, *candidates: Path) -> str:
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which(name) or name


def _process_group_options() -> dict[str, object]:
    if IS_WINDOWS:
        return {"creationflags": CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _signal_process_group(process: subprocess.Popen, force: bool = False) -> None:
    if IS_WINDOWS:
        if not force:
            process.send_signal(CTRL_BREAK_EVENT)
            return
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode and process.poll() is None:
            process.kill()
        return
    os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)


@dataclass
class Service:
    name: str
    port: int
    command: list[str]
    cwd: Path
    log_path: Path
    url: str
    process: subprocess.Popen | None = field(default=None, init=False, repr=False)
    error: str = field(default="", init=False)
    log_offset: int = field(default=0, init=False, repr=False)
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=500), init=False, repr=False)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def status(self) -> str:
        if self.process is not None:
            returncode = self.process.poll()
            if returncode is None:
                return f"RUNNING pid={self.process.pid}"
            return f"EXIT {returncode}"
        if self.error:
            return "FAILED"
        return "STOPPED"

    def start(self) -> None:
        if self.running:
            return
        if self.process is not None:
            self.stop()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.lines.clear()
        self.log_offset = 0
        self.error = ""
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1", "FORCE_COLOR": "0"}
        try:
            with self.log_path.open("w", encoding="utf-8") as log:
                self.process = subprocess.Popen(
                    self.command,
                    cwd=self.cwd,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    **_process_group_options(),
                )
        except OSError as exc:
            self.error = str(exc)
            self.log_path.write_text(f"launcher: {exc}\n", encoding="utf-8")

    def stop(self) -> None:
        process = self.process
        if process is None:
            self.error = ""
            return
        if process.poll() is None:
            try:
                _signal_process_group(process)
            except (OSError, ValueError):
                try:
                    _signal_process_group(process, force=True)
                except (OSError, ValueError):
                    try:
                        process.terminate()
                    except OSError:
                        pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    _signal_process_group(process, force=True)
                except (OSError, ValueError):
                    process.kill()
                process.wait()
        self.process = None
        self.error = ""

    def read_log(self) -> None:
        try:
            size = self.log_path.stat().st_size
            if size < self.log_offset:
                self.log_offset = 0
                self.lines.clear()
            start = self.log_offset
            if start == 0 and size > LOG_LIMIT_BYTES:
                start = size - LOG_LIMIT_BYTES
            with self.log_path.open("rb") as log:
                log.seek(start)
                if start:
                    log.readline()
                data = log.read()
                self.log_offset = log.tell()
        except OSError:
            return
        self.lines.extend(data.decode("utf-8", errors="replace").splitlines())


def build_services() -> list[Service]:
    host = os.environ.get("KGC_DEV_BIND_HOST", "127.0.0.1")
    uvicorn = _executable(
        "uvicorn",
        ROOT.parent / ".venv" / "bin" / "uvicorn",
        ROOT / ".venv" / "bin" / "uvicorn",
        ROOT.parent / ".venv" / "Scripts" / "uvicorn.exe",
        ROOT / ".venv" / "Scripts" / "uvicorn.exe",
    )
    reload_args = [
        "--reload",
        "--reload-dir", ".",
        "--reload-dir", "xml_live",
        "--reload-include", "*.py",
        "--reload-include", "*.json",
        "--reload-include", "*.xml",
        "--reload-exclude", str(ROOT / "state"),
        "--reload-exclude", str(ROOT / "webui-next"),
    ]

    def api(name: str, app: str, port: int, *extra: str) -> Service:
        scheme = "https" if port == 8443 else "http"
        return Service(
            name,
            port,
            [uvicorn, app, "--host", host, "--port", str(port), *extra, *reload_args],
            ROOT,
            TEMP_DIR / {8080: "kgc_server.log", 8443: "kgc_server_tls.log",
                        8081: "kgc_dashboard.log"}[port],
            f"{scheme}://127.0.0.1:{port}",
        )

    services = [
        api("Game HTTP", "server:app", 8080),
        api("Game TLS", "server:app", 8443,
            "--ssl-keyfile", "key.pem", "--ssl-certfile", "cert.pem"),
        api("Admin API", "dashboard:app", 8081),
    ]
    webui = ROOT / "webui-next"
    if webui.is_dir():
        services.append(Service(
            "Next.js", 3000,
            [_executable("pnpm"), "--config.verify-deps-before-run=false", "run", "dev",
             "--hostname", host, "--port", "3000"], webui,
            TEMP_DIR / "kgc_nextjs.log", "http://127.0.0.1:3000",
        ))
    return services


def wire_device() -> str:
    adb = shutil.which("adb")
    serial = os.environ.get("ADB_SERIAL", "localhost:5556")
    if not adb:
        return "adb is not on PATH"
    options = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
               "text": True, "timeout": 5, "check": False}
    try:
        subprocess.run([adb, "connect", serial], **options)
        state = subprocess.run([adb, "-s", serial, "get-state"], **options)
        if state.returncode:
            return f"device {serial} is not connected"
        commands = [
            ["reverse", "tcp:443", "tcp:8443"],
            ["reverse", "tcp:80", "tcp:8080"],
            ["shell", "settings", "put", "global", "http_proxy", ":0"],
        ]
        failed = [args[0] for args in commands
                  if subprocess.run([adb, "-s", serial, *args], **options).returncode]
    except subprocess.TimeoutExpired:
        return f"adb timed out for {serial}"
    if failed:
        return f"device {serial}: failed {', '.join(failed)}"
    return f"device {serial}: 443->8443, 80->8080, proxy cleared"


def validate(services: list[Service]) -> list[str]:
    issues = []
    if curses is None:
        issues.append("Python curses support is unavailable; install server/requirements.txt")
    for service in services:
        executable = service.command[0]
        if not (Path(executable).is_file() or shutil.which(executable)):
            issues.append(f"{service.name}: executable not found: {executable}")
    for filename in ("key.pem", "cert.pem"):
        if not (ROOT / filename).is_file():
            issues.append(f"Game TLS: missing {ROOT / filename}")
    return issues


def _put(screen, y: int, x: int, text: str, style: int = 0) -> None:
    height, width = screen.getmaxyx()
    if y >= height or x >= width - 1:
        return
    try:
        screen.addnstr(y, x, text, width - x - 1, style)
    except curses.error:
        pass


def run_tui(screen, services: list[Service]) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.timeout(200)
    selected = 0
    message = "Starting services..."
    for service in services:
        service.start()
    message = "Services launched; press d to wire an emulator"

    while True:
        current = services[selected]
        current.read_log()
        screen.erase()
        host = os.environ.get("KGC_DEV_BIND_HOST", "127.0.0.1")
        serial = os.environ.get("ADB_SERIAL", "localhost:5556")
        _put(screen, 0, 0, "KGC DEVELOPMENT STACK", curses.A_BOLD)
        _put(screen, 1, 0, f"bind={host}  adb={serial}")
        _put(screen, 2, 0, "j/k select  Enter start/stop  a start all  x stop all  r restart  d device  q quit")

        row = 4
        for index, service in enumerate(services):
            marker = ">" if index == selected else " "
            text = f"{marker} {service.name:<12} :{service.port:<5} {service.status:<19} {service.url}"
            _put(screen, row + index, 0, text, curses.A_REVERSE if index == selected else 0)

        log_top = row + len(services) + 2
        _put(screen, log_top - 1, 0, f"Log: {current.log_path}", curses.A_BOLD)
        available = max(0, screen.getmaxyx()[0] - log_top - 2)
        if available:
            for index, line in enumerate(list(current.lines)[-available:]):
                _put(screen, log_top + index, 0, line.replace("\t", "  "))
        if current.error:
            message = current.error
        _put(screen, screen.getmaxyx()[0] - 1, 0, message, curses.A_BOLD)
        screen.refresh()

        key = screen.getch()
        if key in (ord("q"), ord("Q")):
            return
        if key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(services)
        elif key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(services)
        elif key in (curses.KEY_ENTER, 10, 13):
            if current.running:
                current.stop()
                message = f"Stopped {current.name}"
            else:
                current.start()
                message = f"Started {current.name}"
        elif key == ord("a"):
            for service in services:
                service.start()
            message = "Started all services"
        elif key == ord("x"):
            for service in services:
                service.stop()
            message = "Stopped all services"
        elif key == ord("r"):
            for service in services:
                service.stop()
            for service in services:
                service.start()
            message = "Restarted all services"
        elif key == ord("d"):
            message = wire_device()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate commands without starting services")
    args = parser.parse_args(argv)
    services = build_services()
    issues = validate(services)
    if args.check:
        for service in services:
            print(f"{service.name:<12} :{service.port}  {' '.join(service.command)}")
        if issues:
            print(*[f"ERROR: {issue}" for issue in issues], sep="\n", file=sys.stderr)
            return 1
        print("configuration ok")
        return 0
    if issues:
        parser.error("; ".join(issues))
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("an interactive terminal is required; use --check for validation")

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, interrupt)
    try:
        curses.wrapper(run_tui, services)
    except KeyboardInterrupt:
        return 130
    finally:
        for service in services:
            service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
