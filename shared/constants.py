"""
constants.py - Naming conventions, states, and system-wide constants.
Follows the grid notation defined in the project specification.
"""

# ─── Traffic Light States ───
VERDE = "VERDE"
ROJO = "ROJO"
LIGHT_STATES = [VERDE, ROJO]

# ─── Traffic States ───
NORMAL = "normal"
CONGESTION = "congestion"
PRIORIDAD = "prioridad"
TRAFFIC_STATES = [NORMAL, CONGESTION, PRIORIDAD]

# ─── Sensor Types ───
SENSOR_ESPIRA = "espira"
SENSOR_CAMARA = "camara"
SENSOR_GPS = "gps"
SENSOR_TYPES = [SENSOR_ESPIRA, SENSOR_CAMARA, SENSOR_GPS]
SENSOR_PREFIXES = {
    SENSOR_ESPIRA: "ESP",
    SENSOR_CAMARA: "CAM",
    SENSOR_GPS: "GPS",
}

# ─── Directions ───
NORTH = "N"
SOUTH = "S"
EAST = "E"
WEST = "W"
DIRECTIONS = [NORTH, SOUTH, EAST, WEST]

# ─── Action Reasons ───
REASON_CONGESTION = "congestion_detectada"
REASON_PRIORITY = "prioridad"
REASON_MANUAL = "manual"
REASON_NORMAL = "normal"

# ─── Action Origins ───
ORIGIN_ANALYTICS = "analytics"
ORIGIN_MONITORING = "monitoring"

# ─── Command Types ───
CMD_CONSULTA = "CONSULTA"
CMD_OVERRIDE = "OVERRIDE"
CMD_ESTADO_INTERSECCION = "ESTADO_INTERSECCION"
CMD_ESTADO_GENERAL = "ESTADO_GENERAL"
CMD_LISTAR_SEMAFOROS = "LISTAR_SEMAFOROS"
CMD_CAMBIO_LUZ = "CAMBIO_LUZ"

# ─── DB Modes ───
DB_MAIN = "main"
DB_REPLICA = "replica"

# ─── Replication ───
SYNC_INSERT = "INSERT"
SYNC_UPDATE = "UPDATE"

# ─── ZMQ Topic Prefixes ───
TOPIC_SENSOR = "sensor"
TOPIC_SEMAFORO = "semaforo"
TOPIC_ALERTA = "alerta"
TOPIC_HEARTBEAT = "heartbeat"
TOPIC_SYNC = "sync"


def intersection_id(col: int, row: int) -> str:
    """Generate intersection ID: INT_C{col}K{row}"""
    return f"INT_C{col}K{row}"


def sensor_id(sensor_type: str, col: int, row: int) -> str:
    """Generate sensor ID: {PREFIX}_C{col}K{row}"""
    prefix = SENSOR_PREFIXES[sensor_type]
    return f"{prefix}_C{col}K{row}"


def semaforo_id(col: int, row: int, direction: str) -> str:
    """Generate traffic light ID: SEM_C{col}K{row}_{DIR}"""
    return f"SEM_C{col}K{row}_{direction}"


def sensor_topic(sensor_type: str, col: int, row: int) -> str:
    """Generate ZMQ topic: sensor/{type}/C{col}K{row}"""
    return f"{TOPIC_SENSOR}/{sensor_type}/C{col}K{row}"


def semaforo_topic(col: int, row: int) -> str:
    """Generate ZMQ topic for traffic light changes."""
    return f"{TOPIC_SEMAFORO}/cambio/C{col}K{row}"


def parse_intersection(int_id: str) -> tuple:
    """Parse INT_C{col}K{row} → (col, row)"""
    # INT_C5K3 → col=5, row=3
    parts = int_id.replace("INT_C", "").split("K")
    return int(parts[0]), int(parts[1])
