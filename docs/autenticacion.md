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

## Códigos de recuperación del administrador (V25)

Si el administrador olvida su contraseña ya no hace falta entrar a Render:

1. Desde **Mi cuenta → Códigos de recuperación** genera 8 códigos de un solo
   uso (pide la contraseña actual) y los guarda impresos en un lugar seguro.
2. Si la olvida, en **¿Olvidaste tu contraseña? → Tengo un código** escribe su
   usuario, un código y la contraseña nueva. Se cierran todas sus sesiones.

Los códigos se guardan con bcrypt; tras 5 intentos fallidos la recuperación se
bloquea por tiempo creciente. Generar códigos nuevos anula los anteriores.
`ADMIN_RESET_PASSWORD` sigue disponible como último recurso desde Render.

### Actualización a V27

Antes del despliegue, el responsable de planta debe comprobar que puede iniciar sesión con su propia
contraseña o que dispone del procedimiento de recuperación desde Render. V27 retira el código
compartido instalado por V26 si aún estaba disponible. Los lotes personales siguen vigentes.
Después de desplegar, verificar en el registro del migrador la versión 27 y consultar **Mi cuenta**
con la cuenta administrativa. Si necesita un lote personal, generarlo y guardarlo en privado.

Cada emisión reemplaza el lote completo, incluso desde dos sesiones simultáneas. Cambiar de rol
invalida los códigos de esa cuenta. Si se necesita revertir la aplicación, conservar V27 y su
checksum en la versión de corrección para que el migrador reconozca el esquema.

## Correo de recuperación (V29)

Cada usuario puede registrar su correo en **Mi cuenta**. El correo queda verificado cuando escribe el código de 6 dígitos que le llega. Con un correo verificado, en **¿Olvidaste tu contraseña? → Por correo** escribe su usuario, recibe un código y crea una contraseña nueva.

- **Envío:** Render (plan gratis) bloquea el correo SMTP. Por eso los correos salen por un script de Google Apps Script publicado desde la cuenta de Gmail del administrador, con hasta ~100 correos al día. El administrador lo activa en Mi cuenta → Envío de correos: copia el script, que ya trae el secreto, lo implementa como aplicación web («Ejecutar como: Yo», «Cualquier usuario») y pega la URL `/exec`.
- **Seguridad:**
  - La app solo acepta URLs de `script.google.com`.
  - Los códigos vencen en 15 minutos, se guardan con bcrypt y admiten 5 intentos.
  - Se envía como máximo un código por minuto y cinco por hora.
  - Pedir un código responde siempre lo mismo y el correo sale en segundo plano.
  - Cambiar o quitar el correo exige la contraseña actual.
  - Recuperar cierra todas las sesiones y avisa al correo.
- Quien no tiene correo verificado sigue con la contraseña temporal que entrega un responsable. El administrador conserva además sus códigos impresos.

### Retirada del código administrativo de V30

V32 retira el código compartido de V30 si continúa disponible. La comprobación usa el prefijo
y el hash completo aunque la cuenta haya cambiado de nombre. Un código ya utilizado conserva
su fecha de uso. La contraseña, las sesiones y los lotes personales se conservan.

**Comprobación del titular.** V30 asignó directamente un correo de recuperación. La etiqueta
«verificado» por sí sola no acredita que el titular recibiera un mensaje. El titular debe
comprobar el buzón por un canal conocido y completar la verificación desde **Mi cuenta** con su
contraseña actual. Si ya lo verificó personalmente después de V30, puede conservarlo. Si la
dirección es incorrecta, debe quitarla desde **Mi cuenta** y registrar la correcta. Si falta
activar el envío, debe conservar el acceso por contraseña y sus códigos personales mientras
se completa la verificación. V32 retira la marca automática cuando la dirección y la fecha coinciden con V30. Para reconocerla usa
el registro original del código o la fecha de aplicación registrada por el migrador propio.
También invalida los códigos de recuperación por correo pendientes de esa cuenta. Conserva la
dirección y las verificaciones posteriores. En instalaciones con Flyway que hayan eliminado el
registro original y carezcan de la fecha del migrador propio, la comprobación corresponde al titular.

**Comprobación del despliegue.** En Render, confirmar la aplicación de V32 en el registro del
migrador. En la base desplegada, auditar la revocación contando las filas que satisfacen el
mismo prefijo y hash de V30, filtrando las filas con `usado_en IS NULL`. El resultado esperado es cero. La prueba del acceso del titular
consiste en iniciar sesión con su propia contraseña. Para un rollback de la aplicación,
conservar V32 y su checksum en el paquete de migraciones.

### Entrega de códigos de recuperación (V33)

El envío de recuperación se registra como pendiente. Cuando el servicio de Google confirma la
solicitud, el código queda aceptado y reemplaza a los anteriores. Aceptado indica que Google
procesó el envío; la recepción en la bandeja se comprueba con el titular. Un fallo deja
disponible el último código aceptado hasta que venza o se utilice. La persona puede solicitar
otro después de un minuto, hasta cinco solicitudes por hora. Cambiar de buzón invalida los
códigos de recuperación anteriores.

En una prueba con un buzón controlado, verificar la dirección en Mi cuenta, pedir el código
desde el login y completar el cambio de contraseña. Para diagnosticar el envío se pueden
contar las filas por estado sin consultar direcciones, hashes ni el contenido de los mensajes.
Un envío que permanece pendiente tras vencer puede corresponder a un proceso interrumpido.
