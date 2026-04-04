"""
start_pc3.py - Launcher para todos los servicios de PC3.
Inicia Main DB y Monitoring Service.
"""

import subprocess
import sys
import os
import json
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PC3-Launcher] %(levelname)s: %(message)s")
logger = logging.getLogger("PC3-Launcher")


def main():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    python = sys.executable
    pc3_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.join(pc3_dir, "..")

    # Asegurar que el directorio de datos exista
    os.makedirs(os.path.join(project_root, "data"), exist_ok=True)

    processes = []

    # 1. Iniciar servicio de base de datos principal
    logger.info("Iniciando servicio de base de datos principal...")
    proc = subprocess.Popen(
        [python, os.path.join(pc3_dir, "main_db.py")],
        cwd=project_root,
    )
    processes.append(("MainDB", proc))
    time.sleep(2)  # Dar tiempo a la DB para inicializarse y comenzar el heartbeat

    # 2. Iniciar servicio de monitoreo (interactivo — se ejecuta en primer plano)
    logger.info("iniciando servicio de monitoreo...")
    logger.info("PC3 iniciado: MainDB + MonitoringService")
    logger.info("El cli de monitoreo se lanzará ahora...")
    print()

    # Ejecutar monitoreo en primer plano (es interactivo)
    try:
        mon_proc = subprocess.Popen(
            [python, os.path.join(pc3_dir, "monitoring_service.py")],
            cwd=project_root,
        )
        processes.append(("MonitoringService", mon_proc))
        mon_proc.wait()
    except KeyboardInterrupt:
        pass

    # Apagado
    logger.info("apagando todos los procesos de PC3...")
    for name, proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=3)
            logger.info(f"  {name} apagado")    
        except Exception:
            proc.kill()
            logger.warning(f"  {name} apagado")

    logger.info("PC3 apagado")


if __name__ == "__main__":
    main()
