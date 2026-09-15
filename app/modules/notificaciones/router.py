"""
Rutas HTTP del modulo Notificaciones: /api/v1/notificaciones/...

Cada quien ve solo sus propios avisos: el usuario sale del token, nunca de
un parametro que se pueda manipular.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.identidad.dependencias import UsuarioAutenticado
from app.modules.notificaciones import service
from app.modules.notificaciones.schemas import NotificacionSalida, ResumenNotificaciones

BD = Annotated[Session, Depends(get_db)]

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones"])


@router.get("/pendientes", response_model=ResumenNotificaciones)
def consultar_pendientes(db: BD, usuario: UsuarioAutenticado) -> ResumenNotificaciones:
    """
    Lo que la app consulta cada pocos segundos: avisos que ya toca mostrar y
    que la persona aun no ha visto. Con esto suena la alarma.
    """
    lista = service.pendientes(db, usuario)
    return ResumenNotificaciones(
        sin_leer=len(lista),
        pendientes=[NotificacionSalida.model_validate(n) for n in lista],
    )


@router.get("", response_model=list[NotificacionSalida])
def listar_historial(db: BD, usuario: UsuarioAutenticado):
    """Ultimos avisos recibidos, para el panel de la campana."""
    return service.historial(db, usuario)


@router.post("/{notificacion_id}/leida", status_code=status.HTTP_204_NO_CONTENT)
def marcar_leida(notificacion_id: int, db: BD, usuario: UsuarioAutenticado) -> None:
    service.marcar_leida(db, notificacion_id, usuario)


@router.post("/leidas", status_code=status.HTTP_204_NO_CONTENT)
def marcar_todas(db: BD, usuario: UsuarioAutenticado) -> None:
    service.marcar_todas_leidas(db, usuario)
