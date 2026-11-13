from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.api.manejadores import registrar_manejadores


class Datos(BaseModel):
    password: str = Field(min_length=12)


def test_validacion_no_devuelve_password_recibido():
    app = FastAPI()
    registrar_manejadores(app)

    @app.post("/validar")
    def validar(datos: Datos):
        return {"ok": True}

    respuesta = TestClient(app).post("/validar", json={"password": "secreto"})
    assert respuesta.status_code == 422
    assert "secreto" not in respuesta.text
    assert respuesta.json()["errores"][0]["loc"] == ["body", "password"]
