"""
Traduccion de errores a respuestas HTTP.

Los servicios lanzan errores de negocio con un mensaje en espanol; aqui se
convierten en un JSON uniforme:

    { "detail": "La cantidad programada debe ser mayor a cero." }

El frontend siempre lee el mismo campo, sin importar de donde venga el
error, y nunca le muestra al usuario un rastro tecnico.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError

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
                "errores": jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(IntegrityError)
    async def _error_de_integridad(_: Request, exc: IntegrityError) -> JSONResponse:
        """
        La base de datos rechazo la operacion (llave duplicada, indice
        unico...). Es la ultima linea de defensa de las reglas de negocio.
        """
        logger.warning("Integridad rechazada por PostgreSQL: %s", exc)
        return JSONResponse(
            status_code=409,
            content={
                "detail": "La operación choca con un dato que ya existe. Recarga e intenta de nuevo."
            },
        )

    @app.exception_handler(Exception)
    async def _error_inesperado(_: Request, exc: Exception) -> JSONResponse:
        # El detalle tecnico queda en los logs del servidor, nunca en la
        # respuesta: al usuario no se le muestra un rastro de Python.
        logger.exception("Error no controlado", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Ocurrió un error inesperado. Intenta de nuevo."},
        )
