"""
Instancia unica del limitador de peticiones (rate limiting).

Vive aparte para que tanto el arranque de la app (app/main.py) como los
routers (que aplican limites especificos con @limiter.limit) importen la
MISMA instancia, sin crear importaciones circulares entre modulos.

Detras de Nginx, request.client.host es la IP del proxy, no la del
navegador. Si se usara tal cual, todos los usuarios compartirian el mismo
cupo de 120 peticiones por minuto. Por eso se lee X-Real-IP, pero SOLO
cuando la conexion viene de un proxy de la red interna: cualquiera puede
inventar esa cabecera desde Internet.
"""

import inspect
from ipaddress import ip_address, ip_network

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.routing import Match

from app.core.config import settings

# Loopback y redes privadas (RFC 1918). En Docker Compose el proxy Nginx
# llega desde una de estas; una conexion publica directa nunca califica.
_REDES_DE_CONFIANZA = (
    ip_network("127.0.0.0/8"),
    ip_network("::1/128"),
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)


def _es_proxy_de_confianza(host: str) -> bool:
    try:
        direccion = ip_address(host)
    except ValueError:
        return False
    return any(direccion in red for red in _REDES_DE_CONFIANZA)


def obtener_ip_cliente(request: Request) -> str:
    """
    IP real del cliente para el limite de peticiones.

    Nginx envia X-Real-IP (y X-Forwarded-For) con la IP del navegador. Solo
    se confia en esa cabecera si quien conecta es un proxy de la red interna;
    de lo contrario se usa la IP de la conexion, para que nadie pueda saltarse
    el limite inventando una cabecera.
    """
    host = request.client.host if request.client else "127.0.0.1"
    if not _es_proxy_de_confianza(host):
        return host

    ip_real = request.headers.get("x-real-ip", "").strip()
    if not ip_real:
        reenviadas = request.headers.get("x-forwarded-for", "")
        ip_real = reenviadas.split(",")[0].strip()

    if not ip_real:
        return host

    try:
        ip_address(ip_real)
    except ValueError:
        # Cabecera corrupta o manipulada: se ignora.
        return host
    return ip_real


limiter = Limiter(key_func=obtener_ip_cliente, default_limits=[settings.rate_limit_minute])


def buscar_handler(routes, scope) -> object | None:
    """
    Encuentra la funcion que atiende una peticion.

    FastAPI 0.156 conserva los routers incluidos como ``_IncludedRouter`` en
    ``app.routes`` en vez de aplanar todas las rutas. SlowAPI busca solo en
    el primer nivel y por eso dejaba de aplicar los limites. Esta busqueda
    entra recursivamente en ``original_router`` y descuenta el prefijo de
    cada inclusion (/api/v1, /auth, ...).
    """
    for route in routes:
        match, _ = route.matches(scope)
        if match != Match.FULL:
            continue

        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            return endpoint

        original = getattr(route, "original_router", None)
        if original is None:
            continue

        contexto = getattr(route, "include_context", None)
        prefijo = getattr(contexto, "prefix", "") or ""
        ruta_hija = scope
        if prefijo and scope["path"].startswith(prefijo):
            ruta_hija = {**scope, "path": scope["path"][len(prefijo) :] or "/"}

        encontrado = buscar_handler(original.routes, ruta_hija)
        if encontrado is not None:
            return encontrado

    return None


class MiddlewareLimite(SlowAPIMiddleware):
    """Aplica el limite global y los limites por ruta con el router actual."""

    async def dispatch(self, request: Request, call_next):
        if not limiter.enabled:
            return await call_next(request)

        handler = buscar_handler(request.app.routes, request.scope)
        try:
            limiter._check_request_limit(request, handler, True)
        except RateLimitExceeded as exc:
            # Usa el mismo manejador que las rutas con @limiter.limit, para
            # que el frontend reciba siempre el mismo JSON de error.
            manejador = request.app.exception_handlers.get(RateLimitExceeded)
            if manejador is None:
                return _rate_limit_exceeded_handler(request, exc)
            respuesta = manejador(request, exc)
            if inspect.isawaitable(respuesta):
                respuesta = await respuesta
            return respuesta

        return await call_next(request)
