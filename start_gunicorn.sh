#!/bin/bash

# Activar virtualenv
source /home/appuser/apps/AppCitaNet/venv/bin/activate

# Crear carpeta de logs si no existe
mkdir -p /home/appuser/apps/AppCitaNet/logs

# Loop infinito para reiniciar Gunicorn si se cae
while true; do
    echo "[$(date)] Iniciando Gunicorn..." >> /home/appuser/apps/AppCitaNet/logs/gunicorn_restart.log
    /home/appuser/apps/AppCitaNet/venv/bin/gunicorn \
        --chdir /home/appuser/apps/AppCitaNet \
        app:app \
        --bind 0.0.0.0:8000 \
        --workers 2 \
        --access-logfile /home/appuser/apps/AppCitaNet/logs/gunicorn_access.log \
        --error-logfile /home/appuser/apps/AppCitaNet/logs/gunicorn_error.log
    echo "[$(date)] Gunicorn se detuvo, reiniciando en 5 segundos..." >> /home/appuser/apps/AppCitaNet/logs/gunicorn_restart.log
    sleep 5
done
