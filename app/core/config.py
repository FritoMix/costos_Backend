"""
Configuracion central de la aplicacion.

Todo lo que cambia entre un computador de pruebas y el servidor real de la
fabrica (claves, host de la base de datos, duracion de la sesion) se lee
del archivo .env con pydantic-settings. En el codigo NUNCA hay contrasenas
escritas a mano.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Aplicacion ---
    app_name: str = "DATACONTROL"
    app_env: str = "development"
    tz: str = "America/Bogota"

    # --- Base de datos ---
    # Si el proveedor de nube entrega una URL completa (Render, Railway...),
    # se usa esa y se ignoran las piezas sueltas de abajo. El alias
    # DATABASE_URL es el nombre estandar que usan esos servicios.
    database_url_externa: str = Field(default="", alias="DATABASE_URL")

    postgres_user: str = "datacontrol"
    postgres_password: str = "datacontrol"
    postgres_db: str = "datacontrol"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # --- Pool de conexiones ---
    # En local se carga poco y bastan unas pocas conexiones. En el servidor
    # real, con varios operarios metiendo datos a la vez, se sube el tamaño
    # con DATABASE_POOL_SIZE / DB_MAX_OVERFLOW. El maximo real lo pone
    # PostgreSQL (default: 100 conexiones).
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_segundos: int = 1800

    # Aplicar las migraciones al arrancar la API. Imprescindible cuando no
    # hay contenedor de Flyway (despliegues en la nube). En local es
    # inofensivo: ve que Flyway ya las aplico y no repite nada.
    migrar_al_arrancar: bool = True

    # --- Seguridad (JWT) ---
    jwt_secret_key: str = "clave-de-desarrollo-cambiar-en-produccion"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # --- Limite de peticiones (rate limiting) ---
    # 120/min por IP es de sobra para un operario humano. Se baja con
    # RATE_LIMIT_MINUTE si hace falta apretar la proteccion.
    rate_limit_minute: str = "120/minute"

    # --- Cookie de sesion ---
    # El token de sesion viaja en una cookie HttpOnly: el JavaScript del
    # navegador NUNCA puede leerla, asi que un ataque XSS no puede robar la
    # sesion (a diferencia de guardarla en localStorage). El navegador la
    # envia sola en cada peticion a la API.
    cookie_nombre: str = "datacontrol_sesion"
    # Solo se manda por HTTPS. En desarrollo (http://localhost) tiene que ser
    # False o el navegador descarta la cookie; en produccion, con HTTPS, se
    # activa sola (ver la propiedad cookie_secure).
    cookie_secure_forzar: bool = False

    # --- CORS ---
    # Se lee como texto separado por comas (ver la propiedad origenes_cors).
    # Si se declarara como list[str], pydantic-settings exigiria escribirlo
    # en el .env como una lista JSON, que es mucho mas incomodo de mantener.
    cors_origins: str = "http://localhost:4200"

    # --- Administrador inicial ---
    admin_username: str = "admin"
    admin_nombre_completo: str = "Administrador DATACONTROL"
    admin_password: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # populate_by_name: permite que el campo se llene tanto por su alias
        # (DATABASE_URL) como por su nombre en Python.
        populate_by_name=True,
    )

    @property
    def origenes_cors(self) -> list[str]:
        """CORS_ORIGINS=a,b,c -> ["a", "b", "c"]."""
        return [origen.strip() for origen in self.cors_origins.split(",") if origen.strip()]

    @property
    def database_url(self) -> str:
        """
        Cadena de conexion que usa SQLAlchemy para hablar con PostgreSQL.

        Dos formas de configurarla:
          1) DATABASE_URL completa. Es lo que entregan los servicios de nube
             (Render, Railway, Heroku...) y tiene prioridad.
          2) Las piezas sueltas POSTGRES_USER/PASSWORD/HOST/PORT/DB, que es
             lo comodo en local con Docker Compose.
        """
        if self.database_url_externa:
            return self._normalizar(self.database_url_externa)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def destino_base_datos(self) -> str:
        """
        A donde se esta intentando conectar, SIN la contrasena. Sirve para
        escribirlo en el log sin filtrar credenciales.
        """
        sin_driver = self.database_url.split("://", 1)[-1]
        # usuario:clave@host:puerto/base  ->  host:puerto/base
        return sin_driver.split("@")[-1] if "@" in sin_driver else sin_driver

    @property
    def usa_host_de_compose(self) -> bool:
        """
        True cuando se va a conectar al host "db", que SOLO existe dentro de
        Docker Compose. Si esto pasa en un servidor de nube, es que falta
        configurar DATABASE_URL.
        """
        return not self.database_url_externa and self.postgres_host == "db"

    @staticmethod
    def _normalizar(url: str) -> str:
        """
        Ajusta la URL al driver que usamos (psycopg 3).

        Los proveedores entregan "postgres://" o "postgresql://"; SQLAlchemy
        necesita saber el driver, o intentaria usar psycopg2 (que no esta
        instalado).
        """
        url = url.strip()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    @property
    def es_produccion(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cookie_secure(self) -> bool:
        """
        La cookie de sesion se marca Secure (solo HTTPS) en produccion, o si
        se fuerza a mano. En desarrollo por HTTP queda en False para que el
        navegador no la rechace.
        """
        return self.es_produccion or self.cookie_secure_forzar


@lru_cache
def get_settings() -> Settings:
    """
    Instancia unica de la configuracion (se lee del entorno una sola vez).
    Se expone como funcion para poder sustituirla en las pruebas.
    """
    return Settings()


settings = get_settings()
