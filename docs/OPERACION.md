# Respaldos, recuperación y disponibilidad

## Estado y objetivos

Este repositorio prepara y prueba el mecanismo. No demuestra que una copia de
producción se esté generando ni que exista ya un almacenamiento externo conectado.
La receta anterior para Docker se sustituye por clientes PostgreSQL nativos,
age y rclone en un equipo de operación. No se ejecuta dentro de la API.

Propuesta a validar con FritoMix: RPO de 1 hora, RTO de 60 minutos, copia horaria,
retención local de 14 días y retención externa de 30 días mediante la política
del destino. Son objetivos, no garantías: medirlos con el tamaño y servidor reales.
La rotación externa no se ejecuta desde este script; configurar el ciclo de vida
sin permitir al usuario de respaldo borrar otros datos del destino.

## Requisitos

- Python 3.12+, pg_dump/pg_restore/psql/createdb/dropdb de una versión compatible
  con PostgreSQL origen y destino. Preferir la misma versión mayor.
- age, age-keygen y rclone instalados en el equipo de respaldo.
- Usuario origen con permisos suficientes de lectura para pg_dump; no usar las
  credenciales administrativas de la aplicación si puede evitarse.
- Destino rclone fuera del servidor principal (S3, B2 o SFTP configurados por el operador).
- Cliente remoto y conexiones PostgreSQL con TLS apropiado al proveedor.
- Usuario de restauración con CREATEDB en un entorno independiente de pruebas.

## Cifrado y configuración

Generar la identidad de recuperación en un entorno controlado:

```bash
age-keygen -o /ruta/segura/recuperacion.identity
age-keygen -y /ruta/segura/recuperacion.identity
```

Guardar la identidad privada en un almacén seguro separado del servidor principal.
El proceso de backup solo necesita el destinatario público. No subir identidades,
dumps, URLs con credenciales ni configuraciones rclone al repositorio o al chat.

Variables del proceso de backup:

| Variable | Uso |
| --- | --- |
| DATABASE_URL | PostgreSQL origen; admite postgres/postgresql/postgresql+psycopg |
| BACKUP_AGE_RECIPIENT | Destinatario público age |
| BACKUP_DIR | Directorio local, por ejemplo /var/lib/datacontrol-backups |
| BACKUP_REMOTE | Destino rclone, por ejemplo fritomix:datacontrol |
| RETENTION_DAYS | Retención local; 14 por defecto |
| RCLONE_CONFIG | Archivo privado de configuración del destino |

Alternativamente usar PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD y variables
libpq. No poner contraseñas en argumentos del comando. Las URLs admiten sslmode,
sslrootcert y options; un parámetro no soportado provoca error explícito.

```bash
./scripts/backup_postgres.sh
```

El dump se cifra por tubería sin crear un archivo plano. Se publica mediante
renombrado atómico, con archivo de integridad SHA-256 y permisos 0600. Después se
copian el cifrado y su manifiesto al destino externo. Si la exportación o la copia
remota fallan, el proceso termina con error y no elimina copias anteriores.
La retención solo se aplica tras completar la copia externa. Mantener también
versionado/inmutabilidad en el destino según sus capacidades.

## Programación fuera de Render

Las unidades de deploy/systemd son plantillas para un servidor de operación:

1. Instalar el repositorio en /opt/datacontrol y crear el usuario datacontrol.
2. Guardar el entorno privado en /etc/datacontrol/backup.env y restringir sus permisos.
3. Configurar rclone y comprobar el acceso al destino antes de habilitar el timer.
4. Instalar las unidades y ejecutar manualmente el primer respaldo.
5. Activar el timer horario únicamente después de comprobar backup y restauración.
6. Integrar los errores de la unidad y la ausencia de copias recientes con el sistema
   de alertas de la empresa. Un timer habilitado no demuestra que las copias funcionen.

En Render, usar un ejecutor de operaciones o tarea programada con estos clientes,
secretos y acceso al origen. No confiar en el disco efímero de un servicio web.
La configuración de jobs y las capacidades del plan deben comprobarse en la cuenta
real. Este cambio no crea ni activa tareas, servicios pagados o destinos externos.

## Simulacro seguro de restauración

Configurar RESTORE_DATABASE_URL del servidor de pruebas y BACKUP_AGE_IDENTITY
con la ruta a la identidad privada, y disponer del .dump.age y su .dump.age.json:

```bash
./scripts/restore_backup_test.sh /ruta/copia.dump.age
```

El script valida el manifiesto antes de conectar, genera un nombre temporal
impredecible, crea una base nueva y restaura en una transacción. Comprueba tablas,
conteos, historial de migraciones y suma de cantidades programadas, y elimina la
base temporal al salir. Nunca admite TEST_DB ni restaura con --clean sobre una base
existente. Si createdb falla, no ejecuta dropdb. Para backups antiguos sin cifrado
ni manifiesto, preparar un procedimiento aparte en un entorno aislado.

La prueba de CI exporta y restaura un backup cifrado real con datos ficticios y
compara conteos y cantidades. No sustituye un simulacro de producción ni certifica
el tiempo de recuperación del servicio completo. Medir además arranque, acceso,
permisos y los flujos funcionales antes de habilitar tráfico.

## Incidentes

- Fallo del backup/cifrado/destino: conservar las copias previas, corregir permisos
  o conexión y repetir. Alertar si la antigüedad supera el RPO acordado.
- Base o servidor caído: preservar los originales, obtener una copia externa y la
  identidad, restaurar primero en un entorno nuevo y comprobar integridad.
- Corte de red: avisar a la planta, evitar duplicar registros por reintentos manuales
  y seguir el procedimiento operativo de contingencia acordado con la empresa.
- No promover ni sobrescribir producción automáticamente. Definir el corte de
  tráfico, el destino definitivo y la validación final dentro del incidente.
- Si se necesita un RPO menor, evaluar PITR/WAL y respaldos del proveedor. Estos
  scripts son respaldos lógicos; no implementan recuperación a un punto temporal.

## API y conexiones

- GET /api/v1/vivo: vida del proceso, sin conexión PostgreSQL.
- GET /api/v1/listo: disponibilidad de una conexión y SELECT 1; devuelve 503 sin detalles internos.
- GET /api/v1/salud: contrato anterior, conservado por compatibilidad.
- Render usa /api/v1/listo como comprobación en el Blueprint.
- Pool por proceso: DB_POOL_SIZE=5 y DB_MAX_OVERFLOW=5 por defecto.
- DB_POOL_TIMEOUT_SEGUNDOS=10; DB_CONNECT_TIMEOUT_SEGUNDOS=5.
- DB_STATEMENT_TIMEOUT_MS=30000; DB_LOCK_TIMEOUT_MS=5000;
  DB_IDLE_TRANSACTION_TIMEOUT_MS=60000.
- Presupuesto máximo: procesos * (pool_size + overflow), más conexiones de otros
  consumidores. Ajustar según el límite real del PostgreSQL contratado.
- Fallos temporales de conexión, pool o consultas canceladas devuelven 503 con
  Retry-After. No se reintentan automáticamente escrituras en el servidor.
- X-Request-ID solo acepta 8–64 caracteres seguros; los demás se sustituyen.
  Los errores no registran valores de conexión ni representaciones de excepciones.

## Listado de órdenes

GET /api/v1/ordenes/pagina admite pagina (1–1000000), tamano (1–100), estado y
solo_propias. Devuelve items, total, pagina y tamano, con orden fecha/id descendente.
Mantiene los filtros de visibilidad del servicio anterior. Angular muestra páginas
de 50, cancela solicitudes obsoletas al cambiar filtros y ofrece reintento en error.
El endpoint anterior /ordenes conserva su lista limitada a 500 para clientes viejos.
La paginación de otros catálogos/reportes y las mediciones de rendimiento siguen
siendo trabajo posterior; no se ha realizado una prueba de carga sobre Render.
