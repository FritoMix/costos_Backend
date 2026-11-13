"""Una confirmación por operación de negocio, también con servicios compuestos."""

from functools import wraps

from sqlalchemy.orm import Session

_CLAVE = "datacontrol_unidad_de_trabajo"


def atomica(funcion):
    @wraps(funcion)
    def ejecutar(db: Session, *args, **kwargs):
        if db.info.get(_CLAVE):
            return funcion(db, *args, **kwargs)
        # El savepoint aísla esta operación de una transacción del llamador.
        # begin_nested también fuerza los cambios previos antes de abrirlo.
        try:
            savepoint = db.begin_nested()
        except Exception:
            db.rollback()
            raise
        db.info[_CLAVE] = True
        try:
            resultado = funcion(db, *args, **kwargs)
            db.flush()
            savepoint.commit()
        except Exception:
            savepoint.rollback()
            raise
        finally:
            db.info.pop(_CLAVE, None)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return resultado

    return ejecutar
