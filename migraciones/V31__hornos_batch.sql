-- V31: hornos de batch (y de horneado, como el de extruido).
-- Un horno es "continuo" (como hasta ahora: una tanda por hora y el aceite
-- por nivel del tanque en cm) o "batch": la orden lleva UN solo registro al
-- terminar, con el total de baches, y el aceite se mide por los litros que
-- se agregaron (pistola dosificadora o canecas), no por nivel.
-- Todos los hornos existentes quedan "continuo": nada cambia para ellos.

ALTER TABLE hornos ADD COLUMN IF NOT EXISTS tipo VARCHAR(10) NOT NULL DEFAULT 'continuo';
ALTER TABLE hornos DROP CONSTRAINT IF EXISTS ck_hornos_tipo;
ALTER TABLE hornos ADD CONSTRAINT ck_hornos_tipo CHECK (tipo IN ('continuo', 'batch'));

-- Los registros de un horno batch no tienen nivel de aceite.
ALTER TABLE registro_horno ALTER COLUMN nivel_aceite_inicial_cm DROP NOT NULL;
ALTER TABLE registro_horno ALTER COLUMN nivel_aceite_final_cm DROP NOT NULL;
ALTER TABLE registro_horno ALTER COLUMN diferencia_aceite_cm DROP NOT NULL;
ALTER TABLE registro_horno ALTER COLUMN temperatura_aceite_c DROP NOT NULL;

-- Cuantos baches (cargas) se hicieron en la orden de un horno batch.
ALTER TABLE registro_horno ADD COLUMN IF NOT EXISTS cantidad_baches SMALLINT;
ALTER TABLE registro_horno DROP CONSTRAINT IF EXISTS ck_registro_horno_baches;
ALTER TABLE registro_horno ADD CONSTRAINT ck_registro_horno_baches
    CHECK (cantidad_baches IS NULL OR cantidad_baches > 0);
