-- V23: sabores por categoria. Cada categoria tiene sus sabores; en
-- saborizado solo se ofrecen esos. Una categoria sin sabores asignados acepta
-- todos los activos (asi trocillo y nachos siguen funcionando hasta que se
-- les asignen).
-- Los sabores que no quedan en ninguna categoria se DESACTIVAN (no se borran:
-- las recepciones viejas los siguen mostrando).

CREATE TABLE categoria_sabor (
    categoria_id INTEGER NOT NULL REFERENCES categorias_producto (id) ON DELETE CASCADE,
    sabor_id     INTEGER NOT NULL REFERENCES sabores (id) ON DELETE CASCADE,
    PRIMARY KEY (categoria_id, sabor_id)
);

-- Grupo de categorias -> sabores, como lo definio planta (24/11/2026).
-- 'PAPA' = todas las categorias que no son de las lineas nuevas.
CREATE TEMPORARY TABLE _sabor_grupo (grupo VARCHAR(100), sabor VARCHAR(100)) ON COMMIT DROP;
INSERT INTO _sabor_grupo (grupo, sabor) VALUES
    ('PAPA', 'LIMON'), ('PAPA', 'POLLO'), ('PAPA', 'MAYONESA'), ('PAPA', 'BBQ'), ('PAPA', 'HOTCHILI'),
    ('PELLET', 'JAMON'), ('PELLET', 'TOCINETA'), ('PELLET', 'BBQ'), ('PELLET', 'HOTCHILI'), ('PELLET', 'LIMON'),
    ('PLATANO', 'SAL'), ('PLATANO', 'LIMON'),
    ('EXTRUIDO DE MAIZ', 'NATURAL'), ('EXTRUIDO DE MAIZ', 'POLLO'), ('EXTRUIDO DE MAIZ', 'JALAPEÑO'),
    ('EXTRUIDO DE MAIZ', 'CARAMELO'), ('EXTRUIDO DE MAIZ', 'LIMON'), ('EXTRUIDO DE MAIZ', 'QUESO');

-- Crea los sabores que falten (sin duplicar por mayusculas o tildes).
INSERT INTO sabores (nombre)
SELECT DISTINCT g.sabor FROM _sabor_grupo g
WHERE NOT EXISTS (SELECT 1 FROM sabores s WHERE upper(translate(trim(s.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(g.sabor), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')));

-- Asigna los sabores a las categorias.
INSERT INTO categoria_sabor (categoria_id, sabor_id)
SELECT DISTINCT c.id, s.id
FROM categorias_producto c
JOIN _sabor_grupo g
  ON g.grupo = CASE
       WHEN upper(translate(trim(c.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) IN ('PELLET', 'PLATANO', 'EXTRUIDO DE MAIZ') THEN upper(translate(trim(c.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'))
       WHEN upper(translate(trim(c.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) IN ('TROCILLO', 'HARINAS (NACHOS)') THEN NULL
       ELSE 'PAPA'
     END
JOIN sabores s ON upper(translate(trim(s.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(g.sabor), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'))
ON CONFLICT DO NOTHING;

-- Los sabores asignados quedan activos; los demas se desactivan.
UPDATE sabores SET activo = TRUE WHERE id IN (SELECT sabor_id FROM categoria_sabor);
UPDATE sabores SET activo = FALSE WHERE id NOT IN (SELECT sabor_id FROM categoria_sabor);
