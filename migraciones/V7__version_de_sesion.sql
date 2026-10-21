-- ---------------------------------------------------------------------------
-- DATACONTROL - version de sesion por usuario
--
-- Los JWT incluyen la version actual del usuario. Al cambiar la contrasena o
-- desactivar la cuenta esa version se incrementa y todos los tokens emitidos
-- antes dejan de ser validos, sin necesidad de guardar sesiones en la base.
-- ---------------------------------------------------------------------------

ALTER TABLE usuarios
    ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0;
