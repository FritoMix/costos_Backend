"""Correo de recuperacion: verificar el correo y recuperar la contraseña (V29)."""

import io
import json
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.core.errores import CredencialesInvalidas, ErrorDeValidacion
from app.core.limite import limiter
from app.core.seguridad import hash_password, verificar_password
from app.db.session import get_db
from app.main import app
from app.modules.identidad import correo
from app.modules.identidad.models import CodigoCorreo
from app.modules.identidad.sesiones import AccesoTemporalmenteLimitado, ahora

ACTUAL = "ClaveActual-2026"
NUEVA = "ClaveNueva-2026"
IP = "10.0.0.9"
AUTH = "/api/v1/auth"
URL = "https://script.google.com/macros/s/AKfycbxPRUEBA1234567890abc/exec"


@pytest.fixture
def enviados(monkeypatch, db):
    """En vez de llamar a Google, guarda los correos que se habrian enviado."""
    monkeypatch.setattr(correo, "SessionLocal", sessionmaker(
        bind=db.get_bind(), join_transaction_mode="create_savepoint"
    ))
    lista: list[correo.Envio] = []
    monkeypatch.setattr(correo, "enviar", lista.append)
    return lista


@pytest.fixture
def usuario(db, datos_base):
    u = datos_base.operario_horno
    u.password_hash = hash_password(ACTUAL)
    db.flush()
    return u


@pytest.fixture
def con_envio(db):
    correo.guardar_url(db, URL)


@pytest.fixture
def cliente(db, datos_base):
    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    limiter.reset()
    c = TestClient(app)
    try:
        yield c
    finally:
        c.close()
        app.dependency_overrides.pop(get_db, None)


def _codigo(envio: correo.Envio) -> str:
    return re.search(r"Código: (\d{6})", envio.mensaje.texto).group(1)


def _verificar(db, usuario, enviados, direccion="planta@example.com"):
    correo.iniciar_verificacion(db, usuario, direccion, ACTUAL)
    return correo.confirmar_verificacion(db, usuario, _codigo(enviados[-1]))


def _envejecer(db, usuario):
    """Corre el reloj de los codigos para pasar el limite de un envio por minuto."""
    db.execute(
        update(CodigoCorreo)
        .where(CodigoCorreo.usuario_id == usuario.id)
        .values(creado_en=CodigoCorreo.creado_en - timedelta(minutes=2))
    )


def test_configuracion_solo_acepta_apps_script_y_entrega_el_script(db):
    cfg = correo.configuracion(db)
    assert len(cfg.secreto) >= 40
    assert cfg.secreto in correo.script(cfg)
    assert not correo.envio_configurado(db)
    for mala in ["https://evil.example.com/exec", "http://script.google.com/macros/s/abcdefghijk/exec"]:
        with pytest.raises(ErrorDeValidacion, match="script.google.com"):
            correo.guardar_url(db, mala)
    correo.guardar_url(db, f"  {URL} ")
    assert correo.envio_configurado(db)
    anterior = cfg.secreto
    assert correo.regenerar_secreto(db).secreto != anterior


def test_sin_envio_configurado_no_se_puede_registrar_correo(db, usuario, enviados):
    with pytest.raises(ErrorDeValidacion, match="no está configurado"):
        correo.iniciar_verificacion(db, usuario, "planta@example.com", ACTUAL)
    assert enviados == []


def test_verificar_correo(db, usuario, enviados, con_envio):
    with pytest.raises(ErrorDeValidacion, match="contraseña actual"):
        correo.iniciar_verificacion(db, usuario, "planta@example.com", "otra")
    with pytest.raises(ErrorDeValidacion, match="correo válido"):
        correo.iniciar_verificacion(db, usuario, "sin-arroba", ACTUAL)

    estado = correo.iniciar_verificacion(db, usuario, " Planta@Example.com ", ACTUAL)
    assert enviados[-1].mensaje.para == "planta@example.com"
    assert enviados[-1].url == URL
    # Hasta escribir el codigo el correo no cambia.
    assert estado == {
        "correo": None,
        "verificado": False,
        "pendiente": "planta@example.com",
        "envio_configurado": True,
    }
    codigo = _codigo(enviados[-1])
    # El codigo no queda en claro en la base.
    fila = db.scalar(select(CodigoCorreo).where(CodigoCorreo.usuario_id == usuario.id))
    assert codigo not in fila.codigo_hash

    with pytest.raises(ErrorDeValidacion, match="quedan 4"):
        correo.confirmar_verificacion(db, usuario, "000000" if codigo != "000000" else "111111")
    estado = correo.confirmar_verificacion(db, usuario, codigo)
    assert estado["correo"] == "planta@example.com" and estado["verificado"]
    assert usuario.correo_verificado
    # Un codigo no sirve dos veces.
    with pytest.raises(ErrorDeValidacion, match="venció"):
        correo.confirmar_verificacion(db, usuario, codigo)


def test_un_envio_por_minuto_y_maximo_cinco_por_hora(db, usuario, enviados, con_envio):
    correo.iniciar_verificacion(db, usuario, "planta@example.com", ACTUAL)
    with pytest.raises(ErrorDeValidacion, match="Espera un minuto"):
        correo.iniciar_verificacion(db, usuario, "planta@example.com", ACTUAL)
    for _ in range(4):
        _envejecer(db, usuario)
        correo.iniciar_verificacion(db, usuario, "planta@example.com", ACTUAL)
    _envejecer(db, usuario)
    with pytest.raises(ErrorDeValidacion, match="muchos códigos"):
        correo.iniciar_verificacion(db, usuario, "planta@example.com", ACTUAL)
    # Solo el ultimo codigo sirve.
    vigentes = db.scalars(
        select(CodigoCorreo).where(CodigoCorreo.usuario_id == usuario.id, CodigoCorreo.expira_en > ahora())
    ).all()
    assert len(vigentes) == 1


def test_si_google_falla_no_queda_codigo(db, usuario, con_envio, monkeypatch):
    def falla(_envio):
        raise ErrorDeValidacion("No se pudo enviar el correo.")

    monkeypatch.setattr(correo, "enviar", falla)
    with pytest.raises(ErrorDeValidacion, match="No se pudo enviar"):
        correo.iniciar_verificacion(db, usuario, "planta@example.com", ACTUAL)
    assert db.scalar(select(CodigoCorreo).where(CodigoCorreo.usuario_id == usuario.id)) is None


def _entregar(db, nombre):
    envio = correo.solicitar_recuperacion(db, nombre)
    correo.enviar_en_segundo_plano(envio)
    db.expire_all()
    return envio


def test_recuperar_contrasena_por_correo(db, usuario, enviados, con_envio):
    nombre = usuario.nombre_usuario
    # Sin correo verificado no se envia nada (y quien pide no se entera).
    assert correo.solicitar_recuperacion(db, nombre) is None
    assert correo.solicitar_recuperacion(db, "no_existe") is None

    _verificar(db, usuario, enviados)
    envio = _entregar(db, f" {nombre.upper()} ")
    assert envio.mensaje.para == "planta@example.com"
    assert nombre in envio.mensaje.texto
    codigo = _codigo(envio)
    version = usuario.token_version

    with pytest.raises(CredencialesInvalidas):
        correo.recuperar(db, nombre, "12345", NUEVA, IP)
    aviso = correo.recuperar(db, nombre, codigo, NUEVA, IP)
    assert verificar_password(NUEVA, usuario.password_hash)
    assert usuario.token_version == version + 1
    assert aviso.mensaje.para == "planta@example.com"
    assert "cambió" in aviso.mensaje.asunto
    # De un solo uso.
    with pytest.raises(CredencialesInvalidas):
        correo.recuperar(db, nombre, codigo, "OtraClave-2026", IP)


def test_codigo_de_recuperacion_se_anula_tras_cinco_fallos_y_al_vencer(db, usuario, enviados, con_envio):
    nombre = usuario.nombre_usuario
    _verificar(db, usuario, enviados)
    _envejecer(db, usuario)
    codigo = _codigo(_entregar(db, nombre))
    malo = "000000" if codigo != "000000" else "111111"
    for i in range(5):
        with pytest.raises(CredencialesInvalidas):
            # IP distinta en cada intento: el limite es del codigo, no solo de la IP.
            correo.recuperar(db, nombre, malo, NUEVA, f"10.1.0.{i}")
    fila = db.scalar(select(CodigoCorreo).where(CodigoCorreo.proposito == correo.RECUPERAR))
    assert fila.intentos == 5
    # Con el codigo agotado ni el correcto sirve (la cuenta ademas puede
    # quedar bloqueada por tiempo; en ambos casos no entra).
    with pytest.raises((CredencialesInvalidas, AccesoTemporalmenteLimitado)):
        correo.recuperar(db, nombre, codigo, NUEVA, "10.2.0.1")
    assert not verificar_password(NUEVA, usuario.password_hash)


def test_codigo_vencido_no_sirve(db, usuario, enviados, con_envio):
    nombre = usuario.nombre_usuario
    _verificar(db, usuario, enviados)
    _envejecer(db, usuario)
    codigo = _codigo(_entregar(db, nombre))
    db.execute(update(CodigoCorreo).values(expira_en=ahora() - timedelta(seconds=1)))
    with pytest.raises(CredencialesInvalidas):
        correo.recuperar(db, nombre, codigo, NUEVA, IP)


def test_quitar_correo(db, usuario, enviados, con_envio):
    _verificar(db, usuario, enviados)
    with pytest.raises(ErrorDeValidacion, match="contraseña actual"):
        correo.quitar(db, usuario, "otra")
    estado = correo.quitar(db, usuario, ACTUAL)
    assert estado["correo"] is None and not estado["verificado"]
    assert correo.solicitar_recuperacion(db, usuario.nombre_usuario) is None


def test_usuario_inactivo_no_recupera(db, usuario, enviados, con_envio):
    _verificar(db, usuario, enviados)
    usuario.activo = False
    db.flush()
    assert correo.solicitar_recuperacion(db, usuario.nombre_usuario) is None


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.parametrize(
    ("cuerpo", "error"),
    [
        (b'{"ok": true, "restantes": 99}', None),
        (b'{"ok": false, "error": "secreto"}', "secreto actual"),
        (b"<html>Iniciar sesion</html>", "Cualquier usuario"),
    ],
)
def test_envio_interpreta_la_respuesta_de_google(monkeypatch, cuerpo, error):
    peticiones = []

    def falso_urlopen(peticion, timeout):
        peticiones.append(peticion)
        return _Respuesta(cuerpo)

    monkeypatch.setattr(correo.urllib.request, "urlopen", falso_urlopen)
    envio = correo.Envio(URL, "s3creto", correo._plantilla("a@b.co", "Prueba", "Hola", "123456"))
    if error is None:
        correo.enviar(envio)
    else:
        with pytest.raises(ErrorDeValidacion, match=error):
            correo.enviar(envio)
    enviado = json.loads(peticiones[0].data)
    assert enviado["secreto"] == "s3creto" and enviado["para"] == "a@b.co"
    assert "123456" in enviado["html"]


def test_rutas_publicas_no_delatan_usuarios(db, usuario, enviados, con_envio, cliente):
    assert cliente.get(f"{AUTH}/recuperacion/opciones").json() == {"correo": True}
    existente = cliente.post(
        f"{AUTH}/recuperar-por-correo/solicitar", json={"nombre_usuario": usuario.nombre_usuario}
    )
    inexistente = cliente.post(f"{AUTH}/recuperar-por-correo/solicitar", json={"nombre_usuario": "nadie"})
    assert existente.status_code == inexistente.status_code == 202
    assert existente.json() == inexistente.json()


def test_flujo_por_la_api(db, datos_base, usuario, enviados, cliente):
    admin = datos_base.admin
    admin.password_hash = hash_password(ACTUAL)
    db.flush()
    login = cliente.post(f"{AUTH}/login", json={"nombre_usuario": admin.nombre_usuario, "password": ACTUAL})
    assert login.status_code == 200, login.text

    envio = cliente.get(f"{AUTH}/envio-correo").json()
    assert envio["configurado"] is False and "const SECRETO" in envio["script"]
    malo = cliente.put(f"{AUTH}/envio-correo", json={"url_envio": "https://otro.com/exec"})
    assert malo.status_code in (400, 422)
    assert cliente.put(f"{AUTH}/envio-correo", json={"url_envio": URL}).json()["configurado"]
    assert cliente.post(f"{AUTH}/envio-correo/prueba", json={"para": "admin@example.com"}).status_code == 200
    assert enviados[-1].mensaje.para == "admin@example.com"

    pendiente = cliente.post(
        f"{AUTH}/correo", json={"correo": "admin@example.com", "password_actual": ACTUAL}
    )
    assert pendiente.json()["pendiente"] == "admin@example.com"
    verificado = cliente.post(f"{AUTH}/correo/verificar", json={"codigo": _codigo(enviados[-1])})
    assert verificado.json()["verificado"] is True
    yo = cliente.get(f"{AUTH}/yo").json()
    assert yo["correo"] == "admin@example.com" and yo["correo_verificado"] is True

    cliente.post(f"{AUTH}/logout")
    cliente.post(f"{AUTH}/recuperar-por-correo/solicitar", json={"nombre_usuario": admin.nombre_usuario})
    codigo = _codigo(enviados[-1])
    listo = cliente.post(
        f"{AUTH}/recuperar-por-correo",
        json={"nombre_usuario": admin.nombre_usuario, "codigo": codigo, "password_nueva": NUEVA},
    )
    assert listo.status_code == 200, listo.text
    assert "cambió" in enviados[-1].mensaje.asunto
    entra = cliente.post(f"{AUTH}/login", json={"nombre_usuario": admin.nombre_usuario, "password": NUEVA})
    assert entra.status_code == 200

    # Un usuario que no es administrador no ve ni cambia el envio.
    cliente.post(f"{AUTH}/logout")
    cliente.post(f"{AUTH}/login", json={"nombre_usuario": usuario.nombre_usuario, "password": ACTUAL})
    assert cliente.get(f"{AUTH}/envio-correo").status_code == 403


def test_cambio_de_buzon_anula_codigo_y_filtra_registros_historicos(db, usuario, enviados, con_envio):
    _verificar(db, usuario, enviados)
    viejo = _entregar(db, usuario.nombre_usuario)
    _envejecer(db, usuario)
    _verificar(db, usuario, enviados, "nuevo@example.com")
    fila = db.get(CodigoCorreo, viejo.codigo_id)
    assert fila.expira_en <= ahora()
    # Simula un código previo a V33 que quedó activo con el correo antiguo.
    fila.expira_en = ahora() + timedelta(minutes=5)
    fila.estado_envio = None
    db.flush()
    with pytest.raises(CredencialesInvalidas):
        correo.recuperar(db, usuario.nombre_usuario, _codigo(viejo), NUEVA, IP)
    assert verificar_password(ACTUAL, usuario.password_hash)
    nuevo = _entregar(db, usuario.nombre_usuario)
    assert nuevo.mensaje.para == "nuevo@example.com"
    correo.recuperar(db, usuario.nombre_usuario, _codigo(nuevo), NUEVA, IP)


def test_reenvio_fallido_preserva_codigo_y_espera(db, usuario, enviados, con_envio, monkeypatch):
    nombre = usuario.nombre_usuario
    _verificar(db, usuario, enviados)
    anterior = _entregar(db, nombre)
    _envejecer(db, usuario)
    intento = correo.solicitar_recuperacion(db, nombre)
    assert db.get(CodigoCorreo, intento.codigo_id).estado_envio == "pendiente"

    def rechazo(_envio):
        raise ErrorDeValidacion("Envío rechazado")

    with monkeypatch.context() as cambios:
        cambios.setattr(correo, "enviar", rechazo)
        correo.enviar_en_segundo_plano(intento)
    db.expire_all()
    assert db.get(CodigoCorreo, intento.codigo_id).estado_envio == "fallido"
    assert correo.solicitar_recuperacion(db, nombre) is None
    vigente = correo._pendiente(db, usuario.id, correo.RECUPERAR, destino=usuario.correo)
    assert vigente.id == anterior.codigo_id
    _envejecer(db, usuario)
    nuevo = _entregar(db, nombre)
    assert db.get(CodigoCorreo, nuevo.codigo_id).estado_envio == "aceptado"
    assert db.get(CodigoCorreo, anterior.codigo_id).expira_en <= ahora()
    correo.recuperar(db, nombre, _codigo(nuevo), NUEVA, IP)


def test_confirmacion_tardia_no_reactiva_un_codigo_reemplazado(db, usuario, enviados, con_envio):
    nombre = usuario.nombre_usuario
    _verificar(db, usuario, enviados)
    antiguo = correo.solicitar_recuperacion(db, nombre)
    _envejecer(db, usuario)
    nuevo = _entregar(db, nombre)
    correo.enviar_en_segundo_plano(antiguo)
    db.expire_all()
    assert db.get(CodigoCorreo, antiguo.codigo_id).expira_en <= ahora()
    correo.recuperar(db, nombre, _codigo(nuevo), NUEVA, IP)
