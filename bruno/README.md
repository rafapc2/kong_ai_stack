# Colección Bruno — Kong AI Stack

1. Abre [Bruno](https://www.usebruno.com/) → *Open Collection* → esta carpeta (`bruno/`).
2. Elige el entorno **local** (arriba a la derecha).
3. Levanta el stack: `./scripts/stack.sh up`.
4. Ejecuta primero `00-oauth/Token alice` (guarda `access_token` en una variable de la colección) y luego el resto. *Run collection* ejecuta todo en orden.

Los tests de cada petición (pestaña *Assert*) equivalen a los de `./scripts/stack.sh test`.
Ojo: el rate limit es de 10/min por consumidor en IA (30/min en MCP): si ejecutas la colección varias veces seguidas, espera al minuto siguiente.
La carpeta `99-rate-limit` consume la cuota de bob a propósito: déjala para el final.
