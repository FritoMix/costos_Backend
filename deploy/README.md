# Despliegue on-premise

Artefactos de operación que acompañan a los repositorios. El código de la
aplicación vive en `backdata/` y `frontdata/`; esta carpeta solo contiene
piezas de servidor.

## Backup automático

1. Copiar las unidades al servidor:
   ```bash
   sudo cp deploy/systemd/datacontrol-backup.* /etc/systemd/system/
   ```
2. Ajustar `User`/`Group` y la ruta `/opt/datacontrol` si el sistema está en
   otra ubicación (el usuario debe poder ejecutar `docker` y leer `.env`).
3. Activar el timer:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now datacontrol-backup.timer
   systemctl list-timers datacontrol-backup.timer
   ```
4. Probar una ejecución y un restore:
   ```bash
   sudo systemctl start datacontrol-backup.service
   sudo -u datacontrol ./scripts/restore_backup_test.sh /var/lib/datacontrol-backups/ARCHIVO.dump
   ```
5. Copiar `/var/lib/datacontrol-backups` a un NAS o servidor externo. Un
   backup que solo vive en el mismo disco no protege contra falla de disco.

Detalle de RPO/RTO y restauración: `docs/OPERACION.md`.
