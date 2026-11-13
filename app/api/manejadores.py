"""
Traduccion de errores a respuestas HTTP.

Los servicios lanzan errores de negocio con un mensaje en espanol; aqui se
convierten en un JSON uniforme:

    { "detail": "La cantidad programada debe ser mayor a cero." }

El frontend siempre lee el mismo campo, sin importar de donde venga el
error, y nunca le muestra al usuario un rastro tecnico.
"""

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.errores import ErrorDeAplicacion

logger = logging.getLogger("datacontrol")


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(RateLimitExceeded)
    async def _demasiadas_peticiones(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Demasiadas peticiones en poco tiempo. Espera un momento y vuelve a intentar."
            },
        )

    @app.exception_handler(ErrorDeAplicacion)
    async def _error_de_aplicacion(_: Request, exc: ErrorDeAplicacion) -> JSONResponse:
        respuesta = JSONResponse(status_code=exc.codigo_http, content={"detail": exc.mensaje})
        if getattr(exc, "retry_after", None) is not None:
            respuesta.headers["Retry-After"] = str(exc.retry_after)
        if exc.codigo_http == 401:
            # Le dice al navegador (y al frontend) que hace falta un token.
            respuesta.headers["WWW-Authenticate"] = "Bearer"
        return respuesta

    @app.exception_handler(RequestValidationError)
    async def _datos_invalidos(_: Request, exc: RequestValidationError) -> JSONResponse:
        """
        Los datos no cumplen el contrato (falta un campo, un numero es
        negativo...). Se devuelve un mensaje legible ademas del detalle
        tecnico, que el frontend puede usar para marcar el campo.
        """
        primer_error = exc.errors()[0] if exc.errors() else {}
        campo = ".".join(str(p) for p in primer_error.get("loc", []) if p != "body")
        mensaje = primer_error.get("msg", "Revisa los datos del formulario.")
        return JSONResponse(
            status_code=422,
            content={
                "detail": f"{campo}: {mensaje}" if campo else mensaje,
                # jsonable_encoder: el detalle de Pydantic puede traer valores
                # que json.dumps no sabe serializar (por ejemplo un Decimal en
                # los limites de un campo numerico). Sin esto, el manejador de
                # errores fallaba y devolvia un 500 en vez del 422.
                "errores": jsonable_encoder(
                    [
                        {k: v for k, v in error.items() if k in {"loc", "msg", "type"}}
                        for error in exc.errors()
                    ]
                ),
            },
        )

    @app.exception_handler(IntegrityError)
    async def _error_de_integridad(_: Request, exc: IntegrityError) -> JSONResponse:
        """
        La base de datos rechazo la operacion (llave duplicada, indice
        unico...). Es la ultima linea de defensa de las reglas de negocio.
        """
        logger.warning("Integridad rechazada por PostgreSQL (%s)", type(exc.orig).__name__)
        return JSONResponse(
            status_code=409,
            content={"detail": "La operación choca con un dato que ya existe. Recarga e intenta de nuevo."},
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeoutError)
    async def _base_no_disponible(request: Request, exc: Exception) -> JSONResponse:
        logger.warning(
            "Base de datos temporalmente no disponible tipo=%s request_id=%s",
            type(exc).__name__,
            getattr(request.state, "request_id", ""),
        )
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "3"},
            content={"detail": "El servicio está temporalmente ocupado. Intenta de nuevo."},
        )

    @app.exception_handler(Exception)
    async def _error_inesperado(request: Request, exc: Exception) -> JSONResponse:
        # El detalle tecnico queda en los logs del servidor, nunca en la
        # respuesta: al usuario no se le muestra un rastro de Python.
        logger.error(
            "Error no controlado tipo=%s request_id=%s ubicaciones=%s",
            type(exc).__name__,
            getattr(request.state, "request_id", ""),
            [
                f"{marco.filename}:{marco.lineno}:{marco.name}"
                for marco in traceback.extract_tb(exc.__traceback__)
            ],
        )
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
            content={"detail": "Ocurrió un error inesperado. Intenta de nuevo."},
        )
