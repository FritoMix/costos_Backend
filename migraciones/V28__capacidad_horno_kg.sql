-- V28: capacidad del horno en kilos por hora para las lineas sin Bodega
-- (platano, pellet, trocillo, harinas, extruido de maiz).
-- La papa (linea con Bodega) sigue en bultos por hora, porque la formula
-- de Bodega reparte la mezcla en bultos de cada referencia.
-- Solo agrega la columna y limpia un dato que no aplica: no borra hornos.

ALTER TABLE hornos ADD COLUMN IF NOT EXISTS capacidad_kg_hora NUMERIC(8, 2);

ALTER TABLE hornos DROP CONSTRAINT IF EXISTS ck_hornos_capacidad_kg_positiva;
ALTER TABLE hornos ADD CONSTRAINT ck_hornos_capacidad_kg_positiva
    CHECK (capacidad_kg_hora IS NULL OR capacidad_kg_hora > 0);

-- Un horno de una linea sin Bodega no tiene "bultos por hora": ese valor
-- se escribio cuando la pantalla solo ofrecia bultos. Se limpia para que
-- no entre al reparto de la mezcla de papa; la planta lo registra en kg.
UPDATE hornos h
SET capacidad_bultos_hora = NULL
FROM lineas l
WHERE l.id = h.linea_id
  AND l.usa_bodega = FALSE
  AND h.capacidad_bultos_hora IS NOT NULL;
