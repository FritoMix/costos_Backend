"""
Pruebas del manejo de horas y de la deteccion de turno.

Es la parte mas facil de equivocar del sistema: el turno nocturno cruza la
medianoche, y la hora que escribe el operario es hora de Colombia, no UTC.
"""

from datetime import date, time

from app.core.tiempo import ZONA_HORARIA_LOCAL, combinar_fecha_y_hora
from app.modules.catalogos.models import Turno


def test_una_tanda_normal_empieza_y_termina_el_mismo_dia():
    inicio, fin = combinar_fecha_y_hora(date(2026, 8, 26), time(6, 0), time(14, 0))

    assert inicio.date() == date(2026, 8, 26)
    assert fin.date() == date(2026, 8, 26)
    assert fin > inicio


def test_una_tanda_que_cruza_la_medianoche_termina_al_dia_siguiente():
    inicio, fin = combinar_fecha_y_hora(date(2026, 8, 26), time(23, 30), time(1, 15))

    assert inicio.date() == date(2026, 8, 26)
    assert fin.date() == date(2026, 8, 27)
    assert (fin - inicio).total_seconds() == 105 * 60  # 1 hora 45 minutos


def test_las_horas_se_guardan_en_hora_de_colombia():
    inicio, _ = combinar_fecha_y_hora(date(2026, 8, 26), time(6, 0), time(14, 0))

    assert inicio.tzinfo == ZONA_HORARIA_LOCAL
    # Colombia es UTC-5: las 06:00 locales son las 11:00 UTC.
    assert inicio.utcoffset().total_seconds() == -5 * 3600


def _turno(nombre: str, inicio: time, fin: time, cruza: bool) -> Turno:
    turno = Turno()
    turno.nombre = nombre
    turno.hora_inicio = inicio
    turno.hora_fin = fin
    turno.cruza_medianoche = cruza
    turno.activo = True
    return turno


def test_turno_diurno_contiene_solo_su_franja():
    turno = _turno("Turno 1", time(6, 0), time(14, 0), False)

    assert turno.contiene(time(6, 0)) is True
    assert turno.contiene(time(13, 59)) is True
    assert turno.contiene(time(14, 0)) is False  # ya es del turno siguiente
    assert turno.contiene(time(5, 59)) is False


def test_turno_nocturno_contiene_antes_y_despues_de_medianoche():
    turno = _turno("Turno 3", time(22, 0), time(6, 0), True)

    assert turno.contiene(time(22, 0)) is True
    assert turno.contiene(time(23, 59)) is True
    assert turno.contiene(time(0, 30)) is True
    assert turno.contiene(time(5, 59)) is True
    assert turno.contiene(time(6, 0)) is False
    assert turno.contiene(time(15, 0)) is False
