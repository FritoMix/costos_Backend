-- ---------------------------------------------------------------------------
-- Duracion programada de la orden (pedido de la planta).
--
-- Al crear una orden, el supervisor indica cuantas horas va a mandar esa
-- produccion. Sirve para planear la ocupacion del horno y para comparar
-- despues contra el tiempo real de las tandas.
--
-- Se agrega como NULL porque las ordenes que ya existen no tienen este dato:
-- no se puede inventar un valor para ellas. Las ordenes nuevas si lo exigen
-- (la validacion vive en la aplicacion, ver produccion/servicios/ordenes.py).
--
-- La regla de negocio "minimo una hora" se refuerza aqui con un CHECK, para
-- que ningun camino (ni un script, ni un error de codigo) guarde algo menor.
-- ---------------------------------------------------------------------------

ALTER TABLE ordenes_produccion
    ADD COLUMN horas_produccion NUMERIC(5, 2) NULL;

COMMENT ON COLUMN ordenes_produccion.horas_produccion IS
    'Horas que se programa mantener la orden en produccion. Minimo 1. NULL en las ordenes anteriores a esta funcion.';

ALTER TABLE ordenes_produccion
    ADD CONSTRAINT ck_orden_horas_minimo_una
    CHECK (horas_produccion IS NULL OR horas_produccion >= 1);
