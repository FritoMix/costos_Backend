"""
Errores propios de la aplicacion.

La idea: los servicios (la logica de negocio) nunca saben nada de HTTP.
Lanzan uno de estos errores con un mensaje escrito para que lo lea una
persona, y la capa de API (app/api/manejadores.py) lo traduce al codigo
HTTP que corresponda.
"""


class ErrorDeAplicacion(Exception):
    """Base de todos los errores propios. No se usa directamente."""

    codigo_http = 400

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class ErrorDeValidacion(ErrorDeAplicacion):
    """
    Una regla de negocio no se cumple (ej: el horno no puede producir esa
    categoria). El mensaje se muestra tal cual en pantalla.
    """

    codigo_http = 400


class RecursoNoEncontrado(ErrorDeAplicacion):
    """El id pedido no existe o esta eliminado."""

    codigo_http = 404


class CredencialesInvalidas(ErrorDeAplicacion):
    """No hay sesion valida: usuario/contrasena incorrectos o token vencido."""

    codigo_http = 401


class PermisoDenegado(ErrorDeAplicacion):
    """Hay sesion, pero el rol del usuario no alcanza para esta accion."""

    codigo_http = 403


class ConflictoDeDatos(ErrorDeAplicacion):
    """Choca con algo que ya existe (ej: un nombre que debe ser unico)."""

    codigo_http = 409
