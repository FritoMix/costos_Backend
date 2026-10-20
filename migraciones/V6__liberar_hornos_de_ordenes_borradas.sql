-- ---------------------------------------------------------------------------
-- DATACONTROL - liberar hornos de ordenes borradas
--
-- El borrado es suave: la fila queda con eliminado = true para auditoria.
-- Antes, una orden En produccion borrada conservaba ese estado y el indice
-- unico parcial ux_un_horno_en_produccion seguia considerandola, por lo que
-- el horno quedaba bloqueado para siempre.
--
-- Se cierran como Canceladas las ordenes borradas que hayan quedado activas.
-- A partir de ahora el servicio de borrado hace lo mismo en la misma
-- transaccion (ver eliminar_orden en produccion/servicios/ordenes.py).
-- ---------------------------------------------------------------------------

UPDATE ordenes_produccion
SET estado = 'cancelada'
WHERE eliminado = true
  AND estado IN ('pendiente', 'en_produccion');
