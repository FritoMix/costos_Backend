"""
Logica del catalogo de referencias de papa y de la proyeccion de produccion.

Solo el Administrador, el Supervisor y el Bodeguero pueden crear, corregir o
eliminar referencias. Cualquier usuario conectado puede consultarlas porque
el operario de horno necesita elegir una al registrar la tanda.

La proyeccion usa las referencias activas, su peso por bulto y la capacidad
del horno. El reparto es en partes iguales: la participacion por referencia
ya no se captura en Bodega; la mezcla real de cada orden se define en el
modulo de Formula (plantillas por producto). Los kg fritos solo se estiman
cuando la referencia tiene rendimiento configurado.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.modules.bodega.models import ReferenciaPapa
from app.modules.bodega.schemas import (
    ProyeccionProduccionSalida,
    ProyeccionReferenciaSalida,
    ReferenciaPapaGuardar,
)
from app.modules.catalogos.models import Horno
from app.modules.produccion.dominio.calculos import (
    Participacion,
    calcular_kg_crudos,
    calcular_kg_fritos_estimados,
    distribuir_bultos,
    validar_participaciones,
)

CIEN = Decimal("100")


def listar(db: Session, solo_activas: bool = False) -> list[ReferenciaPapa]:
    consulta = select(ReferenciaPapa).order_by(func.lower(ReferenciaPapa.nombre))
    if solo_activas:
        consulta = consulta.where(ReferenciaPapa.activo.is_(True))
    return list(db.scalars(consulta).all())


def obtener(db: Session, referencia_id: int) -> ReferenciaPapa:
    referencia = db.get(ReferenciaPapa, referencia_id)
    if referencia is None:
        raise RecursoNoEncontrado("Esa referencia de papa no existe.")
    return referencia


def _nombre_libre(db: Session, nombre: str, excluir_id: int | None) -> None:
    consulta = select(ReferenciaPapa.id).where(
        func.lower(ReferenciaPapa.nombre) == nombre.lower()
    )
    if excluir_id is not None:
        consulta = consulta.where(ReferenciaPapa.id != excluir_id)
    if db.scalar(consulta) is not None:
        raise ErrorDeValidacion(f'Ya existe una referencia de papa llamada "{nombre}".')


def _texto_limpio(valor: str, campo: str) -> str:
    limpio = valor.strip()
    if not limpio:
        raise ErrorDeValidacion(f"{campo} no puede estar vacío.")
    return limpio


def _tipo_opcional(valor: str | None) -> str | None:
    """El tipo de papa ya no se pide: se guarda NULL si no viene."""
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


def _validar_parametros(datos: ReferenciaPapaGuardar) -> None:
    """Segunda barrera, ademas de Pydantic, para llamadas internas."""
    rendimiento = datos.rendimiento_fritura_pct
    if rendimiento is not None and (rendimiento <= 0 or rendimiento > CIEN):
        raise ErrorDeValidacion(
            "El rendimiento de fritura debe ser mayor a 0 % y menor o igual a 100 %."
        )
    participacion = datos.porcentaje_produccion_pct
    if participacion is not None and (participacion < 0 or participacion > CIEN):
        raise ErrorDeValidacion(
            "La participación de producción debe estar entre 0 % y 100 %."
        )


def crear(db: Session, datos: ReferenciaPapaGuardar) -> ReferenciaPapa:
    nombre = _texto_limpio(datos.nombre, "El nombre de la referencia")
    _validar_parametros(datos)
    _nombre_libre(db, nombre, None)
    referencia = ReferenciaPapa(
        nombre=nombre,
        tipo=_tipo_opcional(datos.tipo),
        peso_promedio_bulto_kg=datos.peso_promedio_bulto_kg,
        rendimiento_fritura_pct=datos.rendimiento_fritura_pct,
        porcentaje_produccion_pct=datos.porcentaje_produccion_pct,
        activo=datos.activo,
    )
    db.add(referencia)
    db.commit()
    db.refresh(referencia)
    return referencia


def actualizar(
    db: Session, referencia_id: int, datos: ReferenciaPapaGuardar
) -> ReferenciaPapa:
    referencia = obtener(db, referencia_id)
    nombre = _texto_limpio(datos.nombre, "El nombre de la referencia")
    _validar_parametros(datos)
    _nombre_libre(db, nombre, referencia_id)
    referencia.nombre = nombre
    referencia.tipo = _tipo_opcional(datos.tipo)
    referencia.peso_promedio_bulto_kg = datos.peso_promedio_bulto_kg
    referencia.rendimiento_fritura_pct = datos.rendimiento_fritura_pct
    referencia.porcentaje_produccion_pct = datos.porcentaje_produccion_pct
    referencia.activo = datos.activo
    db.commit()
    db.refresh(referencia)
    return referencia


def eliminar(db: Session, referencia_id: int) -> None:
    from app.modules.produccion.models import (
        FormulaPapaReferencia,
        OrdenReferencia,
        RegistroHorno,
        RegistroHornoReferencia,
    )

    referencia = obtener(db, referencia_id)
    usada = db.scalar(
        select(RegistroHorno.id)
        .where(RegistroHorno.referencia_papa_id == referencia_id)
        .limit(1)
    )
    if usada is None:
        usada = db.scalar(
            select(RegistroHornoReferencia.id)
            .where(RegistroHornoReferencia.referencia_papa_id == referencia_id)
            .limit(1)
        )
    if usada is None:
        usada = db.scalar(
            select(OrdenReferencia.id)
            .where(OrdenReferencia.referencia_papa_id == referencia_id)
            .limit(1)
        )
    if usada is None:
        usada = db.scalar(
            select(FormulaPapaReferencia.id)
            .where(FormulaPapaReferencia.referencia_papa_id == referencia_id)
            .limit(1)
        )
    if usada is not None:
        raise ErrorDeValidacion(
            f'No se puede eliminar "{referencia.nombre}": se usa en una fórmula o en '
            "una tanda de horno. Puedes desactivarla en su lugar."
        )
    db.delete(referencia)
    db.commit()


def capacidad_entera(horno: Horno) -> int:
    if horno.capacidad_bultos_hora is None:
        raise ErrorDeValidacion(
            f'El {horno.nombre} no tiene configurada su capacidad de bultos por hora. '
            "Configúrala en Hornos antes de proyectar la producción."
        )
    capacidad = horno.capacidad_bultos_hora
    if capacidad <= 0 or capacidad != capacidad.to_integral_value():
        raise ErrorDeValidacion(
            "La capacidad del horno debe ser un número entero de bultos por hora."
        )
    return int(capacidad)


def validar_referencia_completa(referencia: ReferenciaPapa) -> None:
    """Lo unico imprescindible para proyectar es el peso por bulto."""
    if referencia.peso_promedio_bulto_kg is None or referencia.peso_promedio_bulto_kg <= 0:
        raise ErrorDeValidacion(
            f'La referencia "{referencia.nombre}" está incompleta: configura el '
            "peso promedio por bulto antes de proyectar la producción."
        )


def _participaciones_de_proyeccion(
    referencias: list[ReferenciaPapa],
) -> list[Participacion]:
    """
    Participacion de cada referencia para repartir la capacidad.

    Si todas tienen participacion y suman 100 % (tolerancia 0,01 %) se usa
    tal cual; si no, se reparte en partes iguales. La participacion por
    referencia ya no se captura en la pantalla de Bodega.
    """
    if all(referencia.porcentaje_produccion_pct is not None for referencia in referencias):
        candidatas = [
            Participacion(
                referencia_id=referencia.id,
                porcentaje=referencia.porcentaje_produccion_pct,
            )
            for referencia in referencias
        ]
        try:
            validar_participaciones(candidatas)
            return candidatas
        except ErrorDeValidacion:
            pass

    partes = CIEN / Decimal(len(referencias))
    return [
        Participacion(referencia_id=referencia.id, porcentaje=partes)
        for referencia in referencias
    ]


def proyectar(db: Session, horno_id: int, horas: int = 1) -> ProyeccionProduccionSalida:
    """
    Distribuye la capacidad del horno entre las referencias activas.

    Usa mayores restos para que la suma de bultos sea exactamente la
    capacidad. Los kg crudos y fritos se calculan con los parametros
    vigentes; no se guardan (es una simulacion planificada).
    """
    horno = db.get(Horno, horno_id)
    if horno is None:
        raise RecursoNoEncontrado("Ese horno no existe.")
    if not horno.activo:
        raise ErrorDeValidacion(
            f'El {horno.nombre} está inactivo. Actívalo o elige otro horno para proyectar.'
        )
    if horas < 1:
        raise ErrorDeValidacion("El número de horas debe ser mínimo 1.")

    capacidad_hora = capacidad_entera(horno)
    referencias = listar(db, solo_activas=True)
    if not referencias:
        raise ErrorDeValidacion(
            "No hay referencias de papa activas. Bodega debe registrar al menos una."
        )

    for referencia in referencias:
        validar_referencia_completa(referencia)

    participaciones = _participaciones_de_proyeccion(referencias)
    capacidad_total = capacidad_hora * horas
    bultos_por_referencia = distribuir_bultos(capacidad_total, participaciones)
    porcentaje_por_referencia = {
        participacion.referencia_id: participacion.porcentaje
        for participacion in participaciones
    }

    filas: list[ProyeccionReferenciaSalida] = []
    total_kg_crudos = Decimal("0")
    total_kg_fritos = Decimal("0")
    falta_rendimiento = False
    for referencia in referencias:
        rendimiento = referencia.rendimiento_fritura_pct
        bultos = bultos_por_referencia[referencia.id]
        kg_crudos = calcular_kg_crudos(bultos, referencia.peso_promedio_bulto_kg)
        total_kg_crudos += kg_crudos
        if rendimiento is None:
            falta_rendimiento = True
            kg_fritos = None
        else:
            kg_fritos = calcular_kg_fritos_estimados(kg_crudos, rendimiento)
            total_kg_fritos += kg_fritos
        filas.append(
            ProyeccionReferenciaSalida(
                referencia_id=referencia.id,
                nombre=referencia.nombre,
                tipo=referencia.tipo,
                porcentaje_produccion_pct=porcentaje_por_referencia[referencia.id],
                bultos=bultos,
                peso_promedio_bulto_kg=referencia.peso_promedio_bulto_kg,
                rendimiento_fritura_pct=rendimiento,
                kg_crudos=kg_crudos,
                kg_fritos_estimados=kg_fritos,
            )
        )

    return ProyeccionProduccionSalida(
        horno_id=horno.id,
        horno_nombre=horno.nombre,
        capacidad_bultos_hora=horno.capacidad_bultos_hora,
        horas=horas,
        total_bultos=sum(fila.bultos for fila in filas),
        total_kg_crudos=total_kg_crudos,
        total_kg_fritos_estimados=None if falta_rendimiento else total_kg_fritos,
        referencias=filas,
    )
