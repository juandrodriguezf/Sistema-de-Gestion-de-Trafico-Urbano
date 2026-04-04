"""
models.py - Data classes and message builders for ZMQ communication.
All messages follow JSON format with mandatory timestamp and source_id fields.
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
# Sensor Event Messages (Sensor → Broker)
# ═══════════════════════════════════════════

@dataclass
class SensorEvent:
    """Message sent by a sensor to the Broker via PUB."""
    sensor_id: str
    tipo_sensor: str          # espira | camara | gps
    interseccion: str         # INT_C5K3
    datos: Dict[str, Any]     # sensor-specific payload
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
# Traffic Analysis Result (Analytics → DB)
# ═══════════════════════════════════════════

@dataclass
class TrafficState:
    """Evaluation result for one intersection."""
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
# Traffic Light Command (Analytics → Lights)
# ═══════════════════════════════════════════

@dataclass
class LightAction:
    """Command to change a traffic light state."""
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
# Monitoring Messages (Monitoring ↔ Analytics)
# ═══════════════════════════════════════════

@dataclass
class MonitoringRequest:
    """Query or override command from Monitoring Service."""
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
    """Response from Analytics to Monitoring."""
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
# DB Replication Message (Main DB → Replica DB)
# ═══════════════════════════════════════════

@dataclass
class ReplicationMessage:
    """Sync message from Main DB to Replica DB."""
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
# Heartbeat Message
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
