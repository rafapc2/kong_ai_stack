"""LLM falso compatible con OpenAI (/v1/chat/completions). Sin dependencias ni API keys."""
import json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        msgs = body.get("messages", [])
        user = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
        system = [m["content"] for m in msgs if m.get("role") == "system"]
        if "[CONTEXT]" in user:  # el orquestador adjunta los resultados de tools/agentes
            ctx = user.split("[CONTEXT]", 1)[1].strip()
            text = f"Esto es lo que encontré: {ctx}"
        else:
            text = f"[mock-llm] system={system} | eco: {user}"
        out = json.dumps({
            "id": "chatcmpl-mock", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "mock"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
