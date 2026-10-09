"""Agente de soporte: orquesta AI Gateway + MCP Gateway + A2A Gateway.

Cada paso es una petición HTTP real a Kong; se registra en una línea de tiempo
(ruta, estado, latencia, X-Request-Id, rate limit restante) que la UI dibuja.
Planificación por reglas (determinista) para funcionar con el LLM falso; el LLM
se usa para redactar la respuesta final.
"""
import json, os, re, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY = os.environ.get("GATEWAY", "http://localhost:8000")
KEYS = {"alice": os.environ.get("KEY_ALICE", "alice-key"),
        "bob": os.environ.get("KEY_BOB", "bob-key")}
HERE = os.path.dirname(os.path.abspath(__file__))


class Trace:
    def __init__(self, consumer):
        self.key, self.consumer, self.events, self._id = KEYS[consumer], consumer, [], 0

    def call(self, gw, label, path, body=None, method="POST"):
        """Llama a Kong, registra el evento y devuelve (status, json|None)."""
        self._id += 1
        req = urllib.request.Request(
            GATEWAY + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"apikey": self.key, "Content-Type": "application/json"})
        t0 = time.time()
        try:
            r = urllib.request.urlopen(req, timeout=15)
            status, raw, hdr = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw, hdr = e.code, e.read(), e.headers
        except Exception as e:  # Kong inaccesible
            status, raw, hdr = 0, str(e).encode(), {}
        ms = round((time.time() - t0) * 1000)
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        err = status >= 400 or status == 0
        detail = (data or {}).get("message") if err and isinstance(data, dict) else None
        self.events.append({
            "n": self._id, "gateway": gw, "label": label, "method": method, "path": path,
            "status": status, "ms": ms, "ok": not err,
            "request_id": hdr.get("X-Request-Id", ""),
            "ratelimit_remaining": hdr.get("X-RateLimit-Remaining-Minute", ""),
            "consumer": self.consumer,
            "detail": detail or (raw.decode("utf-8", "replace")[:160] if err else ""),
        })
        return status, data


def mcp(t, label, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    st, data = t.call("mcp", label, "/mcp", body)
    return (data or {}).get("result") if st == 200 else None


def run(question, consumer):
    t = Trace(consumer)
    notes = []   # hechos recogidos para el LLM
    q = question.lower()

    # --- MCP: descubrir tools ---
    mcp(t, "initialize", "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                        "clientInfo": {"name": "support-agent", "version": "1"}})
    tools = mcp(t, "tools/list", "tools/list", rid=2)
    available = {x["name"] for x in (tools or {}).get("tools", [])}

    # --- MCP: tools según la intención ---
    nums = [float(x) if "." in x else int(x) for x in re.findall(r"-?\d+(?:\.\d+)?", question)]
    if "add" in available and len(nums) >= 2 and re.search(r"suma|\+|cu[aá]nto es|total", q):
        r = mcp(t, "tools/call add", "tools/call",
                {"name": "add", "arguments": {"a": nums[0], "b": nums[1]}}, rid=3)
        if r:
            notes.append(f"{nums[0]} + {nums[1]} = {r['content'][0]['text']}")
    if "get_time" in available and re.search(r"hora|fecha|time", q):
        r = mcp(t, "tools/call get_time", "tools/call", {"name": "get_time", "arguments": {}}, rid=4)
        if r:
            notes.append(f"hora UTC actual: {r['content'][0]['text']}")

    # --- A2A: delegar si hay que abrir un ticket ---
    if re.search(r"ticket|incidencia|problema|error|escala|ayuda|soporte", q):
        st, card = t.call("a2a", "descubrir Agent Card", "/a2a/.well-known/agent.json", method="GET")
        if st == 200:
            st, data = t.call("a2a", f"message/send → {card.get('name', 'agente')}", "/a2a/", {
                "jsonrpc": "2.0", "id": 1, "method": "message/send",
                "params": {"message": {"kind": "message", "role": "user", "messageId": "m1",
                                       "parts": [{"kind": "text", "text": question}]}}})
            if st == 200 and data and "result" in data:
                notes.append(data["result"]["parts"][0]["text"])

    # --- AI Gateway: redactar la respuesta final ---
    ctx = "\n".join(notes) if notes else "(sin datos de herramientas)"
    st, data = t.call("ai", "chat completion", "/ai/chat", {
        "messages": [{"role": "user", "content": f"{question}\n[CONTEXT]\n{ctx}"}]})
    if st == 200 and data:
        answer = data["choices"][0]["message"]["content"]
    elif st == 400:
        answer = "🛡️ El AI Gateway bloqueó esta consulta (ai-prompt-guard)."
    elif st == 429:
        answer = "⏱️ Límite de peticiones alcanzado (rate-limiting) para este consumidor."
    else:
        answer = f"Error del gateway ({st})."
    return {"answer": answer, "events": t.events}


class H(BaseHTTPRequestHandler):
    def _send(self, code, data, ctype="application/json"):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            return self._send(404, {"error": "not found"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        consumer = body.get("consumer") if body.get("consumer") in KEYS else "alice"
        self._send(200, run(body.get("question", ""), consumer))


ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), H).serve_forever()
