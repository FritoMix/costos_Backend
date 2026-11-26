-- Huella exacta del código emitido por V30. La cuenta puede haber cambiado de nombre.
-- Conserva el historial de uso y cualquier código personal con el mismo prefijo.
DELETE FROM codigos_recuperacion
WHERE identificador = 'GS5B'
  AND codigo_hash = '$2b$12$Ex0be43f768hfJkyPZDxnune1499jdYF2I9W7cT6xBOKaKau9/5m2'
  AND usado_en IS NULL;
