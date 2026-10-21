# Prueba de carga

Mide el comportamiento con 20-30 operarios consultando datos. Usa el stack
E2E (base desechable) para no tocar producción.

```bash
# 1) Stack de producción local, con un límite alto para aislar la app
cd frontdata
E2E_ADMIN_PASS=e2e-admin-pass docker compose -f e2e/docker-compose.e2e.yml up -d --build --wait

# 2) Prueba: 25 usuarios virtuales durante 2 minutos
docker run --rm --network datacontrol-e2e_default \
  -v "$PWD/../backdata/loadtests:/scripts:ro" \
  -e BASE_URL=http://front \
  -e ADMIN_PASS=e2e-admin-pass \
  -e VUS=25 -e DURATION=2m \
  grafana/k6:2.3.0 run /scripts/lectura.js

# 3) Limpiar
docker compose -f e2e/docker-compose.e2e.yml down -v
```

El script hace un solo login y reutiliza la cookie para todas las lecturas.
El límite de la API se configura con `E2E_RATE_LIMIT_MINUTE` (default
`1200/minute`) para que la prueba mida la aplicación, no el rate limiter.

## Interpretación

- `http_req_duration p(95)` debe quedar por debajo de 500 ms.
- `http_req_failed` debe ser menor al 1 %.
- Un `429` significa que se alcanzó el límite por IP; en producción cada
  operario tiene su propia IP (Nginx envía `X-Real-IP`). Si todos salen por
  un NAT, subir `RATE_LIMIT_MINUTE` en `.env` y reiniciar la API.
