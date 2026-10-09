# Dashboard de observabilidad y gobierno

Overlay opcional sobre el stack base: **Prometheus + Grafana + un generador de tráfico** con panel de botones. Muestra en tiempo real qué hace Kong como AI / MCP / A2A gateway y cómo reaccionan las políticas (401, 400, 429).

```
traffic (:8090) ──► Kong :8000 ──► mock-llm / mcp-server / a2a-agent
                      │ plugin prometheus
                      ▼  :8001/metrics
                 Prometheus (:9090) ──► Grafana (:3001)  "Kong AI Stack · Observabilidad y Gobierno"
```

## Arranque
```bash
docker compose -f docker-compose.yml -f observability/docker-compose.yml up -d --build
```
| Servicio | URL |
|---|---|
| Panel de control de tráfico | http://localhost:8090 |
| Grafana (dashboard por defecto, sin login) | http://localhost:3001 |
| Prometheus | http://localhost:9090 |

> Grafana usa el puerto **3001** (configurable con `GRAFANA_PORT=3005 docker compose ...`) para no chocar con otros servicios típicos en `:3000` (p. ej. Metabase). El servicio `traffic` arranca con tráfico de fondo (1 req/s, `AUTOSTART=true`) para que el dashboard tenga datos desde el inicio; deténlo desde el panel si quieres controlarlo a mano.

Parar: `docker compose -f docker-compose.yml -f observability/docker-compose.yml down`

## Qué se mide
Kong expone métricas con el plugin `prometheus` (global en `kong/kong.yml`, con `per_consumer`, latencia, ancho de banda y `ai_metrics`). Prometheus las lee de `kong:8001/metrics` cada 5 s.

| Panel | Métrica | Lectura |
|---|---|---|
| Peticiones/s, 2xx | `kong_http_requests_total` | Carga y éxito globales |
| 🔒 401 / 🛡️ 400 / ⏱️ 429 | `kong_http_requests_total{code=…}` | Gobierno: sin credencial, `ai-prompt-guard`, `rate-limiting` |
| Por gateway | agrupado por `route` (`ai-chat`, `mcp`, `a2a`) | Uso de cada gateway |
| Por consumidor | agrupado por `consumer` | Quién consume (alice/bob) |
| Bloqueos por gateway | códigos 401/400/429 por `route` | Dónde actúan las políticas |
| Latencia p95 | `kong_request_latency_ms_bucket`, `kong_upstream_latency_ms_bucket` | Kong + upstream vs. solo upstream |
| 🤖 Tokens y peticiones LLM | `kong_ai_llm_tokens_total`, `kong_ai_llm_requests_total` | Consumo de IA por consumidor/modelo |
| Ancho de banda | `kong_bandwidth_bytes` | Tráfico entrante/saliente |

## Guion de demo (5 minutos)
1. Abre **Grafana** y el **panel de tráfico** en pestañas/ventanas separadas. Rango por defecto: últimos 15 min, refresco 5 s.
2. **Tráfico continuo → Iniciar** (2 req/s). En Grafana: sube "Peticiones/s", aparecen las tres rutas y los dos consumidores; los 2xx dominan.
3. **Ráfaga → 429**: en "⏱️ 429" y en "Bloqueos por gateway" aparece `ai-chat · 429`. Explica: el límite es por consumidor (10/min en `/ai/chat`) y protege el presupuesto de LLM; MCP y A2A siguen sin afectarse.
4. **Ataque de prompts → 400**: sube "🛡️ 400" (`ai-prompt-guard`). Los prompts maliciosos no llegan al LLM.
5. **Sin credencial → 401**: sube "🔒 401" en las tres rutas; el backend no recibe nada.
6. Mira **latencia p95** (la diferencia entre total y upstream es el coste de Kong) y **Tokens LLM/s por consumidor** para hablar de FinOps.
7. **Detener** el tráfico continuo: las curvas caen a cero.

## Verificación rápida (sin Grafana)
```bash
curl -s localhost:8001/metrics | grep -E '^kong_http_requests_total' | head
curl -s 'localhost:9090/api/v1/targets' | python3 -c "import sys,json;print([t['health'] for t in json.load(sys.stdin)['data']['activeTargets']])"   # ['up']
curl -s 'localhost:9090/api/v1/query?query=sum(rate(kong_http_requests_total[1m]))'
```

## Si no se ve nada
| Síntoma | Causa y solución |
|---|---|
| `localhost:3000` muestra otra aplicación (Metabase, etc.) | Otro contenedor ocupa el puerto. Grafana está en **:3001**. Comprueba con `docker ps` qué publica cada puerto. |
| Prometheus no devuelve `kong_http_requests_total` | Kong solo exporta ese contador tras recibir tráfico. Inicia el tráfico continuo o lanza un escenario y espera ~10 s. |
| Paneles de tokens/peticiones LLM vacíos | Requiere `logging.log_statistics: true` en `ai-proxy` (ya configurado en `kong.yml`) y tráfico a `/ai/chat`. Estas métricas **no** llevan etiqueta de consumidor. |
| El panel de 400 está a 0 durante una ráfaga | `rate-limiting` se evalúa **antes** que `ai-prompt-guard`: con la cuota agotada la respuesta es 429, no 400. Espera 1 min y lanza el ataque con cuota libre. |
| Target de Prometheus en `down` | Mira `http://localhost:9090/targets`; Kong debe estar `healthy` (`docker compose ps`). |
| Paneles con "No data" justo tras reiniciar Kong | Los contadores se reinician; basta con volver a generar tráfico. |

## Limitaciones / a verificar
- **Verificado** con Kong 3.9.3: las 14 consultas del dashboard devuelven series en Prometheus. Los nombres `kong_ai_llm_*` y sus etiquetas (`ai_provider`, `ai_model`, `token_type`) dependen de la versión de Kong (≥ 3.8). Con el LLM falso los tokens son un valor fijo (20 por petición).
- Grafana tiene acceso anónimo como Admin y Prometheus está sin autenticar: **solo para demo**.
- Las series necesitan unos segundos de tráfico para aparecer (scrape cada 5 s, ventana `rate` de 1 min).
- La Admin API (`:8001`) queda accesible para Prometheus dentro de la red de Docker; en producción usa el *Status API* de Kong con un listener dedicado.
