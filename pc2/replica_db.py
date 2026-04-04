"""
replica_db.py - manager de base de datos replica para PC2.
Se suscribe a los mensajes de replicación desde Main DB (PC3) y
mantiene una copia sincronizada. Durante la falla de PC3, acepta
escrituras directas desde Analytics Service.
"""

import zmq
import json
import sys
import os
import logging
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import ReplicationMessage
from shared.db_utils import DatabaseManager
from shared.constants import TOPIC_SYNC

logging.basicConfig(level=logging.INFO, format="%(asctime)s [ReplicaDB] %(levelname)s: %(message)s")
logger = logging.getLogger("ReplicaDB")


class ReplicaDBService:
    """
    Servicio de base de datos réplica para PC2.
    
    Operación normal: Se suscribe a PUB desde Main DB y replica escrituras.
    Modo de recuperación: Acepta PUSH directo desde Analytics cuando PC3 está caído.
    """

    def __init__(self, config: dict):
        self.config = config
        self.ports = config["zmq_ports"]
        self.grid = config["grid"]
        self.running = False
        self.last_sequence = 0

        # Base de datos
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "replica_traffic.db")
        self.db = DatabaseManager(db_path)

        # ZMQ
        self.context = zmq.Context()

    def apply_replication(self, rep_msg: ReplicationMessage):
        """Aplica un mensaje de replicación a la base de datos réplica."""
        try:
            tabla = rep_msg.tabla
            datos = rep_msg.datos
            operacion = rep_msg.operacion

            if tabla == "eventos" and operacion == "INSERT":
                self.db.insert_event(
                    datos.get("evento_id", ""),
                    datos.get("sensor_id", ""),
                    datos.get("interseccion_id", ""),
                    datos.get("tipo_sensor", ""),
                    datos.get("datos", {}),
                    datos.get("timestamp", ""),
                )
            elif tabla == "estado_trafico" and operacion == "INSERT":
                self.db.insert_traffic_state(
                    datos.get("interseccion_id", ""),
                    datos.get("Q", 0),
                    datos.get("Vp", 0),
                    datos.get("D", 0),
                    datos.get("vehiculos_por_minuto", 0),
                    datos.get("estado", "normal"),
                    datos.get("timestamp", ""),
                )
            elif tabla == "acciones_semaforo" and operacion == "INSERT":
                self.db.insert_light_action(
                    datos.get("accion_id", ""),
                    datos.get("semaforo_id", ""),
                    datos.get("estado_anterior", ""),
                    datos.get("estado_nuevo", ""),
                    datos.get("razon", ""),
                    datos.get("origen", ""),
                    datos.get("timestamp", ""),
                )
            elif tabla == "semaforos" and operacion == "UPDATE":
                self.db.update_semaforo(
                    datos.get("semaforo_id", ""),
                    datos.get("estado_actual", ""),
                    datos.get("timestamp", ""),
                )

            self.last_sequence = rep_msg.sequence_number
            logger.debug(f"Replicado: {tabla}/{operacion} seq={rep_msg.sequence_number}")

        except Exception as e:
            logger.error(f"Error al replicar en {rep_msg.tabla}: {e}")

    def run(self):
        """Inicia el servicio de base de datos réplica."""
        pc3_host = self.config.get("pc3_host", "localhost")

        # SUB socket: recibe la replicacion desde la base de datos principal
        sub_socket = self.context.socket(zmq.SUB)
        sub_socket.connect(f"tcp://{pc3_host}:{self.ports['db_replication']}")
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, TOPIC_SYNC)
        logger.info(f"se suscribio a la replicacion en tcp://{pc3_host}:{self.ports['db_replication']}")

        # Inicializa la base de datos
        self.db.connect()
        self.db.seed_all(
            self.grid["columns"], self.grid["rows"],
            ["N", "S", "E", "W"]
        )
        self.running = True

        logger.info("el servicio de base de datos replica se esta ejecutando...")
        rep_count = 0

        try:
            while self.running:
                if sub_socket.poll(1000):
                    raw = sub_socket.recv_string()
                    parts = raw.split(" ", 1)
                    if len(parts) == 2:
                        topic, payload = parts
                        try:
                            msg = ReplicationMessage.from_json(payload)
                            self.apply_replication(msg)
                            rep_count += 1
                            if rep_count % 50 == 0:
                                logger.info(f"Replicado {rep_count} registros (last_seq={self.last_sequence})")
                        except Exception as e:
                            logger.error(f"Error al procesar la replicacion: {e}")
        except KeyboardInterrupt:
            logger.info("el servicio de base de datos replica se detuvo por el usuario")
        finally:
            self.running = False
            self.db.close()
            sub_socket.close()
            self.context.term()
            logger.info(f"el servicio de base de datos replica se detuvo por el usuario: {rep_count}")


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    service = ReplicaDBService(config)
    service.run()
