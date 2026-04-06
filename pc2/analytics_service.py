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
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import (
    SensorEvent, TrafficState, LightAction,
    MonitoringRequest, MonitoringResponse, Heartbeat
)
from shared.constants import (
    VERDE, ROJO, NORMAL, CONGESTION, PRIORIDAD,
    SENSOR_ESPIRA, SENSOR_CAMARA, SENSOR_GPS,
    REASON_CONGESTION, REASON_NORMAL, REASON_PRIORITY, REASON_MANUAL,
    ORIGIN_ANALYTICS, ORIGIN_MONITORING,
    CMD_CONSULTA, CMD_OVERRIDE, CMD_LISTAR_SEMAFOROS,
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

    # ═══════════════════════════════════════════
    # Evaluación de reglas de tráfico
    # ═══════════════════════════════════════════

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

    def process_event(self, event: SensorEvent, push_socket: zmq.Socket, light_pub: zmq.Socket):
        """Procesa un evento de sensor: valida, actualiza, evalua y actúa."""
        # 1. Valida
        event_dict = json.loads(event.to_json())
        valid, reason = validate_sensor_event(event_dict, self.registered_sensors)
        if not valid:
            logger.warning(f"Evento inválido de {event.sensor_id}: {reason}")
            return

        # 2. Actualiza métricas
        self.update_metrics(event)
        int_id = event.interseccion

        # 3. Evalua reglas de tráfico
        estado = self.evaluate_traffic(int_id)
        metrics = self.intersection_metrics[int_id].copy()

        # 4. Determina la acción
        accion = None
        if estado == CONGESTION:
            # Parsea la intersección para obtener la columna/fila para el ID del semáforo
            parts = int_id.replace("INT_C", "").split("K")
            col, row = int(parts[0]), int(parts[1])
            sem_id = f"SEM_C{col}K{row}_N"  # Default: cambia luz norte

            prev = self.replica_db.get_semaforo_state(sem_id)
            estado_anterior = prev if prev in (VERDE, ROJO) else ROJO

            accion = {
                "tipo": "CAMBIO_LUZ",
                "semaforo_id": sem_id,
                "estado_anterior": estado_anterior,
                "estado_nuevo": VERDE,
                "razon": REASON_CONGESTION,
                "origen": ORIGIN_ANALYTICS,
            }

            # Envía comando de cambio de luz
            light_cmd = LightAction(
                semaforo_id=sem_id,
                nuevo_estado=VERDE,
                razon=REASON_CONGESTION,
                origen=ORIGIN_ANALYTICS,
            )
            topic = semaforo_topic(col, row)
            light_pub.send_string(f"{topic} {light_cmd.to_json()}")
            logger.info(f"CONGESTION en {int_id} → {sem_id} → VERDE")

        # 5. Construye el registro de estado de tráfico
        traffic_state = TrafficState(
            interseccion=int_id,
            estado=estado,
            metricas=metrics,
            accion_tomada=accion,
        )

        # 6. Push a la BD
        if not self.use_replica:
            try:
                db_msg = traffic_state.to_json()
                push_socket.send_string(db_msg, flags=zmq.NOBLOCK)
            except zmq.error.Again:
                logger.debug("Socket PUSH lleno o no disponible. Mensaje descartado.")

        # 7. También almacena el evento en la BD réplica si está en modo de failover
        if self.use_replica:
            try:
                self.replica_db.insert_event(
                    event.message_id, event.sensor_id, event.interseccion,
                    event.tipo_sensor, event.datos, event.timestamp
                )
                self.replica_db.insert_traffic_state(
                    int_id, metrics["Q"], metrics["Vp"], metrics["D"],
                    metrics["vehiculos_por_minuto"], estado, traffic_state.timestamp
                )
            except Exception as e:
                logger.error(f"Error al escribir en la BD réplica: {e}")

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
                #se retorna los semaforos desde la bd replica, filtrados por grilla configurada
                sems = self.replica_db.get_all_semaforos(
                    columns=self.config["grid"]["columns"],
                    rows=self.config["grid"]["rows"]
                )
                mode_str = "replica" if self.use_replica else "main"
                return MonitoringResponse(
                    tipo="RESPUESTA",
                    datos={"semaforos": sems, "db_mode": mode_str},
                    mensaje=f"Lista de {len(sems)} semáforos (Modo: {mode_str})"
                )

        elif tipo == CMD_OVERRIDE:
            valid, reason = validate_override_command(data, self.monitor_token)
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

        prev = self.replica_db.get_semaforo_state(sem_id)
        estado_anterior = prev if prev in (VERDE, ROJO) else ROJO

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

        metrics = dict(
            self.intersection_metrics.get(
                int_id,
                {"Q": 0.0, "Vp": 50.0, "D": 0.0, "vehiculos_por_minuto": 0.0},
            )
        )
        accion = {
            "tipo": "CAMBIO_LUZ",
            "semaforo_id": sem_id,
            "estado_anterior": estado_anterior,
            "estado_nuevo": nuevo_estado,
            "razon": razon,
            "origen": ORIGIN_MONITORING,
        }
        traffic_state = TrafficState(
            interseccion=int_id,
            estado=PRIORIDAD,
            metricas=metrics,
            accion_tomada=accion,
        )

        if not self.use_replica:
            try:
                self._push_socket.send_string(traffic_state.to_json(), flags=zmq.NOBLOCK)
            except zmq.error.Again:
                logger.warning("Override: socket PUSH lleno o no disponible; BD principal puede no reflejar el cambio.")
            except Exception as e:
                logger.error(f"Override: error al enviar a la BD principal: {e}")
                return MonitoringResponse(
                    tipo="ERROR",
                    mensaje=f"Comando enviado al semaforo pero fallo la persistencia: {e}",
                )
        else:
            try:
                ts = traffic_state.timestamp
                self.replica_db.insert_traffic_state(
                    int_id,
                    metrics["Q"],
                    metrics["Vp"],
                    metrics["D"],
                    metrics["vehiculos_por_minuto"],
                    PRIORIDAD,
                    ts,
                )
                self.replica_db.insert_light_action(
                    str(uuid.uuid4()),
                    sem_id,
                    estado_anterior,
                    nuevo_estado,
                    razon,
                    ORIGIN_MONITORING,
                    ts,
                )
                self.replica_db.update_semaforo(sem_id, nuevo_estado, ts)
            except Exception as e:
                logger.error(f"Override: error al escribir en la BD replica: {e}")
                return MonitoringResponse(
                    tipo="ERROR",
                    mensaje=f"Comando enviado al semaforo pero fallo la BD replica: {e}",
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
        logger.info(f"Monitor de heartbeat iniciado (timeout={self.heartbeat_timeout}s)")
        while self.running:
            try:
                if hb_socket.poll(1000):
                    msg = hb_socket.recv_string()
                    self.last_heartbeat_time = time.time()
                    if self.use_replica:
                        logger.info("Heartbeat de PC3 restaurado! Volviendo a la BD principal")
                        self.use_replica = False

                # Verificar timeout
                elapsed = time.time() - self.last_heartbeat_time
                if elapsed > self.heartbeat_timeout and not self.use_replica:
                    logger.warning(f"PC3 heartbeat se quedo sin pulso ({elapsed:.0f}s). Cambiando a BD Réplica!")
                    self.use_replica = True

            except zmq.ZMQError:
                if self.running:
                    time.sleep(1)

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
