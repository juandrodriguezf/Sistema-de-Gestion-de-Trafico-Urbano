"""
constants.py - Convenciones de nomenclatura, estados y constantes de todo el sistema.
Sigue la notación de cuadrícula definida en la especificación del proyecto.
"""

import re
from typing import Optional, Tuple

# ─── Estados de los semáforos ───
VERDE = "VERDE"
ROJO = "ROJO"
LIGHT_STATES = [VERDE, ROJO]

# ─── Estados del tráfico ───
NORMAL = "normal"
CONGESTION = "congestion"
PRIORIDAD = "prioridad"
TRAFFIC_STATES = [NORMAL, CONGESTION, PRIORIDAD]

# ─── Tipos de sensores ───
SENSOR_ESPIRA = "espira"
SENSOR_CAMARA = "camara"
SENSOR_GPS = "gps"
SENSOR_TYPES = [SENSOR_ESPIRA, SENSOR_CAMARA, SENSOR_GPS]
SENSOR_PREFIXES = {
    SENSOR_ESPIRA: "ESP",
    SENSOR_CAMARA: "CAM",
    SENSOR_GPS: "GPS",
}

# ─── Direcciones ───
NORTH = "N"
SOUTH = "S"
EAST = "E"
WEST = "W"
DIRECTIONS = [NORTH, SOUTH, EAST, WEST]

# ─── Razones de acción ───
REASON_CONGESTION = "congestion_detectada"
REASON_PRIORITY = "prioridad"
REASON_MANUAL = "manual"
REASON_NORMAL = "normal"

# ─── Orígenes de acción ───
ORIGIN_ANALYTICS = "analytics"
ORIGIN_MONITORING = "monitoring"

# ─── Tipos de comandos ───
CMD_CONSULTA = "CONSULTA"
CMD_OVERRIDE = "OVERRIDE"
CMD_ESTADO_INTERSECCION = "ESTADO_INTERSECCION"
CMD_ESTADO_GENERAL = "ESTADO_GENERAL"
CMD_LISTAR_SEMAFOROS = "LISTAR_SEMAFOROS"
CMD_CAMBIO_LUZ = "CAMBIO_LUZ"

# ─── Modos de base de datos ───
DB_MAIN = "main"
DB_REPLICA = "replica"

# ─── Replicación ───
SYNC_INSERT = "INSERT"
SYNC_UPDATE = "UPDATE"

# ─── Prefijos de temas ZMQ ───
TOPIC_SENSOR = "sensor"
TOPIC_SEMAFORO = "semaforo"
TOPIC_ALERTA = "alerta"
TOPIC_HEARTBEAT = "heartbeat"
TOPIC_SYNC = "sync"


def intersection_id(col: int, row: int) -> str:
    """Genera el ID de la interseccion: INT_C{col}K{row}"""
    return f"INT_C{col}K{row}"


def sensor_id(sensor_type: str, col: int, row: int) -> str:
    """Genera el ID del sensor: {PREFIX}_C{col}K{row}"""
    prefix = SENSOR_PREFIXES[sensor_type]
    return f"{prefix}_C{col}K{row}"


def semaforo_id(col: int, row: int, direction: str) -> str:
    """Genera el ID del semaforo: SEM_C{col}K{row}_{DIR}"""
    return f"SEM_C{col}K{row}_{direction}"


def sensor_topic(sensor_type: str, col: int, row: int) -> str:
    """Genera el tema ZMQ: sensor/{type}/C{col}K{row}"""
    return f"{TOPIC_SENSOR}/{sensor_type}/C{col}K{row}"


def semaforo_topic(col: int, row: int) -> str:
    """Genera el tema ZMQ para cambios en los semaforos."""
    return f"{TOPIC_SEMAFORO}/cambio/C{col}K{row}"


def parse_intersection(int_id: str) -> tuple:
    """Parsea INT_C{col}K{row} → (col, row)"""
    # INT_C5K3 → col=5, row=3
    parts = int_id.replace("INT_C", "").split("K")
    return int(parts[0]), int(parts[1])


def parse_semaforo_id(sem_id: str) -> Optional[Tuple[int, int, str]]:
    """
    Parsea SEM_C{col}K{row}_{DIR} → (col, row, direccion).
    Retorna None si el formato no es válido.
    """
    m = re.match(r"^SEM_C(\d+)K(\d+)_([NSEW])$", sem_id)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3)
