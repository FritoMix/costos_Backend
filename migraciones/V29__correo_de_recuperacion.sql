-- V29: correo de recuperacion por usuario y envio de correos.
-- Cada usuario puede registrar su correo en "Mi cuenta"; queda verificado
-- cuando escribe el codigo que le llega. Con un correo verificado, en
-- "¿Olvidaste tu contraseña?" recibe un codigo para crear una nueva.
-- Los correos salen por un enlace HTTPS (Google Apps Script de la cuenta de
-- Gmail del administrador): Render gratis bloquea el correo SMTP.
-- Solo agrega columnas y tablas: no cambia ni borra datos.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS correo VARCHAR(254);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS correo_verificado_en TIMESTAMPTZ;

-- Codigos de 6 digitos que llegan al correo: verificar el correo o
-- recuperar la contraseña. Se guardan cifrados con bcrypt.
CREATE TABLE codigos_correo (
    id           SERIAL PRIMARY KEY,
    usuario_id   INTEGER      NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    proposito    VARCHAR(20)  NOT NULL CHECK (proposito IN ('verificar', 'recuperar')),
    correo       VARCHAR(254) NOT NULL,
    codigo_hash  VARCHAR(100) NOT NULL,
    intentos     SMALLINT     NOT NULL DEFAULT 0,
    creado_en    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expira_en    TIMESTAMPTZ  NOT NULL,
    usado_en     TIMESTAMPTZ
);

CREATE INDEX ix_codigos_correo_usuario ON codigos_correo (usuario_id, proposito, creado_en);

-- Una sola fila: el enlace del script que envia los correos y su secreto.
CREATE TABLE configuracion_correo (
    id                SMALLINT     PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    url_envio         VARCHAR(300),
    secreto           VARCHAR(100) NOT NULL,
    actualizado_en    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
