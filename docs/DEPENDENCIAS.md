# Dependencias y escaneo de seguridad

## Backend

El escaneo se ejecuta en CI con `pip-audit` sobre `requirements.txt`:

```bash
docker build --target desarrollo -t datacontrol-test .
docker run --rm -v "$PWD":/code -w /code datacontrol-test \
  sh -lc 'pip-audit -r requirements.txt --strict'
```

Estado al cerrar Sprint 3: **sin vulnerabilidades conocidas**.

Reglas:

- Las versiones de producción están fijadas en `requirements.txt`.
- Un cambio de dependencia debe pasar pruebas unitarias, integración con
  PostgreSQL, `ruff` y `pip-audit` antes de mergear.
- Dependabot abre PR semanales; no se mergean automáticamente.
- Si una vulnerabilidad no se puede corregir todavía, se documenta aquí el
  CVE/GHSA, por qué no aplica y hasta cuándo se acepta. No se usa
  `--ignore-vuln` sin esa justificación.
