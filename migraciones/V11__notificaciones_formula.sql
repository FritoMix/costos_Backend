-- ---------------------------------------------------------------------------
-- DATACONTROL - avisos del flujo de formula por orden
--
-- Se agregan dos tipos:
--   orden_para_bodega : el supervisor creo una orden y Bodega debe definir su
--                       formula.
--   formula_lista     : Bodega guardo/corrigio la formula; horno ya puede
--                       iniciar la produccion.
--
-- orden_creada se conserva para las notificaciones historicas. Las ordenes
-- nuevas ya no lo generan.
-- ---------------------------------------------------------------------------

ALTER TABLE notificaciones DROP CONSTRAINT IF EXISTS ck_notificacion_tipo_valido;

ALTER TABLE notificaciones ADD CONSTRAINT ck_notificacion_tipo_valido
    CHECK (tipo IN (
        'orden_creada',
        'produccion_por_terminar',
        'orden_para_bodega',
        'formula_lista'
    ));
