# Limpieza operativa y siguientes mejoras

Alcance elegido: conservar usuarios y catálogos. Se conservan también referencias
de papa, fórmulas reutilizables, calibraciones, configuración, sesiones, controles
de acceso y migraciones. Se eliminan órdenes, mezclas por orden, tandas de horno,
recepciones, canastillas, desperdicios, notificaciones y respuestas idempotentes.
Los eventos de auditoría de estas operaciones se eliminan; se conservan otros
eventos y se añade un evento técnico de limpieza con cantidades afectadas.

No se reinician identificadores ni numeración diaria: evita reutilizar referencias
antiguas. No se elimina el esquema ni se vuelven a ejecutar migraciones históricas.
Los scripts no se ejecutan al desplegar y no hay un endpoint de borrado masivo.

## Ejecución en Supabase

1. En SQL Editor, ejecutar completo `scripts/previsualizar_limpieza.sql` y revisar
   las cantidades a borrar y conservar. Solo lee la base.
2. Detener temporalmente las escrituras del backend y cerrar las pantallas abiertas.
3. Ejecutar completo `scripts/limpiar_operaciones.sql`, con un usuario que tenga
   permisos para esas tablas. Este archivo SÍ borra las operaciones descritas.
4. Si falla un bloqueo, referencia o comprobación, la transacción se revierte:
   ejecutar ROLLBACK si el editor mantiene abierta la transacción fallida, corregir
   el problema y repetir el archivo completo. No ejecutar instrucciones sueltas.
5. Volver a ejecutar la vista previa: los contadores operativos deben ser cero y
   los conservados deben coincidir. Reactivar el backend y recargar el navegador
   para descartar datos que aún pudieran estar en caché.
6. Verificar inicio de sesión, catálogos, fórmulas reutilizables y creación de una
   nueva orden. Los backups de Drive continúan pendientes de activación.

TRUNCATE usa una lista explícita, sin CASCADE ni reinicio de secuencias; si aparece
una relación nueva fuera del alcance, PostgreSQL debe rechazar la limpieza. Todo
ocurre en una transacción con límites de espera. No se ha ejecutado esta limpieza
sobre Supabase desde este entorno: requiere el SQL Editor o una conexión operativa
autorizada. No enviar credenciales por el chat.

## Mejoras de este bloque

Las filas de órdenes y la bandeja de bodega cargan explícitamente sus relaciones
necesarias. Evitan recorrer roles, categorías vinculadas a hornos, referencias de
papa y otras relaciones que no aparecen en la respuesta. Las pruebas limitan el número de consultas y comparan respuestas para detectar
regresiones de carga sin bloquear lecturas posteriores del detalle.
No cambia el contrato HTTP ni la visibilidad de las órdenes por rol.

Análisis valida identificadores positivos, fechas válidas y rangos cronológicos.
Los errores de filtros se devuelven como 422 con ubicación query, en lugar de
convertir una excepción de Pydantic en 500. Las fechas vacías siguen sin filtrar.

Las pruebas de rendimiento comparan las consultas con el comportamiento anterior
en una base ficticia. Son evidencia de consultas evitadas, no una certificación de
capacidad en Render o Supabase. Continúan pendientes paginar la bandeja de bodega,
otros catálogos, medir volúmenes reales y ajustar índices según EXPLAIN.
