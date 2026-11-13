# Mediciones de lectura en un entorno desechable

`lectura.js` rechaza URLs externas, HTTPS y cualquier ejecución sin
`LOADTEST_DISPOSABLE=1`. Solo admite localhost, 127.0.0.1 o el servicio Docker
`front`. No redirigir estos nombres mediante túneles o proxies a producción.
Las credenciales corresponden únicamente a usuarios ficticios del stack E2E.
No se incluye el cuerpo de errores de login en los logs.

```sh
LOADTEST_DISPOSABLE=1 BASE_URL=http://127.0.0.1:4200 \
ADMIN_PASS=clave-ficticia VUS=10 DURATION=30s \
k6 run --summary-export=lectura.json loadtests/lectura.js
```

El CI del frontend ejecuta esta medición después de Playwright en su stack
Docker efímero. Publica `loadtest-results/lectura.json`, con latencias,
solicitudes, errores y checks. Umbrales: errores <1%, p95 <500 ms y p99 <1 s.
Cada usuario espera entre 2 y 4 segundos entre lecturas. Una sesión compartida
sirve para medir lecturas; esta prueba no certifica concurrencia de escrituras
ni capacidad máxima, y usa un conjunto pequeño de datos ficticios.

Comparar métricas usando el mismo número de usuarios, duración, datos e
infraestructura. La variabilidad de los runners requiere repetir mediciones
antes de atribuir una mejora al código. Falta medir consultas con datos de
volumen representativo y EXPLAIN (ANALYZE, BUFFERS) en preproducción. No se
han modificado índices sin esas evidencias.
