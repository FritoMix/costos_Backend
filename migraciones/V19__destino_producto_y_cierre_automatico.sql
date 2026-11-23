-- ---------------------------------------------------------------------------
-- DATACONTROL - destino del producto, aviso de fin y cierre automatico
--
-- * productos.destino: nacional, exportacion o ambos. Al crear la orden
--   solo se ofrecen los productos de su destino. Los productos que ya
--   existen quedan en "ambos" para no cambiar nada de lo que hoy funciona;
--   el administrador los ajusta en Catalogos > Productos.
-- * Nuevos avisos: "se acabo el tiempo" (supervisores y administradores)
--   y "la app cerro la orden" cuando nadie la finalizo 30 minutos despues
--   de su hora de fin.
-- * ordenes_produccion.cerrada_automaticamente: distingue el cierre de la
--   app del cierre de una persona.
-- ---------------------------------------------------------------------------

ALTER TABLE productos
    ADD COLUMN destino VARCHAR(20) NOT NULL DEFAULT 'ambos'
        CONSTRAINT ck_producto_destino CHECK (destino IN ('nacional', 'exportacion', 'ambos'));

ALTER TABLE notificaciones DROP CONSTRAINT IF EXISTS ck_notificacion_tipo_valido;
ALTER TABLE notificaciones ADD CONSTRAINT ck_notificacion_tipo_valido
    CHECK (tipo IN (
        'orden_creada',
        'produccion_por_terminar',
        'orden_para_bodega',
        'formula_lista',
        'produccion_terminada',
        'orden_cerrada_sola'
    ));

ALTER TABLE ordenes_produccion
    ADD COLUMN cerrada_automaticamente BOOLEAN NOT NULL DEFAULT FALSE;
