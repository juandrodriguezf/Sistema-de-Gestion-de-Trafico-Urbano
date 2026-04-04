"""
traffic_light_controller.py - Administrador de estado de semaforos para PC2.
Se suscribe a los comandos de cambio de semaforo desde Analytics y
mantiene el estado actual de todos los semaforos.
"""

import zmq
import json
import sys
import os
import logging
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import LightAction
from shared.constants import VERDE, ROJO, DIRECTIONS
from shared.db_utils import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TrafficLights] %(levelname)s: %(message)s")
logger = logging.getLogger("TrafficLightController")


class TrafficLightController:
    """
    ADMINISTRA LOS SEMAFOROS.
    Se suscribe a los comandos de Analytics y aplica los cambios de estado.
    Mantiene el estado en memoria y lo persiste en la base de datos réplica.
    """

    def __init__(self, config: dict):
        self.config = config
        self.grid = config["grid"]
        self.ports = config["zmq_ports"]
        self.running = False

        # Estados de los semáforos en memoria: {semaforo_id: estado}
        self.light_states = {}
        self._init_lights()

        # Contexto ZMQ
        self.context = zmq.Context()

        # Replica base de datos para persistencia
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "replica_traffic.db")
        self.db = DatabaseManager(db_path)

    def _init_lights(self):
        """Inicializa todos los semaforos con estados alternos."""
        for c in range(1, self.grid["columns"] + 1):
            for r in range(1, self.grid["rows"] + 1):
                for d in DIRECTIONS:
                    sem_id = f"SEM_C{c}K{r}_{d}"
                    # Estado inicial alterno basado en la posicion
                    self.light_states[sem_id] = VERDE if (c + r) % 2 == 0 else ROJO

        logger.info(f"se inicializaron {len(self.light_states)} semaforos")

    def change_light(self, semaforo_id: str, nuevo_estado: str, razon: str, origen: str):
        """Cambia el estado de un semaforo y registra la accion."""
        if semaforo_id not in self.light_states:
            logger.warning(f"semaforo desconocido: {semaforo_id}")
            return

        estado_anterior = self.light_states[semaforo_id]
        if estado_anterior == nuevo_estado:
            logger.debug(f"{semaforo_id} ya esta en {nuevo_estado}, no hay cambio")
            return

        self.light_states[semaforo_id] = nuevo_estado
        now = datetime.now(timezone.utc).isoformat()

        logger.info(f"Light changed: {semaforo_id} {estado_anterior} → {nuevo_estado} ({razon})")

        # Persistencia en la base de datos
        try:
            self.db.update_semaforo(semaforo_id, nuevo_estado, now)
            self.db.insert_light_action(
                accion_id=str(uuid.uuid4()),
                semaforo_id=semaforo_id,
                estado_anterior=estado_anterior,
                estado_nuevo=nuevo_estado,
                razon=razon,
                origen=origen,
                timestamp=now,
            )
        except Exception as e:
            logger.error(f"error al escribir en la base de datos: {e}")

    def get_state(self, semaforo_id: str) -> str:
        """Obtiene el estado actual de un semaforo."""
        return self.light_states.get(semaforo_id, "UNKNOWN")

    def run(self):
        """suscribe a los comandos de los semaforos y los procesa."""
        pc2_host = self.config.get("pc2_host", "localhost")

        # SUB socket: recibe comandos desde Analytics
        sub_socket = self.context.socket(zmq.SUB)
        sub_socket.connect(f"tcp://{pc2_host}:{self.ports['analytics_to_lights']}")
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, "semaforo/")
        logger.info(f"Subscrito a comandos de semaforos en tcp://{pc2_host}:{self.ports['analytics_to_lights']}")

        # Conecta a la base de datos
        self.db.connect()
        self.running = True

        logger.info("el controlador de semaforos se esta ejecutando...")
        change_count = 0

        try:
            while self.running:
                if sub_socket.poll(1000):
                    raw = sub_socket.recv_string()
                    parts = raw.split(" ", 1)
                    if len(parts) == 2:
                        topic, payload = parts
                        try:
                            action = LightAction.from_json(payload)
                            self.change_light(
                                action.semaforo_id,
                                action.nuevo_estado,
                                action.razon,
                                "analytics",
                            )
                            change_count += 1
                        except Exception as e:
                            logger.error(f"Error al procesar el comando del semaforo: {e}")
        except KeyboardInterrupt:
            logger.info("el controlador de semaforos se detuvo por el usuario")
        finally:
            self.running = False
            self.db.close()
            sub_socket.close()
            self.context.term()
            logger.info(f"el controlador de semaforos se detuvo: {change_count}")


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    controller = TrafficLightController(config)
    controller.run()
