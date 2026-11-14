#!/usr/bin/env python3
"""Ejecutor efímero de Render: mantiene la configuración OAuth fuera de la imagen."""

import os
import tempfile
from pathlib import Path

try:
    from scripts.backup_postgres import ErrorOperacion, respaldo
except ModuleNotFoundError:
    from backup_postgres import ErrorOperacion, respaldo


def ejecutar_job(env: dict) -> None:
    fuente = Path(env.get("RCLONE_CONFIG_SOURCE", "/etc/secrets/rclone.conf"))
    try:
        contenido = fuente.read_bytes()
    except OSError:
        raise ErrorOperacion("Falta el archivo secreto rclone.conf de Render.") from None
    if not contenido.strip() or len(contenido) > 1024 * 1024:
        raise ErrorOperacion("El archivo secreto rclone.conf está vacío o es demasiado grande.")
    with tempfile.TemporaryDirectory(prefix="datacontrol-backup-") as temporal:
        configuracion = Path(temporal) / "rclone.conf"
        with configuracion.open("xb") as salida:
            os.fchmod(salida.fileno(), 0o600)
            salida.write(contenido)
        entorno = dict(env)
        entorno["RCLONE_CONFIG"] = str(configuracion)
        entorno["BACKUP_DIR"] = str(Path(temporal) / "copias")
        respaldo(entorno)
    print("Respaldo cifrado y manifiesto enviados al destino externo.")


if __name__ == "__main__":
    try:
        ejecutar_job(dict(os.environ))
    except (ErrorOperacion, OSError, ValueError):
        print("Respaldo fallido: revisa secretos, permisos, conexión y versiones. Sin detalles sensibles.")
        raise SystemExit(1) from None
