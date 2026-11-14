#!/usr/bin/env python3
"""Respaldos cifrados y simulacros de restauración sin elegir bases de destino."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4


class ErrorOperacion(RuntimeError):
    pass


def configuracion(env: dict, variable="DATABASE_URL") -> dict:
    resultado = dict(env)
    url = env.get(variable, "")
    if url:
        partes = urlsplit(url)
        if partes.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ErrorOperacion("La URL debe ser de PostgreSQL.")
        for nombre, valor in {
            "PGHOST": partes.hostname,
            "PGPORT": str(partes.port or 5432),
            "PGUSER": unquote(partes.username or ""),
            "PGPASSWORD": unquote(partes.password or ""),
            "PGDATABASE": unquote(partes.path.lstrip("/")),
        }.items():
            resultado[nombre] = valor or ""
        permitidos = {"sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "options": "PGOPTIONS"}
        for clave, valores in parse_qs(partes.query).items():
            if clave not in permitidos:
                raise ErrorOperacion("Parámetro de conexión no soportado por el respaldo.")
            resultado[permitidos[clave]] = valores[-1]
    if not all(resultado.get(k) for k in ("PGHOST", "PGDATABASE", "PGUSER")):
        raise ErrorOperacion("Configura DATABASE_URL o PGHOST, PGDATABASE y PGUSER.")
    resultado.setdefault("PGCONNECT_TIMEOUT", "10")
    # Los binarios reciben credenciales por entorno, nunca en argumentos o logs.
    resultado.pop("DATABASE_URL", None)
    resultado.pop("RESTORE_DATABASE_URL", None)
    return resultado


def ejecutar(argumentos, env, *, salida=False):
    try:
        proceso = subprocess.run(argumentos, env=env, capture_output=True, timeout=900, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErrorOperacion(f"No se pudo ejecutar {argumentos[0]}.") from exc
    if proceso.returncode:
        raise ErrorOperacion(f"Falló {argumentos[0]}; revisa conexión, permisos y versiones del cliente.")
    return proceso.stdout.decode().strip() if salida else None


def tuberia(primero, segundo, env, destino=None):
    procesos = []
    with tempfile.TemporaryFile() as errores:
        try:
            origen = subprocess.Popen(primero, env=env, stdout=subprocess.PIPE, stderr=errores)
            procesos.append(origen)
            consumidor = subprocess.Popen(
                segundo, env=env, stdin=origen.stdout, stdout=destino or subprocess.DEVNULL, stderr=errores
            )
            procesos.append(consumidor)
            origen.stdout.close()
            consumidor.wait(timeout=900)
            origen.wait(timeout=900)
            if any(p.returncode for p in procesos):
                raise ErrorOperacion("Falló la exportación, el cifrado o la restauración.")
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ErrorOperacion("No se pudo completar el respaldo/restauración.") from exc
        finally:
            for proceso in procesos:
                if proceso.poll() is None:
                    proceso.kill()
                proceso.wait()


def sha256(archivo: Path) -> str:
    h = hashlib.sha256()
    with archivo.open("rb") as entrada:
        for bloque in iter(lambda: entrada.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def guardar_json(archivo: Path, datos):
    temporal = archivo.with_suffix(archivo.suffix + ".partial")
    try:
        with temporal.open("x", encoding="utf-8") as salida:
            os.fchmod(salida.fileno(), 0o600)
            json.dump(datos, salida, indent=2)
            salida.flush()
            os.fsync(salida.fileno())
        os.replace(temporal, archivo)
    finally:
        temporal.unlink(missing_ok=True)


def respaldo(env: dict) -> Path:
    config = configuracion(env)
    origen_id = hashlib.sha256(
        f"{config['PGHOST']}:{config.get('PGPORT', '5432')}/{config['PGDATABASE']}".encode()
    ).hexdigest()
    destinatario = env.get("BACKUP_AGE_RECIPIENT")
    remoto = env.get("BACKUP_REMOTE", "")
    pruebas = env.get("APP_ENV") == "testing" and config["PGDATABASE"].endswith("_test")
    if not destinatario:
        raise ErrorOperacion("Falta BACKUP_AGE_RECIPIENT: no se crean copias sin cifrar.")
    if not pruebas and not re.match(r"^[A-Za-z0-9_-]+:.+", remoto):
        raise ErrorOperacion("Configura BACKUP_REMOTE con un destino externo de rclone.")
    seleccion = env.get("BACKUP_SCHEMAS", "").strip()
    esquemas = [nombre.strip() for nombre in seleccion.split(",")] if seleccion else []
    if any(not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", nombre) for nombre in esquemas):
        raise ErrorOperacion("BACKUP_SCHEMAS debe contener nombres simples separados por comas.")
    argumentos_dump = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges"]
    argumentos_dump.extend(f"--schema={nombre}" for nombre in dict.fromkeys(esquemas))
    retencion = int(env.get("RETENTION_DAYS", "14"))
    if retencion < 1:
        raise ErrorOperacion("RETENTION_DAYS debe ser mayor a cero.")
    carpeta = Path(env.get("BACKUP_DIR", "backups")).resolve()
    carpeta.mkdir(mode=0o700, parents=True, exist_ok=True)
    nombre = f"datacontrol-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex}.dump.age"
    archivo = carpeta / nombre
    parcial = carpeta / (nombre + ".partial")
    try:
        with parcial.open("xb") as salida:
            os.fchmod(salida.fileno(), 0o600)
            tuberia(
                argumentos_dump,
                ["age", "--recipient", destinatario],
                config,
                salida,
            )
            salida.flush()
            os.fsync(salida.fileno())
        os.replace(parcial, archivo)
        guardar_json(
            archivo.with_suffix(archivo.suffix + ".json"),
            {
                "version": 1,
                "source_id": origen_id,
                "archivo": nombre,
                "sha256": sha256(archivo),
                "creado_en": datetime.now(UTC).isoformat(),
                "formato": "pg_dump-custom+age",
                "schemas": esquemas,
            },
        )
        if remoto:
            for pieza in (archivo, archivo.with_suffix(archivo.suffix + ".json")):
                ejecutar(["rclone", "copyto", str(pieza), f"{remoto.rstrip('/')}/{pieza.name}"], config)
        # Retención local solo tras completar ambas copias remotas (o en pruebas).
        limite = datetime.now(UTC) - timedelta(days=retencion)
        for viejo in carpeta.glob("datacontrol-*.dump.age"):
            if viejo == archivo or viejo.is_symlink():
                continue
            meta = viejo.with_suffix(viejo.suffix + ".json")
            if not meta.is_file() or meta.is_symlink():
                continue
            datos = json.loads(meta.read_text())
            if (
                datos.get("archivo") == viejo.name
                and datos.get("source_id") == origen_id
                and datos.get("schemas", []) == esquemas
                and datetime.fromisoformat(datos["creado_en"]) < limite
            ):
                viejo.unlink()
                meta.unlink()
        return archivo
    finally:
        parcial.unlink(missing_ok=True)


def restaurar_prueba(archivo: Path, env: dict) -> dict:
    if env.get("TEST_DB"):
        raise ErrorOperacion("TEST_DB ya no se admite: el destino temporal se genera automáticamente.")
    if not env.get("RESTORE_DATABASE_URL"):
        raise ErrorOperacion("Falta RESTORE_DATABASE_URL del entorno independiente de pruebas.")
    identidad = env.get("BACKUP_AGE_IDENTITY")
    if not identidad:
        raise ErrorOperacion("Falta BACKUP_AGE_IDENTITY para descifrar el respaldo.")
    archivo = archivo.resolve(strict=True)
    meta = json.loads(archivo.with_suffix(archivo.suffix + ".json").read_text())
    if (
        meta.get("version") != 1
        or meta.get("archivo") != archivo.name
        or sha256(archivo) != meta.get("sha256")
    ):
        raise ErrorOperacion("El respaldo no coincide con su manifiesto de integridad.")
    config = configuracion(env, "RESTORE_DATABASE_URL")
    destino = f"datacontrol_restore_test_{uuid4().hex}"
    # Nunca aceptar nombres recibidos desde el usuario ni usar --clean sobre una base existente.
    creada = False
    inicio = datetime.now(UTC)
    try:
        ejecutar(["createdb", "--maintenance-db=postgres", "--template=template0", destino], config)
        creada = True  # Solo la ejecución que creó la base puede borrarla.
        tuberia(
            ["age", "--decrypt", "--identity", identidad, str(archivo)],
            [
                "pg_restore",
                "--dbname",
                destino,
                "--single-transaction",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
            ],
            config,
        )
        sql = (
            "SELECT json_build_object('usuarios',(SELECT count(*) FROM usuarios),"
            "'ordenes',(SELECT count(*) FROM ordenes_produccion),"
            "'migraciones',(SELECT count(*) FROM esquema_migraciones),"
            "'cantidad_programada_kg',(SELECT coalesce(sum(cantidad_programada),0)::text "
            "FROM ordenes_produccion))"
        )
        conteos = json.loads(
            ejecutar(
                ["psql", "--dbname", destino, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql], config, salida=True
            )
        )
        if conteos["migraciones"] < 1:
            raise ErrorOperacion("La restauración no contiene historial de migraciones.")
        return {
            "estado": "restaurado",
            "conteos": conteos,
            "duracion_segundos": (datetime.now(UTC) - inicio).total_seconds(),
        }
    finally:
        if creada:
            ejecutar(["dropdb", "--maintenance-db=postgres", "--if-exists", destino], config)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=["backup", "restore-test"])
    parser.add_argument("archivo", nargs="?", type=Path)
    args = parser.parse_args()
    try:
        if args.accion == "backup":
            print(json.dumps({"estado": "guardado", "archivo": str(respaldo(dict(os.environ)))}))
        elif args.archivo:
            print(json.dumps(restaurar_prueba(args.archivo, dict(os.environ))))
        else:
            parser.error("restore-test requiere el archivo cifrado")
    except (ErrorOperacion, ValueError, OSError, KeyError) as exc:
        # No mostrar excepciones de conexión ni argumentos que puedan contener secretos.
        print(
            f"ERROR: {exc}"
            if isinstance(exc, ErrorOperacion)
            else "ERROR: configuración o archivo inválido.",
            file=__import__("sys").stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
