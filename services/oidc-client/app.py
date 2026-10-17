"""Mini app web cliente OIDC para probar los gateways /oidc/*.

Flujo: authorization_code + PKCE (S256) contra Keycloak (cliente público mcp-oidc-client). En la pantalla
de login de Keycloak se puede entrar con demo/demo o con Google / GitHub / LinkedIn (si hay claves en .env).
El servidor guarda el token en una sesión en memoria y llama a Kong en nombre del usuario; el navegador nunca
ve el access_token completo en las llamadas, solo los claims. También permite repetir cada llamada SIN token,
con apikey o con un token de máquina, para ver los 401/403 esperados.
"""
import base64, hashlib, json, os, secrets, time, urllib.parse, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY = os.environ.get("GATEWAY", "http://localhost:8000")
KC_PUBLIC = os.environ.get("KC_PUBLIC", "http://localhost:8180/realms/kong-demo")      # lo abre el navegador
KC_INTERNAL = os.environ.get("KC_INTERNAL", "http://keycloak:8080/realms/kong-demo")  # lo usa este servidor
CLIENT_ID = os.environ.get("CLIENT_ID", "mcp-oidc-client")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:8085/callback")
HOME = os.environ.get("HOME_URL", "http://localhost:8085/")
MACHINE = (os.environ.get("MACHINE_CLIENT", "alice-client"), os.environ.get("MACHINE_SECRET", "alice-secret"))
APIKEY = os.environ.get("APIKEY", "alice-key")
HERE = os.path.dirname(os.path.abspath(__file__))
SESSIONS = {}   # sid -> {state, verifier, token, claims, exp}

MSG = lambda t: {"messages": [{"role": "user", "content": t}]}
RPC = lambda m, p=None, i=1: {"jsonrpc": "2.0", "id": i, "method": m, **({"params": p} if p else {})}
TARGETS = {   # nombre -> (método, ruta OIDC, cuerpo)
    "ai": ("POST", "/oidc/ai/chat", MSG("Hola desde la app OIDC")),
    "openai": ("POST", "/oidc/ai/openai/chat", MSG("Responde solo: ok")),
    "anthropic": ("POST", "/oidc/ai/anthropic/chat", MSG("Responde solo: ok")),
    "mcp_list": ("POST", "/oidc/mcp", RPC("tools/list")),
    "mcp_add": ("POST", "/oidc/mcp", RPC("tools/call", {"name": "add", "arguments": {"a": 2, "b": 40}}, 3)),
    "a2a_card": ("GET", "/oidc/a2a/.well-known/agent.json", None),
    "a2a_send": ("POST", "/oidc/a2a/", RPC("message/send", {"message": {"kind": "message", "role": "user", "messageId": "m1",
                 "parts": [{"kind": "text", "text": "mi factura"}]}})),
}


def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def claims_of(jwt):
    p = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def http(method, url, data=None, headers=None):
    req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=20)
        status, raw, hdr = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, raw, hdr = e.code, e.read(), e.headers
    except Exception as e:
        status, raw, hdr = 0, str(e).encode(), {}
    return status, raw, hdr, round((time.time() - t0) * 1000)


def token_request(form):
    s, raw, _, _ = http("POST", KC_INTERNAL + "/protocol/openid-connect/token",
                        urllib.parse.urlencode(form).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return s, json.loads(raw)
    except ValueError:
        return s, {"error": raw.decode(errors="replace")}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def sid(self, create=False):
        c = self.headers.get("Cookie", "")
        sid = next((p.split("=", 1)[1] for p in c.split("; ") if p.startswith("sid=")), None)
        if (not sid or sid not in SESSIONS) and create:
            sid = secrets.token_urlsafe(24); SESSIONS[sid] = {}
        return sid if sid in SESSIONS else None

    def send(self, code, body, ctype="application/json", headers=None):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(raw)

    def redirect(self, url, headers=None):
        self.send_response(302); self.send_header("Location", url)
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/":
            return self.send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
        if u.path == "/login":
            sid = self.sid(True); st = SESSIONS[sid]
            st.update(state=secrets.token_urlsafe(16), verifier=b64(secrets.token_bytes(48)), token=None)
            challenge = b64(hashlib.sha256(st["verifier"].encode()).digest())
            url = KC_PUBLIC + "/protocol/openid-connect/auth?" + urllib.parse.urlencode({
                "client_id": CLIENT_ID, "response_type": "code", "scope": "openid", "redirect_uri": REDIRECT_URI,
                "state": st["state"], "code_challenge": challenge, "code_challenge_method": "S256"})
            return self.redirect(url, {"Set-Cookie": f"sid={sid}; HttpOnly; SameSite=Lax; Path=/"})
        if u.path == "/callback":
            st = SESSIONS.get(self.sid() or "")
            if "error" in q:
                return self.send(400, f"Login rechazado: {q.get('error')} {q.get('error_description', '')}".encode(), "text/plain; charset=utf-8")
            if not st or q.get("state") != st.get("state"):
                return self.send(400, b"state invalido: vuelve a iniciar sesion en /login", "text/plain; charset=utf-8")
            s, tok = token_request({"grant_type": "authorization_code", "client_id": CLIENT_ID, "code": q.get("code", ""),
                                    "redirect_uri": REDIRECT_URI, "code_verifier": st["verifier"]})
            if s != 200 or "access_token" not in tok:
                return self.send(400, f"Error canjeando el codigo: {tok}".encode(), "text/plain; charset=utf-8")
            st["token"], st["claims"] = tok["access_token"], claims_of(tok["access_token"])
            st["id_token"] = tok.get("id_token")
            return self.redirect(HOME)
        if u.path == "/logout":
            st = SESSIONS.pop(self.sid() or "", {})
            url = KC_PUBLIC + "/protocol/openid-connect/logout?" + urllib.parse.urlencode(
                {"client_id": CLIENT_ID, "post_logout_redirect_uri": HOME})
            return self.redirect(url, {"Set-Cookie": "sid=; Max-Age=0; Path=/"})
        if u.path == "/api/session":
            st = SESSIONS.get(self.sid() or "", {})
            c = st.get("claims")
            return self.send(200, {"logged_in": bool(st.get("token")), "claims": c,
                                   "expires_in": max(0, c["exp"] - int(time.time())) if c else None})
        self.send(404, {"error": "no encontrado"})

    def do_POST(self):
        if self.path != "/api/call":
            return self.send(404, {"error": "no encontrado"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send(400, {"error": "json invalido"})
        target, mode = req.get("target"), req.get("mode", "user")
        if target not in TARGETS:
            return self.send(400, {"error": "target desconocido"})
        method, path, body = TARGETS[target]
        headers = {"Content-Type": "application/json"}
        if mode == "user":
            tok = SESSIONS.get(self.sid() or "", {}).get("token")
            if not tok:
                return self.send(200, {"mode": mode, "status": 0, "body": "No hay sesion: pulsa 'Iniciar sesion'."})
            headers["Authorization"] = "Bearer " + tok
        elif mode == "machine":
            s, tok = token_request({"grant_type": "client_credentials", "client_id": MACHINE[0], "client_secret": MACHINE[1]})
            headers["Authorization"] = "Bearer " + tok.get("access_token", "")
        elif mode == "apikey":
            headers["apikey"] = APIKEY
        status, raw, hdr, ms = http(method, GATEWAY + path, json.dumps(body).encode() if body is not None else None, headers)
        try:
            out = json.loads(raw)
        except ValueError:
            out = raw.decode(errors="replace")
        keep = {k: hdr.get(k) for k in ("WWW-Authenticate", "X-Request-Id", "X-RateLimit-Remaining-Minute") if hdr and hdr.get(k)}
        self.send(200, {"mode": mode, "request": f"{method} {path}", "status": status, "ms": ms, "headers": keep, "body": out})


ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8085))), H).serve_forever()
