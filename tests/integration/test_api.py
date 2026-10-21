"""
Pruebas de la API HTTP completa contra PostgreSQL real.

Complementan las pruebas de servicios: ejercitan routers, dependencias,
serializacion, permisos y el flujo que usa el frontend. Usan la misma
sesion de la prueba (con savepoints) para que cada caso quede aislado.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.limite import limiter
from app.core.seguridad import hash_password
from app.db.session import get_db
from app.main import app

PASSWORD = "clave-api-123"
API = "/api/v1"


@pytest.fixture
def cliente(db: Session, datos_base):
    """Cliente HTTP con la sesion de prueba y todos los usuarios habilitados."""
    for usuario in (
        datos_base.admin,
        datos_base.supervisor,
        datos_base.operario_horno,
        datos_base.operario_saborizado,
        datos_base.bodeguero,
    ):
        usuario.password_hash = hash_password(PASSWORD)
    db.flush()

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    limiter.reset()
    cliente = TestClient(app)
    try:
        yield cliente
    finally:
        cliente.close()
        app.dependency_overrides.pop(get_db, None)


def _login(cliente: TestClient, nombre: str = "admin_prueba") -> TestClient:
    respuesta = cliente.post(
        f"{API}/auth/login",
        json={"nombre_usuario": nombre, "password": PASSWORD},
    )
    assert respuesta.status_code == 200, respuesta.text
    return cliente


def _json(respuesta, estado: int = 200):
    assert respuesta.status_code == estado, respuesta.text
    return respuesta.json()


def test_salud_login_cambio_de_password_y_logout(cliente: TestClient, db: Session):
    _json(cliente.get(f"{API}/salud"))

    assert cliente.post(
        f"{API}/auth/login",
        json={"nombre_usuario": "admin_prueba", "password": "incorrecta"},
    ).status_code == 401

    _login(cliente)
    _json(cliente.get(f"{API}/auth/yo"))

    cookie_vieja = cliente.cookies.get("datacontrol_sesion")
    assert cookie_vieja

    respuesta = cliente.post(
        f"{API}/auth/cambiar-password",
        json={"password_actual": PASSWORD, "password_nueva": "clave-nueva-456"},
        headers={"X-Real-IP": "10.10.10.10"},
    )
    assert respuesta.status_code == 204, respuesta.text
    # El cliente conserva la sesion porque la API reemite la cookie.
    _json(cliente.get(f"{API}/auth/yo"))

    # Un token anterior (otra pestana/equipo) queda revocado.
    cliente_viejo = TestClient(app)
    cliente_viejo.cookies.set("datacontrol_sesion", cookie_vieja)
    assert cliente_viejo.get(f"{API}/auth/yo").status_code == 401
    cliente_viejo.close()

    assert cliente.post(f"{API}/auth/logout").status_code == 204
    assert cliente.get(f"{API}/auth/yo").status_code == 401


def test_catalogos_crud_configuracion_y_densidad(
    cliente: TestClient, datos_base
):
    _login(cliente)

    # CRUD de catalogos simples: crear, listar, editar y borrar.
    for ruta in ("categorias", "sabores", "tipos-desperdicio"):
        creado = _json(
            cliente.post(f"{API}/catalogos/{ruta}", json={"nombre": f"API {ruta}"}),
            201,
        )
        _json(cliente.get(f"{API}/catalogos/{ruta}?solo_activas=true"))
        _json(
            cliente.put(
                f"{API}/catalogos/{ruta}/{creado['id']}",
                json={"nombre": f"API {ruta} editada"},
            )
        )
        assert cliente.delete(f"{API}/catalogos/{ruta}/{creado['id']}").status_code == 204

    turno = _json(
        cliente.post(
            f"{API}/catalogos/turnos",
            json={"nombre": "Turno API", "hora_inicio": "06:00:00", "hora_fin": "14:00:00"},
        ),
        201,
    )
    _json(cliente.get(f"{API}/catalogos/turnos"))
    _json(
        cliente.put(
            f"{API}/catalogos/turnos/{turno['id']}",
            json={"nombre": "Turno API editado", "hora_inicio": "07:00:00", "hora_fin": "15:00:00"},
        )
    )
    assert cliente.delete(f"{API}/catalogos/turnos/{turno['id']}").status_code == 204

    horno = _json(
        cliente.post(
            f"{API}/catalogos/hornos",
            json={
                "nombre": "Horno API",
                "categoria_ids": [datos_base.categoria.id],
                "tanque_diametro_cm": "100",
            },
        ),
        201,
    )
    _json(cliente.get(f"{API}/catalogos/hornos"))
    _json(
        cliente.put(
            f"{API}/catalogos/hornos/{horno['id']}",
            json={"nombre": "Horno API editado", "categoria_ids": []},
        )
    )
    assert cliente.delete(f"{API}/catalogos/hornos/{horno['id']}").status_code == 204

    producto = _json(
        cliente.post(
            f"{API}/catalogos/productos",
            json={
                "nombre_comercial": "Producto API",
                "categoria_id": datos_base.categoria.id,
                "peso_estandar_canastilla_kg": "6.00",
            },
        ),
        201,
    )
    _json(cliente.get(f"{API}/catalogos/productos"))
    _json(
        cliente.put(
            f"{API}/catalogos/productos/{producto['id']}",
            json={
                "nombre_comercial": "Producto API editado",
                "categoria_id": datos_base.categoria.id,
            },
        )
    )
    assert cliente.delete(f"{API}/catalogos/productos/{producto['id']}").status_code == 204

    _json(cliente.get(f"{API}/catalogos/configuracion"))
    _json(
        cliente.put(
            f"{API}/catalogos/configuracion",
            json={
                "peso_estandar_bulto_kg": "25.00",
                "peso_estandar_canastilla_kg": "6.00",
            },
        )
    )

    muestra = _json(
        cliente.post(
            f"{API}/catalogos/densidad-aceite",
            json={
                "horno_id": datos_base.horno.id,
                "fecha": date.today().isoformat(),
                "densidad_kg_por_litro": "0.910",
            },
        ),
        201,
    )
    assert muestra["horno_id"] == datos_base.horno.id
    _json(cliente.get(f"{API}/catalogos/densidad-aceite"))
    _json(cliente.get(f"{API}/catalogos/densidad-aceite/vigentes"))


def test_bodega_referencias_crud_y_permisos(cliente: TestClient, datos_base):
    _login(cliente)
    _json(cliente.get(f"{API}/bodega/referencias-papa"))

    payload = {
        "nombre": "Papa API",
        "tipo": "Papa lavada",
        "peso_promedio_bulto_kg": "48.50",
        "rendimiento_fritura_pct": "24.50",
        "porcentaje_produccion_pct": "33.33",
    }
    creada = _json(
        cliente.post(f"{API}/bodega/referencias-papa", json=payload),
        201,
    )
    assert creada["peso_promedio_bulto_kg"] == "48.50"
    assert creada["tipo"] == "Papa lavada"
    assert creada["rendimiento_fritura_pct"] == "24.5000"
    assert creada["porcentaje_produccion_pct"] == "33.3300"
    assert creada["fecha_actualizacion"]
    _json(cliente.get(f"{API}/bodega/referencias-papa/{creada['id']}"))
    _json(cliente.get(f"{API}/bodega/referencias-papa?solo_activas=true"))

    # Nombre duplicado sin importar mayusculas.
    assert cliente.post(
        f"{API}/bodega/referencias-papa",
        json={**payload, "nombre": "papa api"},
    ).status_code == 400
    # Valores fuera de rango: los rechaza el contrato con un mensaje legible.
    for cambio in (
        {"tipo": "   "},
        {"rendimiento_fritura_pct": "0"},
        {"rendimiento_fritura_pct": "101"},
        {"porcentaje_produccion_pct": "-1"},
        {"porcentaje_produccion_pct": "100.01"},
        {"peso_promedio_bulto_kg": "0"},
    ):
        respuesta = cliente.post(
            f"{API}/bodega/referencias-papa", json={**payload, **cambio}
        )
        assert respuesta.status_code == 422, respuesta.text
        assert "IntegrityError" not in respuesta.text
        assert "Traceback" not in respuesta.text

    actualizada = _json(
        cliente.put(
            f"{API}/bodega/referencias-papa/{creada['id']}",
            json={
                **payload,
                "nombre": "Papa API corregida",
                "tipo": "Papa pareja",
                "peso_promedio_bulto_kg": "49.25",
                "rendimiento_fritura_pct": "26.75",
                "porcentaje_produccion_pct": "50",
                "activo": False,
            },
        )
    )
    assert actualizada["activo"] is False
    assert actualizada["tipo"] == "Papa pareja"

    # El Supervisor tambien administra el catalogo.
    supervisor = TestClient(app)
    _login(supervisor, "supervisor_prueba")
    creada_supervisor = _json(
        supervisor.post(
            f"{API}/bodega/referencias-papa",
            json={**payload, "nombre": "Papa del supervisor"},
        ),
        201,
    )
    supervisor.close()

    # El bodeguero gestiona su catalogo, pero no los demas modulos.
    bodeguero = TestClient(app)
    _login(bodeguero, "bodeguero_prueba")
    _json(bodeguero.get(f"{API}/bodega/referencias-papa"))
    for ruta in (
        "/ordenes",
        "/catalogos/productos",
        "/catalogos/configuracion",
        "/usuarios",
    ):
        assert bodeguero.get(f"{API}{ruta}").status_code == 403
    creada_bodeguero = _json(
        bodeguero.post(
            f"{API}/bodega/referencias-papa",
            json={**payload, "nombre": "Papa del bodeguero", "porcentaje_produccion_pct": "16.67"},
        ),
        201,
    )
    assert bodeguero.post(
        f"{API}/catalogos/categorias", json={"nombre": "No permitido"}
    ).status_code == 403
    bodeguero.close()

    # El operario puede leerlas para registrar la tanda, pero no editarlas.
    operario = TestClient(app)
    _login(operario, "operario_horno_prueba")
    _json(operario.get(f"{API}/bodega/referencias-papa"))
    assert operario.post(
        f"{API}/bodega/referencias-papa",
        json={**payload, "nombre": "No permitido"},
    ).status_code == 403
    operario.close()

    for referencia_id in (
        creada["id"],
        creada_supervisor["id"],
        creada_bodeguero["id"],
    ):
        assert cliente.delete(
            f"{API}/bodega/referencias-papa/{referencia_id}"
        ).status_code == 204


def test_proyeccion_distribuye_capacidad_y_valida_porcentajes(
    cliente: TestClient, db: Session, datos_base
):
    from app.modules.bodega.models import ReferenciaPapa

    _login(cliente)
    # La referencia del fixture queda con 66,67 % y se agrega otra con 33,33 %.
    datos_base.referencia_papa.porcentaje_produccion_pct = Decimal("66.67")
    otra = ReferenciaPapa(
        nombre="Papa Proyeccion",
        tipo="Papa lavada",
        peso_promedio_bulto_kg=Decimal("50.00"),
        rendimiento_fritura_pct=Decimal("25.00"),
        porcentaje_produccion_pct=Decimal("33.33"),
        activo=True,
    )
    db.add(otra)
    db.flush()

    proyeccion = _json(
        cliente.get(
            f"{API}/bodega/proyeccion",
            params={"horno_id": datos_base.horno.id},
        )
    )
    assert proyeccion["total_bultos"] == 50
    assert proyeccion["total_kg_crudos"] == "2500.00"
    assert proyeccion["total_kg_fritos_estimados"] == "625.00"
    assert {fila["nombre"]: fila["bultos"] for fila in proyeccion["referencias"]} == {
        "Papa de Prueba": 33,
        "Papa Proyeccion": 17,
    }

    # 2 horas duplican la capacidad, no cambian el reparto porcentual.
    proyeccion_2h = _json(
        cliente.get(
            f"{API}/bodega/proyeccion",
            params={"horno_id": datos_base.horno.id, "horas": 2},
        )
    )
    assert proyeccion_2h["total_bultos"] == 100
    assert proyeccion_2h["total_kg_crudos"] == "5000.00"

    # Una referencia activa incompleta tampoco se proyecta.
    otra.tipo = None
    db.flush()
    respuesta = cliente.get(
        f"{API}/bodega/proyeccion",
        params={"horno_id": datos_base.horno.id},
    )
    assert respuesta.status_code == 400
    assert "está incompleta" in respuesta.json()["detail"]
    otra.tipo = "Papa lavada"
    db.flush()

    # Una configuracion inconsistente se bloquea con mensaje funcional.
    datos_base.referencia_papa.porcentaje_produccion_pct = Decimal("50")
    db.flush()
    respuesta = cliente.get(
        f"{API}/bodega/proyeccion",
        params={"horno_id": datos_base.horno.id},
    )
    assert respuesta.status_code == 400
    assert "debe sumar 100" in respuesta.json()["detail"]
    assert "Traceback" not in respuesta.text

    # El operario no proyecta.
    operario = TestClient(app)
    _login(operario, "operario_horno_prueba")
    assert operario.get(
        f"{API}/bodega/proyeccion", params={"horno_id": datos_base.horno.id}
    ).status_code == 403
    operario.close()

    # El Bodeguero administra referencias, pero la proyeccion es de
    # Administracion/Supervision.
    bodeguero = TestClient(app)
    _login(bodeguero, "bodeguero_prueba")
    assert bodeguero.get(
        f"{API}/bodega/proyeccion", params={"horno_id": datos_base.horno.id}
    ).status_code == 403
    bodeguero.close()

    # Sin capacidad configurada no hay proyeccion posible.
    datos_base.horno.capacidad_bultos_hora = None
    db.flush()
    respuesta = cliente.get(
        f"{API}/bodega/proyeccion",
        params={"horno_id": datos_base.horno.id},
    )
    assert respuesta.status_code == 400
    assert "no tiene configurada su capacidad" in respuesta.json()["detail"]


def test_capacidad_de_horno_la_configura_admin_o_supervisor(
    cliente: TestClient, db: Session, datos_base
):
    from app.modules.catalogos.models import Horno

    _login(cliente)
    horno = db.get(Horno, datos_base.horno.id)
    horno.capacidad_bultos_hora = None
    db.flush()

    respuesta = cliente.patch(
        f"{API}/catalogos/hornos/{horno.id}/capacidad",
        json={"capacidad_bultos_hora": "50"},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["capacidad_bultos_hora"] == "50.00"

    assert cliente.patch(
        f"{API}/catalogos/hornos/{horno.id}/capacidad",
        json={"capacidad_bultos_hora": "50.5"},
    ).status_code == 422
    assert cliente.patch(
        f"{API}/catalogos/hornos/{horno.id}/capacidad",
        json={"capacidad_bultos_hora": "0"},
    ).status_code == 422

    supervisor = TestClient(app)
    _login(supervisor, "supervisor_prueba")
    assert supervisor.patch(
        f"{API}/catalogos/hornos/{horno.id}/capacidad",
        json={"capacidad_bultos_hora": "60"},
    ).status_code == 200
    # El Supervisor no puede cambiar el resto de la configuracion del horno.
    assert supervisor.put(
        f"{API}/catalogos/hornos/{horno.id}",
        json={"nombre": "Horno cambiado por supervisor"},
    ).status_code == 403
    supervisor.close()

    bodeguero = TestClient(app)
    _login(bodeguero, "bodeguero_prueba")
    assert bodeguero.patch(
        f"{API}/catalogos/hornos/{horno.id}/capacidad",
        json={"capacidad_bultos_hora": "70"},
    ).status_code == 403
    bodeguero.close()

def test_usuarios_crud_y_permisos(cliente: TestClient, datos_base):
    _login(cliente)
    _json(cliente.get(f"{API}/usuarios/roles"))
    _json(cliente.get(f"{API}/usuarios/supervisores"))
    _json(cliente.get(f"{API}/usuarios"))

    creado = _json(
        cliente.post(
            f"{API}/usuarios",
            json={
                "nombre_completo": "Usuario API",
                "nombre_usuario": "usuario_api",
                "password": PASSWORD,
                "rol_id": datos_base.operario_horno.rol_id,
            },
        ),
        201,
    )
    _json(cliente.get(f"{API}/usuarios/{creado['id']}"))
    _json(
        cliente.put(
            f"{API}/usuarios/{creado['id']}",
            json={
                "nombre_completo": "Usuario API Editado",
                "nombre_usuario": "usuario_api",
                "rol_id": datos_base.operario_horno.rol_id,
                "activo": True,
            },
        )
    )

    # Un operario puede consultar catalogos, pero no administrar usuarios.
    operario = TestClient(app)
    _login(operario, "usuario_api")
    _json(operario.get(f"{API}/auth/yo"))
    _json(operario.get(f"{API}/catalogos/productos"))
    assert operario.get(f"{API}/usuarios").status_code == 403
    assert operario.post(
        f"{API}/catalogos/categorias", json={"nombre": "No permitido"}
    ).status_code == 403
    operario.close()

    assert cliente.delete(f"{API}/usuarios/{creado['id']}").status_code == 204
    assert cliente.get(f"{API}/usuarios/{creado['id']}").status_code == 404


def test_flujo_de_orden_registros_notificaciones_y_analitica(
    cliente: TestClient, datos_base, db: Session, monkeypatch
):
    # Los indicadores usan su propia sesion para el cache; en la prueba se
    # calculan sobre la sesion transaccional para no tocar otra base.
    from app.modules.analitica import service as analitica_service

    monkeypatch.setattr(
        analitica_service,
        "calcular_indicadores",
        lambda sesion, filtros: analitica_service._calcular_indicadores_interno(
            sesion, filtros
        ),
    )
    _login(cliente)

    orden = _json(
        cliente.post(
            f"{API}/ordenes",
            json={
                "turno_id": datos_base.turno.id,
                "horno_id": datos_base.horno.id,
                "categoria_id": datos_base.categoria.id,
                "producto_id": datos_base.producto.id,
                "destino": "nacional",
                "unidad_solicitada": "kg",
                "cantidad_kg": "100.00",
                "horas_produccion": 2,
            },
        ),
        201,
    )
    orden_id = orden["id"]

    _json(
        cliente.put(
            f"{API}/ordenes/{orden_id}",
            json={
                "turno_id": datos_base.turno.id,
                "horno_id": datos_base.horno.id,
                "categoria_id": datos_base.categoria.id,
                "producto_id": datos_base.producto.id,
                "destino": "nacional",
                "unidad_solicitada": "kg",
                "cantidad_kg": "120.00",
                "horas_produccion": 2,
            },
        )
    )
    _json(cliente.post(f"{API}/ordenes/{orden_id}/iniciar"))
    _json(cliente.get(f"{API}/ordenes"))
    _json(cliente.get(f"{API}/ordenes?estado=en_produccion"))
    _json(cliente.get(f"{API}/ordenes/{orden_id}"))

    registro = _json(
        cliente.post(
            f"{API}/ordenes/{orden_id}/registros-horno",
            json={
                "hora_inicio": "06:00:00",
                "hora_fin": "07:00:00",
                "referencia_papa_id": datos_base.referencia_papa.id,
                "cantidad_bultos": "10",
                "operarios_seleccion": 2,
                "operarios_horno": 1,
                "nivel_aceite_inicial_cm": "20",
                "nivel_aceite_final_cm": "18",
                "temperatura_aceite_c": "175",
                "tipo_desperdicio_id": datos_base.tipo_desperdicio.id,
                "cantidad_desperdicio_kg": "2.5",
            },
        ),
        201,
    )
    _json(cliente.get(f"{API}/ordenes/{orden_id}/registros-horno"))
    _json(
        cliente.put(
            f"{API}/ordenes/{orden_id}/registros-horno/{registro['id']}",
            json={
                "hora_inicio": "06:00:00",
                "hora_fin": "07:30:00",
                "referencia_papa_id": datos_base.referencia_papa.id,
                "cantidad_bultos": "11",
                "operarios_seleccion": 2,
                "operarios_horno": 1,
                "nivel_aceite_inicial_cm": "20",
                "nivel_aceite_final_cm": "18",
                "temperatura_aceite_c": "175",
            },
        )
    )

    recepcion = _json(
        cliente.post(
            f"{API}/ordenes/{orden_id}/recepciones",
            json={
                "hora_inicio": "07:00:00",
                "hora_fin": "08:00:00",
                "sabor_id": datos_base.sabor.id,
                "cantidad_sabor_kg": "1.00",
                "pesos_canastillas": ["6.00", "5.50"],
            },
        ),
        201,
    )
    _json(cliente.get(f"{API}/ordenes/{orden_id}/recepciones"))
    _json(
        cliente.put(
            f"{API}/ordenes/{orden_id}/recepciones/{recepcion['id']}",
            json={
                "hora_inicio": "07:00:00",
                "hora_fin": "08:30:00",
                "sabor_id": datos_base.sabor.id,
                "cantidad_sabor_kg": "1.00",
                "pesos_canastillas": ["6.00", "5.50", "5.00"],
            },
        )
    )

    # Las notificaciones de la orden nueva llegan a los operarios.
    operario = TestClient(app)
    _login(operario, "operario_horno_prueba")
    pendientes = _json(operario.get(f"{API}/notificaciones/pendientes"))
    assert pendientes["sin_leer"] >= 1
    aviso_id = pendientes["pendientes"][0]["id"]
    assert operario.post(f"{API}/notificaciones/{aviso_id}/leida").status_code == 204
    _json(operario.get(f"{API}/notificaciones"))
    assert operario.post(f"{API}/notificaciones/leidas").status_code == 204
    operario.close()

    # Analitica: lectura, filtros, exportaciones y permisos.
    _json(cliente.get(f"{API}/analitica/indicadores"))
    _json(cliente.get(f"{API}/analitica/por-categoria"))
    _json(cliente.get(f"{API}/analitica/baches"))
    assert cliente.get(f"{API}/analitica/exportar.csv").status_code == 200
    assert cliente.get(f"{API}/analitica/exportar.xlsx").status_code == 200

    operario = TestClient(app)
    _login(operario, "operario_horno_prueba")
    assert operario.get(f"{API}/analitica/indicadores").status_code == 403
    operario.close()

    assert cliente.delete(
        f"{API}/ordenes/{orden_id}/registros-horno/{registro['id']}"
    ).status_code == 204
    assert cliente.delete(
        f"{API}/ordenes/{orden_id}/recepciones/{recepcion['id']}"
    ).status_code == 204
    _json(cliente.post(f"{API}/ordenes/{orden_id}/finalizar"))
    _json(cliente.delete(f"{API}/ordenes/{orden_id}"))
    assert cliente.get(f"{API}/ordenes/{orden_id}").status_code == 404


def test_el_limite_global_responde_429(cliente: TestClient):
    _login(cliente)
    limiter.reset()

    for _ in range(120):
        assert cliente.get(f"{API}/salud").status_code == 200

    respuesta = cliente.get(f"{API}/salud")
    assert respuesta.status_code == 429
    assert "Demasiadas peticiones" in respuesta.json()["detail"]


def test_el_limite_por_ruta_de_exportacion_responde_429(cliente: TestClient):
    _login(cliente)
    limiter.reset()

    for _ in range(10):
        assert cliente.get(f"{API}/analitica/exportar.csv").status_code == 200

    respuesta = cliente.get(f"{API}/analitica/exportar.csv")
    assert respuesta.status_code == 429
    assert "Demasiadas peticiones" in respuesta.json()["detail"]
