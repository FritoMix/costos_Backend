-- Se protegen escrituras nuevas sin reescribir datos históricos.
-- VALIDATE CONSTRAINT requiere revisar primero los registros existentes.
ALTER TABLE ordenes_produccion ADD CONSTRAINT ck_orden_cantidad_positiva
    CHECK (cantidad_programada > 0 AND cantidad_programada <> 'NaN'::numeric) NOT VALID;
ALTER TABLE registro_horno ADD CONSTRAINT ck_horno_bultos_positivos
    CHECK (cantidad_bultos > 0 AND cantidad_bultos <> 'NaN'::numeric) NOT VALID;
ALTER TABLE registro_saborizado ADD CONSTRAINT ck_saborizado_peso_positivo
    CHECK (kg_recibidos > 0 AND kg_recibidos <> 'NaN'::numeric) NOT VALID;
ALTER TABLE registro_saborizado ADD CONSTRAINT ck_saborizado_sabor_no_negativo
    CHECK (cantidad_sabor_kg >= 0 AND cantidad_sabor_kg <> 'NaN'::numeric) NOT VALID;
ALTER TABLE canastillas ADD CONSTRAINT ck_canastilla_peso_positivo
    CHECK (peso_kg > 0 AND peso_kg <> 'NaN'::numeric AND numero > 0) NOT VALID;
ALTER TABLE desperdicios ADD CONSTRAINT ck_desperdicio_no_negativo
    CHECK (cantidad_kg >= 0 AND cantidad_kg <> 'NaN'::numeric) NOT VALID;
