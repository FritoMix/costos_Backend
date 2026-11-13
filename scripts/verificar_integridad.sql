-- Solo lectura. Ejecutar sobre copia saneada y posteriormente sobre producción.
SELECT 'ordenes_cantidad' AS problema, id FROM ordenes_produccion
 WHERE NOT (cantidad_programada > 0 AND cantidad_programada <> 'NaN'::numeric);
SELECT 'horno_bultos' AS problema, id FROM registro_horno
 WHERE NOT (cantidad_bultos > 0 AND cantidad_bultos <> 'NaN'::numeric);
SELECT 'saborizado_peso' AS problema, id FROM registro_saborizado
 WHERE NOT (kg_recibidos > 0 AND kg_recibidos <> 'NaN'::numeric);
SELECT 'saborizado_sabor' AS problema, id FROM registro_saborizado
 WHERE NOT (cantidad_sabor_kg >= 0 AND cantidad_sabor_kg <> 'NaN'::numeric);
SELECT 'canastillas' AS problema, id FROM canastillas
 WHERE NOT (peso_kg > 0 AND peso_kg <> 'NaN'::numeric AND numero > 0);
SELECT 'desperdicios' AS problema, id FROM desperdicios
 WHERE NOT (cantidad_kg >= 0 AND cantidad_kg <> 'NaN'::numeric);
SELECT conrelid::regclass AS tabla, conname FROM pg_constraint
 WHERE contype = 'c' AND NOT convalidated AND connamespace = current_schema()::regnamespace;
