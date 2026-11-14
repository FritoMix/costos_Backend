-- EJECUCIÓN MANUAL EN SUPABASE SQL EDITOR. No es una migración.
-- Alcance autorizado: conservar usuarios, catálogos y fórmulas reutilizables.
-- Detener escrituras del backend durante esta operación y ejecutar el archivo completo.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
LOCK TABLE public.canastillas, public.desperdicios, public.registro_horno_referencias, public.registro_saborizado, public.registro_horno, public.orden_referencias, public.notificaciones, public.operaciones_idempotentes, public.ordenes_produccion IN ACCESS EXCLUSIVE MODE;
LOCK TABLE public.roles, public.usuarios, public.sesiones_usuario, public.intentos_login, public.categorias_producto, public.turnos, public.hornos, public.sabores, public.productos, public.tipos_desperdicio, public.configuracion_planta, public.muestras_densidad_aceite, public.referencias_papa, public.formulas_papa, public.formula_papa_referencias, public.secuencia_ordenes, public.esquema_migraciones IN SHARE MODE;
CREATE TEMP TABLE limpieza_dc_resumen ON COMMIT DROP AS SELECT jsonb_build_object(
    'canastillas', (SELECT count(*) FROM public.canastillas),
    'desperdicios', (SELECT count(*) FROM public.desperdicios),
    'registro_horno_referencias', (SELECT count(*) FROM public.registro_horno_referencias),
    'registro_saborizado', (SELECT count(*) FROM public.registro_saborizado),
    'registro_horno', (SELECT count(*) FROM public.registro_horno),
    'orden_referencias', (SELECT count(*) FROM public.orden_referencias),
    'notificaciones', (SELECT count(*) FROM public.notificaciones),
    'operaciones_idempotentes', (SELECT count(*) FROM public.operaciones_idempotentes),
    'ordenes_produccion', (SELECT count(*) FROM public.ordenes_produccion)
) AS operativas,
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
) AS conservadas;
-- Sin CASCADE ni RESTART IDENTITY: nuevas referencias no previstas hacen abortar.
TRUNCATE TABLE public.canastillas, public.desperdicios, public.registro_horno_referencias, public.registro_saborizado, public.registro_horno, public.orden_referencias, public.notificaciones, public.operaciones_idempotentes, public.ordenes_produccion CONTINUE IDENTITY RESTRICT;
DELETE FROM public.auditoria_operaciones WHERE recurso IN ('orden','horno','saborizado','formula_orden');
DO $limpieza$
BEGIN
    IF (SELECT conservadas FROM limpieza_dc_resumen) IS DISTINCT FROM
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
) THEN
        RAISE EXCEPTION 'La limpieza alteró las cantidades de datos que debían conservarse';
    END IF;
END
$limpieza$;
INSERT INTO public.auditoria_operaciones (recurso, recurso_id, accion, antes, despues)
SELECT 'mantenimiento', 0, 'limpieza_operativa', operativas,
       jsonb_build_object('resultado', 'operaciones eliminadas; usuarios y catalogos conservados')
FROM limpieza_dc_resumen;
SELECT operativas AS eliminadas, conservadas AS conservadas FROM limpieza_dc_resumen;
COMMIT;
