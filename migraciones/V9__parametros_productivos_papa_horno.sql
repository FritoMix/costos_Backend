-- ---------------------------------------------------------------------------
-- DATACONTROL - parametros productivos de papa y capacidad de horno
--
-- Bodega deja de guardar solo el peso del bulto: cada referencia incorpora
-- tipo de papa, rendimiento de fritura y participacion en la produccion.
-- El horno incorpora su capacidad de bultos por hora para poder proyectar
-- la distribucion entre referencias.
--
-- Los campos nuevos son NULL para los datos que ya existen. No se inventan
-- rendimientos ni participaciones historicas: Bodega/Administracion debe
-- completarlos antes de usar la referencia en una tanda nueva o proyectar.
-- Los registros de horno antiguos siguen funcionando y conservan sus kg
-- crudos; sus columnas nuevas quedan NULL.
-- ---------------------------------------------------------------------------

ALTER TABLE referencias_papa
    ADD COLUMN tipo VARCHAR(100) NULL,
    ADD COLUMN rendimiento_fritura_pct NUMERIC(7, 4) NULL,
    ADD COLUMN porcentaje_produccion_pct NUMERIC(7, 4) NULL,
    ADD COLUMN fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT NOW();

COMMENT ON COLUMN referencias_papa.tipo IS
    'Tipo o variedad de papa (ej. Papa pareja, Papa lavada).';
COMMENT ON COLUMN referencias_papa.rendimiento_fritura_pct IS
    'Porcentaje de papa cruda que se convierte en papa frita. Se copia a cada tanda.';
COMMENT ON COLUMN referencias_papa.porcentaje_produccion_pct IS
    'Participacion de esta referencia en la mezcla de produccion. Las activas deben sumar 100 %.';
COMMENT ON COLUMN referencias_papa.fecha_actualizacion IS
    'Ultima modificacion del catalogo, para auditoria.';

ALTER TABLE referencias_papa
    ADD CONSTRAINT ck_referencia_papa_tipo_no_vacio
        CHECK (tipo IS NULL OR length(btrim(tipo)) > 0),
    ADD CONSTRAINT ck_referencia_papa_rendimiento_valido
        CHECK (
            rendimiento_fritura_pct IS NULL
            OR (rendimiento_fritura_pct > 0 AND rendimiento_fritura_pct <= 100)
        ),
    ADD CONSTRAINT ck_referencia_papa_participacion_valida
        CHECK (
            porcentaje_produccion_pct IS NULL
            OR (porcentaje_produccion_pct >= 0 AND porcentaje_produccion_pct <= 100)
        );

-- Consulta caliente: referencias activas para el selector del horno.
CREATE INDEX ix_referencias_papa_activas
    ON referencias_papa (activo)
    WHERE activo = TRUE;

ALTER TABLE hornos
    ADD COLUMN capacidad_bultos_hora NUMERIC(6, 2) NULL;

COMMENT ON COLUMN hornos.capacidad_bultos_hora IS
    'Cuantos bultos de papa cruda procesa el horno en una hora. NULL hasta que la planta lo confirme.';

ALTER TABLE hornos
    ADD CONSTRAINT ck_horno_capacidad_positiva
        CHECK (capacidad_bultos_hora IS NULL OR capacidad_bultos_hora > 0),
    ADD CONSTRAINT ck_horno_capacidad_entera
        CHECK (
            capacidad_bultos_hora IS NULL
            OR capacidad_bultos_hora = TRUNC(capacidad_bultos_hora)
        );

-- Los registros historicos quedan NULL: no tenian rendimiento ni
-- participacion confiables. Las tandas nuevas los exigen y los congelan.
ALTER TABLE registro_horno
    ADD COLUMN rendimiento_fritura_pct NUMERIC(7, 4) NULL,
    ADD COLUMN porcentaje_produccion_pct NUMERIC(7, 4) NULL,
    ADD COLUMN kg_fritos_estimados NUMERIC(12, 2) NULL;

COMMENT ON COLUMN registro_horno.rendimiento_fritura_pct IS
    'Copia del rendimiento de la referencia al crear la tanda. NULL en registros historicos.';
COMMENT ON COLUMN registro_horno.porcentaje_produccion_pct IS
    'Copia de la participacion de la referencia al crear la tanda. NULL en registros historicos.';
COMMENT ON COLUMN registro_horno.kg_fritos_estimados IS
    'kg crudos x rendimiento / 100, congelado al crear la tanda. NULL en registros historicos.';

ALTER TABLE registro_horno
    ADD CONSTRAINT ck_registro_horno_rendimiento_valido
        CHECK (
            rendimiento_fritura_pct IS NULL
            OR (rendimiento_fritura_pct > 0 AND rendimiento_fritura_pct <= 100)
        ),
    ADD CONSTRAINT ck_registro_horno_participacion_valida
        CHECK (
            porcentaje_produccion_pct IS NULL
            OR (porcentaje_produccion_pct >= 0 AND porcentaje_produccion_pct <= 100)
        ),
    ADD CONSTRAINT ck_registro_horno_kg_fritos_no_negativos
        CHECK (kg_fritos_estimados IS NULL OR kg_fritos_estimados >= 0);

-- El indice de referencia_papa ya existe desde V8; no se duplica.
