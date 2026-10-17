# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

Stack open source de Kong Gateway OSS (DB-less) que funciona como AI gateway, MCP gateway y A2A gateway. Documentación completa en `README.md`.

## Comandos

`./scripts/stack.sh` orquesta todo (`up [--obs]`, `test`, `reset`, `all --obs` = limpiar + reconstruir + 31 pruebas; `help` lista el resto). Comprobar sus pruebas es la validación end-to-end. Con bash 3.2 de macOS evita arrays vacíos bajo `set -u`.

Comandos equivalentes a mano:

```bash
docker compose up -d --build   # levanta Kong (:8000 proxy, :8001 admin) + 3 backends
./scripts/demo.sh              # ejercita /ai/chat, /mcp y /a2a vía Kong
docker compose logs kong       # primer sitio donde mirar si falla la config declarativa
docker compose restart kong    # tras editar kong/kong.yml (DB-less: se carga al arrancar)
```

No hay suite de tests ni linter; `scripts/demo.sh` es la verificación end-to-end.

## Arquitectura

- Toda la lógica de gateway está en `kong/kong.yml` (config declarativa): un `service`+`route` por gateway (`/ai/chat`, `/mcp`, `/a2a`), cada uno con `key-auth` + `rate-limiting`; `/ai/chat` añade `ai-proxy`, `ai-prompt-decorator` y `ai-prompt-guard`.
- El AI Gateway tiene 3 rutas con el mismo contrato OpenAI: `/ai/chat` (mock), `/ai/openai/chat` y `/ai/anthropic/chat`. Las políticas comunes están a nivel de service (presupuesto de rate-limit compartido) y `ai-proxy` por ruta. Las claves llegan por `.env` → entorno de Kong → `{vault://env/...}`; OpenAI usa `OPENAI_AUTH_HEADER="Bearer $OPENAI_API_KEY"` porque una referencia de vault debe ocupar el valor completo.
- `ai-proxy` ignora la `url` del service y llama a `model.options.upstream_url` (aquí el mock); en un LLM real se quita ese campo.
- `services/*` son backends de ejemplo en Python stdlib (sin dependencias), solo accesibles dentro de la red de compose: `mock-llm` (OpenAI-compatible), `mcp-server` (JSON-RPC Streamable HTTP), `a2a-agent` (Agent Card + `message/send`; su `url` pública viene de `PUBLIC_URL` y debe apuntar al gateway).
- `services/support-agent` (UI en :8080) es el orquestador de la demo: planifica por reglas y hace **todas** sus llamadas a Kong (`GATEWAY`), registrando cada una en una línea de tiempo que `index.html` dibuja. El mock-llm responde a partir del bloque `[CONTEXT]` que el orquestador añade al prompt.
- `observability/` es un overlay opcional de compose (`-f docker-compose.yml -f observability/docker-compose.yml`): Prometheus scrapea `kong:8001/metrics` (plugin `prometheus` global en `kong.yml`), Grafana carga el dashboard provisionado de `observability/grafana/dashboards/kong-ai-gov.json` y `observability/traffic` genera carga/escenarios (401/400/429) con UI en :8090. Ver `docs/OBSERVABILIDAD.md`.
- OAuth2: Keycloak (:8180, realm `kong-demo` importado de `keycloak/`) emite tokens `client_credentials`; Kong los valida con el plugin OSS `jwt` (`key_claim_name: azp`, clave pública fija en `kong.yml`). `jwt` y `key-auth` usan `anonymous`; `pre-function`/`post-function` dan el 401. Sin JWKS ni rotación automática.
- Kong Manager OSS está habilitado en `127.0.0.1:8002` (`KONG_ADMIN_GUI_*` en `docker-compose.yml`); en DB-less es solo lectura, los cambios se hacen en `kong.yml`.
- Los plugins MCP/A2A específicos de Kong son de pago; aquí MCP y A2A pasan como proxy HTTP con plugins OSS.
