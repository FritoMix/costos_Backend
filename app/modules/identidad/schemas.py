"""
Contratos de entrada y salida del modulo Identidad.

Los "schemas" son la frontera entre el mundo exterior (JSON) y el interior
(modelos de base de datos). Gracias a ellos el password_hash nunca sale
por la API, y los datos que entran se validan antes de tocar la logica.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RolSalida(BaseModel):
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


class UsuarioCrear(BaseModel):
    nombre_completo: str = Field(min_length=3, max_length=150)
    nombre_usuario: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    rol_id: int
    activo: bool = True


class UsuarioActualizar(BaseModel):
    nombre_completo: str = Field(min_length=3, max_length=150)
    nombre_usuario: str = Field(min_length=3, max_length=50)
    rol_id: int
    activo: bool = True
    # Solo si el administrador quiere cambiarla; si viene vacia, se deja
    # la que ya tenia.
    password: str | None = Field(default=None, min_length=8, max_length=128)


class LoginPeticion(BaseModel):
    nombre_usuario: str = Field(min_length=1)
    password: str = Field(min_length=1)


class SesionSalida(BaseModel):
    """
    Respuesta del login. NO incluye el token a proposito: el token viaja en
    una cookie HttpOnly que el frontend nunca ve. Aqui solo van los datos
    del usuario y cuanto dura la sesion (para avisar antes de que expire).
    """

    expira_en_segundos: int
    usuario: UsuarioSalida


class CambiarPasswordPeticion(BaseModel):
    password_actual: str = Field(min_length=1)
    password_nueva: str = Field(min_length=8, max_length=128)
