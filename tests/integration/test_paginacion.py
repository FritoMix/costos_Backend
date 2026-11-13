from datetime import date
from decimal import Decimal

import pytest

from app.modules.produccion.models import OrdenProduccion
from app.modules.produccion.servicios.ordenes import pagina_ordenes
from tests.integration.test_api import _login
from tests.integration.test_api import cliente as fixture_cliente


@pytest.fixture(name="cliente")
def cliente_paginacion(db, datos_base):
    yield from fixture_cliente.__wrapped__(db, datos_base)


def test_paginacion_permite_ver_mas_de_500_ordenes(db, datos_base):
    filas = [
        OrdenProduccion(
            numero_orden=f"OP-PAG-{i:04d}",
            fecha=date(2026, 1, 1),
            supervisor_id=datos_base.supervisor.id,
            turno_id=datos_base.turno.id,
            horno_id=datos_base.horno.id,
            producto_id=datos_base.producto.id,
            categoria_id=datos_base.categoria.id,
            cantidad_programada=Decimal("100"),
            horas_produccion=2,
            estado="pendiente",
        )
        for i in range(513)
    ]
    db.add_all(filas)
    db.flush()
    ids = [f.id for f in filas]
    db.commit()
    primera = pagina_ordenes(db, usuario=datos_base.admin, pagina=1, tamano=100)
    ultima = pagina_ordenes(db, usuario=datos_base.admin, pagina=6, tamano=100)
    assert primera["total"] == ultima["total"] == 513
    assert len(primera["items"]) == 100
    assert len(ultima["items"]) == 13
    assert primera["items"][0].id == ids[-1]
    assert ultima["items"][-1].id == ids[0]
    assert not ({f.id for f in primera["items"]} & {f.id for f in ultima["items"]})


def test_endpoint_valida_limites_y_estado(cliente):
    _login(cliente)
    respuesta = cliente.get("/api/v1/ordenes/pagina?pagina=1&tamano=10")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"items": [], "total": 0, "pagina": 1, "tamano": 10}
    for query in ("pagina=0", "tamano=101", "pagina=999999999999999999999", "estado=desconocido"):
        assert cliente.get(f"/api/v1/ordenes/pagina?{query}").status_code == 422


def test_paginacion_respeta_filtro_de_supervisor(db, datos_base, orden_guardar):
    from app.modules.produccion.servicios.ordenes import crear_orden

    propia = crear_orden(db, orden_guardar(), datos_base.supervisor)
    crear_orden(db, orden_guardar(), datos_base.admin)
    pagina = pagina_ordenes(db, usuario=datos_base.supervisor)
    assert pagina["total"] == 1
    assert pagina["items"][0].id == propia.id
