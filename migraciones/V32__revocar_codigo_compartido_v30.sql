-- V30 escribió ahora() tanto en la verificación como en la creación del código.
-- El migrador propio también registra la versión en esa misma transacción.
DO $v32$
DECLARE
    prefijo_v30 CONSTANT text := 'GS5B';
    huella_v30 CONSTANT text := '$2b$12$Ex0be43f768hfJkyPZDxnune1499jdYF2I9W7cT6xBOKaKau9/5m2';
    fecha_v30 timestamptz;
BEGIN
    -- Flyway puede ejecutar el SQL sin la tabla del migrador de la aplicación.
    IF to_regclass('esquema_migraciones') IS NOT NULL THEN
        SELECT aplicada_en INTO fecha_v30 FROM esquema_migraciones WHERE version = 30;
    END IF;

    WITH cuentas AS (
        UPDATE usuarios u SET correo_verificado_en = NULL
        -- Huella de la dirección fijada por V30, sin volver a publicar el buzón.
        WHERE sha256(convert_to(u.correo, 'UTF8')) = decode(
            'bd3ef17e761ac8d6910e44d28ddcea2729a4b2cdfe75958d0f05c2a501475342', 'hex'
        )
          AND (u.correo_verificado_en = fecha_v30 OR EXISTS (
              SELECT 1 FROM codigos_recuperacion c
              WHERE c.usuario_id = u.id AND c.identificador = prefijo_v30
                AND c.codigo_hash = huella_v30 AND c.creado_en = u.correo_verificado_en
          ))
        RETURNING u.id
    )
    UPDATE codigos_correo SET usado_en = now()
    WHERE usuario_id IN (SELECT id FROM cuentas) AND proposito = 'recuperar' AND usado_en IS NULL;

    -- Conserva los códigos personales y el historial de códigos ya utilizados.
    DELETE FROM codigos_recuperacion
    WHERE identificador = prefijo_v30 AND codigo_hash = huella_v30 AND usado_en IS NULL;
END
$v32$;
