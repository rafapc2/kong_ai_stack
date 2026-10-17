# Guía: probar el flujo OIDC (`/oidc/...`)

Los gateways `/oidc/ai/*`, `/oidc/mcp` y `/oidc/a2a/` solo aceptan un **usuario con login** (Keycloak).
Hay cinco formas de probarlos. **La recomendada para el flujo real es la mini app web (sección 3)**. Requisito: stack levantado (`./scripts/stack.sh up`).

| Qué se espera | Resultado |
|---|---|
| Bearer de un usuario con login | 200 |
| Sin credenciales, o Bearer alterado | 401 (con `WWW-Authenticate: ... resource_metadata=...`) |
| `apikey` | 401 |
| Token de máquina (`client_credentials`, p. ej. `alice-client`) | 403 |

## 1. Automática, sin navegador

```bash
./scripts/stack.sh test
```

Hace el login del usuario `demo` con `authorization_code` + PKCE y recorre AI, MCP y A2A bajo `/oidc/...`.
Mira las secciones que empiezan por "OIDC" (incluye la app web de la sección 3).

## 2. Colección Bruno (esta carpeta)

1. Abre `bruno/` en Bruno (*Open Collection*) y elige el entorno **local**.
2. Ejecuta primero `oidc/00-login` (guarda `access_token_user` y `access_token_alice`) y luego el resto de `oidc/`. *Run collection* ya respeta el orden. Por terminal: `cd bruno && npx @usebruno/cli run --env local -r`.
3. El token de usuario sale del cliente `mcp-oidc-test` (password grant, usuario `demo`/`demo`). Es un cliente de **solo pruebas** para poder automatizar sin navegador.

Para el flujo con navegador dentro de Bruno: *Auth → OAuth 2.0 → Authorization Code*, client `mcp-oidc-client`, PKCE activado,
auth URL `http://localhost:8180/realms/kong-demo/protocol/openid-connect/auth` y token URL `.../token`.

## 3. Mini app web cliente (recomendada)

Abre **http://localhost:8085** (se levanta con el stack; código en `services/oidc-client/`).

1. Pulsa **Iniciar sesión (Keycloak)**: la app lanza `authorization_code` + PKCE y te lleva a Keycloak.
2. Entra con `demo` / `demo`, o con Google / GitHub / LinkedIn si configuraste sus claves (sección 5).
3. Vuelves a la app con la sesión iniciada: verás tu usuario, el `azp` y los claims del token y cuánto falta para que expire.
4. Pulsa los botones de AI (mock, OpenAI, Anthropic), MCP (`tools/list`, `add(2, 40)`) y A2A (Agent Card, `message/send`): cada uno muestra ruta, estado HTTP, latencia, `X-Request-Id` y la respuesta.
5. Cambia **Enviar con** y repite: *sin token* y *apikey* dan 401, *token de máquina* da 403. Así compruebas que solo entra un usuario con login.

La app guarda el token en el servidor (sesión en memoria) y llama a Kong en su nombre; el navegador solo ve los claims.
Con *Cerrar sesión* se cierra también la sesión en Keycloak. `./scripts/stack.sh test` también recorre este flujo de punta a punta.

## 4. Manual con navegador y curl (sin app)

```bash
# 1) Genera el verifier y el challenge de PKCE e imprime la URL de login
V=$(openssl rand -base64 48 | tr -d '=+/\n' | cut -c1-64)
CH=$(printf '%s' "$V" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
echo "http://localhost:8180/realms/kong-demo/protocol/openid-connect/auth?client_id=mcp-oidc-client&response_type=code&scope=openid&redirect_uri=http://localhost:9999/cb&code_challenge=$CH&code_challenge_method=S256"
```

1. Abre esa URL en el navegador: verás el login de Keycloak con los botones de **Google, GitHub y LinkedIn**.
2. Entra con `demo` / `demo`.
3. El navegador te redirige a `http://localhost:9999/cb?...&code=XXXX`. La página no carga y es normal: copia el valor de `code` de la barra de direcciones.
4. Cambia el código por un token y llama al gateway (mismo terminal, para conservar `$V`):

```bash
TOKEN=$(curl -s localhost:8180/realms/kong-demo/protocol/openid-connect/token \
  -d grant_type=authorization_code -d client_id=mcp-oidc-client -d code=XXXX \
  -d redirect_uri=http://localhost:9999/cb -d code_verifier="$V" | jq -r .access_token)

curl localhost:8000/oidc/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

El código vale una sola vez y caduca en pocos minutos; si falla, repite desde el paso 1.

## 5. Login real con Google, GitHub o LinkedIn

1. Crea una app OAuth en el proveedor.
2. Registra esta redirect URI en la app: `http://localhost:8180/realms/kong-demo/broker/<google|github|linkedin>/endpoint`.
3. Pon `<PROVEEDOR>_CLIENT_ID` y `<PROVEEDOR>_CLIENT_SECRET` en `.env` (ver `.env.example`).
4. Recrea Keycloak: `docker compose up -d --force-recreate keycloak` (el realm se importa al arrancar).
5. Repite el flujo de la sección 3 (o la 4), pero pulsa el botón del proveedor en vez de usar `demo`.

> Esta parte no está cubierta por ninguna prueba automática: requiere tus credenciales y un navegador.

## Comprobaciones negativas (deben fallar)

```bash
# apikey → 401
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/oidc/mcp -H 'apikey: alice-key' -H 'Content-Type: application/json' -d '{}'

# token de máquina → 403
MT=$(curl -s localhost:8180/realms/kong-demo/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=alice-client -d client_secret=alice-secret | jq -r .access_token)
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/oidc/mcp -H "Authorization: Bearer $MT" -H 'Content-Type: application/json' -d '{}'
```

## Problemas frecuentes

| Síntoma | Causa |
|---|---|
| `invalid_grant` al canjear el código | Código ya usado o caducado, o `$V` distinto al de la URL de login. Repite desde el paso 1. |
| Keycloak responde 302 con `error=invalid_request` | Falta `code_challenge`: el cliente exige PKCE. |
| 429 | Rate limit (30/min en MCP y A2A, 10/min en IA, por cliente): espera al minuto siguiente. |
| El botón social falla en el proveedor | Credenciales sin configurar o redirect URI mal registrada (sección 5). |
