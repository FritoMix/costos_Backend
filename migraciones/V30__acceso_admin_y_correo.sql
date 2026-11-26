-- V30: devolver el acceso al administrador (usuario admin) sin Render.
-- Andres (responsable de la planta) no puede entrar y no tiene cuenta de
-- Render. Se le crea UN codigo de recuperacion de un solo uso: aqui solo
-- queda su identificador y su hash bcrypt; el codigo en claro se le entrego
-- por un canal privado. Al usarlo queda gastado y al generar su lote propio
-- en Mi cuenta se borra.
-- Ademas queda registrado y verificado su correo de recuperacion (lo pidio
-- el propio administrador), para recuperar por correo cuando el envio este
-- activo.

INSERT INTO codigos_recuperacion (usuario_id, identificador, codigo_hash)
SELECT u.id, 'GS5B', '$2b$12$Ex0be43f768hfJkyPZDxnune1499jdYF2I9W7cT6xBOKaKau9/5m2'
FROM usuarios u
JOIN roles r ON r.id = u.rol_id
WHERE u.nombre_usuario = 'admin'
  AND r.codigo = 'admin'
  AND u.activo
  AND NOT u.eliminado;

UPDATE usuarios u
SET correo = 'ingenieroandresramirezpalacio@gmail.com',
    correo_verificado_en = now()
FROM roles r
WHERE r.id = u.rol_id
  AND u.nombre_usuario = 'admin'
  AND r.codigo = 'admin';
