-- No se guardan JWT ni nombres/IP en texto plano.
CREATE TABLE sesiones_usuario (
    token_hash VARCHAR(64) PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    expira_en TIMESTAMPTZ NOT NULL,
    ultima_actividad TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_sesiones_usuario_usuario_id ON sesiones_usuario(usuario_id);
CREATE INDEX ix_sesiones_usuario_expira_en ON sesiones_usuario(expira_en);

CREATE TABLE intentos_login (
    clave VARCHAR(64) PRIMARY KEY,
    fallos INTEGER NOT NULL DEFAULT 0 CHECK (fallos >= 0),
    ultimo_intento TIMESTAMPTZ NOT NULL,
    bloqueado_hasta TIMESTAMPTZ
);
CREATE INDEX ix_intentos_login_ultimo_intento ON intentos_login(ultimo_intento);
