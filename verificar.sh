#!/usr/bin/env bash
# Verifica los 3 criterios de aceptación de US-07 (requiere Docker).
# Uso: ./verificar.sh
set -u
ok(){ echo "  ✅ $1"; }; fail(){ echo "  ❌ $1"; FAILED=1; }
FAILED=0

[ -f .env ] || { echo "Falta .env  →  cp .env.example .env y define POSTGRES_PASSWORD"; exit 1; }
PORT=$(grep -E '^BACKEND_PORT=' .env | cut -d= -f2); PORT=${PORT:-8000}

echo "Criterio 3 (portabilidad): construir desde cero y levantar"
docker compose down -v >/dev/null 2>&1
docker compose build --no-cache >/dev/null 2>&1 && ok "La imagen se construye sin errores" || fail "Falla la construcción"
docker compose up -d >/dev/null 2>&1 && ok "docker compose up levanta los servicios" || fail "Falla docker compose up"

echo "Criterio 1 (backend y PostgreSQL se comunican)"
for i in $(seq 1 30); do
  R=$(curl -s "http://localhost:${PORT}/api/v1/health"); [ -n "$R" ] && break; sleep 2
done
echo "  Respuesta: ${R:-sin respuesta}"
echo "$R" | grep -q '"database":"up"' && ok "Backend conectado a PostgreSQL" || fail "El backend no llega a la base de datos"
docker compose ps

echo "Criterio 2 (sin credenciales en Dockerfile ni código)"
PASS=$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
if [ -n "$PASS" ] && grep -rqF -- "$PASS" backend/Dockerfile docker-compose.yml backend/app 2>/dev/null; then
  fail "La contraseña aparece escrita en Dockerfile/compose/código"
else ok "La contraseña no aparece en Dockerfile, compose ni código"; fi
docker compose exec -T backend printenv DATABASE_URL >/dev/null 2>&1 && ok "DATABASE_URL llega al contenedor por variable de entorno" || fail "DATABASE_URL no está en el contenedor"

[ $FAILED -eq 0 ] && echo -e "\nTodo OK ✅" || echo -e "\nHay criterios sin cumplir ❌"
exit $FAILED
