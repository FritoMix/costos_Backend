# Estabilización: fases 2 y 3

## Alcance implementado

- Una confirmación por operación: orden, mezcla copiada, avisos y auditoría.
  Los servicios compuestos no hacen commits independientes. Los errores revierten
  el savepoint de la operación; los errores de commit revierten la sesión.
- Las notificaciones son filas de PostgreSQL: se guardan en la misma transacción,
  no requieren una cola externa ni se pierden por un fallo entre dos commits.
- Orden de acceso: bloquear orden, recargar estado/relaciones, validar, escribir.
  Las plantillas y referencias comparten un bloqueo transaccional del catálogo.
- Las restricciones de horno y fórmula activa siguen siendo la defensa final
  frente a colisiones. Las eliminaciones de registros de órdenes cerradas se rechazan.
- Revisión de fórmulas, cambios de estado y correcciones de registros dejan
  snapshots antes/después en auditoria_operaciones. La auditoría también revierte
  si la operación falla. Las llamadas internas sin actor dejan usuario_id NULL.
- Al cambiar el producto de una orden pendiente se descarta la mezcla del producto
  anterior y se intenta aplicar la nueva plantilla; en producción no se permite
  cambiar de producto. La revisión previa queda en el historial.
- Las rutas de edición/borrado comprueban que el registro pertenece a la orden de la URL.

Los cálculos de cantidades y porcentajes usan ROUND_HALF_UP de forma explícita.
Los pesos de canastilla deben ser positivos y ocupar como máximo dos decimales,
acordes a NUMERIC(6,2), para que el total coincida con la suma de filas guardadas.

## Estados y reintentos

| Acción | Origen permitido | Destino | Repetición en destino |
| --- | --- | --- | --- |
| Iniciar | pendiente | en_produccion | Devuelve la orden sin cambiar hora_inicio |
| Finalizar | en_produccion | finalizada | Devuelve la orden sin cambiar hora_fin |
| Cancelar | pendiente/en_produccion | cancelada | Devuelve la orden sin repetir efectos |

Los demás cruces se rechazan. El borrado administrativo de una orden conserva
el mecanismo de borrado suave y su cascada, con historial.

Las creaciones de órdenes, tandas y recepciones aceptan Idempotency-Key (16–128
caracteres). La clave se separa por usuario y operación. Solicitudes simultáneas
con la misma clave y datos recuperan exactamente el mismo resultado; datos
cambiados reciben 409. Efectos y respuesta se confirman juntos. Los errores no
consumen la clave. La ventana de retención es 24 h.

Angular genera una clave por envío y la conserva para el mismo formulario tras
un error de red o 5xx. Una nueva operación confirmada recibe otra clave.
La conservación del cliente es en memoria: no sobrevive a recargar/cerrar la
aplicación. Integraciones externas deben conservar su propia clave entre reintentos.
Los clientes antiguos que omitan la cabecera conservan compatibilidad, sin garantía
de deduplicación de creaciones. Las validaciones de solapamiento siguen aplicándose.

## Migraciones

V1–V14 permanecen sin modificaciones. V15 añade idempotencia y auditoría; V16
protege cantidades nuevas. checksums.json identifica cada archivo SQL con SHA-256.
El arranque rechaza cambios de archivos, versiones duplicadas, huecos, archivos
faltantes y diferencias con hashes ya registrados. El historial registra el hash
en la misma transacción que el SQL. El bloqueo entre workers se mantiene.

En la primera actualización de un historial antiguo sin hashes se adopta el
manifiesto publicado y se escribe una advertencia. Esto no demuestra los bytes
que se ejecutaron históricamente: contrastar antes el origen de la instalación.
No ejecutar Flyway simultáneamente con el migrador propio.

## Datos existentes: revisión pendiente antes de cerrar fase 2

Las restricciones nuevas se crean NOT VALID: se aplican a nuevas escrituras y
actualizaciones, sin borrar ni inventar valores antiguos. Ejecutar en una copia
saneada y después en la base real, con acceso de solo lectura:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/verificar_integridad.sql
```

Resolver los registros que devuelva con la empresa y conservar su trazabilidad.
Después ejecutar ALTER TABLE ... VALIDATE CONSTRAINT para cada restricción de
V16 sobre una copia primero. No declarar cerrada la integridad histórica hasta
que todas estén validadas. Obtener un respaldo comprobado antes de intervenir datos.

## Si falla una migración

1. Mantener el servicio fuera de tráfico; no desactivar las verificaciones.
2. Leer el error y el historial en modo lectura. El lote fallido revierte SQL
   e historial juntos; los archivos de migraciones publicadas no se editan.
3. Si falla un checksum, recuperar los archivos exactos del commit desplegado.
4. Si falla una migración nueva por datos, reproducir sobre una copia y corregir
   mediante un procedimiento revisado o una versión nueva; no marcarla aplicada
   a mano ni borrar filas del historial para forzar el arranque.
5. Reintentar el mismo artefacto corregido compatible. Un rollback de código debe
   evaluarse con el esquema ya confirmado; no se ejecutan migraciones inversas
   destructivas automáticamente.

## Evidencia y límites

Las pruebas añaden fallos de fórmula/avisos/recalculo, rollback de DDL, actualización
V14 con datos ficticios existentes, comprobación de checksums e idempotencia.
La concurrencia usa conexiones reales independientes: ocupación de horno,
finalización contra cancelación, doble tanda y doble creación con la misma clave.

Queda pendiente comprobar el despliegue y una copia saneada de datos reales,
la contención/rendimiento con carga real y la aceptación de la planta.
Bodega actualmente es un catálogo y fórmulas; este cambio no inventa un sistema
de entradas/salidas de inventario ni una contabilidad monetaria inexistente.
La restauración de respaldos corresponde al bloque de continuidad separado.
