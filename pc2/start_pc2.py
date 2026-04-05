"""
start_pc2.py - Lanzador para todos los servicios de PC2.
Inicia Analytics Service, Traffic Light Controller, y Replica DB.
"""

import subprocess
import sys
import os
import json
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PC2-Launcher] %(levelname)s: %(message)s")
logger = logging.getLogger("PC2-Launcher")


def main():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    python = sys.executable
    pc2_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.join(pc2_dir, "..")

    # Asegura que el directorio de datos exista
    os.makedirs(os.path.join(project_root, "data"), exist_ok=True)

    processes = []

    # 1. Inicia el servicio de base de datos réplica
    logger.info("Iniciando servicio de base de datos replica...")
    proc = subprocess.Popen(
        [python, os.path.join(pc2_dir, "replica_db.py")],
        cwd=project_root,
    )
    processes.append(("ReplicaDB", proc))
    time.sleep(1)

    # 2. Inicia el controlador de semaforos
    logger.info("Iniciando controlador de semaforos...")
    proc = subprocess.Popen(
        [python, os.path.join(pc2_dir, "traffic_light_controller.py")],
        cwd=project_root,
    )
    processes.append(("TrafficLightController", proc))
    time.sleep(1)

    # 3. Inicia el servicio de analitica
    logger.info("Iniciando servicio de analitica...")
    proc = subprocess.Popen(
        [python, os.path.join(pc2_dir, "analytics_service.py")],
        cwd=project_root,
    )
    processes.append(("AnalyticsService", proc))

    logger.info("PC2 iniciado: AnalyticsService + TrafficLightController + ReplicaDB")
    logger.info("Presiona Ctrl+C para apagar todos los procesos")

    try:
        for name, proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        logger.info("Apagando todos los procesos de PC2...")
        for name, proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=3)
                logger.info(f"  {name} apagado")
            except Exception:
                proc.kill()
                logger.warning(f"  {name} apagado")

    logger.info("PC2 apagado")


if __name__ == "__main__":
    main()
