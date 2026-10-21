"""
Pruebas de la IP usada como clave del rate limiting.

El objetivo es que dos usuarios detras del mismo Nginx no compartan el
cupo, y que un cliente externo no pueda falsificar su IP con cabeceras.
"""

from starlette.requests import Request

from app.core.limite import obtener_ip_cliente


def _request(ip_cliente: str, cabeceras: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (nombre.lower().encode("latin-1"), valor.encode("latin-1"))
                for nombre, valor in (cabeceras or {}).items()
            ],
            "client": (ip_cliente, 12345),
        }
    )


def test_usa_la_ip_real_cuando_viene_de_nginx():
    request = _request("172.18.0.5", {"X-Real-IP": "203.0.113.7"})

    assert obtener_ip_cliente(request) == "203.0.113.7"


def test_ignora_la_cabecera_si_el_cliente_es_publico():
    request = _request("198.51.100.20", {"X-Real-IP": "1.2.3.4"})

    assert obtener_ip_cliente(request) == "198.51.100.20"


def test_usa_x_forwarded_for_si_falta_x_real_ip():
    request = _request(
        "10.0.0.4",
        {"X-Forwarded-For": "203.0.113.9, 10.0.0.4"},
    )

    assert obtener_ip_cliente(request) == "203.0.113.9"


def test_ignora_una_cabecera_con_formato_invalido():
    request = _request("172.18.0.5", {"X-Real-IP": "no-es-una-ip"})

    assert obtener_ip_cliente(request) == "172.18.0.5"


def test_sin_cabeceras_usa_la_ip_de_la_conexion():
    request = _request("192.168.1.30")

    assert obtener_ip_cliente(request) == "192.168.1.30"


def test_encuentra_el_handler_a_traves_de_los_routers_anidados():
    from app.core.limite import buscar_handler
    from app.main import app

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": [],
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }

    handler = buscar_handler(app.routes, scope)

    assert handler is not None
    assert handler.__name__ == "iniciar_sesion"
