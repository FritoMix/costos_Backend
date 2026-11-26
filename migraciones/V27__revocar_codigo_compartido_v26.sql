-- Retira únicamente el código de V26 todavía disponible, incluso si se renombró la cuenta.
-- Conserva los códigos personales y el historial de códigos ya utilizados.
DELETE FROM codigos_recuperacion
WHERE identificador = 'YS5N'
  AND codigo_hash = '$2b$12$OMCx7dO3dkzeorogDTkM4ObBc.H0t4oYjjiyo3HO/qc1Q2Mxd/Y/W'
  AND usado_en IS NULL;
