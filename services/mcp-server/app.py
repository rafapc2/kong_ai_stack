"""Servidor MCP mínimo (transporte Streamable HTTP, JSON-RPC 2.0) con 3 tools."""
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = {
    "add": ("Suma dos números", {"a": "number", "b": "number"}, lambda a: a["a"] + a["b"]),
    "echo": ("Devuelve el texto recibido", {"text": "string"}, lambda a: a["text"]),
    "get_time": ("Hora UTC actual", {}, lambda a: datetime.now(timezone.utc).isoformat()),
}


def schema(props):
    return {"type": "object", "properties": {k: {"type": v} for k, v in props.items()},
            "required": list(props)}


def handle(req):
    m, p = req.get("method"), req.get("params", {})
    if m == "initialize":
        return {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                "serverInfo": {"name": "demo-mcp", "version": "1.0"}}
    if m == "ping":
        return {}
    if m == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": schema(s)}
                          for n, (d, s, _) in TOOLS.items()]}
    if m == "tools/call":
        _, _, fn = TOOLS[p["name"]]
        return {"content": [{"type": "text", "text": str(fn(p.get("arguments", {})))}]}
    raise KeyError(m)


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj=None):
        data = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if "id" not in req:  # notificación
            return self._send(202)
        try:
            self._send(200, {"jsonrpc": "2.0", "id": req["id"], "result": handle(req)})
        except Exception as e:
            self._send(200, {"jsonrpc": "2.0", "id": req["id"],
                             "error": {"code": -32601, "message": f"error: {e}"}})

    def do_GET(self):  # sin stream SSE de servidor
        self._send(405)


ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
