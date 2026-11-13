from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.limite import limiter
from app.db.session import argumentos_conexion
from app.main import app


def test_liveness_no_consume_base_y_reemplaza_id_de_peticion_invalido(monkeypatch):
    from app.api import router

    def no_conectar():
        raise AssertionError("Liveness no debe consultar PostgreSQL")

    monkeypatch.setattr(router.engine, "connect", no_conectar)
    limiter.reset()
    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/vivo", headers={"X-Request-ID": "id-invalido!"})
    assert respuesta.status_code == 200
    assert len(respuesta.headers["X-Request-ID"]) == 32
    cliente.close()


def test_readiness_devuelve_503_sin_exponer_credenciales(monkeypatch):
    from app.api import router

    def fallar():
        raise OperationalError("SELECT secreto", {}, RuntimeError("password=privado"))

    monkeypatch.setattr(router.engine, "connect", fallar)
    limiter.reset()
    cliente = TestClient(app)
    respuesta = cliente.get("/api/v1/listo")
    assert respuesta.status_code == 503
    assert "privado" not in respuesta.text
    assert respuesta.headers["Cache-Control"] == "no-store"
    cliente.close()


def test_timeouts_respetan_opciones_existentes(monkeypatch):
    monkeypatch.setattr(
        settings, "database_url_externa", "postgresql://u:p@localhost/db?options=-csearch_path%3Dpublic"
    )
    args = argumentos_conexion()
    assert "-csearch_path=public" in args["options"]
    assert "statement_timeout=30000" in args["options"]
    assert args["connect_timeout"] == 5


def test_error_inesperado_conserva_traza_sin_imprimir_sus_valores(caplog):
    from fastapi import FastAPI

    from app.api.manejadores import registrar_manejadores
    from app.main import middleware_trazabilidad

    app_prueba = FastAPI()
    registrar_manejadores(app_prueba)
    app_prueba.middleware("http")(middleware_trazabilidad)

    @app_prueba.get("/error")
    def fallar():
        raise RuntimeError("password=valor-que-no-debe-publicarse")

    cliente = TestClient(app_prueba)
    respuesta = cliente.get("/error")
    assert respuesta.status_code == 500
    assert len(respuesta.headers["X-Request-ID"]) == 32
    assert "valor-que-no-debe-publicarse" not in respuesta.text + caplog.text
    assert "RuntimeError" in caplog.text
    cliente.close()
