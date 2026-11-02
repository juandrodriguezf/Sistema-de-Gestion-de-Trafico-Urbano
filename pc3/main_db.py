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

from shared.models import (
    TrafficState, ReplicationMessage, Heartbeat, ResyncBatch, ResyncResponse, _now
)
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
        self.resync_batch_size = config.get("resync_batch_size", 100)
        self.resync_timeout = config.get("resync_timeout_seconds", 5)
        self.running = False
        self.sequence_number = 0
        self.session_id = ""
        # Serializa el acceso a SQLite entre el hilo principal y el de resync
        self._db_lock = threading.RLock()

        # Base de datos
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "main_traffic.db")
        self.db = DatabaseManager(db_path)

        # ZMQ
        self.context = zmq.Context()

    def _next_sequence(self) -> int:
        """Obtiene y persiste el siguiente numero de secuencia de replicacion."""
        with self._db_lock:
            self.sequence_number += 1
            try:
                self.db.set_replication_state(last_sequence=self.sequence_number)
            except Exception as e:
                logger.error(f"No se pudo persistir la secuencia de replicacion: {e}")
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
                session_id=self.session_id,
            )
            msg = f"{TOPIC_SYNC} {rep_msg.to_json()}"
            rep_pub.send_string(msg)
        except Exception as e:
            logger.error(f"error al publicar la replicacion: {e}")

    def process_traffic_state(self, state: TrafficState, rep_pub: zmq.Socket):
        """Procesa y almacena un estado de tráfico desde Analytics."""
        with self._db_lock:
            self._process_traffic_state_locked(state, rep_pub)

    def _process_traffic_state_locked(self, state: TrafficState, rep_pub: zmq.Socket):
        try:
            int_id = state.interseccion
            metrics = state.metricas
            ts = state.timestamp

            # Solo los eventos reales de sensores van a la tabla `eventos`.
            # Los estados generados por Analytics no se registran como eventos sinteticos.
            if state.original_event_id:
                event_id = state.original_event_id
                sensor_id = state.original_sensor_id
                tipo_sensor = state.original_tipo_sensor
                datos = json.loads(state.original_datos) if state.original_datos else metrics
                timestamp_sensor = state.original_timestamp or ts

                self.db.insert_event(
                    evento_id=event_id,
                    sensor_id=sensor_id,
                    interseccion_id=int_id,
                    tipo_sensor=tipo_sensor,
                    datos=datos,
                    timestamp=ts,
                    timestamp_sensor=timestamp_sensor,
                )

                self.publish_replication(rep_pub, "eventos", "INSERT", {
                    "evento_id": event_id,
                    "sensor_id": sensor_id,
                    "interseccion_id": int_id,
                    "tipo_sensor": tipo_sensor,
                    "datos": datos,
                    "timestamp": ts,
                    "timestamp_sensor": timestamp_sensor,
                })

            # Almacena el estado del trafico
            self.db.insert_traffic_state(
                interseccion_id=int_id,
                Q=metrics.get("Q", 0),
                Vp=metrics.get("Vp", 0),
                D=metrics.get("D", 0),
                veh_min=metrics.get("vehiculos_por_minuto", 0),
                estado=state.estado,
                timestamp=ts,
                message_id=state.message_id,
            )

            # Publica la replicacion del estado del trafico
            self.publish_replication(rep_pub, "estado_trafico", "INSERT", {
                "interseccion_id": int_id,
                "Q": metrics.get("Q", 0),
                "Vp": metrics.get("Vp", 0),
                "D": metrics.get("D", 0),
                "vehiculos_por_minuto": metrics.get("vehiculos_por_minuto", 0),
                "estado": state.estado,
                "timestamp": ts,
                "message_id": state.message_id,
            })

            # Almacena y replica todas las acciones tomadas (principal y adyacentes)
            acciones = state.acciones_tomadas or (
                [state.accion_tomada] if state.accion_tomada else []
            )
            for accion in acciones:
                accion_id = str(uuid.uuid4())
                sem_id = accion.get("semaforo_id", "")
                estado_ant = accion.get("estado_anterior", "")
                estado_new = accion.get("estado_nuevo", "")
                razon = accion.get("razon", "congestion_detectada")
                origen = accion.get("origen", "analytics")

                if not sem_id or estado_ant == estado_new:
                    continue

                self.db.insert_light_action(
                    accion_id=accion_id,
                    semaforo_id=sem_id,
                    estado_anterior=estado_ant,
                    estado_nuevo=estado_new,
                    razon=razon,
                    origen=origen,
                    timestamp=ts,
                )
                self.db.update_semaforo(sem_id, estado_new, ts)

                self.publish_replication(rep_pub, "acciones_semaforo", "INSERT", {
                    "accion_id": accion_id,
                    "semaforo_id": sem_id,
                    "estado_anterior": estado_ant,
                    "estado_nuevo": estado_new,
                    "razon": razon,
                    "origen": origen,
                    "timestamp": ts,
                })
                self.publish_replication(rep_pub, "semaforos", "UPDATE", {
                    "semaforo_id": sem_id,
                    "estado_actual": estado_new,
                    "timestamp": ts,
                })

        except Exception as e:
            logger.error(f"error al procesar el registro: {e}")

    # ═══════════════════════════════════════════
    # Reconciliación tras failover (REP)
    # ═══════════════════════════════════════════

    def apply_resync_message(self, msg: dict) -> str:
        """Aplica un mensaje del outbox de forma idempotente.

        Returns: "aplicado" | "duplicado".
        """
        with self._db_lock:
            return self._apply_resync_message_locked(msg)

    def _apply_resync_message_locked(self, msg: dict) -> str:
        tabla = msg.get("tabla", "")
        operacion = msg.get("operacion", "")
        datos = msg.get("datos") or {}

        if tabla == "eventos" and operacion == "INSERT":
            evento_id = datos.get("evento_id", "")
            if not evento_id or self.db.event_exists(evento_id):
                return "duplicado"
            self.db.insert_event(
                evento_id,
                datos.get("sensor_id", ""),
                datos.get("interseccion_id", ""),
                datos.get("tipo_sensor", ""),
                datos.get("datos", {}),
                datos.get("timestamp", ""),
                timestamp_sensor=datos.get("timestamp_sensor"),
            )
            return "aplicado"

        if tabla == "estado_trafico" and operacion == "INSERT":
            message_id = datos.get("message_id")
            if self.db.traffic_state_exists(message_id):
                return "duplicado"
            self.db.insert_traffic_state(
                datos.get("interseccion_id", ""),
                datos.get("Q", 0),
                datos.get("Vp", 0),
                datos.get("D", 0),
                datos.get("vehiculos_por_minuto", 0),
                datos.get("estado", "normal"),
                datos.get("timestamp", ""),
                message_id=message_id,
            )
            return "aplicado"

        if tabla == "acciones_semaforo" and operacion == "INSERT":
            accion_id = datos.get("accion_id", "")
            if not accion_id or self.db.light_action_exists(accion_id):
                return "duplicado"
            self.db.insert_light_action(
                accion_id,
                datos.get("semaforo_id", ""),
                datos.get("estado_anterior", ""),
                datos.get("estado_nuevo", ""),
                datos.get("razon", ""),
                datos.get("origen", ""),
                datos.get("timestamp", ""),
            )
            return "aplicado"

        if tabla == "semaforos" and operacion == "UPDATE":
            sem_id = datos.get("semaforo_id", "")
            nuevo_estado = datos.get("estado_actual", "")
            if not sem_id:
                return "duplicado"
            if self.db.get_semaforo_state(sem_id) == nuevo_estado:
                return "duplicado"
            self.db.update_semaforo(sem_id, nuevo_estado, datos.get("timestamp", ""))
            return "aplicado"

        raise ValueError(f"mensaje de resync no soportado: {tabla}/{operacion}")

    def process_resync_batch(self, batch: ResyncBatch) -> ResyncResponse:
        """Aplica un lote completo y devuelve el resumen."""
        with self._db_lock:
            return self._process_resync_batch_locked(batch)

    def _process_resync_batch_locked(self, batch: ResyncBatch) -> ResyncResponse:
        aplicados = duplicados = errores = 0
        for msg in batch.mensajes:
            try:
                resultado = self.apply_resync_message(msg)
                if resultado == "aplicado":
                    aplicados += 1
                else:
                    duplicados += 1
            except Exception as e:
                errores += 1
                logger.error(f"Error al aplicar resync: {e}")

        logger.info(
            f"Resync {batch.batch_id[:8]}: recibidos={len(batch.mensajes)} "
            f"aplicados={aplicados} duplicados={duplicados} errores={errores}"
        )
        return ResyncResponse(
            recibidos=len(batch.mensajes),
            aplicados=aplicados,
            duplicados=duplicados,
            errores=errores,
            mensaje=f"Resync aplicado: {aplicados} nuevos, {duplicados} duplicados",
        )

    def handle_resync(self, rep_socket: zmq.Socket):
        """Atiende lotes de reconciliacion desde la replica."""
        logger.info("Endpoint de resync listo")
        while self.running:
            try:
                if rep_socket.poll(1000):
                    raw = rep_socket.recv_string()
                    try:
                        batch = ResyncBatch.from_json(raw)
                        response = self.process_resync_batch(batch)
                    except Exception as e:
                        logger.error(f"Lote de resync invalido: {e}")
                        response = ResyncResponse(
                            tipo="ERROR", mensaje=f"Lote invalido: {e}"
                        )
                    rep_socket.send_string(response.to_json())
            except zmq.ZMQError as e:
                if self.running:
                    logger.error(f"Error en el endpoint de resync: {e}")
            except Exception as e:
                logger.error(f"Error en el endpoint de resync: {e}")

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

        # REP socket: reconciliacion desde la replica tras failover
        resync_rep = self.context.socket(zmq.REP)
        resync_rep.bind(f"tcp://{pc3_host}:{self.ports['resync_port']}")
        logger.info(f"resync REP bound at tcp://{pc3_host}:{self.ports['resync_port']}")

        # Inicializa la base de datos
        self.db.connect()
        self.db.seed_all(
            self.grid["columns"], self.grid["rows"],
            ["N", "S", "E", "W"]
        )

        # Restaura la sesion y secuencia de replicacion persistidas
        state = self.db.get_replication_state()
        self.session_id = state["session_id"] or str(uuid.uuid4())
        self.sequence_number = state["last_sequence"] or 0
        self.db.set_replication_state(
            session_id=self.session_id, last_sequence=self.sequence_number
        )
        logger.info(
            f"Sesion de replicacion {self.session_id[:8]} "
            f"(ultima secuencia={self.sequence_number})"
        )

        self.running = True

        # Inicia el heartbeat en un hilo separado
        hb_thread = threading.Thread(target=self.send_heartbeat, args=(hb_pub,), daemon=True)
        hb_thread.start()

        resync_thread = threading.Thread(target=self.handle_resync, args=(resync_rep,), daemon=True)
        resync_thread.start()

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
                            with self._db_lock:
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
            resync_rep.close()
            self.context.term()
            logger.info(f"el servicio se detuvo correctamente, total de registros: {record_count}")


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    service = MainDBService(config)
    service.run()
