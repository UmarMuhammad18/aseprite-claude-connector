"""Local relay between the MCP server and a LIVE Aseprite session.

Aseprite's Lua WebSocket can only dial out, so this hosts the socket it connects to:

  WS   127.0.0.1:9877  <- the Claude Bridge extension, from inside Aseprite.
  HTTP 127.0.0.1:9878  <- the live backend POSTs raw Lua to /exec; it runs against
                          the live app and returns the result. GET /status for health.

Protocol per WS text frame:  request  = "<id>\\n<lua code>"
                             response = "<id>\\nOK\\n<result>"  or  "<id>\\nERR\\n<error>"

The MCP server runs this on a daemon thread, so it lives and dies with the server:
``ensure_running`` is safe to call from several servers, and whichever binds the
ports owns the relay. Logs go to stderr because stdout carries JSON-RPC.

Localhost only, and browsers are refused: /exec is local code execution, and any web
page can send a plain POST to 127.0.0.1. Run standalone: python -m aseprite_claude_connector.relay
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socketserver
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets

WS_PORT, HTTP_PORT = 9877, 9878
MAX_FRAME = 64 * 1024 * 1024

loop = None  # asyncio loop (set in main)
client = None  # current Aseprite websocket connection
client_info = ""  # version string learned from the hello exec
pending = {}  # message id -> Future awaiting the Lua result

# Aseprite retries every few seconds, so one refused client would flood the MCP logs.
logging.getLogger("websockets").setLevel(logging.ERROR)

_lock = threading.Lock()
_thread = None


def log(message: str) -> None:
    print(f"[relay] {message}", file=sys.stderr, flush=True)


async def submit(code: str, timeout: float = 60.0) -> dict:
    """Send one Lua snippet to the connected Aseprite and await its reply."""
    if client is None:
        return {
            "ok": False,
            "error": "Aseprite isn't connected. Open Aseprite with the Claude Bridge "
            "extension installed (run: aseprite-claude-connector setup).",
        }
    mid = uuid.uuid4().hex[:8]
    fut = asyncio.get_running_loop().create_future()
    pending[mid] = fut
    try:
        await client.send(mid + "\n" + code)
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": f"timeout after {timeout}s (a modal dialog may be blocking Aseprite)",
        }
    except Exception as e:
        return {"ok": False, "error": f"send failed: {e}"}
    finally:
        pending.pop(mid, None)


async def hello():
    global client_info
    res = await submit(
        'return "aseprite " .. tostring(app.version) .. " | sprites open: " .. #app.sprites', 15
    )
    client_info = res.get("result", "") if res.get("ok") else f"hello failed: {res.get('error')}"
    log(f"aseprite connected: {client_info}")


async def ws_handler(ws):
    global client, client_info
    client = ws
    log("websocket accepted")
    asyncio.create_task(hello())
    try:
        async for msg in ws:
            mid, _, payload = msg.partition("\n")
            status, _, body = payload.partition("\n")
            fut = pending.get(mid)
            if fut and not fut.done():
                if status == "OK":
                    fut.set_result({"ok": True, "result": body})
                else:
                    fut.set_result({"ok": False, "error": body})
    except websockets.ConnectionClosed:
        pass
    finally:
        if client is ws:
            client = None
            client_info = ""
            log("aseprite disconnected")


class Http(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, code, obj):
        try:
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        except (ConnectionError, OSError):
            pass  # caller (curl) gave up first - harmless

    def _refused(self) -> bool:
        """Turn away browsers: they always send Origin on a cross-site POST, and a
        DNS-rebinding page arrives with its own hostname in Host."""
        host = self.headers.get("Host", "")
        allowed = (f"127.0.0.1:{HTTP_PORT}", f"localhost:{HTTP_PORT}")
        if self.headers.get("Origin") is None and host in allowed:
            return False
        self._json(403, {"ok": False, "error": "refused: browser or foreign host"})
        return True

    def do_GET(self):
        if self._refused():
            return
        if self.path == "/status":
            self._json(200, {"connected": client is not None, "info": client_info})
        else:
            self._json(404, {"ok": False, "error": "unknown path"})

    def do_POST(self):
        if self._refused():
            return
        if self.path != "/exec":
            self._json(404, {"ok": False, "error": "unknown path"})
            return
        n = int(self.headers.get("Content-Length", 0))
        code = self.rfile.read(n).decode("utf-8", "replace")
        fut = asyncio.run_coroutine_threadsafe(submit(code), loop)
        try:
            res = fut.result(70)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        self._json(200, res)


class _HttpServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process share the port, which would hide
    # the fact that a relay is already running.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        # HTTPServer's own version does a reverse DNS lookup that nothing here uses and
        # that can stall startup on a Mac, before the relay is listening.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


async def main(on_ready=None):
    global loop
    loop = asyncio.get_running_loop()
    httpd = _HttpServer(("127.0.0.1", HTTP_PORT), Http)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        # compression=None: refuse permessage-deflate outright - IXWebSocket (Aseprite's
        # client) and python-websockets disagree on it and frames silently vanish.
        # max_size: pixel data for the look tools can exceed the library's 1 MiB default.
        # origins: Aseprite's client sends its own ws:// URL as Origin; browsers only
        # ever send http(s) or null, so no web page can pose as the bridge.
        async with websockets.serve(
            ws_handler,
            "127.0.0.1",
            WS_PORT,
            compression=None,
            max_size=MAX_FRAME,
            origins=[None, f"ws://127.0.0.1:{WS_PORT}"],
        ):
            log(f"listening on 127.0.0.1 (WS {WS_PORT}, HTTP {HTTP_PORT})")
            if on_ready:
                on_ready()
            await asyncio.Future()
    finally:
        httpd.shutdown()
        httpd.server_close()


def ensure_running(timeout: float = 5.0) -> bool:
    """Start the relay on a daemon thread unless this process already has one.
    Returns False if the ports are taken, which normally means another server owns
    the relay: that's fine, and a later call takes over if that server exits."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        ready = threading.Event()

        def run():
            try:
                asyncio.run(main(ready.set))
            except OSError as e:
                log(f"not started here: {e}")
            finally:
                ready.set()

        _thread = threading.Thread(target=run, name="aseprite-relay", daemon=True)
        _thread.start()
        ready.wait(timeout)
        return _thread.is_alive()


if __name__ == "__main__":
    asyncio.run(main())
