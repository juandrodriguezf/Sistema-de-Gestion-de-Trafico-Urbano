"""
start_pc1.py - Lanzador para todos los procesos de PC1 (Broker + Sensores).
Inicia el broker primero, luego genera un proceso sensor por tipo por intersección.
"""

import subprocess
import sys
import os
import json
import time
import signal
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PC1-Launcher] %(levelname)s: %(message)s")
logger = logging.getLogger("PC1-Launcher")


def main():
    # Carga la configuración
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    grid = config["grid"]
    cols = grid["columns"]
    rows = grid["rows"]
    ports = config["zmq_ports"]
    broker_host = config.get("pc1_host", "localhost")
    broker_port = ports["broker_frontend"]
    python = sys.executable
    pc1_dir = os.path.dirname(os.path.abspath(__file__))

    processes = []

    # 1. Inicia el broker
    logger.info("Iniciando broker...")
    broker_proc = subprocess.Popen(
        [python, os.path.join(pc1_dir, "broker.py")],
        cwd=os.path.join(pc1_dir, ".."),
    )
    processes.append(("BrokerZMQ", broker_proc))
    time.sleep(1)  # Da tiempo al broker para conectarse

    # 2. Inicia los sensores (3 por interseccion)
    sensor_scripts = {
        "espira": os.path.join(pc1_dir, "sensor_espira.py"),
        "camara": os.path.join(pc1_dir, "sensor_camara.py"),
        "gps": os.path.join(pc1_dir, "sensor_gps.py"),
    }

    total_sensors = 0
    for c in range(1, cols + 1):
        for r in range(1, rows + 1):
            for tipo, script in sensor_scripts.items():
                proc = subprocess.Popen(
                    [python, script, str(c), str(r), broker_host, str(broker_port)],
                    cwd=os.path.join(pc1_dir, ".."),
                )
                name = f"{tipo.upper()}_C{c}K{r}"
                processes.append((name, proc))
                total_sensors += 1

    logger.info(f"PC1 iniciado: 1 Broker + {total_sensors} sensores ({cols}x{rows} grid, 3 por interseccion)")
    logger.info("Presiona Ctrl+C para apagar todos los procesos")

    # Espera la interrupción
    try:
        for name, proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        logger.info("Apagando todos los procesos de PC1...")
        for name, proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=3)
                logger.info(f"  {name} apagado")
            except Exception:
                proc.kill()
                logger.warning(f"  {name} apagado")

    logger.info("PC1 apagado")


if __name__ == "__main__":
    main()
