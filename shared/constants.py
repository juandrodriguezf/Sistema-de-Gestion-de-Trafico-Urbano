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

# ─── Labels de columnas para display ───
COLUMN_LABELS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}
LABEL_TO_COL = {v: k for k, v in COLUMN_LABELS.items()}


def display_intersection(col: int, row: int) -> str:
    """Convierte (2, 2) → B2 para display."""
    return f"{COLUMN_LABELS.get(col, f'C{col}')}{row}"


def display_semaforo(col: int, row: int, direction: str) -> str:
    """Convierte (2, 2, 'N') → SEM_B2_N para display."""
    return f"SEM_{display_intersection(col, row)}_{direction}"


def parse_display_intersection(label: str) -> Tuple[int, int]:
    """Convierte B2 → (2, 2). Acepta tanto A1 como INT_A1."""
    label = label.replace("INT_", "")
    col_letter = label[0].upper()
    row = int(label[1:])
    return LABEL_TO_COL[col_letter], row


def parse_display_semaforo(label: str) -> Optional[Tuple[int, int, str]]:
    """Convierte SEM_B2_N → (2, 2, 'N')."""
    m = re.match(r"^SEM_([A-E])(\d+)_([NSEW])$", label)
    if not m:
        return None
    col = LABEL_TO_COL[m.group(1)]
    row = int(m.group(2))
    direction = m.group(3)
    return col, row, direction

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
CMD_CONSULTA_HISTORICA = "CONSULTA_HISTORICA"
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


def parse_sensor_id(sensor_id_str: str) -> Optional[Tuple[str, int, int]]:
    """
    Parsea {PREFIX}_C{col}K{row} → (tipo_sensor, col, row).
    Retorna None si el formato no es válido.
    """
    m = re.match(r"^(ESP|CAM|GPS)_C(\d+)K(\d+)$", sensor_id_str)
    if not m:
        return None
    prefix_to_type = {v: k for k, v in SENSOR_PREFIXES.items()}
    return prefix_to_type[m.group(1)], int(m.group(2)), int(m.group(3))


def _within_grid(col: int, row: int, columns: int, rows: int) -> bool:
    return 1 <= col <= columns and 1 <= row <= rows


def is_valid_intersection_id(int_id: str, columns: int, rows: int) -> bool:
    """Valida INT_C{col}K{row} y que la posición exista en la grilla."""
    m = re.match(r"^INT_C(\d+)K(\d+)$", int_id)
    if not m:
        return False
    return _within_grid(int(m.group(1)), int(m.group(2)), columns, rows)


def is_valid_semaforo_id(sem_id: str, columns: int, rows: int) -> bool:
    """Valida SEM_C{col}K{row}_{DIR} y que la posición exista en la grilla."""
    parsed = parse_semaforo_id(sem_id)
    if parsed is None:
        return False
    col, row, direction = parsed
    return direction in DIRECTIONS and _within_grid(col, row, columns, rows)
