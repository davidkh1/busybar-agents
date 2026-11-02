"""A control panel for the bar in the browser.

    busybar-agents panel            # http://127.0.0.1:8765

Both screens live, the hands, the wheel switch, the settings in effect and
the event log as it grows. Every verb can be sent from the page, and the
wheel and buttons can be pressed from software, so ASK and GO can be tried
without an agent. A standard-library HTTP server; busylib does the talking.
It listens on localhost and refuses cross-origin POSTs.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import threading
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .bar import Bar
from .cli import build_parser, execute
from .config import Config
from .log import Cursor, log_path, read, record
from .state import HandsFile, WheelFile

FRONT, BACK = 0, 1
SIZES = {FRONT: (72, 16), BACK: (160, 80)}
FRAME_PERIOD = {FRONT: 0.25, BACK: 1.0}  # seconds between reads of each screen
STATUS_PERIOD = 5.0
HISTORY = 200  # events a freshly opened page starts with
VERBS = ("hello", "raise", "lower", "done", "redraw", "clear", "ask", "choose", "wheel")
EXTRA_ARGS = {"raise": ("reason",), "done": ("message",), "ask": ("question", "detail", "timeout"), "choose": ("title", "options", "timeout")}
KEYS = ("up", "down", "ok", "back", "start")  # wheel steps and the three buttons


def argv_for(body: dict[str, Any]) -> list[str]:
    """The command line for a request from the page; the parser then checks it as it would a shell's."""
    verb = body.get("verb")
    if verb not in VERBS:
        raise ValueError(f"verb must be one of {', '.join(VERBS)}")
    if verb == "wheel":
        return [verb, str(body.get("state") or "status")]
    argv = [verb]
    if verb in ("redraw", "clear"):
        return argv
    for key in ("agent", "session", "project", "color", *EXTRA_ARGS.get(verb, ())):
        value = body.get(key)
        if key == "options":
            argv += [piece for option in value or [] if str(option).strip() for piece in ("--option", str(option).strip())]
        elif key == "timeout":
            if value:
                argv += ["--timeout", str(int(value))]
        elif value not in (None, ""):
            argv += [f"--{key}", str(value)]
    return argv


def parse_argv(argv: list[str]):
    try:
        return build_parser().parse_args(argv)
    except SystemExit as err:  # argparse has printed why
        raise ValueError(f"bad arguments: {' '.join(argv)}") from err


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class Poller(threading.Thread):
    """Reads the screens and the status while a page is watching, and shares the latest copy."""

    def __init__(self, cfg: Config):
        super().__init__(name="busybar-panel-poller", daemon=True)
        self.cfg = cfg
        self.lock = threading.Lock()
        self.watchers = 0
        self.frames: dict[int, tuple[int, bytes]] = {}  # display -> (version, rgb)
        self.status: dict[str, Any] = {"reachable": False}
        self.inputs: list[dict[str, Any]] = []  # recent wheel and button events
        self.watch_inputs = False
        self.version = 0

    def watch(self, delta: int) -> None:
        with self.lock:
            self.watchers += delta

    def snapshot(self) -> tuple[dict[str, Any], dict[int, tuple[int, bytes]], list[dict[str, Any]]]:
        with self.lock:
            return dict(self.status), dict(self.frames), list(self.inputs)

    def run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        while True:
            if self.watchers <= 0:
                await asyncio.sleep(0.5)
                continue
            try:
                async with Bar(self.cfg) as bar:
                    await self._session(bar)
            except Exception as err:
                self._set_status({"reachable": False, "error": f"{type(err).__name__}: {err}", "checked": time.time()})
                await asyncio.sleep(2)

    async def _session(self, bar: Bar) -> None:
        due: dict[Any, float] = {"status": 0.0, FRONT: 0.0, BACK: 0.0}
        pump: asyncio.Task | None = None
        try:
            while self.watchers > 0:
                now = time.monotonic()
                if now >= due["status"]:
                    info = await bar.snapshot()
                    self._set_status({**info, "reachable": True, "checked": time.time()})
                    due["status"] = now + STATUS_PERIOD
                for display in (FRONT, BACK):
                    if now >= due[display]:
                        self._set_frame(display, await bar.screen(display))
                        due[display] = now + FRAME_PERIOD[display]
                if pump is not None and pump.done():
                    pump = None
                if self.watch_inputs and pump is None:
                    pump = asyncio.create_task(self._pump(bar))
                elif not self.watch_inputs and pump is not None:
                    pump.cancel()
                    pump = None
                await asyncio.sleep(0.05)
        finally:
            if pump is not None:
                pump.cancel()

    async def _pump(self, bar: Bar) -> None:
        """Wheel, buttons and selector from the bar's status stream, while the page asks for them."""
        events = importlib.import_module("busylib.features.input_events")
        try:
            async for message in bar.client.stream_status_ws():
                if not isinstance(message, dict):
                    continue
                for event in events.input_events(message):
                    if isinstance(event, events.EncoderEvent):
                        self._add_input("wheel", "forward" if event.delta > 0 else "back", delta=event.delta)
                    elif isinstance(event, events.ButtonEvent):
                        self._add_input("button", f"{event.button} {event.action}")
                    else:
                        self._add_input("selector", str(getattr(event, "position", "?")))
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self._add_input("stream", f"ended: {type(err).__name__}: {err}")
            await asyncio.sleep(2)

    def _set_status(self, status: dict[str, Any]) -> None:
        with self.lock:
            self.status = status

    def _set_frame(self, display: int, rgb: bytes) -> None:
        with self.lock:
            old = self.frames.get(display)
            if old is None or old[1] != rgb:
                self.version += 1
                self.frames[display] = (self.version, rgb)

    def _add_input(self, kind: str, detail: str, **extra: Any) -> None:
        with self.lock:
            self.version += 1
            self.inputs.append({"seq": self.version, "t": time.time(), "kind": kind, "detail": detail, **extra})
            del self.inputs[:-50]


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], cfg: Config):
        super().__init__(address, Handler)
        self.cfg = cfg
        self.log = log_path(cfg.state_path)
        self.running = True
        self.poller = Poller(cfg)
        self.poller.start()

    def shutdown(self) -> None:
        self.running = False
        super().shutdown()

    def state(self) -> dict[str, Any]:
        cfg = self.cfg
        hands = [hand for hand in HandsFile(cfg.state_path).load() if hand.age < cfg.ttl]
        status, _, _ = self.poller.snapshot()
        return {
            "version": __version__,
            "time": time.time(),
            "config": {
                "addr": cfg.addr, "token": bool(cfg.token), "priority": cfg.priority, "ttl": cfg.ttl,
                "done_seconds": cfg.done_seconds, "hello_seconds": cfg.hello_seconds, "ask_timeout": cfg.ask_timeout,
                "go_seconds": cfg.go_seconds, "sound": cfg.sound, "dry_run": cfg.dry_run,
                "state": str(cfg.state_path), "log": str(self.log),
            },
            "hands": [{**asdict(hand), "age": int(hand.age)} for hand in hands],
            "wheel": {
                "file": WheelFile(cfg.wheel_path).read(),
                "env": {name: os.environ[name] for name in ("BUSYBAR_ASK", "BUSYBAR_GO") if os.environ.get(name, "").strip()},
            },
            "bar": status,
            "watchers": self.poller.watchers,
            "watch_inputs": self.poller.watch_inputs,
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # quiet; the event log is the record
        pass

    @property
    def panel(self) -> PanelServer:
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/":
            self._send(resources.files("busybar_agents").joinpath("panel.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self._json(self.panel.state())
        elif url.path == "/api/log":
            self._json(read(self.panel.log, min(int(query.get("n", ["200"])[0]), 5000)))
        elif url.path == "/api/stream":
            self._stream(min(int(query.get("n", [str(HISTORY)])[0]), 5000))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if not self._same_origin():
            self._json({"ok": False, "error": "cross-origin request refused"}, 403)
            return
        try:
            body = self._body()
        except ValueError as err:
            self._json({"ok": False, "error": str(err)}, 400)
            return
        path = urlparse(self.path).path
        started = time.monotonic()
        try:
            if path == "/api/do":
                result = self._do(body)
            elif path == "/api/input":
                result = self._input(body)
            elif path == "/api/watch":
                self.panel.poller.watch_inputs = bool(body.get("inputs"))
                result = {"inputs": self.panel.poller.watch_inputs}
            else:
                self.send_error(404)
                return
        except ValueError as err:
            self._json({"ok": False, "error": str(err)}, 400)
        except Exception as err:
            self._json({"ok": False, "error": f"{type(err).__name__}: {err}", "ms": elapsed_ms(started)}, 500)
        else:
            self._json({"ok": True, "ms": elapsed_ms(started), **result})

    def _do(self, body: dict[str, Any]) -> dict[str, Any]:
        """A verb from the page, through the same code and log line as the command line."""
        args = parse_argv(argv_for(body))
        return {"result": asyncio.run(execute(args, self.panel.cfg, src="panel"))}

    def _input(self, body: dict[str, Any]) -> dict[str, Any]:
        key = body.get("key")
        if key not in KEYS:
            raise ValueError(f"key must be one of {', '.join(KEYS)}")
        cfg = self.panel.cfg

        async def press() -> list:
            async with Bar(cfg) as bar:
                await bar.press(key)
            return bar.trail

        started, error = time.monotonic(), None
        try:
            trail = asyncio.run(press())
        except Exception as err:
            error = f"{type(err).__name__}: {err}"
            raise
        finally:
            record(self.panel.log, src="panel", verb="press", key=key, ms=elapsed_ms(started), error=error, addr=cfg.addr)
        return {"result": key, "bar": [step["note"] for step in trail]}

    def _stream(self, history: int) -> None:
        """Server-sent events: history, then every new log line, state every 2 s, frames and inputs as they change."""
        panel, poller = self.panel, self.panel.poller
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        cursor = Cursor(panel.log)
        cursor.poll()  # from here on, new lines only; the history below covers what came before
        poller.watch(+1)
        sent_frames: dict[int, int] = {}
        seen_input, last_state = 0, 0.0
        try:
            self._event("history", read(panel.log, history))
            while panel.running:
                for event in cursor.poll():
                    self._event("log", event)
                status, frames, inputs = poller.snapshot()
                for display, (version, rgb) in frames.items():
                    if sent_frames.get(display) != version:
                        width, height = SIZES[display]
                        self._event("frame", {"display": display, "width": width, "height": height, "rgb": base64.b64encode(rgb).decode("ascii")})
                        sent_frames[display] = version
                for item in inputs:
                    if item["seq"] > seen_input:
                        self._event("input", item)
                        seen_input = item["seq"]
                if time.monotonic() - last_state >= 2:
                    self._event("state", panel.state())
                    last_state = time.monotonic()
                time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            poller.watch(-1)

    def _event(self, name: str, data: Any) -> None:
        self.wfile.write(f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n".encode("utf-8"))

    def _same_origin(self) -> bool:
        """Browsers send Origin on POST; it must be this page. Scripts without one are welcome."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin.rstrip("/") == f"http://{self.headers.get('Host', '')}"

    def _body(self) -> dict[str, Any]:
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ValueError("send application/json")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 65536:
            raise ValueError("request too large")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("send a JSON object")
        return data

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(json.dumps(data, default=str).encode("utf-8"), "application/json", status)


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    server = PanelServer((host, port), cfg)
    url = f"http://{host}:{server.server_port}/"
    print(f"busybar-agents panel: {url}", flush=True)
    print(f"  bar {cfg.addr}{' (dry run)' if cfg.dry_run else ''}; log {log_path(cfg.state_path)}; Ctrl-C stops", flush=True)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, [url]).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print()
    finally:
        server.running = False
        server.server_close()
    return 0
