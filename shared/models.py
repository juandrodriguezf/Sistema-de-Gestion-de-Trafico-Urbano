"""
models.py - clases de mensajes para la comunicacion ZMQ.
Todos los mensajes siguen el formato JSON con campos obligatorios de timestamp y source_id.  
"""

import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any


def _now() -> str:
    """ISO 8601 timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _uuid() -> str:
    """Generate a UUID v4 string."""
    return str(uuid.uuid4())


# ═══════════════════════════════════════════
# Mensajes de eventos de sensores (Sensor → Broker)
# ═══════════════════════════════════════════

@dataclass
class SensorEvent:
    """Mensaje enviado por un sensor al Broker via PUB."""
    sensor_id: str
    tipo_sensor: str          # espira | camara | gps
    interseccion: str         # INT_C5K3
    datos: Dict[str, Any]     # payload específico del sensor
    auth_token: str = ""
    message_id: str = field(default_factory=_uuid)
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "SensorEvent":
        d = json.loads(raw)
        return cls(**d)


# ═══════════════════════════════════════════
# Resultado del análisis de tráfico (Analytics → DB)
# ═══════════════════════════════════════════

@dataclass
class TrafficState:
    """Resultado de la evaluación para una intersección."""
    interseccion: str
    estado: str               # normal | congestion
    metricas: Dict[str, float]
    accion_tomada: Optional[Dict[str, str]] = None
    message_id: str = field(default_factory=_uuid)
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "TrafficState":
        d = json.loads(raw)
        return cls(**d)


# ═══════════════════════════════════════════
# Comando de semaforo (Analytics → Lights)
# ═══════════════════════════════════════════

@dataclass
class LightAction:
    """Comando para cambiar el estado de un semaforo."""
    semaforo_id: str
    nuevo_estado: str         # VERDE | ROJO
    razon: str                # congestion_detectada | prioridad | manual
    comando: str = "CAMBIO_LUZ"
    prioridad: bool = False
    message_id: str = field(default_factory=_uuid)
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "LightAction":
        d = json.loads(raw)
        return cls(**d)


# ═══════════════════════════════════════════
# Mensajes de monitoreo (Monitoring ↔ Analytics)
# ═══════════════════════════════════════════

@dataclass
class MonitoringRequest:
    """Consulta o comando de override del servicio de monitoreo."""
    tipo: str                 # CONSULTA | OVERRIDE
    consulta: str = ""        # ESTADO_INTERSECCION | ESTADO_GENERAL
    interseccion: str = ""
    semaforo_id: str = ""
    nuevo_estado: str = ""
    motivo: str = ""
    origen: str = "monitoring_service"
    auth_token: str = ""
    message_id: str = field(default_factory=_uuid)
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "MonitoringRequest":
        d = json.loads(raw)
        return cls(**d)


@dataclass
class MonitoringResponse:
    """Respuesta del servicio de monitoreo."""
    tipo: str                 # RESPUESTA | ERROR
    datos: Dict[str, Any] = field(default_factory=dict)
    mensaje: str = ""
    message_id: str = field(default_factory=_uuid)
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "MonitoringResponse":
        d = json.loads(raw)
        return cls(**d)


# ═══════════════════════════════════════════
# Mensajes de replicación de base de datos (Main DB → Replica DB)
# ═══════════════════════════════════════════

@dataclass
class ReplicationMessage:
    """Mensaje de sincronización de la base de datos principal a la base de datos réplica."""
    tabla: str
    operacion: str            # INSERT | UPDATE
    datos: Dict[str, Any] = field(default_factory=dict)
    sequence_number: int = 0
    tipo: str = "SYNC"
    message_id: str = field(default_factory=_uuid)
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "ReplicationMessage":
        d = json.loads(raw)
        return cls(**d)


# ═══════════════════════════════════════════
# Mensaje de Heartbeat
# ═══════════════════════════════════════════

@dataclass
class Heartbeat:
    """Heartbeat from PC3 Main DB to PC2 Analytics."""
    source: str = "main_db"
    status: str = "alive"
    tipo: str = "HEARTBEAT"
    timestamp: str = field(default_factory=_now)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Heartbeat":
        d = json.loads(raw)
        return cls(**d)
