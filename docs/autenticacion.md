# Inicio de sesión y despliegue

El login crea un JWT con identificador aleatorio y guarda únicamente su SHA-256
en `sesiones_usuario`. Cada petición protegida verifica firma, claims, cuenta,
versión, existencia de sesión, expiración absoluta e inactividad.
Cerrar sesión elimina solo esa sesión: una copia del JWT deja de funcionar.
Cambiar contraseña, desactivar o eliminar una cuenta revoca sus sesiones.
Las cookies anteriores a V14 exigen iniciar sesión de nuevo.

## Inactividad

`SESSION_IDLE_MINUTES=30` por defecto (rango 1–480). La vigencia absoluta
continúa controlada por `ACCESS_TOKEN_EXPIRE_MINUTES` (480 por defecto).
El frontend envía `/auth/actividad` al interactuar con teclado o controles,
como máximo una vez por minuto (menos si el TTL configurado es corto).
Las consultas automáticas no renuevan la actividad. Recuperar una sesión al
cargar la app renueva su actividad solo si todavía no ha vencido.
El servidor aplica el límite aunque se suspenda la pestaña o se cambie el reloj local.
El cierre local se realiza inmediatamente; si no hay red se avisa de que no se
pudo confirmar la revocación remota. La cookie HttpOnly solo la borra el servidor.

## Intentos y auditoría

- Cinco fallos por cuenta o veinte por IP activan una espera de 30 segundos.
- Cada nuevo fallo tras la espera aumenta el bloqueo, hasta 15 minutos.
- Quince minutos sin fallos permitidos reinician el contador.
- Respuesta 429 con `Retry-After`; la política incluye cuentas inexistentes.
- Límites configurables con `LOGIN_ACCOUNT_ATTEMPTS` y `LOGIN_IP_ATTEMPTS`.
- Contadores persistentes y bloqueos de fila de PostgreSQL compartidos por workers.
- Los logs `datacontrol.auth` registran acceso correcto, fallido, limitado,
  cierre y revocación. No incluyen contraseñas, tokens ni nombres de usuario.
  Las referencias de cuenta y origen son HMAC con la clave JWT, truncadas en logs.
- Al iniciar sesión se limpian sesiones expiradas y contadores antiguos (>1 día).
  El historial de auditoría sigue la retención configurada para los logs del servicio.
- Este control no evita todos los ataques distribuidos ni sustituye un WAF.

## Render y frontend

Mantener `APP_ENV=production`, `JWT_SECRET_KEY` aleatorio de al menos 32 bytes,
`DATABASE_URL` y `CORS_ORIGINS` con los orígenes HTTPS exactos del frontend.
El Blueprint declara también CORS_ORIGINS para que se configure explícitamente.
No se guardan secretos en el repositorio.

Conservar el proxy `/api` del frontend (Vercel rewrites o Nginx): el navegador
habla con el mismo origen y la cookie sigue siendo HttpOnly, Secure y
SameSite=Strict. No apuntar Angular directamente a otro sitio ni cambiar a
SameSite=None para resolver un proxy mal configurado.

Se rechazan escrituras con Origin ajeno a la lista CORS o al propio origen.
Los endpoints de autenticación devuelven Cache-Control: no-store.
En Nginx, el límite de login existente se mantiene como defensa adicional.
Comprobar que el proxy de despliegue sobreescribe las cabeceras de IP: la
configuración actual de la API confía en cabeceras recibidas desde redes privadas.
No exponer un proxy interno que deje pasar X-Real-IP arbitrario.

## Migración y validación

V14 crea dos tablas e índices sin alterar los datos de usuarios existentes.
El migrador propio adquiere un advisory lock y confirma todas las pendientes
en una transacción, evitando aplicar la misma migración desde dos workers.
No ejecutar Flyway y el migrador propio simultáneamente: elegir un solo ejecutor.
Para Render, MIGRAR_AL_ARRANCAR=true (valor predeterminado).

Pruebas: revocación/replay, sesiones independientes, inactividad frente a polling,
heartbeat sin ampliar el vencimiento absoluto, origen, espera progresiva,
concurrencia de intentos y migraciones; más las suites previas y E2E.
