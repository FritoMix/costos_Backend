"""
Rutas HTTP del modulo Bodega: /api/v1/bodega/referencias-papa.

Consultar las referencias lo puede hacer cualquier usuario conectado: el
operario de horno las necesita para registrar una tanda. Crear, corregir y
eliminar es exclusivo del Administrador y del Bodeguero.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.bodega import service
from app.modules.bodega.schemas import ReferenciaPapaGuardar, ReferenciaPapaSalida
from app.modules.identidad.dependencias import UsuarioAutenticado, requiere_roles
from app.modules.identidad.models import RolCodigo, Usuario

BD = Annotated[Session, Depends(get_db)]
GestionaBodega = Annotated[
    Usuario, Depends(requiere_roles(RolCodigo.ADMIN, RolCodigo.BODEGUERO))
]

router = APIRouter(prefix="/bodega/referencias-papa", tags=["Bodega de papa"])


@router.get("", response_model=list[ReferenciaPapaSalida])
def listar(db: BD, _: UsuarioAutenticado, solo_activas: bool = False):
    return service.listar(db, solo_activas)


@router.get("/{referencia_id}", response_model=ReferenciaPapaSalida)
def detalle(referencia_id: int, db: BD, _: UsuarioAutenticado):
    return service.obtener(db, referencia_id)


@router.post("", response_model=ReferenciaPapaSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: ReferenciaPapaGuardar, db: BD, _: GestionaBodega):
    return service.crear(db, datos)


@router.put("/{referencia_id}", response_model=ReferenciaPapaSalida)
def actualizar(referencia_id: int, datos: ReferenciaPapaGuardar, db: BD, _: GestionaBodega):
    return service.actualizar(db, referencia_id, datos)


@router.delete("/{referencia_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(referencia_id: int, db: BD, _: GestionaBodega) -> None:
    service.eliminar(db, referencia_id)
