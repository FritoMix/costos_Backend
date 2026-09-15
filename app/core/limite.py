"""
Instancia unica del limitador de peticiones (rate limiting).

Vive aparte para que tanto el arranque de la app (app/main.py) como los
routers (que aplican limites especificos con @limiter.limit) importen la
MISMA instancia, sin crear importaciones circulares entre modulos.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_minute])
