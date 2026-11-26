"""Líneas de producción, variedades, unidad por línea y % de sabor (V21)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errores import ConflictoDeDatos, ErrorDeValidacion
from app.modules.catalogos import service as catalogos
from app.modules.catalogos.models import CategoriaProducto, Horno, Linea, Producto, Variedad
from app.modules.catalogos.schemas import HornoGuardar, VariedadGuardar
from app.modules.identidad.models import Rol, RolCodigo, Usuario
from app.modules.notificaciones.models import Notificacion, TipoNotificacion
from app.modules.produccion.models import UnidadSolicitada
from app.modules.produccion.schemas import OrdenGuardar, RecepcionGuardar, RegistroHornoGuardar
from app.modules.produccion.servicios import formula as servicio_formula
from app.modules.produccion.servicios import horno as servicio_horno
from app.modules.produccion.servicios import ordenes as servicio_ordenes
from app.modules.produccion.servicios import saborizado as servicio_saborizado


def _linea(db, codigo: str) -> Linea:
    return db.scalar(select(Linea).where(Linea.codigo == codigo))


def _montar_linea(db, datos_base, codigo: str, nombre_horno: str):
    """Horno, categoría y producto de una línea, con operarios de esa línea."""
    linea = _linea(db, codigo)
    categoria = CategoriaProducto(nombre=f"Categoría {codigo}", activo=True)
    db.add(categoria)
    db.flush()
    horno = Horno(nombre=nombre_horno, activo=True, linea_id=linea.id, apto_exportacion=False)
    horno.categorias = [categoria]
    producto = Producto(
        nombre_comercial=f"Producto {codigo}",
        categoria_id=categoria.id,
        activo=True,
        sabor_minimo_pct=Decimal("1.5"),
        sabor_maximo_pct=Decimal("2.5"),
    )
    roles = {r.codigo: r for r in db.scalars(select(Rol)).all()}
    operario_horno = Usuario(
        nombre_completo=f"Horno {codigo}",
        nombre_usuario=f"horno_{codigo}",
        password_hash="x",
        rol_id=roles[RolCodigo.OPERARIO_HORNO].id,
        linea_id=linea.id,
        activo=True,
    )
    operario_sabor = Usuario(
        nombre_completo=f"Sabor {codigo}",
        nombre_usuario=f"sabor_{codigo}",
        password_hash="x",
        rol_id=roles[RolCodigo.OPERARIO_SABORIZADO].id,
        linea_id=linea.id,
        activo=True,
    )
    db.add_all([horno, producto, operario_horno, operario_sabor])
    db.flush()
    return linea, horno, categoria, producto, operario_horno, operario_sabor


def _orden(datos_base, horno, categoria, producto, **cambios) -> OrdenGuardar:
    base = dict(
        turno_id=datos_base.turno.id,
        horno_id=horno.id,
        categoria_id=categoria.id,
        producto_id=producto.id,
        destino="nacional",
        unidad_solicitada=UnidadSolicitada.KG,
        cantidad_kg=Decimal("300"),
        horas_produccion=2,
    )
    base.update(cambios)
    return OrdenGuardar(**base)


def _tanda(**cambios) -> RegistroHornoGuardar:
    base = dict(
        operarios_seleccion=2,
        operarios_horno=1,
        nivel_aceite_inicial_cm=Decimal("20"),
        nivel_aceite_final_cm=Decimal("18"),
        temperatura_aceite_c=Decimal("175"),
    )
    base.update(cambios)
    return RegistroHornoGuardar(**base)


def test_lo_existente_queda_como_papa(db, datos_base):
    assert datos_base.horno.linea.codigo == "papa"
    assert datos_base.horno.linea.usa_bodega is True
    lineas = [linea.codigo for linea in catalogos.listar_lineas(db)]
    assert lineas == ["papa", "platano", "pellet", "extruido", "trocillo", "nachos"]


def test_orden_de_platano_pide_variedad_y_no_espera_bodega(db, datos_base):
    _, horno, categoria, producto, op_horno, _ = _montar_linea(db, datos_base, "platano", "Horno P")
    with pytest.raises(ErrorDeValidacion, match="qué tipo de plátano"):
        servicio_ordenes.crear_orden(
            db, _orden(datos_base, horno, categoria, producto), datos_base.supervisor
        )

    harton = db.scalar(select(Variedad).where(Variedad.nombre == "Hartón"))
    orden = servicio_ordenes.crear_orden(
        db, _orden(datos_base, horno, categoria, producto, variedad_id=harton.id), datos_base.supervisor
    )
    assert orden.linea.codigo == "platano"
    assert orden.variedad.nombre == "Hartón"
    assert orden.formula_obligatoria is False
    assert orden.formula_estado == "no_aplica"
    # Bodega (de papa) no recibe nada; el horno de plátano recibe "nueva orden".
    avisos = db.scalars(select(Notificacion).where(Notificacion.orden_id == orden.id)).all()
    destinatarios = {a.usuario_id for a in avisos}
    assert datos_base.bodeguero.id not in destinatarios
    assert op_horno.id in destinatarios
    assert all(a.tipo == TipoNotificacion.ORDEN_CREADA for a in avisos)
    assert "Ya se puede producir" in avisos[0].mensaje

    # Sin fórmula de Bodega: se inicia y se registra en kg de plátano.
    orden = servicio_ordenes.iniciar_orden(db, orden)
    orden.hora_inicio -= timedelta(hours=2)
    db.flush()
    with pytest.raises(ValueError, match="kilos de materia prima"):
        _tanda()
    with pytest.raises(ErrorDeValidacion, match="kilos de plátano"):
        servicio_horno.crear_registro(
            db,
            orden,
            _tanda(referencia_papa_id=datos_base.referencia_papa.id, cantidad_bultos=Decimal("10")),
            op_horno,
        )
    tanda = servicio_horno.crear_registro(db, orden, _tanda(kg_materia_prima=Decimal("420.5")), op_horno)
    assert tanda.cantidad_bultos == 0
    assert tanda.kg_crudos_calculados == Decimal("420.50")
    assert not tanda.alertas or "bultos" not in " ".join(tanda.alertas)

    with pytest.raises(ErrorDeValidacion, match="no lleva fórmula"):
        servicio_formula.guardar(db, orden, None, datos_base.bodeguero)


def test_unidades_por_linea_y_meta_sin_estimar(db, datos_base):
    _, horno, categoria, producto, _, _ = _montar_linea(db, datos_base, "trocillo", "Horno T")
    with pytest.raises(ErrorDeValidacion, match="se pide en mojes"):
        servicio_ordenes.crear_orden(
            db, _orden(datos_base, horno, categoria, producto), datos_base.supervisor
        )
    with pytest.raises(ErrorDeValidacion, match="cuántos mojes"):
        servicio_ordenes.crear_orden(
            db,
            _orden(datos_base, horno, categoria, producto, unidad_solicitada="mojes", cantidad_kg=None),
            datos_base.supervisor,
        )
    orden = servicio_ordenes.crear_orden(
        db,
        _orden(
            datos_base,
            horno,
            categoria,
            producto,
            unidad_solicitada="mojes",
            cantidad_kg=None,
            cantidad_unidades=3,
        ),
        datos_base.supervisor,
    )
    db.flush()  # la restricción de la base acepta la meta en 0 para mojes
    assert orden.cantidad_programada == 0
    assert orden.meta_texto == "3 mojes"

    # La papa sigue igual: no acepta mojes.
    with pytest.raises(ErrorDeValidacion, match="Papa la orden se pide en kg o canastillas"):
        servicio_ordenes.crear_orden(
            db,
            OrdenGuardar(
                turno_id=datos_base.turno.id,
                horno_id=datos_base.horno.id,
                categoria_id=datos_base.categoria.id,
                producto_id=datos_base.producto.id,
                unidad_solicitada="mojes",
                cantidad_unidades=2,
                horas_produccion=1,
            ),
            datos_base.supervisor,
        )


def test_cada_operario_ve_y_trabaja_solo_su_linea(db, datos_base, orden_guardar, guardar_formula):
    _, horno, categoria, producto, op_horno, _ = _montar_linea(db, datos_base, "pellet", "Horno Pe")
    de_papa = servicio_ordenes.crear_orden(db, orden_guardar(horas_produccion=2), datos_base.supervisor)
    guardar_formula(de_papa)
    de_pellet = servicio_ordenes.crear_orden(
        db,
        _orden(
            datos_base,
            horno,
            categoria,
            producto,
            unidad_solicitada="bultos",
            cantidad_kg=None,
            cantidad_unidades=4,
        ),
        datos_base.supervisor,
    )
    visibles = {o.id for o in servicio_ordenes.listar_ordenes(db, usuario=op_horno)}
    assert de_pellet.id in visibles
    assert de_papa.id not in visibles

    de_papa = servicio_ordenes.iniciar_orden(db, de_papa)
    de_papa.hora_inicio -= timedelta(hours=2)
    db.flush()
    with pytest.raises(ErrorDeValidacion, match="tú trabajas en la línea Pellet"):
        servicio_horno.crear_registro(db, de_papa, _tanda(kg_materia_prima=Decimal("100")), op_horno)

    # Bodega solo ve órdenes de papa.
    de_bodega = {o.id for o in servicio_formula.listar_ordenes_bodega(db)}
    assert de_papa.id in de_bodega
    assert de_pellet.id not in de_bodega


def test_rango_de_sabor_avisa_fuera_de_rango(db, datos_base):
    _, horno, categoria, producto, op_horno, op_sabor = _montar_linea(db, datos_base, "nachos", "Horno N")
    orden = servicio_ordenes.crear_orden(
        db, _orden(datos_base, horno, categoria, producto), datos_base.supervisor
    )
    orden = servicio_ordenes.iniciar_orden(db, orden)
    orden.hora_inicio -= timedelta(hours=2)
    db.flush()
    # 5 kg de sabor sobre 50 kg = 10 %: por encima del 2,5 %.
    recepcion = servicio_saborizado.crear_recepcion(
        db,
        orden,
        RecepcionGuardar(
            sabor_id=datos_base.sabor.id,
            cantidad_sabor_kg=Decimal("5"),
            pesos_canastillas=[Decimal("25"), Decimal("25")],
        ),
        op_sabor,
    )
    assert recepcion.porcentaje_sabor == Decimal("10.00")
    assert any("Sabor alto" in a for a in recepcion.alertas)


def test_variedades_se_corrigen_y_no_se_repiten(db):
    platano = _linea(db, "platano")
    fhia = db.scalar(select(Variedad).where(Variedad.nombre == "FHIA 21"))
    corregida = catalogos.actualizar_variedad(
        db, fhia.id, VariedadGuardar(linea_id=platano.id, nombre="FHIA-21")
    )
    assert corregida.nombre == "FHIA-21"
    with pytest.raises(ConflictoDeDatos):
        catalogos.crear_variedad(db, VariedadGuardar(linea_id=platano.id, nombre="hartón"))


def test_horno_no_cambia_de_linea_con_orden_abierta(db, datos_base, orden_guardar):
    servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    platano = _linea(db, "platano")
    with pytest.raises(ErrorDeValidacion, match="orden abierta"):
        catalogos.actualizar_horno(
            db,
            datos_base.horno.id,
            HornoGuardar(
                nombre=datos_base.horno.nombre, linea_id=platano.id, categoria_ids=[datos_base.categoria.id]
            ),
        )
    # Un horno nuevo sin línea queda de papa.
    nuevo = catalogos.crear_horno(db, HornoGuardar(nombre="Horno sin línea"))
    assert nuevo.linea.codigo == "papa"
    assert db.scalar(select(func.count()).select_from(Horno).where(Horno.linea_id.is_(None))) == 0


@pytest.mark.parametrize("peso", ["0.2", "45", "600"])
def test_canastilla_de_peso_imposible_se_rechaza(peso):
    """A prueba de errores: una canastilla fuera de 0,5 a 30 kg no se acepta."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RecepcionGuardar(sabor_id=1, cantidad_sabor_kg=Decimal("1"), pesos_canastillas=[Decimal(peso)])
    assert RecepcionGuardar(sabor_id=1, cantidad_sabor_kg=Decimal("1"), pesos_canastillas=[Decimal("6.5")])


def test_sabores_por_categoria(db, datos_base):
    """Cada categoría ofrece solo sus sabores; sin asignar, acepta todos."""
    from app.modules.catalogos.models import Sabor
    from app.modules.catalogos.schemas import CategoriaGuardar

    _, horno, categoria, producto, _, op_sabor = _montar_linea(db, datos_base, "pellet", "Horno P")
    jamon = Sabor(nombre="Jamón de Prueba", activo=True)
    db.add(jamon)
    db.flush()

    # Sin sabores asignados: la categoría acepta todos los activos.
    assert datos_base.sabor in catalogos.listar_sabores(db, True, categoria.id)

    catalogos.actualizar_categoria(
        db, categoria.id, CategoriaGuardar(nombre=categoria.nombre, sabor_ids=[jamon.id])
    )
    assert catalogos.listar_sabores(db, True, categoria.id) == [jamon]
    assert categoria.sabor_ids == [jamon.id]
    # Un cliente viejo que no envía sabor_ids los conserva.
    catalogos.actualizar_categoria(db, categoria.id, CategoriaGuardar(nombre=categoria.nombre))
    assert categoria.sabor_ids == [jamon.id]

    orden = servicio_ordenes.crear_orden(
        db,
        _orden(
            datos_base, horno, categoria, producto,
            unidad_solicitada=UnidadSolicitada.BULTOS, cantidad_kg=None, cantidad_unidades=10,
        ),
        datos_base.supervisor,
    )
    orden = servicio_ordenes.iniciar_orden(db, orden)
    orden.hora_inicio -= timedelta(hours=2)
    db.flush()
    datos = dict(cantidad_sabor_kg=Decimal("1"), pesos_canastillas=[Decimal("6")])
    with pytest.raises(ErrorDeValidacion, match="no es de la categoría"):
        servicio_saborizado.crear_recepcion(
            db, orden, RecepcionGuardar(sabor_id=datos_base.sabor.id, **datos), op_sabor
        )
    recepcion = servicio_saborizado.crear_recepcion(
        db, orden, RecepcionGuardar(sabor_id=jamon.id, **datos), op_sabor
    )
    assert recepcion.sabor_id == jamon.id


def test_capacidad_en_kilos_para_lineas_sin_bodega(db, datos_base):
    """V28: plátano y demás líneas sin Bodega guardan kg/h; la papa, bultos/h."""
    from app.modules.produccion.servicios import formulas_papa

    platano = _linea(db, "platano")
    papa_capacidad = formulas_papa.capacidad_de_hornos(db)

    # Un horno de plátano guarda kilos y descarta cualquier "bultos" que llegue.
    horno = catalogos.crear_horno(
        db,
        HornoGuardar(
            nombre="Hojuelas de plátano",
            linea_id=platano.id,
            capacidad_kg_hora=Decimal("450"),
            capacidad_bultos_hora=Decimal("9000"),
        ),
    )
    assert horno.capacidad_kg_hora == Decimal("450")
    assert horno.capacidad_bultos_hora is None
    # No altera la capacidad con la que Bodega reparte la mezcla de papa.
    assert formulas_papa.capacidad_de_hornos(db) == papa_capacidad

    # Un cliente viejo que solo manda bultos no le borra los kilos.
    actualizado = catalogos.actualizar_horno(
        db,
        horno.id,
        HornoGuardar(
            nombre="Hojuelas de plátano", linea_id=platano.id, capacidad_bultos_hora=Decimal("30")
        ),
    )
    assert actualizado.capacidad_kg_hora == Decimal("450")
    assert actualizado.capacidad_bultos_hora is None

    # El asistente de la orden solo ajusta bultos de hornos de papa.
    with pytest.raises(ErrorDeValidacion, match="kilos por hora"):
        catalogos.actualizar_capacidad_horno(db, horno.id, Decimal("40"))

    # Un horno de papa guarda bultos y descarta los kilos.
    papa = catalogos.crear_horno(
        db,
        HornoGuardar(
            nombre="Horno papa nuevo",
            capacidad_bultos_hora=Decimal("40"),
            capacidad_kg_hora=Decimal("900"),
        ),
    )
    assert papa.capacidad_bultos_hora == Decimal("40")
    assert papa.capacidad_kg_hora is None


def test_capacidad_vieja_en_bultos_de_otra_linea_no_entra_a_la_mezcla(db, datos_base):
    """Un valor heredado en bultos de un horno de plátano no infla el reparto de papa."""
    from app.modules.produccion.servicios import formulas_papa

    papa_capacidad = formulas_papa.capacidad_de_hornos(db)
    horno = Horno(
        nombre="Plátano heredado",
        activo=True,
        linea_id=_linea(db, "platano").id,
        apto_exportacion=False,
        capacidad_bultos_hora=Decimal("9999"),
    )
    db.add(horno)
    db.flush()
    assert formulas_papa.capacidad_de_hornos(db) == papa_capacidad


@pytest.mark.parametrize("valor", ["0", "-5", "450.5", "100000"])
def test_capacidad_kg_invalida_se_rechaza(valor):
    with pytest.raises(ValueError):
        HornoGuardar(nombre="X", capacidad_kg_hora=Decimal(valor))


def _orden_batch(db, datos_base, codigo="nachos", horas=3):
    _, horno, categoria, producto, op_horno, _ = _montar_linea(db, datos_base, codigo, f"Batch {codigo}")
    horno.tipo = "batch"
    db.flush()
    orden = servicio_ordenes.crear_orden(
        db, _orden(datos_base, horno, categoria, producto, horas_produccion=horas), datos_base.supervisor
    )
    orden = servicio_ordenes.iniciar_orden(db, orden)
    orden.hora_inicio -= timedelta(minutes=30)
    db.flush()
    return horno, orden, op_horno


def test_horno_batch_un_registro_por_orden_con_aceite_por_litros(db, datos_base):
    """V31: el horno batch registra la orden completa, sin nivel de aceite."""
    horno, orden, op_horno = _orden_batch(db, datos_base)
    datos = RegistroHornoGuardar(
        kg_materia_prima=Decimal("1500"),
        cantidad_baches=12,
        operarios_seleccion=2,
        operarios_horno=1,
        aceite_agregado_litros=Decimal("40"),
    )
    registro = servicio_horno.crear_registro(db, orden, datos, op_horno)
    assert registro.cantidad_baches == 12
    assert registro.nivel_aceite_inicial_cm is None and registro.diferencia_aceite_cm is None
    assert registro.volumen_aceite_litros == Decimal("40.00")
    # Cubre todas las horas de la orden, aunque no hayan terminado.
    assert registro.hora_fin - registro.hora_inicio == timedelta(hours=3)
    # Una sola vez por orden: lo demás se corrige.
    with pytest.raises(ErrorDeValidacion, match="ya tiene su registro"):
        servicio_horno.crear_registro(db, orden, datos, op_horno)
    corregido = servicio_horno.editar_registro(
        db, registro, datos.model_copy(update={"cantidad_baches": 14}), op_horno
    )
    assert corregido.cantidad_baches == 14


def test_horno_batch_exige_baches_y_el_continuo_exige_niveles(db, datos_base):
    _, orden, op_horno = _orden_batch(db, datos_base, "nachos")
    sin_baches = RegistroHornoGuardar(
        kg_materia_prima=Decimal("300"), operarios_seleccion=1, operarios_horno=1
    )
    with pytest.raises(ErrorDeValidacion, match="cuántos baches"):
        servicio_horno.crear_registro(db, orden, sin_baches, op_horno)

    _, horno, categoria, producto, op_continuo, _ = _montar_linea(db, datos_base, "platano", "Continuo P")
    harton = db.scalar(select(Variedad).where(Variedad.nombre == "Hartón"))
    continua = servicio_ordenes.crear_orden(
        db, _orden(datos_base, horno, categoria, producto, variedad_id=harton.id), datos_base.supervisor
    )
    continua = servicio_ordenes.iniciar_orden(db, continua)
    with pytest.raises(ErrorDeValidacion, match="nivel del aceite"):
        servicio_horno.crear_registro(
            db,
            continua,
            RegistroHornoGuardar(kg_materia_prima=Decimal("300"), operarios_seleccion=1, operarios_horno=1),
            op_continuo,
        )
    # En un continuo siguen valiendo 20.000 kg por hora como tope.
    with pytest.raises(ErrorDeValidacion, match="20,000"):
        servicio_horno.crear_registro(db, continua, _tanda(kg_materia_prima=Decimal("25000")), op_continuo)


def test_tipo_de_horno_no_cambia_con_orden_abierta(db, datos_base):
    horno, orden, _ = _orden_batch(db, datos_base)
    with pytest.raises(ErrorDeValidacion, match="cambiarle el tipo"):
        catalogos.actualizar_horno(
            db, horno.id, HornoGuardar(nombre=horno.nombre, linea_id=horno.linea_id, tipo="continuo")
        )
    # Un cliente viejo que no envía el tipo lo conserva.
    sin_tipo = HornoGuardar(nombre=horno.nombre, linea_id=horno.linea_id)
    igual = catalogos.actualizar_horno(db, horno.id, sin_tipo)
    assert igual.tipo == "batch"


def test_la_orden_informa_el_tipo_de_horno(db, datos_base):
    from app.modules.produccion.schemas import OrdenSalida

    _, orden, _ = _orden_batch(db, datos_base)
    assert OrdenSalida.model_validate(orden).horno_tipo == "batch"
