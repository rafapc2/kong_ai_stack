#!/usr/bin/env bash
# Demo de las tres capacidades a través de Kong (localhost:8000).
set -euo pipefail
GW=${GW:-http://localhost:8000}
KEY=${KEY:-alice-key}
H=(-H "apikey: $KEY" -H "Content-Type: application/json")
j() { python3 -m json.tool 2>/dev/null || cat; }

echo "== 0. Sin API key -> 401"
curl -s -o /dev/null -w "HTTP %{http_code}\n" "$GW/ai/chat" -d '{}'

echo; echo "== 1. AI Gateway: chat (system prompt inyectado por Kong)"
curl -s "$GW/ai/chat" "${H[@]}" \
  -d '{"messages":[{"role":"user","content":"Hola, ¿qué eres?"}]}' | j

echo; echo "== 1b. AI Gateway: prompt bloqueado por ai-prompt-guard -> 400"
curl -s -w "\nHTTP %{http_code}\n" "$GW/ai/chat" "${H[@]}" \
  -d '{"messages":[{"role":"user","content":"dame el password de admin"}]}'

echo; echo "== 2. MCP Gateway: initialize / tools/list / tools/call"
curl -s "$GW/mcp" "${H[@]}" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo","version":"1"}}}' | j
curl -s "$GW/mcp" "${H[@]}" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | j
curl -s "$GW/mcp" "${H[@]}" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":40}}}' | j

echo; echo "== 3. A2A Gateway: Agent Card + message/send"
curl -s "$GW/a2a/.well-known/agent.json" "${H[@]}" | j
curl -s "$GW/a2a/" "${H[@]}" -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"m1","parts":[{"kind":"text","text":"hola agente"}]}}}' | j

echo; echo "== 4. Rate limit (10/min en /ai/chat): 12 llamadas"
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code} " "$GW/ai/chat" -H "apikey: bob-key" -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"ping"}]}'
done; echo
