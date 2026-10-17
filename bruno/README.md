# Colección Bruno — Kong AI Stack

1. Abre [Bruno](https://www.usebruno.com/) → *Open Collection* → esta carpeta (`bruno/`).
2. Elige el entorno **local** (arriba a la derecha).
3. Levanta el stack: `./scripts/stack.sh up`.
4. Ejecuta primero `00-oauth/Token alice` (guarda `access_token` en una variable de la colección) y luego el resto. *Run collection* ejecuta todo en orden.

Los tests de cada petición (pestaña *Assert*) equivalen a los de `./scripts/stack.sh test`.
Ojo: el rate limit es de 10/min por consumidor en IA (30/min en MCP): si ejecutas la colección varias veces seguidas, espera al minuto siguiente.
La carpeta `99-rate-limit` consume la cuota de bob a propósito: déjala para el final.


## Pruebas OIDC (carpeta `oidc/`)

> 📖 **Guía paso a paso (automática, Bruno, navegador y login social):** [oidc/GUIA-OIDC.md](oidc/GUIA-OIDC.md)

Duplican los flujos AI, MCP y A2A bajo `/oidc/...`, que **solo aceptan un usuario con login** (apikey → 401, token de máquina → 403). Orden: ejecuta `oidc/00-login` primero; *Run collection* ya respeta el orden.

- El token de usuario se obtiene con `mcp-oidc-test` (password grant, usuario `demo`/`demo`): es un cliente de **solo pruebas** para poder automatizar sin navegador. El flujo real es `authorization_code` + PKCE con `mcp-oidc-client` (pantalla de login con Google/GitHub/LinkedIn); `./scripts/stack.sh test` lo prueba por línea de comandos.
- Para probar el flujo real en Bruno: *Auth → OAuth 2.0 → Authorization Code*, client `mcp-oidc-client`, PKCE, auth URL `{{keycloak}}/realms/kong-demo/protocol/openid-connect/auth` y token URL `.../token`.
