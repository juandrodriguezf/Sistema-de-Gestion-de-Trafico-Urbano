"""
main_db.py - Servicio de base de datos principal para PC3.
Recibe datos de estado de tráfico desde Analytics (PULL), los persiste,
envía heartbeat y publica mensajes de replicación a la base de datos réplica.
"""

import zmq
import json
import sys
import os
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import TrafficState, ReplicationMessage, Heartbeat
from shared.db_utils import DatabaseManager
from shared.constants import TOPIC_SYNC, TOPIC_HEARTBEAT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MainDB] %(levelname)s: %(message)s")
logger = logging.getLogger("MainDB")


class MainDBService:
    """
    Servicio de base de datos principal (PC3).
    
    - recibe datos de estado de tráfico desde Analytics (PULL)
    - almacena todos los eventos y estados en SQLite
    - publica mensajes de replicación a la base de datos replica (PUB)
    - envía heartbeat periódico a Analytics (PUB)
    """

    def __init__(self, config: dict):
        self.config = config
        self.grid = config["grid"]
        self.ports = config["zmq_ports"]
        self.heartbeat_interval = config.get("heartbeat_interval_seconds", 5)
        self.running = False
        self.sequence_number = 0

        # Database
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "main_traffic.db")
        self.db = DatabaseManager(db_path)

        # ZMQ
        self.context = zmq.Context()

    def _next_sequence(self) -> int:
        """Obtiene el siguiente número de secuencia para el ordenamiento de la replicación."""
        self.sequence_number += 1
        return self.sequence_number

    def send_heartbeat(self, hb_pub: zmq.Socket):
        """Envía un heartbeat periódico al servicio de Analytics."""
        logger.info(f"el heartbeat se envio correctamente (interval={self.heartbeat_interval}s)")
        while self.running:
            try:
                hb = Heartbeat()
                msg = f"{TOPIC_HEARTBEAT} {hb.to_json()}"
                hb_pub.send_string(msg)
                logger.debug("Heartbeat enviado")
                time.sleep(self.heartbeat_interval)
            except zmq.ZMQError:
                if self.running:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                time.sleep(1)

    def publish_replication(self, rep_pub: zmq.Socket, tabla: str,
                             operacion: str, datos: dict):
        """Publica un mensaje de replicacion a la base de datos replica."""
        try:
            rep_msg = ReplicationMessage(
                tabla=tabla,
                operacion=operacion,
                datos=datos,
                sequence_number=self._next_sequence(),
            )
            msg = f"{TOPIC_SYNC} {rep_msg.to_json()}"
            rep_pub.send_string(msg)
        except Exception as e:
            logger.error(f"error al publicar la replicacion: {e}")

    def process_traffic_state(self, state: TrafficState, rep_pub: zmq.Socket):
        """Procesa y almacena un estado de tráfico desde Analytics."""
        try:
            int_id = state.interseccion
            metrics = state.metricas

            # Almacena el evento en la base de datos
            event_id = str(uuid.uuid4())
            self.db.insert_event(
                evento_id=event_id,
                sensor_id="analytics",
                interseccion_id=int_id,
                tipo_sensor="analysis",
                datos=metrics,
                timestamp=state.timestamp,
            )

            # Almacena el estado del trafico
            self.db.insert_traffic_state(
                interseccion_id=int_id,
                Q=metrics.get("Q", 0),
                Vp=metrics.get("Vp", 0),
                D=metrics.get("D", 0),
                veh_min=metrics.get("vehiculos_por_minuto", 0),
                estado=state.estado,
                timestamp=state.timestamp,
            )

            # Publica la replicacion del evento
            self.publish_replication(rep_pub, "eventos", "INSERT", {
                "evento_id": event_id,
                "sensor_id": "analytics",
                "interseccion_id": int_id,
                "tipo_sensor": "analysis",
                "datos": metrics,
                "timestamp": state.timestamp,
            })

            # Publica la replicacion del estado del trafico
            self.publish_replication(rep_pub, "estado_trafico", "INSERT", {
                "interseccion_id": int_id,
                "Q": metrics.get("Q", 0),
                "Vp": metrics.get("Vp", 0),
                "D": metrics.get("D", 0),
                "vehiculos_por_minuto": metrics.get("vehiculos_por_minuto", 0),
                "estado": state.estado,
                "timestamp": state.timestamp,
            })

            # Si se tomo una accion, se almacena y se replica
            if state.accion_tomada:
                accion = state.accion_tomada
                accion_id = str(uuid.uuid4())
                sem_id = accion.get("semaforo_id", "")
                estado_ant = accion.get("estado_anterior", "")
                estado_new = accion.get("estado_nuevo", "")

                self.db.insert_light_action(
                    accion_id=accion_id,
                    semaforo_id=sem_id,
                    estado_anterior=estado_ant,
                    estado_nuevo=estado_new,
                    razon="congestion",
                    origen="analytics",
                    timestamp=state.timestamp,
                )
                self.db.update_semaforo(sem_id, estado_new, state.timestamp)

                self.publish_replication(rep_pub, "acciones_semaforo", "INSERT", {
                    "accion_id": accion_id,
                    "semaforo_id": sem_id,
                    "estado_anterior": estado_ant,
                    "estado_nuevo": estado_new,
                    "razon": "congestion",
                    "origen": "analytics",
                    "timestamp": state.timestamp,
                })
                self.publish_replication(rep_pub, "semaforos", "UPDATE", {
                    "semaforo_id": sem_id,
                    "estado_actual": estado_new,
                    "timestamp": state.timestamp,
                })

        except Exception as e:
            logger.error(f"error al procesar el registro: {e}")

    def run(self):
        """Inicia el servicio de base de datos principal."""
        pc3_host = self.config.get("pc3_host", "localhost")

        # PULL socket: recibe datos desde Analytics
        pull_socket = self.context.socket(zmq.PULL)
        pull_socket.bind(f"tcp://{pc3_host}:{self.ports['analytics_to_db']}")
        logger.info(f"PULL bound at tcp://{pc3_host}:{self.ports['analytics_to_db']}")

        # PUB socket: replicacion a la base de datos replica
        rep_pub = self.context.socket(zmq.PUB)
        rep_pub.bind(f"tcp://{pc3_host}:{self.ports['db_replication']}")
        logger.info(f"Replication PUB bound at tcp://{pc3_host}:{self.ports['db_replication']}")

        # PUB socket: heartbeat
        hb_pub = self.context.socket(zmq.PUB)
        hb_pub.bind(f"tcp://{pc3_host}:{self.ports['heartbeat']}")
        logger.info(f"heartbeat PUB bound at tcp://{pc3_host}:{self.ports['heartbeat']}")

        # Inicializa la base de datos
        self.db.connect()
        self.db.seed_all(
            self.grid["columns"], self.grid["rows"],
            ["N", "S", "E", "W"]
        )
        self.running = True

        # Inicia el heartbeat en un hilo separado
        hb_thread = threading.Thread(target=self.send_heartbeat, args=(hb_pub,), daemon=True)
        hb_thread.start()

        logger.info("el servicio de base de datos principal esta funcionando")
        record_count = 0

        try:
            while self.running:
                if pull_socket.poll(1000):
                    raw = pull_socket.recv_string()
                    try:
                        state = TrafficState.from_json(raw)
                        self.process_traffic_state(state, rep_pub)
                        record_count += 1
                        if record_count % 100 == 0:
                            total = self.db.get_event_count()
                            logger.info(f"procesados {record_count} registros (total en la base de datos: {total})")
                    except Exception as e:
                        logger.error(f"error al procesar el registro: {e}")
        except KeyboardInterrupt:
            logger.info("el servicio se detuvo correctamente")
        finally:
            self.running = False
            self.db.close()
            pull_socket.close()
            rep_pub.close()
            hb_pub.close()
            self.context.term()
            logger.info(f"el servicio se detuvo correctamente, total de registros: {record_count}")


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    service = MainDBService(config)
    service.run()
