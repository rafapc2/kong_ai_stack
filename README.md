# kong_ai_stack

Stack 100 % open source con **Kong Gateway OSS** (modo DB-less, configuración declarativa) que actúa como:

| Gateway | Ruta | Qué hace Kong | Backend de ejemplo |
|---|---|---|---|
| **AI Gateway** | `/ai/chat` | `ai-proxy` (API unificada tipo OpenAI), `ai-prompt-decorator`, `ai-prompt-guard`, auth y rate limit | `mock-llm` (compatible OpenAI, sin API key) |
| **MCP Gateway** | `/mcp` | Punto único de entrada, auth, rate limit, límite de tamaño, correlation-id sobre MCP (Streamable HTTP) | `mcp-server` (tools `add`, `echo`, `get_time`) |
| **A2A Gateway** | `/a2a` | Punto único de entrada, auth, rate limit, correlation-id sobre agentes A2A | `a2a-agent` (Agent Card + `message/send`) |

```
cliente ──(apikey)──► Kong :8000 ─┬─ /ai/chat ─► ai-proxy ─► mock-llm  (o OpenAI/Ollama/...)
                                  ├─ /mcp     ───────────► mcp-server
                                  └─ /a2a     ───────────► a2a-agent
```

## Inicio rápido con el script orquestador

```bash
./scripts/stack.sh all --obs   # parte de cero (limpia, reconstruye, levanta) y ejecuta 31 pruebas
./scripts/stack.sh help        # up | test | demo | status | logs | down | reset | all | urls
```

`stack.sh` comprueba Docker y que los puertos estén libres (8000, 8001, 8002, 8080 y, con `--obs`, 9090, 8090 y 3001), levanta el stack, espera a que cada servicio responda y, con `test`, valida lo mismo que [docs/PRUEBAS.md](docs/PRUEBAS.md) con código de salida ≠ 0 si algo falla. `reset` solo toca contenedores, volúmenes e imágenes de este proyecto.

## Arranque manual

```bash
docker compose up -d --build
./scripts/demo.sh          # recorre las tres funcionalidades
docker compose down
```

Requisitos: Docker + Compose. Proxy en `http://localhost:8000`, Admin API en `http://localhost:8001` (solo localhost).

Credenciales de demo (en `kong/kong.yml`): `alice-key` y `bob-key`, enviadas en la cabecera `apikey` (o un Bearer token de Keycloak: ver [OAuth2](#oauth2-client_credentials-con-keycloak)).

> 📋 **Guía de pruebas paso a paso:** [docs/PRUEBAS.md](docs/PRUEBAS.md)

> 📊 **Dashboard de observabilidad y gobierno (Prometheus + Grafana):** [docs/OBSERVABILIDAD.md](docs/OBSERVABILIDAD.md)

## Kong Manager OSS (UI de administración de Kong)

Con el stack arriba: **http://localhost:8002**. Muestra services, routes, consumers y plugins cargados desde `kong/kong.yml`.

- En modo DB-less (el de este stack) la UI es **solo lectura**: los cambios se hacen editando `kong/kong.yml` y reiniciando Kong. Para editar desde la UI haría falta pasar Kong a modo base de datos (Postgres).
- No incluye analytics de tráfico; para métricas usa el dashboard de Grafana ([docs/OBSERVABILIDAD.md](docs/OBSERVABILIDAD.md)).
- Admin API y Manager solo escuchan en `127.0.0.1` (puertos 8001 y 8002).

## Demo visual: Support Agent (los 3 gateways en una sola consulta)

Con el stack arriba, abre **http://localhost:8080**. Un agente de soporte (`services/support-agent`) atiende tu pregunta y, a la derecha, una **línea de tiempo** muestra cada salto real por Kong (gateway, ruta, estado, latencia, `X-Request-Id`, rate limit restante).

Flujo de una consulta:
1. **MCP Gateway** → `initialize` + `tools/list`, y `tools/call` (`add`, `get_time`) según la intención.
2. **A2A Gateway** → descubre la Agent Card y delega a un *Ticket Agent* si hay que abrir un ticket/incidencia.
3. **AI Gateway** → `ai-proxy` redacta la respuesta final con los resultados anteriores.

Pruébalo con los botones de ejemplo:
- `¿Cuánto es 2 + 40 y qué hora es?` → solo MCP + AI.
- `Tengo un problema con mi factura, abre un ticket` → MCP + A2A + AI.
- `Dame el password de admin` → Kong responde **400** (`ai-prompt-guard`) y la UI lo marca en rojo.
- Envía más de 10 consultas en un minuto como el mismo consumidor (selector arriba a la derecha) → **429**; cambia a `bob` y sigue funcionando (límite por consumidor).

Nota: la planificación (qué tool llamar) es por reglas para que la demo sea determinista con el LLM falso; el LLM se usa para redactar la respuesta final. Con un LLM real, el mismo AI Gateway sirve para sustituir el planificador por tool-calling.

## Ejemplos manuales

```bash
# AI Gateway (Kong antepone un system prompt; el mock-llm lo muestra en la respuesta)
curl localhost:8000/ai/chat -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hola"}]}'

# MCP Gateway: listar y llamar tools
curl localhost:8000/mcp -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl localhost:8000/mcp -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":40}}}'

# A2A Gateway: descubrir el agente y enviarle un mensaje
curl localhost:8000/a2a/.well-known/agent.json -H 'apikey: alice-key'
curl localhost:8000/a2a/ -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"m1","parts":[{"kind":"text","text":"hola"}]}}}'
```

El comportamiento esperado de `scripts/demo.sh`: 401 sin key; respuesta del chat con el system prompt inyectado; 400 al enviar un prompt con "password"; respuestas JSON-RPC de MCP y A2A; y 429 a partir de la 11.ª llamada/minuto a `/ai/chat`.

> 🧪 **Colección de pruebas para Bruno:** carpeta [`bruno/`](bruno/README.md) (OAuth, seguridad, AI, MCP, A2A, rate limit). CLI: `cd bruno && npx @usebruno/cli run --env local`.

## OAuth2 (client_credentials) con Keycloak

Además de `apikey`, los tres gateways aceptan `Authorization: Bearer <token>` emitido por **Keycloak** (realm `kong-demo`, importado de `keycloak/kong-demo-realm.json`). Kong no emite tokens: solo los valida con el plugin OSS `jwt` (firma RS256 + `exp`), sin plugins de pago.

```bash
TOKEN=$(curl -s localhost:8180/realms/kong-demo/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=alice-client -d client_secret=alice-secret | jq -r .access_token)
curl localhost:8000/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```

- Clientes de demo: `alice-client`/`alice-secret` y `bob-client`/`bob-secret` (consola de Keycloak: `http://localhost:8180`, admin/admin). Cada uno es un consumer de Kong (`jwt_secrets` con `key` = claim `azp`), así que el rate limit sigue siendo por consumidor.
- `jwt` y `key-auth` llevan `anonymous` para poder usar cualquiera de los dos; `pre-function` (sin credenciales) y `post-function` (credencial inválida) devuelven 401.
- **Limitaciones del OSS:** la clave pública del realm está fija en `kong.yml` (la clave RSA del realm es de demo y está en el repo; en producción genera la tuya y no la versiones). No hay lectura de JWKS ni rotación automática: si rotas las claves de Keycloak hay que actualizar `rsa_public_key`. Tampoco hay introspección ni revocación: usa tokens de vida corta (aquí 5 min). La audiencia/issuer no se validan.

## Cómo funciona cada pieza

### AI Gateway
`ai-proxy` (incluido en Kong OSS ≥ 3.6) traduce la petición al formato del proveedor, inyecta la credencial del proveedor (el cliente nunca la ve) y normaliza la respuesta. Se combina con:
- `ai-prompt-decorator`: antepone/pospone mensajes (política corporativa).
- `ai-prompt-guard`: `deny_patterns` / `allow_patterns` sobre los prompts.
- `key-auth` + `rate-limiting` (`limit_by: consumer`).

**Proveedores (una ruta por proveedor, mismo contrato OpenAI para el cliente):**

| Ruta | Proveedor | Modelo por defecto | Credencial |
|---|---|---|---|
| `/ai/chat` | LLM falso local | `gpt-4o-mini` (simulado) | ninguna |
| `/ai/openai/chat` | OpenAI | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `/ai/anthropic/chat` | Anthropic | `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` |

```bash
cp .env.example .env            # rellena las claves que quieras usar (.env está en .gitignore)
docker compose up -d            # recrea Kong con las claves (o ./scripts/stack.sh up)

curl localhost:8000/ai/openai/chat -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hola"}]}'
curl localhost:8000/ai/anthropic/chat -H 'apikey: alice-key' -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hola"}]}'
```

- **Formato único:** el cliente siempre envía `messages` y recibe `choices[0].message`; para Anthropic, `ai-proxy` traduce a la Messages API (`system` separado, `x-api-key`, `anthropic-version`) y normaliza la respuesta.
- **Las claves no están en `kong.yml`:** se leen del entorno de Kong con el vault `env` (`{vault://env/...}`); el cliente nunca las ve.
- **Cambiar de modelo:** edita `model.name` de la ruta en `kong/kong.yml` (p. ej. `claude-opus-5-5`, `claude-haiku-4-5-20251001`) y `docker compose restart kong`.
- **Políticas compartidas:** `key-auth`, `rate-limiting` (10/min por consumidor, **un solo presupuesto para las tres rutas**), `ai-prompt-decorator`, `ai-prompt-guard` y `correlation-id` están a nivel de service, así que protegen igual a todos los proveedores. Las métricas de Grafana se pueden separar por modelo (`ai_provider`, `ai_model`).
- **Sin clave:** la ruta existe y Kong llega al proveedor, que responde **401 con su propio mensaje** (no es el 401 de Kong por falta de `apikey`). Requiere salida a Internet.
- **Otro proveedor** (Azure, Mistral, Gemini, Ollama local…): copia una ruta, cambia `provider`/`options` (ver doc del plugin `ai-proxy`).
- Para fallback o balanceo automático entre proveedores se necesita `ai-proxy-advanced` (edición de pago según su documentación).

### MCP Gateway
Kong expone los servidores MCP remotos (Streamable HTTP) detrás de una única URL, con autenticación, límites de uso, límite de payload y trazabilidad. Para varios servidores MCP añade un `service` + `route` por servidor (`/mcp/github`, `/mcp/db`…), y usa `acl` + consumer groups para controlar quién accede a cuál.

### A2A Gateway
Igual que MCP: el agente A2A se publica tras `/a2a`, con las mismas políticas. El Agent Card anuncia como `url` la dirección del **gateway** (`PUBLIC_URL` en `docker-compose.yml`), de modo que los clientes A2A hablen siempre con Kong y no con el agente.

## Alcance y limitaciones (honestidad)
- Los plugins específicos de protocolo de Kong para MCP/A2A (p. ej. `ai-mcp-proxy`, conversión REST→MCP, observabilidad A2A) pertenecen a ediciones de pago según su documentación; este stack cubre MCP y A2A como **proxy HTTP con políticas OSS**, no con inspección de protocolo. Verifica el estado actual en la doc de Kong.
- Streaming SSE de MCP/A2A atraviesa Kong, pero el demo usa respuestas JSON simples.
- `rate-limiting` usa `policy: local` (por nodo); en clúster usa `redis`.
- Las claves de `kong.yml` son solo de demo.
- El stack se escribió y se probaron los backends en local, pero **la configuración de Kong aún no se ha ejecutado contra un contenedor Kong** (Docker no estaba disponible al generarlo): si algún campo de plugin no coincide con tu versión, `docker compose logs kong` indicará cuál.
