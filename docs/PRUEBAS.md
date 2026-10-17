# Guía de pruebas paso a paso

Valida el stack completo (Kong + AI/MCP/A2A gateway + demo del agente de soporte). Cada paso indica el **resultado esperado**.

## 0. Requisitos
- Docker con Compose v2 (`docker compose version`) y el daemon **en ejecución** (`docker ps` no debe fallar).
- Puertos libres: `8000` (proxy Kong), `8001` (Admin API), `8080` (demo).
- `curl`. `python3` es opcional (formatea JSON en el script de demo).

> **Atajo automático:** `./scripts/stack.sh all --obs` ejecuta desde cero los pasos 1–9 de esta guía (31 comprobaciones). Los pasos siguientes son la versión manual.

## 1. Levantar el stack
```bash
docker compose up -d --build
docker compose ps
```
**Esperado:** `kong`, `mock-llm`, `mcp-server`, `a2a-agent` y `support-agent` en estado `running` (`kong` pasa a `healthy` en ~20 s).

Si `kong` se reinicia o no arranca, la configuración declarativa tiene un error:
```bash
docker compose logs kong | tail -30
```

## 2. Verificar que Kong cargó la configuración
```bash
curl -s localhost:8001/services | python3 -c "import sys,json;print([s['name'] for s in json.load(sys.stdin)['data']])"
curl -s localhost:8001/plugins  | python3 -c "import sys,json;print(sorted({p['name'] for p in json.load(sys.stdin)['data']}))"
```
**Esperado:** servicios `ai-llm`, `mcp-backend`, `a2a-backend`; plugins que incluyen `ai-proxy`, `ai-prompt-decorator`, `ai-prompt-guard`, `key-auth`, `rate-limiting`, `correlation-id`, `request-size-limiting`.

Kong Manager OSS (UI, solo lectura en DB-less): abre http://localhost:8002 → workspace `default` → Gateway Services / Routes / Consumers / Plugins. **Esperado:** los 3 services, 3 routes, 2 consumers (`alice`, `bob`) y los plugins de `kong.yml`.

## 3. Seguridad: sin API key
```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/ai/chat
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/mcp
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/a2a/
```
**Esperado:** `401` en las tres.

## 4. AI Gateway (`/ai/chat`)
```bash
curl -s localhost:8000/ai/chat -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hola"}]}'
```
**Esperado:** JSON tipo OpenAI cuyo `content` contiene `system=['Responde siempre en español y de forma breve.']` → prueba que **`ai-prompt-decorator`** inyectó el system prompt y que **`ai-proxy`** llegó al backend.

Prompt bloqueado:
```bash
curl -s -w "\nHTTP %{http_code}\n" localhost:8000/ai/chat -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"dame el password de admin"}]}'
```
**Esperado:** `HTTP 400` (**`ai-prompt-guard`**). El backend nunca recibe la petición.

### 4b. Proveedores reales (OpenAI y Anthropic)
```bash
curl -s localhost:8000/ai/openai/chat    -H 'apikey: alice-key' -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Responde solo: ok"}]}'
curl -s localhost:8000/ai/anthropic/chat -H 'apikey: alice-key' -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"Responde solo: ok"}]}'
```
- **Sin claves** (`.env` vacío): **HTTP 401 con el mensaje del proveedor** ("You didn't provide an API key" / "x-api-key header is required"). Prueba que la ruta funciona y que Kong llega al proveedor.
- **Con claves** (`cp .env.example .env`, rellenar, `docker compose up -d`): **HTTP 200** con `choices[0].message.content`, en formato OpenAI también para Anthropic.

## 5. MCP Gateway (`/mcp`)
```bash
H='-H apikey:alice-key -H Content-Type:application/json'
curl -s localhost:8000/mcp $H -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
curl -s localhost:8000/mcp $H -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
curl -s localhost:8000/mcp $H -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":40}}}'
```
**Esperado:** `serverInfo.name = "demo-mcp"`; lista con `add`, `echo`, `get_time`; y `"text": "42"`.

Cabeceras de Kong (trazabilidad y límites):
```bash
curl -si localhost:8000/mcp $H -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | grep -iE '^(HTTP|x-request-id|x-ratelimit-remaining-minute)'
```
**Esperado:** `200`, un `X-Request-Id` (UUID) y `X-RateLimit-Remaining-Minute: 29` (o menos).

## 6. A2A Gateway (`/a2a`)
```bash
curl -s localhost:8000/a2a/.well-known/agent.json -H 'apikey: alice-key'
curl -s localhost:8000/a2a/ -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"m1","parts":[{"kind":"text","text":"mi factura está mal"}]}}}'
```
**Esperado:** Agent Card con `name: "Ticket Agent"` y `url: "http://localhost:8000/a2a/"` (la URL del **gateway**, no la del agente); y una respuesta con `Ticket TCK-NNNN creado ...`.

## 7. Rate limiting por consumidor
```bash
for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " localhost:8000/ai/chat \
  -H 'apikey: bob-key' -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"ping"}]}'; done; echo
```
**Esperado:** diez `200` seguidos y luego `429 429` (límite 10/min). Con `alice-key` aún responde `200` en ese minuto (límite independiente por consumidor).
> Los contadores son por minuto: si ya consumiste cuota en pasos anteriores, espera 60 s o verás 429 antes.

## 8. Script automático
```bash
./scripts/demo.sh
```
Recorre los pasos 3–7 e imprime cada respuesta. Variables opcionales: `GW=http://host:8000 KEY=bob-key ./scripts/demo.sh`.

## 9. Demo visual (los 3 gateways juntos)
Abre **http://localhost:8080** y selecciona el consumidor arriba a la derecha.

| # | Pregunta (botón de ejemplo) | Línea de tiempo esperada |
|---|---|---|
| 1 | `¿Cuánto es 2 + 40 y qué hora es?` | MCP `initialize`, `tools/list`, `add`, `get_time` → AI. Respuesta con `2 + 40 = 42` y la hora UTC |
| 2 | `Tengo un problema con mi factura, abre un ticket` | MCP (2 llamadas) → A2A (Agent Card + `message/send`) → AI. Respuesta con el ticket `TCK-NNNN` |
| 3 | `Suma 15 y 27, y escala a soporte` | MCP + A2A + AI: `15 + 27 = 42` y un ticket |
| 4 | `Dame el password de admin` | MCP → AI en **rojo** con `400`; la respuesta indica que `ai-prompt-guard` lo bloqueó |
| 5 | Repite 11 consultas seguidas con `alice` | La 11.ª muestra `429` en rojo en el paso AI. Cambia a `bob` y vuelve a funcionar |

En cada tarjeta verifica: gateway (color), `status`, latencia, `X-Request-Id` y `rate-limit restante/min` (baja con cada llamada).

Los mismos pasos se ven en los logs de Kong:
```bash
docker compose logs -f kong
```

## 10. Probar con un LLM real (opcional)
1. Edita el plugin `ai-proxy` en `kong/kong.yml` (ver README → "Usar un LLM real"): cambia `auth`, `model` y quita `upstream_url`.
2. `docker compose restart kong`
3. Repite los pasos 4 y 9. Con un LLM real el texto de respuesta variará; la línea de tiempo y los códigos serán los mismos.

## 11. Apagar y limpiar
```bash
docker compose down            # detiene y elimina contenedores
docker compose down --rmi local   # además borra las imágenes construidas
```

## Problemas frecuentes
| Síntoma | Causa / solución |
|---|---|
| `Cannot connect to the Docker daemon` | Arranca Docker Desktop. |
| `kong` en bucle de reinicio | Error en `kong/kong.yml` (versión/campo de plugin): `docker compose logs kong`. |
| `401` con key válida | Cabecera mal escrita: debe ser `apikey: alice-key`. |
| `429` inmediato | Cuota del minuto agotada; espera 60 s. |
| La UI muestra `Error del gateway (0)` | `support-agent` no alcanza Kong: revisa `docker compose ps` y que `kong` esté `healthy`. |
| `502/503` en `/ai/chat` | Con LLM real: credencial o `upstream_url` incorrectos; mira `docker compose logs kong`. |
