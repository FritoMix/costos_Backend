-- Solo lectura: no elimina ningún registro.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT jsonb_build_object(
    'canastillas', (SELECT count(*) FROM public.canastillas),
    'desperdicios', (SELECT count(*) FROM public.desperdicios),
    'registro_horno_referencias', (SELECT count(*) FROM public.registro_horno_referencias),
    'registro_saborizado', (SELECT count(*) FROM public.registro_saborizado),
    'registro_horno', (SELECT count(*) FROM public.registro_horno),
    'orden_referencias', (SELECT count(*) FROM public.orden_referencias),
    'notificaciones', (SELECT count(*) FROM public.notificaciones),
    'operaciones_idempotentes', (SELECT count(*) FROM public.operaciones_idempotentes),
    'ordenes_produccion', (SELECT count(*) FROM public.ordenes_produccion),
    'auditoria_operativa', (SELECT count(*) FROM public.auditoria_operaciones
        WHERE recurso IN ('orden','horno','saborizado','formula_orden'))
) AS se_eliminara,
jsonb_build_object(
    'roles', (SELECT count(*) FROM public.roles),
    'usuarios', (SELECT count(*) FROM public.usuarios),
    'sesiones_usuario', (SELECT count(*) FROM public.sesiones_usuario),
    'intentos_login', (SELECT count(*) FROM public.intentos_login),
    'categorias_producto', (SELECT count(*) FROM public.categorias_producto),
    'turnos', (SELECT count(*) FROM public.turnos),
    'hornos', (SELECT count(*) FROM public.hornos),
    'sabores', (SELECT count(*) FROM public.sabores),
    'productos', (SELECT count(*) FROM public.productos),
    'tipos_desperdicio', (SELECT count(*) FROM public.tipos_desperdicio),
    'configuracion_planta', (SELECT count(*) FROM public.configuracion_planta),
    'muestras_densidad_aceite', (SELECT count(*) FROM public.muestras_densidad_aceite),
    'referencias_papa', (SELECT count(*) FROM public.referencias_papa),
    'formulas_papa', (SELECT count(*) FROM public.formulas_papa),
    'formula_papa_referencias', (SELECT count(*) FROM public.formula_papa_referencias),
    'secuencia_ordenes', (SELECT count(*) FROM public.secuencia_ordenes),
    'esquema_migraciones', (SELECT count(*) FROM public.esquema_migraciones)
) AS se_conservara;
COMMIT;
