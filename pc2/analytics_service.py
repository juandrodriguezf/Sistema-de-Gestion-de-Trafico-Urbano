"""
analytics_service.py - motor analítico central para PC2.
se suscribe a eventos de sensores desde BrokerZMQ (SUB),
envia comandos de cambio de semaforo,
y responde a consultas de Monitoreo via REQ/REP.
"""

import zmq
import json
import sys
import os
import time
import logging
import threading
import uuid
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import (
    SensorEvent, TrafficState, LightAction,
    MonitoringRequest, MonitoringResponse, Heartbeat,
    ResyncBatch, ResyncResponse, _now,
)
from shared.constants import (
    VERDE, ROJO, NORMAL, CONGESTION, PRIORIDAD,
    SENSOR_ESPIRA, SENSOR_CAMARA, SENSOR_GPS,
    REASON_CONGESTION, REASON_NORMAL, REASON_PRIORITY, REASON_MANUAL,
    ORIGIN_ANALYTICS, ORIGIN_MONITORING,
    CMD_CONSULTA, CMD_OVERRIDE, CMD_LISTAR_SEMAFOROS, CMD_CONSULTA_HISTORICA,
    TOPIC_SENSOR, TOPIC_HEARTBEAT,
    parse_semaforo_id, semaforo_topic, intersection_id,
)
from shared.validation import validate_sensor_event, validate_override_command, validate_query
from shared.db_utils import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Analytics] %(levelname)s: %(message)s")
logger = logging.getLogger("AnalyticsService")


class AnalyticsService:
    """
    Motor analítico central que:
    1. Se suscribe a eventos de sensores desde BrokerZMQ (SUB)
    2. Evalúa reglas de tráfico por intersección
    3. Envía comandos de cambio de semáforo (PUB)
    4. Envía eventos/estados a la BD (PUSH)
    5. Responde a consultas de Monitoreo (REP)
    6. Monitorea el heartbeat de PC3 para failover
    """

    def __init__(self, config: dict):
        self.config = config
        self.grid = config["grid"]
        self.thresholds = config["thresholds"]
        self.ports = config["zmq_ports"]
        self.running = False

        # Almacena métricas más recientes: {interseccion_id: {Q, Vp, D, veh_min}}
        self.intersection_metrics = {}
        self._init_metrics()

        # Seguimiento de estado previo y timers de retorno (15s)
        self._prev_traffic_state: dict = {}
        self._return_timers: dict = {}
        self._return_lock = threading.RLock()
        # Overrides de prioridad: sem_id -> expiración y timer de auto-reversión
        self.priority_hold_seconds = config.get("priority_hold_seconds", 30)
        self._priority_holds: dict = {}
        self._priority_timers: dict = {}

        # ─── Auth ───
        self.sensor_token_prefix = config.get("auth_tokens", {}).get("sensors_prefix", "")
        self.monitor_token = config.get("auth_tokens", {}).get("monitoring", "")

        # ─── sensores registrados (para validación) ───
        self.registered_sensors = set()
        self._init_registered_sensors()

        # ─── estado de failover de la BD ───
        self.use_replica = False
        self.last_heartbeat_time = time.time()
        self.heartbeat_timeout = config.get("heartbeat_timeout_seconds", 15)
        self.resync_batch_size = config.get("resync_batch_size", 100)
        self.resync_timeout = config.get("resync_timeout_seconds", 5)
        self._resync_req = None
        self._failover_lock = threading.RLock()

        # ─── ZMQ Contexto ───
        self.context = zmq.Context()

        # ─── Conexión a la BD ───
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "replica_traffic.db")
        self.replica_db = DatabaseManager(db_path)

        # Asignados en run() antes del hilo de monitoreo (override / PUSH)
        self._light_pub = None
        self._push_socket = None

    def _init_metrics(self):
        """Inicializa el seguimiento de métricas para todas las intersecciones."""
        for c in range(1, self.grid["columns"] + 1):
            for r in range(1, self.grid["rows"] + 1):
                int_id = f"INT_C{c}K{r}"
                self.intersection_metrics[int_id] = {
                    "Q": 0.0, "Vp": 50.0, "D": 0.0, "vehiculos_por_minuto": 0.0
                }

    def _init_registered_sensors(self):
        """Construye el conjunto de todos los IDs de sensores válidos."""
        from shared.constants import SENSOR_TYPES, SENSOR_PREFIXES
        for c in range(1, self.grid["columns"] + 1):
            for r in range(1, self.grid["rows"] + 1):
                for stype in SENSOR_TYPES:
                    prefix = SENSOR_PREFIXES[stype]
                    self.registered_sensors.add(f"{prefix}_C{c}K{r}")

    
    # Evaluación de reglas de tráfico
    

    def evaluate_traffic(self, interseccion: str) -> str:
        """
        Evalúa el estado del tráfico para una intersección.
        Retorna: 'normal' o 'congestion'
        """
        m = self.intersection_metrics.get(interseccion, {})
        Q = m.get("Q", 0)
        Vp = m.get("Vp", 50)
        D = m.get("D", 0)

        Q_MAX = self.thresholds["Q_MAX"]
        VP_MIN = self.thresholds["VP_MIN"]
        D_MAX = self.thresholds["D_MAX"]

        # Congestión si CUALQUIERA de las condiciones se cumple
        if Q >= Q_MAX or Vp <= VP_MIN or D >= D_MAX:
            return CONGESTION
        return NORMAL

    def _is_priority_held(self, sem_id: str) -> bool:
        """Indica si un semaforo esta bajo un override de prioridad vigente."""
        with self._return_lock:
            deadline = self._priority_holds.get(sem_id)
            if deadline is None:
                return False
            if time.time() >= deadline:
                self._priority_holds.pop(sem_id, None)
                return False
            return True

    def _schedule_normal_return(self, col: int, row: int, light_pub: zmq.Socket):
        """Programa el cambio de VERDE a ROJO después de 15s en condiciones normales."""
        int_id = f"INT_C{col}K{row}"
        sem_id = f"SEM_C{col}K{row}_N"
        with self._return_lock:
            if self._is_priority_held(sem_id):
                logger.info(f"TIMER: {sem_id} bajo prioridad, no se programa retorno normal")
                return
            timer = self._return_timers.pop(int_id, None)
            if timer:
                timer.cancel()
        timer = threading.Timer(15.0, self._revert_light, args=[col, row, light_pub])
        timer.daemon = True
        with self._return_lock:
            self._return_timers[int_id] = timer
        timer.start()
        logger.info(f"TIMER: {int_id} volvera a ROJO en 15s")

    def _revert_light(self, col: int, row: int, light_pub: zmq.Socket):
        """Revierte el semáforo N de una intersección a ROJO y registra la acción."""
        int_id = f"INT_C{col}K{row}"
        sem_id = f"SEM_C{col}K{row}_N"
        with self._return_lock:
            self._return_timers.pop(int_id, None)
            if self._is_priority_held(sem_id):
                logger.info(f"TIMER: {sem_id} bajo prioridad, se cancela retorno normal")
                return

        light_cmd = LightAction(
            semaforo_id=sem_id,
            nuevo_estado=ROJO,
            razon=REASON_NORMAL,
            origen=ORIGIN_ANALYTICS,
        )
        topic = semaforo_topic(col, row)
        light_pub.send_string(f"{topic} {light_cmd.to_json()}")
        logger.info(f"TIMER: {sem_id} -> ROJO (normal reanudado)")

        accion = self._build_action(sem_id, ROJO, REASON_NORMAL, ORIGIN_ANALYTICS)
        if accion is None:
            logger.info(f"TIMER: {sem_id} ya estaba en ROJO, sin accion que registrar")
            return

        metrics = dict(
            self.intersection_metrics.get(
                int_id, {"Q": 0.0, "Vp": 50.0, "D": 0.0, "vehiculos_por_minuto": 0.0}
            )
        )
        self._persist_traffic_state(TrafficState(
            interseccion=int_id,
            estado=NORMAL,
            metricas=metrics,
            accion_tomada=accion,
            acciones_tomadas=[accion],
        ))

    def _revert_priority(self, col: int, row: int, sem_id: str):
        """Finaliza el hold de prioridad y devuelve el semaforo a ROJO."""
        int_id = f"INT_C{col}K{row}"
        with self._return_lock:
            self._priority_holds.pop(sem_id, None)
            self._priority_timers.pop(sem_id, None)

        if self._light_pub is None:
            logger.warning(f"PRIORIDAD: {sem_id} expiro sin socket de luces disponible")
            return

        light_cmd = LightAction(
            semaforo_id=sem_id,
            nuevo_estado=ROJO,
            razon=REASON_NORMAL,
            origen=ORIGIN_ANALYTICS,
        )
        topic = semaforo_topic(col, row)
        self._light_pub.send_string(f"{topic} {light_cmd.to_json()}")

        accion = self._build_action(sem_id, ROJO, REASON_NORMAL, ORIGIN_ANALYTICS)
        if accion is None:
            logger.info(f"PRIORIDAD: {sem_id} ya estaba en ROJO, sin accion que registrar")
            return

        metrics = dict(
            self.intersection_metrics.get(
                int_id, {"Q": 0.0, "Vp": 50.0, "D": 0.0, "vehiculos_por_minuto": 0.0}
            )
        )
        self._persist_traffic_state(TrafficState(
            interseccion=int_id,
            estado=NORMAL,
            metricas=metrics,
            accion_tomada=accion,
            acciones_tomadas=[accion],
        ))
        logger.info(
            f"PRIORIDAD: {sem_id} revertida a ROJO tras {self.priority_hold_seconds}s"
        )

    def update_metrics(self, event: SensorEvent):
        """Actualiza las métricas de la intersección a partir de un evento de sensor."""
        int_id = event.interseccion
        if int_id not in self.intersection_metrics:
            self.intersection_metrics[int_id] = {
                "Q": 0.0, "Vp": 50.0, "D": 0.0, "vehiculos_por_minuto": 0.0
            }

        datos = event.datos
        if event.tipo_sensor == SENSOR_ESPIRA:
            self.intersection_metrics[int_id]["vehiculos_por_minuto"] = datos.get("vehiculos_por_minuto", 0)
        elif event.tipo_sensor == SENSOR_CAMARA:
            self.intersection_metrics[int_id]["Q"] = datos.get("longitud_cola", 0)
        elif event.tipo_sensor == SENSOR_GPS:
            self.intersection_metrics[int_id]["D"] = datos.get("densidad", 0)
            self.intersection_metrics[int_id]["Vp"] = datos.get("velocidad_promedio", 50)

    # ═══════════════════════════════════════════
    # Procesar evento de sensor
    # ═══════════════════════════════════════════

    def _build_auth_tokens(self) -> dict:
        """Construye dict {sensor_id: token} para pasar a validate_sensor_event."""
        prefix = self.sensor_token_prefix
        return {sid: prefix + sid for sid in self.registered_sensors}

    def _build_action(self, sem_id: str, nuevo_estado: str,
                      razon: str, origen: str) -> Optional[dict]:
        """Construye una accion solo si implica un cambio real de estado."""
        prev = self.replica_db.get_semaforo_state(sem_id)
        if prev not in (VERDE, ROJO):
            prev = ROJO if nuevo_estado == VERDE else VERDE
        if prev == nuevo_estado:
            return None
        return {
            "tipo": "CAMBIO_LUZ",
            "semaforo_id": sem_id,
            "estado_anterior": prev,
            "estado_nuevo": nuevo_estado,
            "razon": razon,
            "origen": origen,
        }

    @staticmethod
    def _iter_actions(traffic_state: TrafficState):
        """Itera las acciones de un estado, con fallback al campo legacy."""
        if traffic_state.acciones_tomadas:
            yield from traffic_state.acciones_tomadas
        elif traffic_state.accion_tomada:
            yield traffic_state.accion_tomada

    def _persist_traffic_state(self, traffic_state: TrafficState,
                               push_socket: zmq.Socket = None) -> bool:
        """Persiste un estado por el unico escritor (MainDB) o en la replica en failover."""
        with self._failover_lock:
            if self.use_replica:
                return self._persist_to_replica(traffic_state)

        socket = push_socket or self._push_socket
        if socket is None:
            logger.warning("Sin socket PUSH; estado no persistido")
            return False
        try:
            socket.send_string(traffic_state.to_json(), flags=zmq.NOBLOCK)
            return True
        except zmq.error.Again:
            logger.debug("Socket PUSH lleno o no disponible. Mensaje descartado.")
            return True
        except Exception as e:
            logger.error(f"Error al enviar estado a la BD principal: {e}")
            return False

    def _enqueue_outbox(self, message_id: str, tabla: str,
                        operacion: str, datos: dict):
        """Encola una escritura de failover para reconciliarla al volver a main."""
        self.replica_db.enqueue_outbox(
            message_id, tabla, operacion, datos, created_at=_now()
        )

    def _persist_to_replica(self, traffic_state: TrafficState) -> bool:
        """Escribe el estado y sus acciones en la replica y los encola en el outbox."""
        try:
            ts = traffic_state.timestamp
            metrics = traffic_state.metricas
            int_id = traffic_state.interseccion
            base_id = traffic_state.message_id

            if traffic_state.original_event_id:
                event_payload = {
                    "evento_id": traffic_state.original_event_id,
                    "sensor_id": traffic_state.original_sensor_id,
                    "interseccion_id": int_id,
                    "tipo_sensor": traffic_state.original_tipo_sensor,
                    "datos": json.loads(traffic_state.original_datos) if traffic_state.original_datos else metrics,
                    "timestamp": ts,
                    "timestamp_sensor": traffic_state.original_timestamp or ts,
                }
                self.replica_db.insert_event(
                    event_payload["evento_id"],
                    event_payload["sensor_id"],
                    event_payload["interseccion_id"],
                    event_payload["tipo_sensor"],
                    event_payload["datos"],
                    event_payload["timestamp"],
                    timestamp_sensor=event_payload["timestamp_sensor"],
                )
                self._enqueue_outbox(f"{base_id}:evento", "eventos", "INSERT", event_payload)

            state_payload = {
                "interseccion_id": int_id,
                "Q": metrics.get("Q", 0),
                "Vp": metrics.get("Vp", 0),
                "D": metrics.get("D", 0),
                "vehiculos_por_minuto": metrics.get("vehiculos_por_minuto", 0),
                "estado": traffic_state.estado,
                "timestamp": ts,
                "message_id": base_id,
            }
            self.replica_db.insert_traffic_state(
                state_payload["interseccion_id"],
                state_payload["Q"],
                state_payload["Vp"],
                state_payload["D"],
                state_payload["vehiculos_por_minuto"],
                state_payload["estado"],
                state_payload["timestamp"],
                message_id=base_id,
            )
            self._enqueue_outbox(f"{base_id}:estado", "estado_trafico", "INSERT", state_payload)

            for accion in self._iter_actions(traffic_state):
                sem_id = accion.get("semaforo_id", "")
                estado_ant = accion.get("estado_anterior", "")
                estado_new = accion.get("estado_nuevo", "")
                if not sem_id or estado_ant == estado_new:
                    continue

                accion_id = str(uuid.uuid4())
                accion_payload = {
                    "accion_id": accion_id,
                    "semaforo_id": sem_id,
                    "estado_anterior": estado_ant,
                    "estado_nuevo": estado_new,
                    "razon": accion.get("razon", ""),
                    "origen": accion.get("origen", ""),
                    "timestamp": ts,
                }
                self.replica_db.insert_light_action(
                    accion_id, sem_id, estado_ant, estado_new,
                    accion_payload["razon"], accion_payload["origen"], ts,
                )
                self._enqueue_outbox(
                    f"{base_id}:accion:{accion_id}", "acciones_semaforo",
                    "INSERT", accion_payload,
                )

                sem_payload = {
                    "semaforo_id": sem_id,
                    "estado_actual": estado_new,
                    "timestamp": ts,
                }
                self.replica_db.update_semaforo(sem_id, estado_new, ts)
                self._enqueue_outbox(
                    f"{base_id}:semaforo:{sem_id}", "semaforos", "UPDATE", sem_payload,
                )
            return True
        except Exception as e:
            logger.error(f"Error al escribir en la BD replica: {e}")
            return False

    def _flush_outbox(self) -> bool:
        """Reconcilia el outbox contra MainDB antes de volver a la BD principal."""
        with self._failover_lock:
            if not self.use_replica:
                return True

            while True:
                pending = self.replica_db.get_pending_outbox(self.resync_batch_size)
                if not pending:
                    return True
                if not self._send_outbox_batch(pending):
                    return False

    def _reset_resync_socket(self):
        """Recrea el socket REQ tras un timeout (REQ queda en estado EFSM)."""
        old = self._resync_req
        if old is not None and hasattr(old, "close"):
            try:
                old.close()
            except Exception:
                pass
        try:
            pc3_host = self.config.get("pc3_host", "localhost")
            self._resync_req = self.context.socket(zmq.REQ)
            self._resync_req.connect(f"tcp://{pc3_host}:{self.ports['resync_port']}")
        except Exception as e:
            self._resync_req = None
            logger.error(f"No se pudo recrear el socket de resync: {e}")

    def _send_outbox_batch(self, pending: list) -> bool:
        """Envia un lote del outbox al endpoint de resync de MainDB."""
        if self._resync_req is None:
            logger.error("Sin socket de resync; no se puede reconciliar el outbox")
            return False

        mensajes = []
        for row in pending:
            try:
                datos = json.loads(row["datos"])
            except Exception as e:
                self.replica_db.mark_outbox_error(row["message_id"], f"JSON invalido: {e}")
                return False
            mensajes.append({
                "message_id": row["message_id"],
                "tabla": row["tabla"],
                "operacion": row["operacion"],
                "datos": datos,
            })

        batch = ResyncBatch(mensajes=mensajes)
        try:
            self._resync_req.send_string(batch.to_json())
            if not self._resync_req.poll(self.resync_timeout * 1000):
                for row in pending:
                    self.replica_db.mark_outbox_error(row["message_id"], "timeout de resync")
                logger.warning("Resync sin respuesta de MainDB; se mantiene la replica")
                self._reset_resync_socket()
                return False

            response = ResyncResponse.from_json(self._resync_req.recv_string())
            if response.tipo == "ERROR" or response.errores:
                for row in pending:
                    self.replica_db.mark_outbox_error(row["message_id"], response.mensaje)
                logger.warning(f"Resync rechazado por MainDB: {response.mensaje}")
                return False

            for row in pending:
                self.replica_db.mark_outbox_sent(row["message_id"])
            logger.info(
                f"Outbox reconciliado: {response.aplicados} aplicados, "
                f"{response.duplicados} duplicados"
            )
            return True
        except Exception as e:
            for row in pending:
                self.replica_db.mark_outbox_error(row["message_id"], str(e))
            logger.error(f"Error al enviar lote de resync: {e}")
            self._reset_resync_socket()
            return False

    def process_event(self, event: SensorEvent, push_socket: zmq.Socket, light_pub: zmq.Socket):
        """Procesa un evento de sensor: valida, actualiza, evalua y actúa."""
        # 1. Valida
        event_dict = json.loads(event.to_json())
        valid, reason = validate_sensor_event(
            event_dict, self.registered_sensors, self._build_auth_tokens(), self.grid
        )
        if not valid:
            logger.warning(f"Evento inválido de {event.sensor_id}: {reason}")
            return

        # 2. Actualiza métricas
        self.update_metrics(event)
        int_id = event.interseccion

        # 3. Evalua reglas de tráfico
        estado = self.evaluate_traffic(int_id)
        prev_state = self._prev_traffic_state.get(int_id, NORMAL)
        self._prev_traffic_state[int_id] = estado
        metrics = self.intersection_metrics[int_id].copy()

        # 4. Determina las acciones (todas las luces modificadas)
        accion = None
        acciones_tomadas = []
        parts = int_id.replace("INT_C", "").split("K")
        col, row = int(parts[0]), int(parts[1])

        if estado == CONGESTION:
            # Cancela cualquier timer de retorno pendiente
            with self._return_lock:
                timer = self._return_timers.pop(int_id, None)
                if timer:
                    timer.cancel()

            # Solo aplicar ola verde en la transicion normal → congestion
            if prev_state != CONGESTION:
                # Ola verde vertical: cambia N a VERDE en esta y filas adyacentes
                affected_rows = [row]
                if row > 1:
                    affected_rows.append(row - 1)
                if row < self.grid["rows"]:
                    affected_rows.append(row + 1)

                changed = []
                for r in affected_rows:
                    sem_id = f"SEM_C{col}K{r}_N"
                    if self._is_priority_held(sem_id):
                        logger.info(f"OLA VERDE: {sem_id} bajo prioridad, se omite")
                        continue
                    light_cmd = LightAction(
                        semaforo_id=sem_id,
                        nuevo_estado=VERDE,
                        razon=REASON_CONGESTION,
                        origen=ORIGIN_ANALYTICS,
                    )
                    topic = semaforo_topic(col, r)
                    light_pub.send_string(f"{topic} {light_cmd.to_json()}")
                    changed.append(sem_id)

                    accion_sem = self._build_action(
                        sem_id, VERDE, REASON_CONGESTION, ORIGIN_ANALYTICS
                    )
                    if accion_sem:
                        acciones_tomadas.append(accion_sem)
                        if r == row:
                            accion = accion_sem
                logger.info(f"OLA VERDE C{col}: {changed}")

        elif estado == NORMAL and prev_state == CONGESTION:
            # Programa el retorno de esta intersección
            self._schedule_normal_return(col, row, light_pub)
            # También de adyacentes si ya están en normal
            if row > 1 and self._prev_traffic_state.get(f"INT_C{col}K{row-1}", NORMAL) == NORMAL:
                self._schedule_normal_return(col, row - 1, light_pub)
            if row < self.grid["rows"] and self._prev_traffic_state.get(f"INT_C{col}K{row+1}", NORMAL) == NORMAL:
                self._schedule_normal_return(col, row + 1, light_pub)

        # 5. Construye el registro de estado de tráfico con trazabilidad
        traffic_state = TrafficState(
            interseccion=int_id,
            estado=estado,
            metricas=metrics,
            accion_tomada=accion,
            acciones_tomadas=acciones_tomadas,
            original_event_id=event.message_id,
            original_sensor_id=event.sensor_id,
            original_tipo_sensor=event.tipo_sensor,
            original_datos=json.dumps(event.datos, ensure_ascii=False),
            original_timestamp=event.timestamp,
        )

        # 6. Persiste el estado (MainDB en operacion normal, replica en failover)
        self._persist_traffic_state(traffic_state, push_socket)

    # ═══════════════════════════════════════════
    # Manejador REP de Monitoreo (se ejecuta en hilo)
    # ═══════════════════════════════════════════

    def handle_monitoring(self, rep_socket: zmq.Socket):
        """Maneja consultas REQ/REP del Servicio de Monitoreo."""
        logger.info("Manejador de monitoreo listo en el socket REP")
        while self.running:
            try:
                if rep_socket.poll(1000):  # Timeout de 1 segundo
                    msg = rep_socket.recv_string()
                    data = json.loads(msg)
                    response = self._process_monitoring_request(data)
                    rep_socket.send_string(response.to_json())
            except zmq.ZMQError as e:
                if self.running:
                    logger.error(f"Error en el manejador de monitoreo: {e}")
            except Exception as e:
                logger.error(f"Error en el manejador de monitoreo: {e}")
                try:
                    err = MonitoringResponse(tipo="ERROR", mensaje=str(e))
                    rep_socket.send_string(err.to_json())
                except Exception:
                    pass

    def _process_monitoring_request(self, data: dict) -> MonitoringResponse:
        """Procesa una solicitud de monitoreo y devuelve una respuesta."""
        tipo = data.get("tipo", "")

        if tipo == CMD_CONSULTA:
            valid, reason = validate_query(data)
            if not valid:
                return MonitoringResponse(tipo="ERROR", mensaje=reason)

            consulta = data.get("consulta", "")
            if consulta == "ESTADO_INTERSECCION":
                int_id = data.get("interseccion", "")
                metrics = self.intersection_metrics.get(int_id)
                if metrics:
                    estado = self.evaluate_traffic(int_id)
                    return MonitoringResponse(
                        tipo="RESPUESTA",
                        datos={"interseccion": int_id, "estado": estado, "metricas": metrics},
                        mensaje=f"Estado de {int_id}: {estado}",
                    )
                return MonitoringResponse(tipo="ERROR", mensaje=f"Interseccion {int_id} no se encontro")

            elif consulta == "ESTADO_GENERAL":
                summary = {}
                for int_id, metrics in self.intersection_metrics.items():
                    estado = self.evaluate_traffic(int_id)
                    summary[int_id] = {"estado": estado, "metricas": metrics}
                return MonitoringResponse(
                    tipo="RESPUESTA", datos=summary,
                    mensaje=f"Estado general: {len(summary)} intersecciones",
                )

            elif consulta == CMD_LISTAR_SEMAFOROS:
                # Analytics siempre lee del archivo replica local; db_mode indica el modo de failover
                sems = self.replica_db.get_all_semaforos(
                    columns=self.config["grid"]["columns"],
                    rows=self.config["grid"]["rows"]
                )
                mode_str = "replica" if self.use_replica else "main"
                return MonitoringResponse(
                    tipo="RESPUESTA",
                    datos={"semaforos": sems, "db_mode": mode_str, "fuente": "replica"},
                    mensaje=(
                        f"Lista de {len(sems)} semáforos "
                        f"(Modo: {mode_str}, Fuente: replica)"
                    )
                )

            elif consulta == "CONSULTA_HISTORICA":
                int_id = data.get("interseccion", "")
                inicio = data.get("fecha_inicio", "")
                fin = data.get("fecha_fin", "")
                eventos = self.replica_db.get_events_between_dates(int_id, inicio, fin)
                estados = self.replica_db.get_traffic_states_between_dates(int_id, inicio, fin)
                acciones = self.replica_db.get_light_actions_between_dates(int_id, inicio, fin)
                return MonitoringResponse(
                    tipo="RESPUESTA",
                    datos={
                        "interseccion": int_id,
                        "eventos": eventos,
                        "estados_trafico": estados,
                        "acciones_semaforo": acciones,
                    },
                    mensaje=f"Historial de {int_id}: {len(eventos)} eventos, {len(estados)} estados, {len(acciones)} acciones",
                )

        elif tipo == CMD_OVERRIDE:
            valid, reason = validate_override_command(data, self.monitor_token, self.grid)
            if not valid:
                return MonitoringResponse(tipo="ERROR", mensaje=reason)
            return self._execute_override(
                data["semaforo_id"],
                data["nuevo_estado"],
                data.get("motivo", "manual"),
            )

        return MonitoringResponse(tipo="ERROR", mensaje=f"Tipo de solicitud desconocido: {tipo}")

    def _execute_override(self, sem_id: str, nuevo_estado: str, motivo: str) -> MonitoringResponse:
        """Publica cambio de luz, persiste en main (PUSH) o en réplica si hay failover."""
        parsed = parse_semaforo_id(sem_id)
        if not parsed:
            return MonitoringResponse(
                tipo="ERROR",
                mensaje=f"semaforo_id invalido (se espera SEM_CxKy_N|S|E|W): {sem_id}",
            )

        col, row, _direction = parsed
        int_id = intersection_id(col, row)

        if self._light_pub is None or self._push_socket is None:
            return MonitoringResponse(
                tipo="ERROR",
                mensaje="Servicio de analitica aun no inicializo los sockets ZMQ",
            )

        motivo_l = str(motivo).lower()
        razon = REASON_PRIORITY if "ambulancia" in motivo_l else REASON_MANUAL

        light_cmd = LightAction(
            semaforo_id=sem_id,
            nuevo_estado=nuevo_estado,
            razon=razon,
            origen=ORIGIN_MONITORING,
        )
        topic = semaforo_topic(col, row)
        try:
            self._light_pub.send_string(f"{topic} {light_cmd.to_json()}")
        except Exception as e:
            logger.error(f"Override: error al publicar comando de semaforo: {e}")
            return MonitoringResponse(
                tipo="ERROR",
                mensaje=f"No se pudo enviar el comando al controlador: {e}",
            )

        with self._return_lock:
            previous_hold = self._priority_timers.pop(sem_id, None)
            if previous_hold:
                previous_hold.cancel()
            if razon == REASON_PRIORITY:
                normal_timer = self._return_timers.pop(int_id, None)
                if normal_timer:
                    normal_timer.cancel()
                self._priority_holds[sem_id] = time.time() + self.priority_hold_seconds
                hold_timer = threading.Timer(
                    self.priority_hold_seconds,
                    self._revert_priority,
                    args=[col, row, sem_id],
                )
                hold_timer.daemon = True
                self._priority_timers[sem_id] = hold_timer
                hold_timer.start()
            else:
                self._priority_holds.pop(sem_id, None)

        accion = self._build_action(sem_id, nuevo_estado, razon, ORIGIN_MONITORING)
        if accion is None:
            logger.info(f"OVERRIDE: {sem_id} ya estaba en {nuevo_estado}, sin accion que registrar")
            return MonitoringResponse(
                tipo="RESPUESTA",
                datos={"semaforo_id": sem_id, "nuevo_estado": nuevo_estado, "ejecutado": False},
                mensaje=f"Sin cambio registrado: {sem_id} ya estaba en {nuevo_estado}",
            )

        metrics = dict(
            self.intersection_metrics.get(
                int_id,
                {"Q": 0.0, "Vp": 50.0, "D": 0.0, "vehiculos_por_minuto": 0.0},
            )
        )
        traffic_state = TrafficState(
            interseccion=int_id,
            estado=PRIORIDAD,
            metricas=metrics,
            accion_tomada=accion,
            acciones_tomadas=[accion],
        )

        if not self._persist_traffic_state(traffic_state):
            return MonitoringResponse(
                tipo="ERROR",
                mensaje="Comando enviado al semaforo pero fallo la persistencia",
            )

        logger.info(f"OVERRIDE: {sem_id} -> {nuevo_estado} (motivo: {motivo}, razon: {razon})")
        return MonitoringResponse(
            tipo="RESPUESTA",
            datos={"semaforo_id": sem_id, "nuevo_estado": nuevo_estado, "ejecutado": True},
            mensaje=f"Override ejecutado: {sem_id} -> {nuevo_estado}",
        )

    # ═══════════════════════════════════════════
    # Monitor de heartbeat (se ejecuta en hilo)
    # ═══════════════════════════════════════════

    def monitor_heartbeat(self, hb_socket: zmq.Socket):
        """Monitorea el heartbeat de PC3. Cambia a réplica si hay timeout."""
        pc3_host = self.config.get("pc3_host", "localhost")
        resync_req = self.context.socket(zmq.REQ)
        resync_req.connect(f"tcp://{pc3_host}:{self.ports['resync_port']}")
        self._resync_req = resync_req
        logger.info(
            f"Monitor de heartbeat iniciado (timeout={self.heartbeat_timeout}s, "
            f"resync=tcp://{pc3_host}:{self.ports['resync_port']})"
        )
        try:
            while self.running:
                try:
                    if hb_socket.poll(1000):
                        msg = hb_socket.recv_string()
                        self.last_heartbeat_time = time.time()
                        if self.use_replica:
                            with self._failover_lock:
                                if self._flush_outbox():
                                    self.use_replica = False
                                    logger.info(
                                        "Heartbeat de PC3 restaurado y outbox reconciliado! "
                                        "Volviendo a la BD principal"
                                    )
                                else:
                                    logger.warning(
                                        "Heartbeat restaurado pero el outbox no se pudo "
                                        "reconciliar; se mantiene la BD replica"
                                    )

                    # Verificar timeout
                    elapsed = time.time() - self.last_heartbeat_time
                    with self._failover_lock:
                        if elapsed > self.heartbeat_timeout and not self.use_replica:
                            logger.warning(
                                f"PC3 heartbeat se quedo sin pulso ({elapsed:.0f}s). "
                                "Cambiando a BD Réplica!"
                            )
                            self.use_replica = True

                except zmq.ZMQError:
                    if self.running:
                        time.sleep(1)
        finally:
            req = self._resync_req
            self._resync_req = None
            if req is not None and hasattr(req, "close"):
                req.close()

    # ═══════════════════════════════════════════
    # Bucle principal
    # ═══════════════════════════════════════════

    def run(self):
        """Inicia todos los componentes del servicio de analítica."""
        pc1_host = self.config.get("pc1_host", "localhost")
        pc2_host = self.config.get("pc2_host", "localhost")
        pc3_host = self.config.get("pc3_host", "localhost")

        # ─── Socket SUB: recibe eventos de sensores desde el Broker ───
        sub_socket = self.context.socket(zmq.SUB)
        sub_socket.connect(f"tcp://{pc1_host}:{self.ports['broker_backend']}")
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, TOPIC_SENSOR)
        logger.info(f"se suscribio al broker en tcp://{pc1_host}:{self.ports['broker_backend']}")

        # ─── PUSH socket: envía datos a la BD principal (PC3) ───
        push_socket = self.context.socket(zmq.PUSH)
        push_socket.connect(f"tcp://{pc3_host}:{self.ports['analytics_to_db']}")
        logger.info(f"PUSH conectado  BD en tcp://{pc3_host}:{self.ports['analytics_to_db']}")

        # ─── PUB socket: envía comandos de cambio de semáforo ───
        light_pub = self.context.socket(zmq.PUB)
        light_pub.bind(f"tcp://{pc2_host}:{self.ports['analytics_to_lights']}")
        logger.info(f"Luces conectadas en tcp://{pc2_host}:{self.ports['analytics_to_lights']}")

        # ─── REP socket: responde a Monitoreo ───
        rep_socket = self.context.socket(zmq.REP)
        rep_socket.bind(f"tcp://{pc2_host}:{self.ports['monitoring_to_analytics']}")
        logger.info(f"REP conectado en tcp://{pc2_host}:{self.ports['monitoring_to_analytics']}")

        # ─── SUB socket: heartbeat de PC3 ───
        hb_socket = self.context.socket(zmq.SUB)
        hb_socket.connect(f"tcp://{pc3_host}:{self.ports['heartbeat']}")
        hb_socket.setsockopt_string(zmq.SUBSCRIBE, TOPIC_HEARTBEAT)
        logger.info(f"Heartbeat SUB conectado a tcp://{pc3_host}:{self.ports['heartbeat']}")

        # ─── Inicializa la BD réplica ───
        self.replica_db.connect()
        self.replica_db.seed_all(
            self.grid["columns"], self.grid["rows"],
            ["N", "S", "E", "W"]
        )

        self._light_pub = light_pub
        self._push_socket = push_socket

        self.running = True

        # Inicia el manejador de monitoreo en un hilo separado
        mon_thread = threading.Thread(target=self.handle_monitoring, args=(rep_socket,), daemon=True)
        mon_thread.start()

        # Inicia el monitor de heartbeat en un hilo separado
        hb_thread = threading.Thread(target=self.monitor_heartbeat, args=(hb_socket,), daemon=True)
        hb_thread.start()

        logger.info("el servicio de analitica se esta ejecutando...")
        event_count = 0

        try:
            while self.running:
                if sub_socket.poll(1000):
                    raw = sub_socket.recv_string()
                    # Parsea: "topic payload"
                    parts = raw.split(" ", 1)
                    if len(parts) == 2:
                        topic, payload = parts
                        try:
                            event = SensorEvent.from_json(payload)
                            self.process_event(event, push_socket, light_pub)
                            event_count += 1
                            if event_count % 100 == 0:
                                mode = "REPLICA" if self.use_replica else "MAIN"
                                logger.info(f"Procesados {event_count} eventos (DB: {mode})")
                        except Exception as e:
                            logger.error(f"Error al procesar el evento: {e}")
        except KeyboardInterrupt:
            logger.info("el servicio de analitica se detuvo por el usuario")
        finally:
            self.running = False
            self.replica_db.close()
            sub_socket.close()
            push_socket.close()
            light_pub.close()
            rep_socket.close()
            hb_socket.close()
            self.context.term()
            logger.info(f"el servicio de analitica se detuvo por el usuario: {event_count}")


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    service = AnalyticsService(config)
    service.run()
