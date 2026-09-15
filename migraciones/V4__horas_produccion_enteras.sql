-- ---------------------------------------------------------------------------
-- La produccion se programa en HORAS COMPLETAS.
--
-- Correccion pedida por la planta: no existe "5 horas y media" de produccion;
-- una orden se manda por 1, 2, 3... horas. Antes la columna era NUMERIC(5,2),
-- lo que permitia decimales sin sentido para el negocio.
--
-- Se convierte a INTEGER redondeando cualquier valor con decimales que se
-- haya alcanzado a guardar (no deberia haber ninguno, pero la conversion no
-- puede fallar si lo hay).
-- ---------------------------------------------------------------------------

ALTER TABLE ordenes_produccion
    ALTER COLUMN horas_produccion TYPE INTEGER
    USING ROUND(horas_produccion)::INTEGER;

COMMENT ON COLUMN ordenes_produccion.horas_produccion IS
    'Horas COMPLETAS que se programa mantener la orden en produccion. Minimo 1. NULL en las ordenes anteriores a esta funcion.';
