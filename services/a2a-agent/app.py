"""Agente A2A mínimo: Agent Card + JSON-RPC `message/send`."""
import json, os, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CARD = {
    "name": "Ticket Agent",
    "description": "Agente de ejemplo que abre tickets de soporte.",
    "url": os.environ.get("PUBLIC_URL", "http://localhost:8000/a2a/"),
    "version": "1.0.0",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": False},
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [{"id": "open-ticket", "name": "Abrir ticket",
                "description": "Crea un ticket de soporte a partir del texto", "tags": ["soporte"]}],
}


class H(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
            return self._json(200, CARD)
        self._json(404, {"error": "not found"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if req.get("method") != "message/send":
            return self._json(200, {"jsonrpc": "2.0", "id": req.get("id"),
                                    "error": {"code": -32601, "message": "method not found"}})
        parts = req["params"]["message"].get("parts", [])
        text = " ".join(p.get("text", "") for p in parts)
        self._json(200, {"jsonrpc": "2.0", "id": req.get("id"), "result": {
            "kind": "message", "role": "agent", "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": f"Ticket TCK-{uuid.uuid4().int % 9000 + 1000} creado (prioridad media): {text}"}]}})


ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
