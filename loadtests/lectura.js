/**
 * Prueba de carga de DATACONTROL (lectura).
 *
 * Simula operarios consultando ordenes, catalogos y notificaciones. Hace un
 * solo login por corrida y reutiliza la cookie; asi el limite de login no
 * distorsiona la medicion.
 *
 * Variables:
 *   BASE_URL    URL de la API o del frontend (default http://127.0.0.1:4200)
 *   ADMIN_USER  usuario (default admin)
 *   ADMIN_PASS  contrasena (obligatoria)
 *   VUS         usuarios virtuales (default 20)
 *   DURATION    duracion (default 2m)
 */

import http from 'k6/http';
import { check, fail, sleep } from 'k6';

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:4200';
const USUARIO = __ENV.ADMIN_USER || 'admin';
const PASSWORD = __ENV.ADMIN_PASS || '';

export const options = {
  vus: Number(__ENV.VUS || 20),
  duration: __ENV.DURATION || '2m',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    checks: ['rate>0.99'],
  },
};

export function setup() {
  if (!PASSWORD) fail('Falta ADMIN_PASS');

  const respuesta = http.post(
    `${BASE}/api/v1/auth/login`,
    JSON.stringify({ nombre_usuario: USUARIO, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );

  if (respuesta.status !== 200) {
    fail(`Login fallo: HTTP ${respuesta.status} ${respuesta.body}`);
  }

  const cookie = respuesta.cookies.datacontrol_sesion;
  if (!cookie || !cookie.length) fail('El login no devolvio la cookie de sesion');
  return { cookie: `datacontrol_sesion=${cookie[0].value}` };
}

const RUTAS = [
  '/api/v1/ordenes',
  '/api/v1/catalogos/productos',
  '/api/v1/catalogos/hornos',
  '/api/v1/notificaciones/pendientes',
];

export default function (datos) {
  const ruta = RUTAS[Math.floor(Math.random() * RUTAS.length)];
  const respuesta = http.get(`${BASE}${ruta}`, {
    headers: { Cookie: datos.cookie },
  });

  check(respuesta, {
    'respuesta 200': (r) => r.status === 200,
    'sin 429': (r) => r.status !== 429,
  });

  // Sondeo cada 20 s por usuario, mas el tiempo de las acciones normales.
  sleep(2 + Math.random() * 2);
}
