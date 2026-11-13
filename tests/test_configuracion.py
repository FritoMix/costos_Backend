import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings, settings
from app.core.errores import CredencialesInvalidas
from app.core.seguridad import leer_token_acceso


def test_produccion_rechaza_clave_de_desarrollo():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, app_env="production")


def test_produccion_rechaza_cors_abierto():
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(_env_file=None, app_env="production", jwt_secret_key="x" * 40, cors_origins="*")


def test_produccion_configurada_activa_cookie_secure():
    config = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key="x" * 40,
        cors_origins="https://costos.example.com",
    )
    assert config.cookie_secure


def test_password_reservado_no_rompe_url_ni_sale_en_diagnostico():
    config = Settings(_env_file=None, DATABASE_URL="", postgres_password="p@ss:/?#word")
    assert make_url(config.database_url).password == "p@ss:/?#word"
    assert config.destino_base_datos == "db:5432/datacontrol"


@pytest.mark.parametrize("campo", ["exp", "iat", "sub", "rol", "tv"])
def test_rechaza_tokens_sin_claim_obligatorio(campo):
    contenido = {"exp": 9999999999, "iat": 1, "sub": "1", "rol": "admin", "tv": 0}
    del contenido[campo]
    token = jwt.encode(contenido, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(CredencialesInvalidas):
        leer_token_acceso(token)


@pytest.mark.parametrize("password", ["x" * 73, "ñ" * 37])
def test_password_nueva_rechaza_exceso_de_bytes(password):
    from app.modules.identidad.schemas import UsuarioCrear

    with pytest.raises(ValidationError):
        UsuarioCrear(nombre_completo="Usuario Prueba", nombre_usuario="prueba", password=password, rol_id=1)


def test_password_multibyte_dentro_del_limite():
    from app.modules.identidad.schemas import CambiarPasswordPeticion

    datos = CambiarPasswordPeticion(password_actual="anterior", password_nueva="ñ" * 36)
    assert len(datos.password_nueva.encode("utf-8")) == 72
