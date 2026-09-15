"""
Contrasenas y tokens de sesion.

- Las contrasenas se guardan solo como hash bcrypt (un algoritmo lento a
  proposito, para que no se puedan adivinar por fuerza bruta aunque
  alguien llegue a ver la base de datos).
- La sesion del usuario viaja en un token JWT firmado con JWT_SECRET_KEY:
  el servidor no necesita guardar sesiones en memoria ni en tablas.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Response

from app.core.config import settings
from app.core.errores import CredencialesInvalidas

# La cookie solo se envia en las rutas de la API, no con los archivos
# estaticos del frontend: no hay razon para que viaje con cada imagen o CSS.
_COOKIE_PATH = "/api"


def hash_password(password: str) -> str:
    """Convierte una contrasena en texto plano en su hash seguro."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, password_hash: str) -> bool:
    """Comprueba si una contrasena coincide con un hash guardado."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Hash con formato invalido (por ejemplo, dato corrupto en la base).
        return False


def crear_token_acceso(usuario_id: int, rol: str) -> tuple[str, int]:
    """
    Genera el token de sesion del usuario.

    Devuelve (token, segundos_de_vida) para que el frontend sepa cuando
    tiene que volver a pedir credenciales.
    """
    duracion = timedelta(minutes=settings.access_token_expire_minutes)
    expira_en = datetime.now(UTC) + duracion
    contenido = {
        "sub": str(usuario_id),
        "rol": rol,
        "exp": expira_en,
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(contenido, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(duracion.total_seconds())


def leer_token_acceso(token: str) -> dict:
    """
    Valida la firma y la vigencia del token y devuelve su contenido.
    Lanza CredencialesInvalidas si el token esta vencido o alterado.
    """
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise CredencialesInvalidas("Tu sesión expiró. Vuelve a iniciar sesión.") from exc
    except jwt.PyJWTError as exc:
        raise CredencialesInvalidas("Tu sesión no es válida. Vuelve a iniciar sesión.") from exc


def poner_cookie_sesion(response: Response, token: str, max_age_segundos: int) -> None:
    """
    Guarda el token en una cookie de sesion segura:

      HttpOnly       el JavaScript del navegador no puede leerla (anti-XSS).
      SameSite=Strict solo se envia en peticiones del propio sitio, lo que
                     corta de raiz los ataques CSRF sin necesidad de un token
                     extra (la app es de un solo origen).
      Secure         solo por HTTPS (activo en produccion; ver config).
    """
    response.set_cookie(
        key=settings.cookie_nombre,
        value=token,
        max_age=max_age_segundos,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=_COOKIE_PATH,
    )


def borrar_cookie_sesion(response: Response) -> None:
    """Elimina la cookie de sesion (cierre de sesion)."""
    response.delete_cookie(
        key=settings.cookie_nombre,
        path=_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
