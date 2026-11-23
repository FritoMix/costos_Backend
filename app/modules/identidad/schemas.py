"""
Contratos de entrada y salida del modulo Identidad.

Los "schemas" son la frontera entre el mundo exterior (JSON) y el interior
(modelos de base de datos). Gracias a ellos el password_hash nunca sale
por la API, y los datos que entran se validan antes de tocar la logica.
"""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _validar_password_bcrypt(valor: str) -> str:
    if len(valor.encode("utf-8")) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes UTF-8.")
    return valor


PasswordNueva = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_validar_password_bcrypt)]


class RolSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str


class LineaRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str


class UsuarioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_completo: str
    nombre_usuario: str
    activo: bool
    fecha_creacion: datetime
    rol: RolSalida
    # Linea del operario o de Bodega (V21). Admin y supervisor no tienen.
    linea: LineaRef | None = None
    # Entro con una contraseña temporal: debe crear la suya (V21).
    debe_cambiar_password: bool = False


class UsuarioCrear(BaseModel):
    nombre_completo: str = Field(min_length=3, max_length=150)
    nombre_usuario: str = Field(min_length=3, max_length=50)
    password: PasswordNueva
    rol_id: int
    activo: bool = True
    # Operarios y Bodega: su linea. Si no se envia, queda en papa.
    linea_id: int | None = None


class UsuarioActualizar(BaseModel):
    nombre_completo: str = Field(min_length=3, max_length=150)
    nombre_usuario: str = Field(min_length=3, max_length=50)
    rol_id: int
    activo: bool = True
    # Operarios y Bodega: su linea. Si no se envia, conserva la que tenia.
    linea_id: int | None = None
    # Solo si el administrador quiere cambiarla; si viene vacia, se deja
    # la que ya tenia.
    password: PasswordNueva | None = None


class LoginPeticion(BaseModel):
    nombre_usuario: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=1024)


class SesionSalida(BaseModel):
    """
    Respuesta del login. NO incluye el token a proposito: el token viaja en
    una cookie HttpOnly que el frontend nunca ve. Aqui solo van los datos
    del usuario y cuanto dura la sesion (para avisar antes de que expire).
    """

    expira_en_segundos: int
    inactividad_segundos: int
    usuario: UsuarioSalida


class CambiarPasswordPeticion(BaseModel):
    password_actual: str = Field(min_length=1)
    password_nueva: PasswordNueva


class SolicitudRecuperacion(BaseModel):
    nombre_usuario: str = Field(min_length=1, max_length=50)


class PasswordTemporalSalida(BaseModel):
    # Se muestra una sola vez a quien la genero, para dictarsela a la persona.
    password_temporal: str
