#!/usr/bin/env python3
# relay_server.py - local relay between an MCP/agent and a LIVE Aseprite session.
#
# Part of aseprite-live-mcp. This process is the bridge that lets tools drive the
# *running* Aseprite GUI (all open files, unsaved state) - as opposed to headless
# --batch runs against files on disk.
#
#   WS   127.0.0.1:9877  <- aseprite_client/claude-bridge.lua (File > Scripts)
#                           connects here from inside the running Aseprite GUI.
#   HTTP 127.0.0.1:9878  <- an agent POSTs raw Lua to /exec; it runs against the
#                           live app and returns the result. GET /status for health.
#
# Protocol per WS text frame:  request  = "<id>\n<lua code>"
#                              response = "<id>\nOK\n<result>"  or  "<id>\nERR\n<error>"
# Localhost only. Run: python relay_server.py   (needs: pip install websockets)
import asyncio
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets  # pip install websockets

WS_PORT, HTTP_PORT = 9877, 9878
MAX_FRAME = 64 * 1024 * 1024

loop = None  # asyncio loop (set in main)
client = None  # current Aseprite websocket connection
client_info = ""  # version string learned from the hello exec
pending = {}  # message id -> Future awaiting the Lua result


async def submit(code: str, timeout: float = 60.0) -> dict:
    """Send one Lua snippet to the connected Aseprite and await its reply."""
    if client is None:
        return {"ok": False, "error": "aseprite not connected (run File > Scripts > claude-bridge)"}
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
    print(f"[relay] aseprite connected: {client_info}", flush=True)


async def ws_handler(ws):
    global client
    client = ws
    try:
        ext = ws.request.headers.get("Sec-WebSocket-Extensions", "(none)")
        ua = ws.request.headers.get("User-Agent", "(none)")
        print(f"[relay] websocket accepted | extensions offered: {ext} | UA: {ua}", flush=True)
    except Exception:
        print("[relay] websocket accepted", flush=True)
    asyncio.create_task(hello())
    try:
        async for msg in ws:
            one_line = str(msg).replace("\n", "\\n")
            print(f"[relay] frame in: {one_line[:120]}", flush=True)
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
            print("[relay] aseprite disconnected", flush=True)


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

    def do_GET(self):
        if self.path == "/status":
            self._json(200, {"connected": client is not None, "info": client_info})
        else:
            self._json(404, {"ok": False, "error": "unknown path"})

    def do_POST(self):
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


async def main():
    global loop
    loop = asyncio.get_running_loop()
    httpd = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Http)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[relay] HTTP on 127.0.0.1:{HTTP_PORT} (POST /exec, GET /status)", flush=True)
    # compression=None: refuse permessage-deflate outright - IXWebSocket (Aseprite's
    # client) and python-websockets disagree on it and frames silently vanish.
    # max_size: pixel data for the look tools can exceed the library's 1 MiB default.
    async with websockets.serve(
        ws_handler, "127.0.0.1", WS_PORT, compression=None, max_size=MAX_FRAME
    ):
        print(
            f"[relay] WS on 127.0.0.1:{WS_PORT} - waiting for Aseprite (File > Scripts > claude-bridge)",
            flush=True,
        )
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
