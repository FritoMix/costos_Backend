"""
Cache en memoria con tiempo de vida (TTL).

Reemplaza @functools.lru_cache cuando la respuesta NO es eterna: aqui cada
entrada caduca al cabo de unos segundos, ideal para resultados pesados que
cambian poco (indicadores de analitica, catalogos estaticos).

Limite pensado para un juego reducido de claves distintas. Si el numero de
claves crece mucho, conviene migrar a Redis (mismo decorador, distinto
backend).
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

MAX_ENTRADAS = 512


def _clave(args: tuple, kwargs: dict) -> str:
    """Clave de cache canónica a partir de los argumentos de la llamada."""
    return repr((args, sorted(kwargs.items(), key=lambda kv: kv[0])))


def cache_ttl(segundos: int | float, *, maxsize: int = MAX_ENTRADAS) -> Callable:
    """
    Decorador: cachea el resultado durante `segundos`.

    Uso:
        @cache_ttl(30)
        def funcion_pesada(...): ...

    Los argumentos deben ser comparables (para armar la clave). El resultado
    debe ser seguro de compartir (no mutar la respuesta cacheada).
    """

    def decorador(funcion: Callable) -> Callable:
        cache: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        cerrojo = threading.Lock()

        def envuelto(*args, **kwargs) -> Any:
            clave = _clave(args, kwargs)
            ahora = time.monotonic()

            with cerrojo:
                entrada = cache.get(clave)
                if entrada is not None and entrada[0] > ahora:
                    # Volver a poner la clave al final (LRU).
                    cache.move_to_end(clave)
                    return entrada[1]

                cache.pop(clave, None)

            resultado = funcion(*args, **kwargs)

            with cerrojo:
                cache[clave] = (ahora + segundos, resultado)
                cache.move_to_end(clave)
                # Poda LRU: si se lleno, se descartan las mas viejas.
                while len(cache) > maxsize:
                    cache.popitem(last=False)

            return resultado

        envuelto.cache_clear = lambda: cache.clear()  # type: ignore[attr-defined]
        return envuelto

    return decorador


class TTL:
    """Constantes de TTL listas para usar (@cache_ttl(TTL.UN_MINUTO))."""

    SEGUNDOS = 1
    TREINTA_SEGUNDOS = 30
    UN_MINUTO = 60
    CINCO_MINUTOS = 300
    UNA_HORA = 3600
