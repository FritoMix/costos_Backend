# Supabase Free → Render Cron Job → Google Drive personal

Estado: configuración preparada, NO activada. El servicio web actual no cambia.
Crear un Cron Job en Render implica un servicio adicional con facturación; no se
crea automáticamente al subir este repositorio. Usar la plantilla separada
`render.backups.yaml` solo después de completar las comprobaciones siguientes.

## 1. Autorizar Drive desde tu computador

Instalar rclone y age desde sus sitios oficiales o el gestor de paquetes del
sistema. Ejecutar `rclone config`, crear un remoto llamado `gdrive`, escoger
Google Drive y el alcance `drive.file` (archivos creados por esta aplicación).
Completar la autorización en el navegador con tu cuenta personal. No configurar
una unidad compartida. Se puede utilizar el cliente OAuth incorporado en rclone;
si se usa un cliente propio, seguir la guía oficial y no dejarlo en modo Testing,
porque sus autorizaciones de Drive pueden caducar semanalmente.

El respaldo creará `DataControl-respaldos` mediante rclone. Con `drive.file` no se
pretende explorar todos tus documentos personales. No elegir alcance completo
para solucionar permisos sin revisar primero la configuración. El cliente OAuth
usado para autorizar debe ser el mismo que se copie al ejecutor.

```sh
rclone mkdir gdrive:DataControl-respaldos
rclone lsf gdrive:DataControl-respaldos
rclone config file
```

El último comando muestra la ubicación de `rclone.conf`. Proteger este archivo:
contiene autorización de acceso y no debe ir al chat, GitHub, correos ni logs.
Si contiene otros remotos, preparar una copia local que incluya únicamente la
sección `[gdrive]`. La renovación del acceso ocurre durante la ejecución; si se
revoca la autorización, reconectar desde el equipo y reemplazar el secreto.

## 2. Preparar la recuperación

```sh
age-keygen -o recuperacion.identity
age-keygen -y recuperacion.identity
```

Guardar `recuperacion.identity` en un lugar seguro separado de Render y de la
carpeta de respaldos. Conservar una segunda copia protegida. El resultado del
segundo comando es público y se usa como `BACKUP_AGE_RECIPIENT`; la clave privada
NO se instala en el Cron Job.

## 3. Comprobar Supabase

En SQL Editor ejecutar `show server_version;`. El Dockerfile de respaldo usa
cliente PostgreSQL 17 por defecto: antes de activar, comprobar compatibilidad y
ajustar `POSTGRES_IMAGE` en `deploy/backup.Dockerfile` si se requiere otra versión.
Preferir la misma versión mayor para exportación y simulacro de restauración.
La construcción en CI valida herramientas, no la versión real de tu proyecto.

En el panel Connect usar conexión directa o, si no hay IPv6, Session pooler
(puerto 5432). No usar el pooler de transacciones del puerto 6543. Configurar TLS
(`sslmode=require` o una verificación más estricta con certificado del proveedor).
Usar un usuario con permisos suficientes para las tablas de la aplicación.
No copiar la cadena al repositorio o a mensajes: ingresarla como secreto en Render.

La plantilla configura `BACKUP_SCHEMAS=public`: exporta datos, tablas, secuencias y
objetos del esquema de DataControl. Comprobar que todas sus tablas están allí.
No es una copia completa del proyecto Supabase: no incluye archivos de Storage,
esquemas internos de Auth/Storage, funciones externas, secretos o configuración
del proyecto. Si se utilizan, requieren un plan de recuperación adicional.

## 4. Crear el servicio en Render

Crear un **Cron Job**, conectar `FritoMix/costos_Backend`, rama `main`, runtime
Docker, contexto `.` y Dockerfile `deploy/backup.Dockerfile`. Conservar el comando
predeterminado de esa imagen. No sustituir el Dockerfile del backend web.

La plantilla propone `0 7 * * *` (07:00 UTC diariamente), sin garantizar puntualidad
ni activarse por sí sola. Definir la frecuencia tras medir tamaño, duración y
tráfico: copias diarias permiten perder hasta aproximadamente un día entre copias
correctas; si fallan, la pérdida potencial es mayor. El objetivo horario anterior
no queda cumplido con esta propuesta. Comprobar las cuotas vigentes de Supabase y
Drive antes de aumentar frecuencia; cada exportación transfiere datos.

Variables exclusivas del Cron Job:

| Variable | Valor |
| --- | --- |
| APP_ENV | production |
| DATABASE_URL | Conexión secreta de Supabase, directa o Session pooler |
| BACKUP_AGE_RECIPIENT | Destinatario público age |
| BACKUP_REMOTE | gdrive:DataControl-respaldos |
| BACKUP_SCHEMAS | public |
| PGSSLMODE | require (si la URL fija sslmode, prevalece ese valor) |
| RCLONE_CONFIG_SOURCE | /etc/secrets/rclone.conf |

En **Secret Files**, agregar `rclone.conf` con la configuración OAuth del remoto
`gdrive`. El ejecutor la copia a un directorio temporal privado con permisos 0600
para que rclone pueda actualizar el token durante el trabajo. Al terminar se
eliminan los temporales. La imagen no contiene secretos y se ejecuta sin root.

El trabajo cifra por tubería y sube dos archivos: `.dump.age` y `.dump.age.json`.
Solo informa éxito cuando ambos se han enviado. Un fallo devuelve código 1.
El disco local es temporal: la copia duradera debe comprobarse en Drive.
No publicar URLs de descarga ni habilitar enlaces públicos de esa carpeta.

## 5. Validar antes de confiar en el respaldo

1. Ejecutar el primer trabajo manualmente y comprobar salida 0 y ambos archivos.
2. Descargar la pareja de archivos a un entorno de pruebas independiente.
3. Seguir `docs/OPERACION.md`, usando `restore_backup_test.sh`; nunca apuntar
   `RESTORE_DATABASE_URL` al Supabase de producción. El simulacro crea y elimina
   una base temporal, por lo que el servidor de pruebas debe admitir CREATEDB.
4. Verificar conteos, cantidades, acceso y procesos funcionales recuperados.
5. Configurar avisos de ejecución fallida en Render y revisar que aparezcan copias
   recientes. Alertar también ante ausencia de ejecuciones, no solo errores.
6. Registrar duración, tamaño y fecha del simulacro. Activar el horario acordado.

Drive no tiene aquí una política automática de retención: el script SOLO rota
copias locales y estas son efímeras en Render. Revisar cuota y conservar copias
anteriores; cualquier limpieza externa debe acordarse y probarse por separado.
Una propuesta es conservar 30 días, pero esta plantilla no elimina archivos de
Drive ni garantiza esa retención. No vaciar copias previas antes del simulacro.

Fuentes: https://rclone.org/drive/ ; https://render.com/docs/cronjobs ;
https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore .
