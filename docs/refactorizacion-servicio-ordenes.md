# Servicio de órdenes: responsabilidades y transacciones

## Mapa de responsabilidades

Todos los archivos indicados viven en `app/modules/produccion/servicios/`.

| Archivo | Responsabilidad |
| --- | --- |
| `ordenes.py` | Fachada de los routers y coordinación de crear, editar, iniciar, finalizar, cancelar y eliminar. Cada operación de escritura mantiene su decorador `@atomica`. |
| `consultas_ordenes.py` | Lectura de órdenes, visibilidad del supervisor, filtros, paginación y búsqueda de la orden que ocupa un horno. |
| `numeracion_ordenes.py` | Consecutivo diario `OP-AAAAMMDD-0001` mediante UPSERT PostgreSQL. Participa en la transacción de creación. |
| `validaciones_ordenes.py` | Horas completas, destino, unidad y compatibilidad de horno, producto, categoría y turno. Conserva el turno anterior al editar si fue desactivado. |
| `cantidades_ordenes.py` | Conversión de canastillas a kg con el peso del producto o el general, Decimal, ROUND_HALF_UP y límites del resultado. |
| `formula.py` y `formulas_papa.py` | Validación, aplicación y conservación de la mezcla; las operaciones de órdenes delegan en estos servicios existentes. |
| `registros.py` | Bloqueo y recarga de la orden antes de validar escrituras. |

Las consultas, validaciones, cantidades y numeración no ejecutan commit. Se mantiene una separación mediante funciones; no se añaden clases de repositorios ni cambios al contrato HTTP.

## Unidad de trabajo

1. La operación pública entra por `@atomica` y abre el savepoint de la unidad de trabajo existente.
2. Si modifica una orden existente, conserva el bloqueo y la recarga antes de validar el estado.
3. Consulta catálogos o disponibilidad y delega cálculos o fórmula según el caso.
4. Guarda los cambios, los avisos y la auditoría en la misma transacción. Los servicios anidados detectan la unidad de trabajo y no confirman por separado.
5. Si todo termina correctamente, la operación superior llama una sola vez a `Session.commit()`. Ante un fallo, se revierte el savepoint y se propaga el error. El mecanismo de `app/db/transacciones.py` no se modifica.

Un `flush()` envía cambios pendientes a PostgreSQL, pero no confirma la transacción. `_guardar_cambio_de_horno()` centraliza el flush y la recarga de edición e inicio, traduciendo únicamente la restricción `ux_un_horno_en_produccion` al mismo mensaje de conflicto anterior. Los demás errores siguen propagándose.

El chequeo de horno libre no sustituye el índice único: una segunda operación puede observarlo libre simultáneamente y PostgreSQL debe seguir rechazando el conflicto. No se modifica el orden de los bloqueos.

## Contratos y reglas conservados

- Los routers siguen accediendo a `servicios.ordenes`. La fachada reexporta las lecturas, numeración y cálculo públicos existentes.
- Los cambios de estados siguen pasando por la máquina de estados de `dominio/estados.py`, incluidos los reintentos sin repetir efectos.
- Se mantienen las fórmulas congeladas, la recuperación de fórmula activa al iniciar, las restricciones de horas y la liberación del horno al cerrar o eliminar.
- El borrado suave conserva su cascada sobre tandas y recepciones y su auditoría.
- El consecutivo diario y su actualización participan en la transacción de la orden; un fallo posterior no consume el consecutivo de negocio. El ID interno de PostgreSQL puede tener saltos, como antes.
- Los permisos permanecen en los routers y dependencias de identidad. Las restricciones de integridad SQL y los schemas Pydantic no cambian.

## Pruebas

`tests/test_ordenes_flujo.py` apunta ahora directamente a las funciones extraídas. La suite de integración existente cubre endpoints, visibilidad, paginación, cantidad de consultas, transiciones, fórmulas, borrado, idempotencia y conexiones PostgreSQL concurrentes.

`tests/integration/test_refactor_ordenes.py` añade seis casos que cuentan las llamadas a `Session.commit()` al crear, editar, iniciar, finalizar, cancelar y eliminar; creación e inicio incluyen la aplicación de plantilla dentro de la operación. Verifica también los eventos de auditoría y el recálculo al editar. Otro caso provoca un fallo después de asignar el número: no se confirman orden ni auditoría y el reintento conserva el primer consecutivo.

Las mediciones de consultas y los resultados definitivos quedan en GitHub Actions del PR de `refactor/servicio-ordenes`.
