-- V22: categorias, productos (referencias) y sabores de las lineas nuevas.
-- Tomados de los graneles de la app de costos (COSTOS FRITOMIX, 24/11/2026):
-- platano, pellet, trocillo (panaderia), harinas (nachos) y extruido de maiz.
-- Solo agrega: no cambia ni borra nada. No duplica lo que ya exista aunque
-- este escrito con otras mayusculas o tildes. Los hornos de estas lineas se
-- crean en Catalogos > Hornos con sus datos reales (tanque, aceite) y ahi se
-- les asignan estas categorias.

CREATE TEMPORARY TABLE _catalogo_nuevo (categoria VARCHAR(100), producto VARCHAR(150)) ON COMMIT DROP;
INSERT INTO _catalogo_nuevo (categoria, producto) VALUES
    ('Extruido de maíz', 'DITOS'),
    ('Extruido de maíz', 'KIKECITO'),
    ('Extruido de maíz', 'KIKITOS'),
    ('Harinas (nachos)', 'NACHOS'),
    ('Pellet', 'ALMUERZO'),
    ('Pellet', 'AROS DE CEBOLLA'),
    ('Pellet', 'CROC AND NACHOS 3D'),
    ('Pellet', 'MAXIPACK'),
    ('Pellet', 'PALITROQUE'),
    ('Pellet', 'PARRILLITAS'),
    ('Pellet', 'ROSQUIS'),
    ('Pellet', 'SUPER ALMUERZO'),
    ('Pellet', 'TOCIENTA'),
    ('Pellet', 'TORNIQUETES'),
    ('Plátano', 'PLATANO MADURO'),
    ('Plátano', 'PLATANO VERDE'),
    ('Trocillo', 'TROCILLO');

INSERT INTO categorias_producto (nombre)
SELECT DISTINCT n.categoria FROM _catalogo_nuevo n
WHERE NOT EXISTS (SELECT 1 FROM categorias_producto c WHERE upper(translate(trim(c.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(n.categoria), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')));

INSERT INTO productos (nombre_comercial, categoria_id, destino)
SELECT n.producto, c.id, 'nacional'
FROM _catalogo_nuevo n
JOIN categorias_producto c ON upper(translate(trim(c.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(n.categoria), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'))
WHERE NOT EXISTS (SELECT 1 FROM productos p WHERE upper(translate(trim(p.nombre_comercial), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(n.producto), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')));

INSERT INTO sabores (nombre)
SELECT v.nombre FROM (VALUES
    ('AJO'),
    ('BBQ'),
    ('BLUEFLAME'),
    ('BOLIQUESO'),
    ('CARAMELO'),
    ('HOTCHESE'),
    ('HOTCHILI'),
    ('HOTQUESE'),
    ('JALAPEÑO'),
    ('JAMON'),
    ('LIMON'),
    ('NATURAL'),
    ('POLLO'),
    ('QUESO'),
    ('QUESO CHEDAR'),
    ('SAL'),
    ('SAL MARINA'),
    ('TOCINO'),
    ('WAKAHOTMOLE')
) AS v (nombre)
WHERE NOT EXISTS (SELECT 1 FROM sabores s WHERE upper(translate(trim(s.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(v.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')));
