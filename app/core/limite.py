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

from ipaddress import ip_address, ip_network

from slowapi import Limiter
from starlette.requests import Request

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
