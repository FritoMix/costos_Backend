-- ---------------------------------------------------------------------------
-- DATACONTROL - datos iniciales
--
-- Solo datos REALES de la planta, confirmados por el negocio: roles del
-- sistema, las tres categorias que se producen, los tres turnos, los dos
-- hornos con las categorias que puede hacer cada uno, el tipo de
-- desperdicio conocido y el peso estandar del bulto.
--
-- Productos y sabores NO se precargan a proposito: los ingresa el
-- administrador desde la pantalla de Catalogos.
--
-- El usuario administrador inicial no se crea aqui porque su contrasena
-- debe quedar cifrada con bcrypt: lo hace la API al arrancar, leyendo
-- ADMIN_USERNAME / ADMIN_PASSWORD del archivo .env
-- (ver backend/app/db/bootstrap.py).
--
-- Todos los INSERT usan ON CONFLICT DO NOTHING para poder repetirse sin
-- romper nada.
-- ---------------------------------------------------------------------------

INSERT INTO roles (codigo, nombre) VALUES
    ('admin',               'Administrador / Analista'),
    ('supervisor',          'Supervisor'),
    ('operario_horno',      'Operario de Horno'),
    ('operario_saborizado', 'Operario de Saborizado')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO categorias_producto (nombre) VALUES
    ('Papa Hojuela'),
    ('Papa Rizada'),
    ('Papa Cabello de Ángel')
ON CONFLICT (nombre) DO NOTHING;

-- Los nombres usan hora normal (AM/PM), como se pidio, no hora militar.
INSERT INTO turnos (nombre, hora_inicio, hora_fin, cruza_medianoche) VALUES
    ('Turno 1 (6:00 AM - 2:00 PM)',  '06:00', '14:00', FALSE),
    ('Turno 2 (2:00 PM - 10:00 PM)', '14:00', '22:00', FALSE),
    ('Turno 3 (10:00 PM - 6:00 AM)', '22:00', '06:00', TRUE)
ON CONFLICT (nombre) DO NOTHING;

INSERT INTO hornos (nombre) VALUES
    ('Horno 1'),
    ('Horno 2')
ON CONFLICT (nombre) DO NOTHING;

-- Que puede producir cada horno (se resuelve por nombre para no depender
-- de los ids generados).
INSERT INTO horno_categoria (horno_id, categoria_id)
SELECT h.id, c.id
FROM hornos h
JOIN categorias_producto c ON TRUE
WHERE (h.nombre = 'Horno 1' AND c.nombre IN ('Papa Hojuela', 'Papa Rizada'))
   OR (h.nombre = 'Horno 2' AND c.nombre = 'Papa Cabello de Ángel')
ON CONFLICT DO NOTHING;

INSERT INTO tipos_desperdicio (nombre) VALUES
    ('Papa quemada')
ON CONFLICT (nombre) DO NOTHING;

-- Peso real del bulto de papa cruda confirmado por la planta. El
-- administrador puede cambiarlo despues en Catalogos > Configuracion.
INSERT INTO configuracion_planta (id, peso_estandar_bulto_kg) VALUES
    (1, 50.00)
ON CONFLICT (id) DO NOTHING;
