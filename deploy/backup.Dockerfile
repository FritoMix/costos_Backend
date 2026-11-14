# Cliente 17 por defecto: comprobar la versión de Supabase antes de activar.
# Si el servidor usa otra versión mayor, ajustar POSTGRES_IMAGE y probar restauración.
ARG POSTGRES_IMAGE=postgres:17-alpine
FROM ${POSTGRES_IMAGE}
RUN apk add --no-cache python3 age rclone ca-certificates
WORKDIR /opt/datacontrol
COPY scripts/backup_postgres.py scripts/backup_render.py ./scripts/
USER postgres
ENTRYPOINT ["python3", "/opt/datacontrol/scripts/backup_render.py"]
