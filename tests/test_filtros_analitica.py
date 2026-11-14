from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.manejadores import registrar_manejadores
from app.modules.analitica.router import filtros_desde_query
from app.modules.analitica.schemas import FiltrosAnalisis


@pytest.fixture
def cliente_filtros():
    app = FastAPI()
    registrar_manejadores(app)

    @app.get('/filtros')
    def endpoint(filtros: Annotated[FiltrosAnalisis, Depends(filtros_desde_query)]):
        return filtros.model_dump(mode="json")

    with TestClient(app) as cliente:
        yield cliente


@pytest.mark.parametrize('parametros', [
    {'fecha_desde': 'no-es-fecha'},
    {'fecha_hasta': '2026-02-30'},
    {'fecha_desde': '2026-12-02', 'fecha_hasta': '2026-12-01'},
    *[{campo: valor} for campo in ('turno_id', 'horno_id', 'producto_id', 'categoria_id',
                                   'supervisor_id', 'sabor_id') for valor in (0, -1)],
])
def test_filtros_invalidos_son_422_sin_datos_internos(cliente_filtros, parametros):
    respuesta = cliente_filtros.get('/filtros', params=parametros)
    assert respuesta.status_code == 422
    assert respuesta.json()['errores'][0]['loc'][0] == 'query'
    assert 'traceback' not in respuesta.text.lower()


def test_fechas_vacias_y_rango_de_un_dia_siguen_funcionando(cliente_filtros):
    respuesta = cliente_filtros.get('/filtros', params={'fecha_desde': '', 'fecha_hasta': ''})
    assert respuesta.status_code == 200
    assert respuesta.json()['fecha_desde'] is None
    respuesta = cliente_filtros.get('/filtros', params={
        'fecha_desde': '2026-11-14', 'fecha_hasta': '2026-11-14', 'horno_id': 1,
    })
    assert respuesta.status_code == 200
    assert respuesta.json()['horno_id'] == 1
