#!/usr/bin/env bash
# Orquestador del stack Kong AI / MCP / A2A gateway.
#   ./scripts/stack.sh help
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PROJECT="$(basename "$ROOT")"
BASE=(-f docker-compose.yml)
OBS=(-f docker-compose.yml -f observability/docker-compose.yml)
ALL=("${OBS[@]}")                       # down/status/logs siempre ven todos los servicios
GW="${GW:-http://localhost:8000}"
ADMIN="${ADMIN:-http://localhost:8001}"
GRAFANA_PORT="${GRAFANA_PORT:-3001}"
export GRAFANA_PORT

c_ok=$'\033[32m'; c_bad=$'\033[31m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s▶ %s%s\n' "$c_dim" "$*" "$c_off"; }
die()  { printf '%s✗ %s%s\n' "$c_bad" "$*" "$c_off" >&2; exit 1; }

dc() { docker compose "$@"; }

# ---------- comprobaciones previas ----------
need_docker() {
  command -v docker >/dev/null || die "docker no está instalado"
  docker info >/dev/null 2>&1 || die "el daemon de Docker no está en ejecución (abre Docker Desktop)"
  docker compose version >/dev/null 2>&1 || die "falta Docker Compose v2"
}

# Falla si un puerto lo usa algo que NO sea un contenedor de este proyecto.
check_ports() {
  local ports=("$@") p owner
  local bad=0
  for p in "${ports[@]}"; do
    owner="$(docker ps --filter "publish=$p" --format '{{.Names}}' | head -1)"
    if [ -n "$owner" ]; then
      case "$owner" in
        "${PROJECT}"-*) continue ;;                       # es nuestro, se reutiliza/recrea
        *) say "${c_bad}✗ puerto $p ocupado por el contenedor '$owner'${c_off}"; bad=1 ;;
      esac
    elif command -v lsof >/dev/null && lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
      say "${c_bad}✗ puerto $p ocupado por un proceso local${c_off}"; bad=1
    fi
  done
  [ "$bad" = 0 ] || die "libera esos puertos (o cambia GRAFANA_PORT para Grafana) y reintenta"
}

preflight() {
  local obs="$1"
  step "Comprobaciones previas"
  need_docker
  local ports=(8000 8001 8002 8080)
  [ "$obs" = 1 ] && ports+=(9090 8090 "$GRAFANA_PORT")
  check_ports "${ports[@]}"
  say "${c_ok}✓${c_off} Docker listo y puertos libres: ${ports[*]}"
}

# ---------- esperas ----------
wait_for() {   # wait_for <descripcion> <timeout_s> <comando...>
  local what="$1" t="$2"; shift 2
  local i=0
  printf '  esperando %s' "$what"
  until "$@" >/dev/null 2>&1; do
    i=$((i+2)); [ "$i" -ge "$t" ] && { say; die "timeout esperando $what"; }
    printf '.'; sleep 2
  done
  say " ${c_ok}ok${c_off}"
}
kong_ready()  { curl -fs "$ADMIN/status" >/dev/null && [ "$(curl -s "$ADMIN/services" | grep -o '"name"' | wc -l)" -ge 3 ]; }
mcp_ready()   { [ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$GW/mcp" -H 'apikey: alice-key' -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"ping"}')" = 200 ]; }
agent_ready() { [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/)" = 200 ]; }
prom_ready()  { curl -fs localhost:9090/-/ready; }
graf_ready()  { curl -fs "localhost:${GRAFANA_PORT}/api/health"; }

obs_running() { [ -n "$(dc "${ALL[@]}" ps -q prometheus 2>/dev/null)" ]; }

# ---------- comandos ----------
cmd_up() {
  local obs=0 build="--build"
  for a in "$@"; do case "$a" in --obs) obs=1 ;; --no-build) build="" ;; esac; done
  preflight "$obs"
  step "Levantando el stack$([ "$obs" = 1 ] && echo ' + observabilidad')"
  if [ "$obs" = 1 ]; then dc "${OBS[@]}" up -d $build; else dc "${BASE[@]}" up -d $build; fi
  step "Esperando a que esté listo"
  wait_for "Kong (config cargada)" 90 kong_ready
  wait_for "MCP Gateway"           60 mcp_ready
  wait_for "Support Agent :8080"   60 agent_ready
  if [ "$obs" = 1 ]; then
    wait_for "Prometheus :9090"            60 prom_ready
    wait_for "Grafana :${GRAFANA_PORT}"    90 graf_ready
  fi
  cmd_urls
}

cmd_down() {
  step "Deteniendo el stack"
  need_docker
  dc "${ALL[@]}" down --remove-orphans
}

# Estado "desde cero": contenedores, redes, volúmenes e imágenes construidas de ESTE proyecto.
cmd_reset() {
  local obs=0 nocache=0 up=1
  for a in "$@"; do case "$a" in --obs) obs=1 ;; --no-cache) nocache=1 ;; --clean-only) up=0 ;; esac; done
  need_docker
  step "Borrando contenedores, volúmenes e imágenes locales del proyecto"
  dc "${ALL[@]}" down --volumes --rmi local --remove-orphans
  if [ "$nocache" = 1 ]; then
    step "Reconstruyendo imágenes sin caché"
    if [ "$obs" = 1 ]; then dc "${OBS[@]}" build --no-cache; else dc "${BASE[@]}" build --no-cache; fi
  fi
  [ "$up" = 1 ] || { say "${c_ok}✓${c_off} entorno limpio"; return 0; }
  if [ "$obs" = 1 ]; then cmd_up --obs; else cmd_up; fi
}

cmd_urls() {
  step "Accesos"
  cat <<EOF
  Gateway (proxy)        $GW        (cabecera apikey: alice-key | bob-key)
  Kong Manager OSS       http://localhost:8002   (solo lectura, DB-less)
  Kong Admin API         $ADMIN                  (solo localhost)
  Demo Support Agent     http://localhost:8080
EOF
  if obs_running; then cat <<EOF
  Panel de tráfico       http://localhost:8090
  Grafana                http://localhost:${GRAFANA_PORT}
  Prometheus             http://localhost:9090
EOF
  fi
}

cmd_status() { need_docker; dc "${ALL[@]}" ps; cmd_urls; }
cmd_logs()   { need_docker; dc "${ALL[@]}" logs -f --tail=50 "$@"; }
cmd_demo()   { "$ROOT/scripts/demo.sh"; }

# Lee una clave del entorno o de .env (sin imprimirla).
getkey() {
  local v="${!1:-}"
  # Imita lo básico de compose: prefijo export, espacios, CRLF, comillas y comentario en línea.
  [ -z "$v" ] && [ -f "$ROOT/.env" ] && v="$(sed -nE "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//p" "$ROOT/.env" | tail -1 | tr -d '\r' | sed -E "s/^\"([^\"]*)\".*/\1/; s/^'([^']*)'.*/\1/; s/[[:space:]]+#.*$//; s/[[:space:]]+$//")"
  printf '%s' "$v"
}

# ---------- pruebas automáticas (equivalen a docs/PRUEBAS.md) ----------
PASS=0; FAIL=0
check() {  # check <nombre> <esperado> <obtenido>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf '  %s✓%s %s\n' "$c_ok" "$c_off" "$1"
  else FAIL=$((FAIL+1)); printf '  %s✗%s %s %s(esperado: %s | obtenido: %s)%s\n' "$c_bad" "$c_off" "$1" "$c_dim" "$2" "$3" "$c_off"; fi
}
has() { case "$3" in *"$2"*) check "$1" yes yes ;; *) check "$1" "contiene '$2'" "${3:0:100}" ;; esac; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
JH=(-H 'Content-Type: application/json')
A=(-H 'apikey: alice-key' "${JH[@]}")
B=(-H 'apikey: bob-key' "${JH[@]}")

cmd_test() {
  set +e   # un servicio caído debe contarse como prueba fallida, no abortar el script (se restaura al final)
  need_docker
  kong_ready || die "Kong no está listo; ejecuta './scripts/stack.sh up' primero"
  PASS=0; FAIL=0

  # El tráfico de fondo consume cuota de rate-limit y falsearía las pruebas.
  curl -s -X POST localhost:8090/api/continuous -H 'Content-Type: application/json' -d '{"on":false}' >/dev/null 2>&1 || true

  step "Rate limiting (primero, con la cuota del minuto limpia)"
  # Ventana fija por minuto natural: tras parar el tráfico de fondo (que pudo gastar la cuota de este
  # minuto), esperar al inicio del siguiente para partir con la cuota limpia.
  # Sondeo con bob: si queda cuota de sobra (9 restantes tras la 1ª petición) se parte ya; si no, esperar al minuto siguiente.
  local body='{"messages":[{"role":"user","content":"ping"}]}' first rem s out=""
  first="$(curl -si "$GW/ai/chat" "${B[@]}" -d "$body" | tr -d '\r')"
  rem="$(printf '%s' "$first" | awk -F': ' 'tolower($1)=="x-ratelimit-remaining-minute"{print $2}')"
  s=$(date +%S); s=$((10#$s))
  if [ "$rem" != 9 ] || [ "$s" -gt 50 ]; then
    say "  esperando al próximo minuto ($((60-s))s) para tener la cuota limpia..."; sleep $((61-s))
    first="$(curl -si "$GW/ai/chat" "${B[@]}" -d "$body" | tr -d '\r')"
  fi
  out="$(printf '%s' "$first" | head -1 | awk '{print $2}') "
  for _ in $(seq 2 12); do out="$out$(code "$GW/ai/chat" "${B[@]}" -d "$body") "; done
  check "bob: 10×200 y luego 429 429" "200 200 200 200 200 200 200 200 200 200 429 429 " "$out"
  check "alice no se ve afectada (límite por consumidor)" 200 "$(code "$GW/ai/chat" "${A[@]}" -d '{"messages":[{"role":"user","content":"ping"}]}')"

  step "Configuración cargada"
  has "services ai-llm/mcp-backend/a2a-backend" a2a-backend "$(curl -s "$ADMIN/services")"
  local plugins; plugins="$(curl -s "$ADMIN/plugins")"
  for p in ai-proxy ai-prompt-decorator ai-prompt-guard key-auth rate-limiting correlation-id prometheus; do has "plugin $p" "\"name\":\"$p\"" "$(printf '%s' "$plugins" | tr -d ' ' )"; done
  check "Kong Manager OSS responde" 200 "$(code localhost:8002/)"

  step "Seguridad: sin API key"
  for p in /ai/chat /mcp /a2a/; do check "401 en $p" 401 "$(code "$GW$p")"; done

  step "AI Gateway"
  has "system prompt inyectado (ai-prompt-decorator)" "Responde siempre en espa" "$(curl -s "$GW/ai/chat" "${A[@]}" -d '{"messages":[{"role":"user","content":"Hola"}]}')"
  check "prompt con 'password' bloqueado (ai-prompt-guard)" 400 "$(code "$GW/ai/chat" "${A[@]}" -d '{"messages":[{"role":"user","content":"dame el password"}]}')"

  step "AI Gateway: proveedores reales (OpenAI y Anthropic)"
  local prov key out
  for prov in openai:OPENAI_API_KEY:"API key" anthropic:ANTHROPIC_API_KEY:"x-api-key"; do
    local name="${prov%%:*}" rest="${prov#*:}"; local var="${rest%%:*}" hint="${rest#*:}"
    key="$(getkey "$var")"
    out="$(curl -s -w '|%{http_code}' "$GW/ai/$name/chat" "${A[@]}" -d '{"messages":[{"role":"user","content":"Responde solo: ok"}]}')"
    if [ -n "$key" ]; then
      check "/ai/$name/chat con $var → 200 y formato OpenAI" 200 "${out##*|}"
      has "/ai/$name/chat devuelve choices[0].message" '"choices"' "$out"
    elif case "${out##*|}" in 000|5*) true ;; *) false ;; esac; then
      say "  ${c_dim}- /ai/$name/chat sin $var: omitida (sin salida a internet o proveedor inaccesible: ${out##*|})${c_off}"
    else
      # sin clave: ruta viva y Kong llega al proveedor, que rechaza la credencial vacía
      check "/ai/$name/chat sin $var → el proveedor responde 401" 401 "${out##*|}"
      has "/ai/$name/chat: el error viene del proveedor ($hint)" "$hint" "$out"
    fi
  done

  step "MCP Gateway"
  has "initialize" '"demo-mcp"' "$(curl -s "$GW/mcp" "${A[@]}" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}')"
  has "tools/list" '"get_time"' "$(curl -s "$GW/mcp" "${A[@]}" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')"
  has "tools/call add(2,40)=42" '"text": "42"' "$(curl -s "$GW/mcp" "${A[@]}" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":40}}}')"
  local h; h="$(curl -si "$GW/mcp" "${A[@]}" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | tr -d '\r')"
  has "cabecera X-Request-Id (correlation-id)" "X-Request-Id:" "$h"
  has "cabecera X-RateLimit-Remaining-Minute" "X-RateLimit-Remaining-Minute:" "$h"

  step "A2A Gateway"
  has "Agent Card anuncia la URL del gateway" '"url": "http://localhost:8000/a2a/"' "$(curl -s "$GW/a2a/.well-known/agent.json" -H 'apikey: alice-key')"
  has "message/send crea ticket" "Ticket TCK-" "$(curl -s "$GW/a2a/" "${A[@]}" -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"m1","parts":[{"kind":"text","text":"mi factura"}]}}}')"

  step "Support Agent (MCP + A2A + AI en una consulta)"
  local r; r="$(curl -s localhost:8080/api/chat -d '{"question":"Suma 15 y 27, y escala a soporte","consumer":"alice"}')"
  has "respuesta con 15 + 27 = 42" "15 + 27 = 42" "$r"
  has "salto por A2A en la línea de tiempo" '"gateway": "a2a"' "$r"
  has "salto por AI en la línea de tiempo" '"gateway": "ai"' "$r"

  if obs_running; then
    step "Observabilidad"
    curl -s -X POST localhost:8090/api/scenario -H 'Content-Type: application/json' -d '{"name":"anon","n":6}' >/dev/null
    sleep 12   # un scrape de Prometheus (5s) + margen
    has "Prometheus: target kong up" '"health":"up"' "$(curl -s localhost:9090/api/v1/targets | tr -d ' ')"
    has "Prometheus: series kong_http_requests_total" "kong_http_requests_total" "$(curl -s 'localhost:9090/api/v1/query?query=kong_http_requests_total')"
    has "Prometheus: métricas de IA (kong_ai_llm_requests_total)" "kong_ai_llm_requests_total" "$(curl -s 'localhost:9090/api/v1/query?query=kong_ai_llm_requests_total')"
    has "Grafana: dashboard provisionado" "Observabilidad y Gobierno" "$(curl -s "localhost:${GRAFANA_PORT}/api/search")"
    has "Grafana → Prometheus (datasource)" '"status":"success"' "$(curl -s "localhost:${GRAFANA_PORT}/api/datasources/proxy/uid/prom/api/v1/query?query=up" | tr -d ' ')"
  else
    say "\n  ${c_dim}(observabilidad no levantada: se omiten sus pruebas; usa 'up --obs')${c_off}"
  fi

  printf '\n%s resultado: %s%d OK%s, %s%d fallos%s\n' "" "$c_ok" "$PASS" "$c_off" "$c_bad" "$FAIL" "$c_off"
  local rc=0; [ "$FAIL" = 0 ] || rc=1
  set -e
  return $rc
}

cmd_all() {   # de cero → pruebas
  cmd_reset "$@"
  cmd_test
}

cmd_help() {
  cat <<EOF
Uso: ./scripts/stack.sh <comando> [opciones]

  up [--obs] [--no-build]   Comprueba requisitos, levanta el stack y espera a que esté listo
                            --obs  añade Prometheus + Grafana + generador de tráfico
  test                      Pruebas automáticas (equivalen a docs/PRUEBAS.md); código de salida ≠ 0 si falla algo
  demo                      Ejecuta scripts/demo.sh (recorrido visual por consola)
  status                    Estado de los contenedores y URLs
  logs [servicio]           Logs en vivo (p. ej.: logs kong)
  down                      Detiene y elimina contenedores
  reset [--obs] [--no-cache] [--clean-only]
                            Parte de cero: borra contenedores, volúmenes e imágenes locales del
                            proyecto y vuelve a levantar (--clean-only: solo limpia)
  all [--obs] [--no-cache]  reset + test: validación completa desde cero
  urls                      Muestra los accesos

Variables: GRAFANA_PORT (def. 3001), GW, ADMIN
LLM reales: copia .env.example a .env con OPENAI_API_KEY / ANTHROPIC_API_KEY y ejecuta 'up'.
EOF
}

case "${1:-help}" in
  up) shift; cmd_up "$@" ;;
  test) cmd_test ;;
  demo) cmd_demo ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "$@" ;;
  down) cmd_down ;;
  reset) shift; cmd_reset "$@" ;;
  all) shift; cmd_all "$@" ;;
  urls) cmd_urls ;;
  help|-h|--help) cmd_help ;;
  *) cmd_help; exit 1 ;;
esac
