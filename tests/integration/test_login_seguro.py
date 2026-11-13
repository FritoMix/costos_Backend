"""Regresiones del login, revocación, inactividad y controles compartidos."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import CredencialesInvalidas
from app.core.limite import limiter
from app.main import app
from app.modules.identidad import sesiones
from app.modules.identidad.models import IntentoLogin, SesionUsuario
from tests.integration.test_api import PASSWORD, _login
from tests.integration.test_api import cliente as fixture_cliente

API = "/api/v1/auth"


@pytest.fixture(name="cliente")
def cliente_login(db, datos_base):
    yield from fixture_cliente.__wrapped__(db, datos_base)


def test_logout_revoca_la_copia_del_token_y_es_idempotente(cliente):
    _login(cliente)
    token = cliente.cookies.get(settings.cookie_nombre)
    assert cliente.post(f"{API}/logout").status_code == 204
    copia = TestClient(app)
    try:
        copia.cookies.set(settings.cookie_nombre, token)
        assert copia.get(f"{API}/yo").status_code == 401
        assert copia.post(f"{API}/logout").status_code == 204
    finally:
        copia.close()


def test_dos_inicios_generan_sesiones_independientes(cliente, db):
    _login(cliente)
    primera = cliente.cookies.get(settings.cookie_nombre)
    _login(cliente)
    segunda = cliente.cookies.get(settings.cookie_nombre)
    assert primera != segunda
    assert db.get(SesionUsuario, sesiones.hash_token(primera)) is not None
    assert db.get(SesionUsuario, sesiones.hash_token(segunda)) is not None
    assert cliente.post(f"{API}/logout").status_code == 204
    assert db.get(SesionUsuario, sesiones.hash_token(primera)) is not None


def test_inactividad_no_se_renueva_por_lecturas_automaticas(cliente, db, monkeypatch):
    _login(cliente)
    token = cliente.cookies.get(settings.cookie_nombre)
    sesion = db.get(SesionUsuario, sesiones.hash_token(token))
    inicio = sesion.ultima_actividad
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio + timedelta(minutes=29))
    assert cliente.get("/api/v1/usuarios").status_code == 200
    db.refresh(sesion)
    assert sesion.ultima_actividad == inicio
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio + timedelta(minutes=30))
    assert cliente.get("/api/v1/usuarios").status_code == 401
    assert cliente.post(f"{API}/actividad").status_code == 401


def test_actividad_renueva_sesion_sin_extender_expiracion_absoluta(cliente, db, monkeypatch):
    _login(cliente)
    token = cliente.cookies.get(settings.cookie_nombre)
    sesion = db.get(SesionUsuario, sesiones.hash_token(token))
    inicio, expiracion = sesion.ultima_actividad, sesion.expira_en
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio + timedelta(minutes=20))
    assert cliente.post(f"{API}/actividad").status_code == 204
    db.refresh(sesion)
    assert sesion.ultima_actividad == inicio + timedelta(minutes=20)
    assert sesion.expira_en == expiracion
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio + timedelta(minutes=40))
    assert cliente.get("/api/v1/usuarios").status_code == 200
    monkeypatch.setattr(sesiones, "ahora", lambda: expiracion)
    assert cliente.get("/api/v1/usuarios").status_code == 401


@pytest.mark.parametrize("nombre", ["admin_prueba", "no_existe"])
def test_limite_cuenta_persistente_y_espera_progresiva(cliente, monkeypatch, nombre):
    inicio = sesiones.ahora()
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio)
    datos = {"nombre_usuario": nombre, "password": "incorrecta"}
    for _ in range(5):
        assert cliente.post(f"{API}/login", json=datos).status_code == 401
    limiter.reset()  # Reiniciar el limitador en memoria no evita el bloqueo persistido.
    respuesta = cliente.post(f"{API}/login", json=datos)
    assert respuesta.status_code == 429
    assert respuesta.headers["Retry-After"] == "30"
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio + timedelta(seconds=31))
    assert cliente.post(f"{API}/login", json=datos).status_code == 401
    respuesta = cliente.post(f"{API}/login", json=datos)
    assert respuesta.status_code == 429
    assert respuesta.headers["Retry-After"] == "60"


def test_recupera_login_tras_espera_y_resetea_fallos_de_cuenta(cliente, monkeypatch):
    inicio = sesiones.ahora()
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio)
    for _ in range(5):
        cliente.post(f"{API}/login", json={"nombre_usuario": "admin_prueba", "password": "mal"})
    monkeypatch.setattr(sesiones, "ahora", lambda: inicio + timedelta(seconds=31))
    assert (
        cliente.post(
            f"{API}/login",
            json={
                "nombre_usuario": " ADMIN_PRUEBA ",
                "password": PASSWORD,
            },
        ).status_code
        == 200
    )
    assert (
        cliente.post(
            f"{API}/login",
            json={
                "nombre_usuario": "admin_prueba",
                "password": "mal",
            },
        ).status_code
        == 401
    )


def test_bloquea_ip_que_prueba_varias_cuentas(db, datos_base, monkeypatch):
    monkeypatch.setattr(settings, "login_ip_attempts", 5)
    for i in range(5):
        with pytest.raises(CredencialesInvalidas):
            sesiones.autenticar_protegido(db, f"inventado{i}", "mal", "198.51.100.20")
    with pytest.raises(sesiones.AccesoTemporalmenteLimitado):
        sesiones.autenticar_protegido(db, "otra_cuenta", "mal", "198.51.100.20")


def test_no_guarda_token_ni_credenciales_en_auditoria(cliente, db, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="datacontrol.auth")
    _login(cliente)
    token = cliente.cookies.get(settings.cookie_nombre)
    assert "auth.login_correcto" in caplog.text
    assert PASSWORD not in caplog.text
    assert token not in caplog.text
    assert "admin_prueba" not in caplog.text
    assert all(token != s.token_hash for s in db.scalars(select(SesionUsuario)))


def test_rechaza_origen_ajeno_y_no_cachea_identidad(cliente):
    _login(cliente)
    assert cliente.get(f"{API}/yo").headers["Cache-Control"] == "no-store"
    assert cliente.post(f"{API}/logout", headers={"Origin": "https://ajeno.example"}).status_code == 403
    assert cliente.get(f"{API}/yo").status_code == 200


def test_intentos_concurrentes_no_pierden_incrementos(engine_integracion):
    barrera = Barrier(6)
    nombre, ip = "cuenta_concurrencia", "198.51.100.99"
    claves = [sesiones._clave("cuenta", nombre), sesiones._clave("ip", ip)]

    def intentar(_):
        barrera.wait()
        with Session(engine_integracion) as db:
            try:
                sesiones.autenticar_protegido(db, nombre, "mal", ip)
            except sesiones.AccesoTemporalmenteLimitado:
                return 429
            except CredencialesInvalidas:
                return 401

    try:
        with ThreadPoolExecutor(max_workers=6) as ejecutor:
            resultados = list(ejecutor.map(intentar, range(6)))
        assert sorted(resultados) == [401] * 5 + [429]
        with Session(engine_integracion) as db:
            assert db.get(IntentoLogin, claves[0]).fallos == 5
    finally:
        with Session(engine_integracion) as db:
            db.execute(delete(IntentoLogin).where(IntentoLogin.clave.in_(claves)))
            db.commit()
