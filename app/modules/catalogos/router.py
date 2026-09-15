"""
Rutas HTTP del modulo Catalogos: /api/v1/catalogos/...

Leer los catalogos lo puede hacer cualquier usuario conectado (los
formularios de ordenes y registros necesitan las listas). Crear, editar y
borrar es exclusivo del Administrador.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.catalogos import service
from app.modules.catalogos.schemas import (
    CatalogoGuardar,
    CatalogoSalida,
    ConfiguracionGuardar,
    ConfiguracionSalida,
    DensidadVigenteSalida,
    HornoGuardar,
    HornoSalida,
    MuestraDensidadCrear,
    MuestraDensidadSalida,
    ProductoGuardar,
    ProductoSalida,
    TurnoGuardar,
    TurnoSalida,
)
from app.modules.identidad.dependencias import UsuarioAutenticado, requiere_roles
from app.modules.identidad.models import RolCodigo, Usuario

BD = Annotated[Session, Depends(get_db)]
SoloAdmin = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN))]

router = APIRouter(prefix="/catalogos", tags=["Catálogos"])


# --- Categorias ------------------------------------------------------------


@router.get("/categorias", response_model=list[CatalogoSalida])
def listar_categorias(db: BD, _: UsuarioAutenticado, solo_activas: bool = False):
    return service.listar_categorias(db, solo_activas)


@router.post("/categorias", response_model=CatalogoSalida, status_code=status.HTTP_201_CREATED)
def crear_categoria(datos: CatalogoGuardar, db: BD, _: SoloAdmin):
    return service.crear_categoria(db, datos)


@router.put("/categorias/{categoria_id}", response_model=CatalogoSalida)
def actualizar_categoria(categoria_id: int, datos: CatalogoGuardar, db: BD, _: SoloAdmin):
    return service.actualizar_categoria(db, categoria_id, datos)


@router.delete("/categorias/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_categoria(categoria_id: int, db: BD, _: SoloAdmin) -> None:
    service.eliminar_categoria(db, categoria_id)


# --- Sabores ---------------------------------------------------------------


@router.get("/sabores", response_model=list[CatalogoSalida])
def listar_sabores(db: BD, _: UsuarioAutenticado, solo_activos: bool = False):
    return service.listar_sabores(db, solo_activos)


@router.post("/sabores", response_model=CatalogoSalida, status_code=status.HTTP_201_CREATED)
def crear_sabor(datos: CatalogoGuardar, db: BD, _: SoloAdmin):
    return service.crear_sabor(db, datos)


@router.put("/sabores/{sabor_id}", response_model=CatalogoSalida)
def actualizar_sabor(sabor_id: int, datos: CatalogoGuardar, db: BD, _: SoloAdmin):
    return service.actualizar_sabor(db, sabor_id, datos)


@router.delete("/sabores/{sabor_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_sabor(sabor_id: int, db: BD, _: SoloAdmin) -> None:
    service.eliminar_sabor(db, sabor_id)


# --- Tipos de desperdicio --------------------------------------------------


@router.get("/tipos-desperdicio", response_model=list[CatalogoSalida])
def listar_tipos_desperdicio(db: BD, _: UsuarioAutenticado, solo_activos: bool = False):
    return service.listar_tipos_desperdicio(db, solo_activos)


@router.post("/tipos-desperdicio", response_model=CatalogoSalida, status_code=status.HTTP_201_CREATED)
def crear_tipo_desperdicio(datos: CatalogoGuardar, db: BD, _: SoloAdmin):
    return service.crear_tipo_desperdicio(db, datos)


@router.put("/tipos-desperdicio/{tipo_id}", response_model=CatalogoSalida)
def actualizar_tipo_desperdicio(tipo_id: int, datos: CatalogoGuardar, db: BD, _: SoloAdmin):
    return service.actualizar_tipo_desperdicio(db, tipo_id, datos)


@router.delete("/tipos-desperdicio/{tipo_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_tipo_desperdicio(tipo_id: int, db: BD, _: SoloAdmin) -> None:
    service.eliminar_tipo_desperdicio(db, tipo_id)


# --- Turnos ----------------------------------------------------------------


@router.get("/turnos", response_model=list[TurnoSalida])
def listar_turnos(db: BD, _: UsuarioAutenticado, solo_activos: bool = False):
    return service.listar_turnos(db, solo_activos)


@router.post("/turnos", response_model=TurnoSalida, status_code=status.HTTP_201_CREATED)
def crear_turno(datos: TurnoGuardar, db: BD, _: SoloAdmin):
    return service.crear_turno(db, datos)


@router.put("/turnos/{turno_id}", response_model=TurnoSalida)
def actualizar_turno(turno_id: int, datos: TurnoGuardar, db: BD, _: SoloAdmin):
    return service.actualizar_turno(db, turno_id, datos)


@router.delete("/turnos/{turno_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_turno(turno_id: int, db: BD, _: SoloAdmin) -> None:
    service.eliminar_turno(db, turno_id)


# --- Hornos ----------------------------------------------------------------


@router.get("/hornos", response_model=list[HornoSalida])
def listar_hornos(db: BD, _: UsuarioAutenticado, solo_activos: bool = False):
    return service.listar_hornos(db, solo_activos)


@router.post("/hornos", response_model=HornoSalida, status_code=status.HTTP_201_CREATED)
def crear_horno(datos: HornoGuardar, db: BD, _: SoloAdmin):
    return service.crear_horno(db, datos)


@router.put("/hornos/{horno_id}", response_model=HornoSalida)
def actualizar_horno(horno_id: int, datos: HornoGuardar, db: BD, _: SoloAdmin):
    return service.actualizar_horno(db, horno_id, datos)


@router.delete("/hornos/{horno_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_horno(horno_id: int, db: BD, _: SoloAdmin) -> None:
    service.eliminar_horno(db, horno_id)


# --- Productos -------------------------------------------------------------


@router.get("/productos", response_model=list[ProductoSalida])
def listar_productos(db: BD, _: UsuarioAutenticado, solo_activos: bool = False):
    return service.listar_productos(db, solo_activos)


@router.post("/productos", response_model=ProductoSalida, status_code=status.HTTP_201_CREATED)
def crear_producto(datos: ProductoGuardar, db: BD, _: SoloAdmin):
    return service.crear_producto(db, datos)


@router.put("/productos/{producto_id}", response_model=ProductoSalida)
def actualizar_producto(producto_id: int, datos: ProductoGuardar, db: BD, _: SoloAdmin):
    return service.actualizar_producto(db, producto_id, datos)


@router.delete("/productos/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_producto(producto_id: int, db: BD, _: SoloAdmin) -> None:
    service.eliminar_producto(db, producto_id)


# --- Configuracion de planta ----------------------------------------------


@router.get("/configuracion", response_model=ConfiguracionSalida)
def ver_configuracion(db: BD, _: UsuarioAutenticado):
    return service.obtener_configuracion(db)


@router.put("/configuracion", response_model=ConfiguracionSalida)
def guardar_configuracion(datos: ConfiguracionGuardar, db: BD, _: SoloAdmin):
    return service.guardar_configuracion(db, datos)


# --- Densidad del aceite ---------------------------------------------------


@router.get("/densidad-aceite", response_model=list[MuestraDensidadSalida])
def listar_muestras(db: BD, _: SoloAdmin, horno_id: int | None = None):
    return service.listar_muestras_densidad(db, horno_id)


@router.get("/densidad-aceite/vigentes", response_model=list[DensidadVigenteSalida])
def densidades_vigentes(db: BD, _: SoloAdmin):
    """Ultima densidad conocida de cada horno, para la pantalla de densidad."""
    from app.core.tiempo import hoy_local

    hoy = hoy_local()
    return service.obtener_densidades_vigentes_todos_hornos(db, hoy)


@router.post(
    "/densidad-aceite", response_model=MuestraDensidadSalida, status_code=status.HTTP_201_CREATED
)
def registrar_muestra(datos: MuestraDensidadCrear, db: BD, admin: SoloAdmin):
    return service.registrar_muestra_densidad(db, datos, admin.id)
