# Operación y respaldos

Las unidades systemd de esta carpeta son plantillas para un equipo de operación,
no tareas activadas en Render. Ejecutan scripts/backup_postgres.sh del repositorio
instalado en /opt/datacontrol, con variables privadas de /etc/datacontrol/backup.env.

La copia se cifra con age antes de escribirse y se envía fuera del servidor con
rclone. La restauración solo utiliza una base temporal generada por el programa.

Requisitos, programación, límites y recuperación: [OPERACION.md](../docs/OPERACION.md).
No activar el timer hasta comprobar una copia y una restauración en pruebas.
