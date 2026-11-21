-- ---------------------------------------------------------------------------
-- DATACONTROL - una tanda y una recepcion por hora programada, y paradas
--
-- * Cada hora que programa el supervisor es una tanda de horno y una
--   recepcion de saborizado: numero_tanda = 1, 2, ... hasta horas_produccion.
--   La app pone la hora de cada tanda (orden.hora_inicio + (n - 1) horas) y
--   el operario ya no la digita. Una hora registrada no se repite: se corrige.
-- * El operario del horno reporta si la linea estuvo parada dentro de la
--   hora: minutos (0-60) y causa. Saborizado ve esa parada.
--
-- Los registros existentes se numeran por orden de hora de inicio. Las
-- validaciones de V9/V16 (horas, cruces, cantidades) siguen igual.
-- ---------------------------------------------------------------------------

ALTER TABLE registro_horno ADD COLUMN numero_tanda SMALLINT NULL;

UPDATE registro_horno r
SET numero_tanda = n.numero
FROM (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY orden_id ORDER BY hora_inicio, id) AS numero
    FROM registro_horno
    WHERE eliminado = FALSE
) n
WHERE r.id = n.id;

CREATE UNIQUE INDEX ux_registro_horno_tanda
    ON registro_horno (orden_id, numero_tanda)
    WHERE eliminado = FALSE AND numero_tanda IS NOT NULL;

ALTER TABLE registro_saborizado ADD COLUMN numero_tanda SMALLINT NULL;

UPDATE registro_saborizado r
SET numero_tanda = n.numero
FROM (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY orden_id ORDER BY hora_inicio, id) AS numero
    FROM registro_saborizado
    WHERE eliminado = FALSE
) n
WHERE r.id = n.id;

CREATE UNIQUE INDEX ux_registro_saborizado_tanda
    ON registro_saborizado (orden_id, numero_tanda)
    WHERE eliminado = FALSE AND numero_tanda IS NOT NULL;

ALTER TABLE registro_horno
    ADD COLUMN minutos_parada SMALLINT NOT NULL DEFAULT 0
        CONSTRAINT ck_horno_minutos_parada CHECK (minutos_parada BETWEEN 0 AND 60),
    ADD COLUMN causa_parada VARCHAR(30) NULL
        CONSTRAINT ck_horno_causa_parada CHECK (causa_parada IN (
            'falta_papa', 'dano_mecanico', 'limpieza', 'aceite',
            'falta_personal', 'gas_energia', 'otro')),
    ADD COLUMN nota_parada VARCHAR(300) NULL;

ALTER TABLE registro_saborizado
    ADD COLUMN minutos_parada SMALLINT NOT NULL DEFAULT 0
        CONSTRAINT ck_saborizado_minutos_parada CHECK (minutos_parada BETWEEN 0 AND 60),
    ADD COLUMN causa_parada VARCHAR(30) NULL
        CONSTRAINT ck_saborizado_causa_parada CHECK (causa_parada IN (
            'falta_papa', 'dano_mecanico', 'limpieza', 'aceite',
            'falta_personal', 'gas_energia', 'otro')),
    ADD COLUMN nota_parada VARCHAR(300) NULL;
