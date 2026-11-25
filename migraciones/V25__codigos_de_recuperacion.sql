-- V25: codigos de recuperacion del administrador.
-- El administrador genera 8 codigos de un solo uso y los guarda impresos. Si
-- olvida su contraseña, entra con su usuario y un codigo y crea una nueva,
-- sin depender de Render ni de otra persona.
-- Cada codigo tiene un identificador visible (sus 4 primeros caracteres) para
-- buscarlo, y el resto se guarda cifrado con bcrypt, como las contraseñas.

CREATE TABLE codigos_recuperacion (
    id             SERIAL PRIMARY KEY,
    usuario_id     INTEGER     NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    identificador  VARCHAR(4)  NOT NULL,
    codigo_hash    VARCHAR(100) NOT NULL,
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    usado_en       TIMESTAMPTZ
);

CREATE INDEX ix_codigos_recuperacion_usuario ON codigos_recuperacion (usuario_id, identificador);
