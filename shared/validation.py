"""
validation.py - Lógica de validación de mensajes para el servicio de Analytics.
Valida eventos de sensores, comandos de override e integridad de datos.
"""

import json
import logging
from typing import Tuple, Optional
from shared.constants import SENSOR_TYPES, SENSOR_PREFIXES

logger = logging.getLogger(__name__)

# ─── Campos requeridos por tipo de mensaje ───

SENSOR_EVENT_REQUIRED = ["message_id", "sensor_id", "tipo_sensor", "interseccion", "timestamp", "datos"]

SENSOR_DATA_FIELDS = {
    "espira": ["vehiculos_por_minuto"],
    "camara": ["longitud_cola"],
    "gps": ["densidad", "velocidad_promedio"],
}

OVERRIDE_REQUIRED = ["tipo", "semaforo_id", "nuevo_estado", "motivo", "origen", "auth_token"]

# ─── Rangos de valores de datos ───

DATA_RANGES = {
    "vehiculos_por_minuto": (0, 100),
    "longitud_cola": (0, 200),
    "densidad": (0, 200),
    "velocidad_promedio": (0, 200),
}


def validate_sensor_event(data: dict, registered_sensors: set = None,
                          auth_tokens: dict = None) -> Tuple[bool, str]:
    """
    Valida un mensaje de evento de sensor.
    
    Returns:
        (True, "") si es válido
        (False, "reason") si es inválido
    """
    # 1. Verificar campos requeridos
    for field in SENSOR_EVENT_REQUIRED:
        if field not in data:
            return False, f"Missing required field: {field}"

    # 2. Validar tipo_sensor
    tipo = data.get("tipo_sensor", "")
    if tipo not in SENSOR_TYPES:
        return False, f"Invalid tipo_sensor: {tipo}. Must be one of {SENSOR_TYPES}"

    # 3. Validar formato de sensor_id
    sid = data.get("sensor_id", "")
    expected_prefix = SENSOR_PREFIXES.get(tipo, "")
    if not sid.startswith(expected_prefix + "_"):
        return False, f"sensor_id '{sid}' does not match tipo_sensor '{tipo}' (expected prefix '{expected_prefix}_')"

    # 4. Validar que el sensor_id esté registrado
    if registered_sensors and sid not in registered_sensors:
        return False, f"sensor_id '{sid}' is not registered"

    # 5. Validar auth_token
    if auth_tokens and sid in auth_tokens:
        if data.get("auth_token", "") != auth_tokens[sid]:
            return False, f"Invalid auth_token for sensor '{sid}'"

    # 6. Validar estructura de datos
    datos = data.get("datos", {})
    if not isinstance(datos, dict):
        return False, "Field 'datos' must be a JSON object"

    expected_fields = SENSOR_DATA_FIELDS.get(tipo, [])
    for field in expected_fields:
        if field not in datos:
            return False, f"Missing data field '{field}' for sensor type '{tipo}'"

    # 7. Validar rangos de datos
    for field, value in datos.items():
        if not isinstance(value, (int, float)):
            return False, f"Data field '{field}' must be numeric, got {type(value).__name__}"
        if value < 0:
            return False, f"Data field '{field}' cannot be negative: {value}"
        if field in DATA_RANGES:
            min_val, max_val = DATA_RANGES[field]
            if value < min_val or value > max_val:
                return False, f"Data field '{field}' value {value} out of range [{min_val}, {max_val}]"

    # 8. Validar formato de interseccion
    interseccion = data.get("interseccion", "")
    if not interseccion.startswith("INT_C"):
        return False, f"Invalid interseccion format: '{interseccion}'. Expected 'INT_CxKy'"

    return True, ""


def validate_override_command(data: dict, valid_auth_token: str = None) -> Tuple[bool, str]:
    """
    Valida un comando de override del servicio de monitoreo.
    
    Returns:
        (True, "") si es válido
        (False, "reason") si es inválido
    """
    # 1. Verificar campos requeridos
    for field in OVERRIDE_REQUIRED:
        if field not in data:
            return False, f"Missing required field: {field}"

    # 2. Validar tipo
    if data.get("tipo") != "OVERRIDE":
        return False, f"Invalid command type: {data.get('tipo')}"

    # 3. Validar origen
    if data.get("origen") != "monitoring_service":
        return False, f"Unauthorized origin: {data.get('origen')}"

    # 4. Validar auth_token
    if valid_auth_token and data.get("auth_token") != valid_auth_token:
        return False, "Invalid auth_token for override command"

    # 5. Validar nuevo_estado
    nuevo_estado = data.get("nuevo_estado", "")
    if nuevo_estado not in ["VERDE", "ROJO"]:
        return False, f"Invalid nuevo_estado: '{nuevo_estado}'. Must be 'VERDE' or 'ROJO'"

    # 6. Validar formato de semaforo_id
    sem_id = data.get("semaforo_id", "")
    if not sem_id.startswith("SEM_C"):
        return False, f"Invalid semaforo_id format: '{sem_id}'"

    return True, ""


def validate_query(data: dict) -> Tuple[bool, str]:
    """
    Valida una consulta del servicio de monitoreo.
    
    Returns:
        (True, "") si es válido
        (False, "reason") si es inválido
    """
    if "tipo" not in data:
        return False, "Missing 'tipo' field"

    if data["tipo"] != "CONSULTA":
        return False, f"Invalid query type: {data['tipo']}"

    consulta = data.get("consulta", "")
    valid_queries = ["ESTADO_INTERSECCION", "ESTADO_GENERAL", "LISTAR_SEMAFOROS"]
    if consulta not in valid_queries:
        return False, f"Invalid consulta: '{consulta}'. Must be one of {valid_queries}"

    if consulta == "ESTADO_INTERSECCION" and not data.get("interseccion"):
        return False, "ESTADO_INTERSECCION requires 'interseccion' field"

    return True, ""
