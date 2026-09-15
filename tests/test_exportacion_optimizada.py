"""
Pruebas de exportación optimizada a CSV y Excel.
"""

from datetime import datetime

from app.modules.analitica.exportacion import (
    ENCABEZADOS,
    generar_csv,
    generar_excel,
    nombre_archivo,
)


def test_nombre_archivo_formato():
    momento = datetime(2026, 8, 27, 10, 30)
    assert nombre_archivo("csv", momento) == "datacontrol_20260827_1030.csv"
    assert nombre_archivo("xlsx", momento) == "datacontrol_20260827_1030.xlsx"


def test_generar_csv_con_bom_y_delimitador():
    filas = [
        ENCABEZADOS,
        [
            "OP-20260827-0001",
            "2026-08-27",
            "Nacional",
            "Finalizada",
            "Supervisor Prueba",
            "Turno 1",
            "Horno 1",
            "Papa Hojuela",
            "Natural 100g",
            500.0,
            500.0,
            10.0,
            150.0,
            5.0,
            2.5,
            40.0,
        ],
    ]
    csv_bytes = generar_csv(filas)
    # Debe empezar con el BOM UTF-8 (\xef\xbb\xbf)
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    texto = csv_bytes.decode("utf-8-sig")
    assert "OP-20260827-0001" in texto
    assert ";" in texto  # delimitador para Excel en español


def test_generar_excel_bytes_validos():
    filas = [
        ENCABEZADOS,
        [
            "OP-20260827-0001",
            "2026-08-27",
            "Nacional",
            "Finalizada",
            "Supervisor Prueba",
            "Turno 1",
            "Horno 1",
            "Papa Hojuela",
            "Natural 100g",
            500.0,
            500.0,
            10.0,
            150.0,
            5.0,
            2.5,
            40.0,
        ],
    ]
    excel_bytes = generar_excel(filas)
    # El archivo Excel (.xlsx) es un zip que empieza con 'PK\x03\x04'
    assert excel_bytes.startswith(b"PK")
    assert len(excel_bytes) > 100
