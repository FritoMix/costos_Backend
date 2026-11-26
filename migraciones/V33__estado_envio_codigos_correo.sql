-- NULL conserva los códigos emitidos por las versiones anteriores, hasta su vencimiento.
ALTER TABLE codigos_correo ADD COLUMN estado_envio VARCHAR(12)
    CHECK (estado_envio IN ('pendiente', 'aceptado', 'fallido'));
