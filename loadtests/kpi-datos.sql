-- Solo sobre la copia efímera de CI, ya migrada. Una transacción para todo el conjunto.
BEGIN;
INSERT INTO usuarios (nombre_completo,nombre_usuario,password_hash,rol_id,activo)
SELECT 'Prueba KPI','benchmark_kpi','cuenta-inactiva',min(id),false FROM roles;
INSERT INTO sabores (nombre) VALUES ('Prueba KPI');
INSERT INTO productos (nombre_comercial,categoria_id)
SELECT 'Benchmark KPI ' || n, (SELECT min(id) FROM categorias_producto) FROM generate_series(1,24) AS n;
INSERT INTO ordenes_produccion (numero_orden,fecha,supervisor_id,turno_id,horno_id,producto_id,
                                categoria_id,cantidad_programada,estado)
SELECT 'KPI-' || p.id || '-' || n, DATE '2036-01-01', u.id, (SELECT min(id) FROM turnos),
       (SELECT min(id) FROM hornos), p.id, p.categoria_id, 1000, 'finalizada'
FROM productos p CROSS JOIN usuarios u CROSS JOIN generate_series(1,10) AS n
WHERE p.nombre_comercial LIKE 'Benchmark KPI %' AND u.nombre_usuario='benchmark_kpi';
INSERT INTO registro_saborizado (orden_id,usuario_id,turno_id,hora_inicio,hora_fin,sabor_id,
                                 cantidad_sabor_kg,kg_recibidos)
SELECT o.id,o.supervisor_id,o.turno_id,now()-interval '1 hour',now(),s.id,1,o.producto_id+10
FROM ordenes_produccion o CROSS JOIN sabores s WHERE o.numero_orden LIKE 'KPI-%' AND s.nombre='Prueba KPI';
COMMIT;
