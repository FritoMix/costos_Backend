-- ---------------------------------------------------------------------------
-- DATACONTROL - rendimiento y kg fritos opcionales en la formula de la orden
--
-- Bodega dejo de capturar tipo, rendimiento de fritura y participacion por
-- referencia: la pantalla solo pide nombre y peso por bulto, y la mezcla real
-- se define en las formulas por producto.
--
-- Las columnas se conservan (los historicos y los snapshots siguen intactos);
-- solo dejan de ser obligatorias para las formulas nuevas. Los kg fritos se
-- estiman unicamente cuando la referencia tiene rendimiento configurado.
-- ---------------------------------------------------------------------------

ALTER TABLE orden_referencias
    ALTER COLUMN rendimiento_fritura_pct DROP NOT NULL,
    ALTER COLUMN kg_fritos_por_tanda DROP NOT NULL,
    ALTER COLUMN kg_fritos_estimados DROP NOT NULL;

COMMENT ON COLUMN orden_referencias.rendimiento_fritura_pct IS
    'Rendimiento congelado al guardar la formula. NULL si la referencia no lo tenia configurado.';
COMMENT ON COLUMN orden_referencias.kg_fritos_estimados IS
    'Kg fritos planificados. NULL cuando no hay rendimiento configurado.';
