-- V26: un codigo de recuperacion de un solo uso para el usuario admin.
-- Andres olvido la contraseña del administrador y no tiene acceso a Render.
-- Aqui solo queda el identificador y el hash bcrypt del codigo; el codigo en
-- claro se le entrego por un canal privado. Al usarlo queda gastado, y al
-- generar sus propios codigos desde Mi cuenta este se borra.

INSERT INTO codigos_recuperacion (usuario_id, identificador, codigo_hash)
SELECT id, 'YS5N', '$2b$12$OMCx7dO3dkzeorogDTkM4ObBc.H0t4oYjjiyo3HO/qc1Q2Mxd/Y/W'
FROM usuarios
WHERE nombre_usuario = 'admin';
