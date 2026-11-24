-- V24: sabores de trocillo y harinas (nachos), como los definio planta
-- (24/11/2026). Trocillo: QUESO y POLLO. Nachos: QUESO, BLUEFLAME y HOTCHILI.
-- Crea o reactiva esos sabores; no toca los de las demas categorias.
-- La tabla temporal lleva nombre propio y se borra al final: las
-- migraciones pendientes corren en una sola transaccion (V23 usa otra).

CREATE TEMPORARY TABLE _sabor_grupo_v24 (grupo VARCHAR(100), sabor VARCHAR(100)) ON COMMIT DROP;
INSERT INTO _sabor_grupo_v24 (grupo, sabor) VALUES
    ('TROCILLO', 'QUESO'), ('TROCILLO', 'POLLO'),
    ('HARINAS (NACHOS)', 'QUESO'), ('HARINAS (NACHOS)', 'BLUEFLAME'), ('HARINAS (NACHOS)', 'HOTCHILI');

INSERT INTO sabores (nombre)
SELECT DISTINCT g.sabor FROM _sabor_grupo_v24 g
WHERE NOT EXISTS (SELECT 1 FROM sabores s WHERE upper(translate(trim(s.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(g.sabor), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')));

INSERT INTO categoria_sabor (categoria_id, sabor_id)
SELECT DISTINCT c.id, s.id
FROM categorias_producto c
JOIN _sabor_grupo_v24 g ON g.grupo = upper(translate(trim(c.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'))
JOIN sabores s ON upper(translate(trim(s.nombre), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) = upper(translate(trim(g.sabor), 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'))
ON CONFLICT DO NOTHING;

UPDATE sabores SET activo = TRUE WHERE id IN (SELECT sabor_id FROM categoria_sabor);

DROP TABLE _sabor_grupo_v24;
