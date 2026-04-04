"""
db_utils.py - Database initialization and helper functions.
Creates and manages SQLite databases for both Main DB and Replica DB.
"""

import sqlite3
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# Schema Definitions
# ═══════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sensores (
    sensor_id       TEXT PRIMARY KEY,
    tipo_sensor     TEXT NOT NULL,
    interseccion_id TEXT NOT NULL,
    estado          TEXT DEFAULT 'activo',
    ultima_lectura  TEXT
);

CREATE TABLE IF NOT EXISTS intersecciones (
    interseccion_id      TEXT PRIMARY KEY,
    columna              INTEGER NOT NULL,
    fila                 INTEGER NOT NULL,
    estado_trafico       TEXT DEFAULT 'normal',
    ultima_actualizacion TEXT
);

CREATE TABLE IF NOT EXISTS eventos (
    evento_id       TEXT PRIMARY KEY,
    sensor_id       TEXT NOT NULL,
    interseccion_id TEXT NOT NULL,
    tipo_sensor     TEXT NOT NULL,
    datos           TEXT NOT NULL,
    timestamp       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS estado_trafico (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    interseccion_id       TEXT NOT NULL,
    Q                     REAL,
    Vp                    REAL,
    D                     REAL,
    vehiculos_por_minuto  REAL,
    estado                TEXT NOT NULL,
    timestamp             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semaforos (
    semaforo_id     TEXT PRIMARY KEY,
    interseccion_id TEXT NOT NULL,
    direccion       TEXT NOT NULL,
    estado_actual   TEXT DEFAULT 'ROJO',
    ultima_accion   TEXT
);

CREATE TABLE IF NOT EXISTS acciones_semaforo (
    accion_id       TEXT PRIMARY KEY,
    semaforo_id     TEXT NOT NULL,
    estado_anterior TEXT NOT NULL,
    estado_nuevo    TEXT NOT NULL,
    razon           TEXT NOT NULL,
    origen          TEXT NOT NULL,
    timestamp       TEXT NOT NULL
);
"""


class DatabaseManager:
    """Manages SQLite database operations for the traffic system."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Open DB connection and initialize schema."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()
        logger.info(f"Database connected: {self.db_path}")

    def close(self):
        """Close DB connection."""
        if self.conn:
            self.conn.close()
            logger.info(f"Database closed: {self.db_path}")

    # ─── Seed Data ───

    def seed_intersections(self, columns: int, rows: int):
        """Insert all intersections for the grid."""
        now = datetime.now(timezone.utc).isoformat()
        for c in range(1, columns + 1):
            for r in range(1, rows + 1):
                int_id = f"INT_C{c}K{r}"
                self.conn.execute(
                    "INSERT OR IGNORE INTO intersecciones (interseccion_id, columna, fila, estado_trafico, ultima_actualizacion) VALUES (?, ?, ?, 'normal', ?)",
                    (int_id, c, r, now)
                )
        self.conn.commit()
        logger.info(f"Seeded {columns * rows} intersections")

    def seed_sensors(self, columns: int, rows: int):
        """Register all sensors for the grid (3 per intersection)."""
        from shared.constants import SENSOR_TYPES, SENSOR_PREFIXES
        for c in range(1, columns + 1):
            for r in range(1, rows + 1):
                int_id = f"INT_C{c}K{r}"
                for stype in SENSOR_TYPES:
                    prefix = SENSOR_PREFIXES[stype]
                    sid = f"{prefix}_C{c}K{r}"
                    self.conn.execute(
                        "INSERT OR IGNORE INTO sensores (sensor_id, tipo_sensor, interseccion_id, estado) VALUES (?, ?, ?, 'activo')",
                        (sid, stype, int_id)
                    )
        self.conn.commit()
        total = columns * rows * 3
        logger.info(f"Seeded {total} sensors")

    def seed_semaforos(self, columns: int, rows: int, directions: List[str]):
        """Register traffic lights for the grid."""
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for c in range(1, columns + 1):
            for r in range(1, rows + 1):
                int_id = f"INT_C{c}K{r}"
                for d in directions:
                    sem_id = f"SEM_C{c}K{r}_{d}"
                    # Alternate initial states
                    initial_state = "VERDE" if (c + r) % 2 == 0 else "ROJO"
                    self.conn.execute(
                        "INSERT OR IGNORE INTO semaforos (semaforo_id, interseccion_id, direccion, estado_actual, ultima_accion) VALUES (?, ?, ?, ?, ?)",
                        (sem_id, int_id, d, initial_state, now)
                    )
                    count += 1
        self.conn.commit()
        logger.info(f"Seeded {count} traffic lights")

    def seed_all(self, columns: int, rows: int, directions: List[str]):
        """Seed all static data."""
        self.seed_intersections(columns, rows)
        self.seed_sensors(columns, rows)
        self.seed_semaforos(columns, rows, directions)

    # ─── Event Operations ───

    def insert_event(self, evento_id: str, sensor_id: str, interseccion_id: str,
                     tipo_sensor: str, datos: dict, timestamp: str):
        """Insert a sensor event."""
        self.conn.execute(
            "INSERT INTO eventos (evento_id, sensor_id, interseccion_id, tipo_sensor, datos, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (evento_id, sensor_id, interseccion_id, tipo_sensor, json.dumps(datos), timestamp)
        )
        self.conn.commit()

    # ─── Traffic State Operations ───

    def insert_traffic_state(self, interseccion_id: str, Q: float, Vp: float,
                             D: float, veh_min: float, estado: str, timestamp: str):
        """Insert a traffic state evaluation."""
        self.conn.execute(
            "INSERT INTO estado_trafico (interseccion_id, Q, Vp, D, vehiculos_por_minuto, estado, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (interseccion_id, Q, Vp, D, veh_min, estado, timestamp)
        )
        self.conn.execute(
            "UPDATE intersecciones SET estado_trafico = ?, ultima_actualizacion = ? WHERE interseccion_id = ?",
            (estado, timestamp, interseccion_id)
        )
        self.conn.commit()

    # ─── Traffic Light Operations ───

    def update_semaforo(self, semaforo_id: str, nuevo_estado: str, timestamp: str):
        """Update a traffic light state."""
        self.conn.execute(
            "UPDATE semaforos SET estado_actual = ?, ultima_accion = ? WHERE semaforo_id = ?",
            (nuevo_estado, timestamp, semaforo_id)
        )
        self.conn.commit()

    def insert_light_action(self, accion_id: str, semaforo_id: str,
                            estado_anterior: str, estado_nuevo: str,
                            razon: str, origen: str, timestamp: str):
        """Record a traffic light action."""
        self.conn.execute(
            "INSERT INTO acciones_semaforo (accion_id, semaforo_id, estado_anterior, estado_nuevo, razon, origen, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (accion_id, semaforo_id, estado_anterior, estado_nuevo, razon, origen, timestamp)
        )
        self.conn.commit()

    def get_semaforo_state(self, semaforo_id: str) -> Optional[str]:
        """Get current state of a traffic light."""
        row = self.conn.execute(
            "SELECT estado_actual FROM semaforos WHERE semaforo_id = ?",
            (semaforo_id,)
        ).fetchone()
        return row["estado_actual"] if row else None

    # ─── Query Operations ───

    def get_intersection_state(self, interseccion_id: str) -> Optional[Dict[str, Any]]:
        """Get current state of an intersection."""
        row = self.conn.execute(
            "SELECT * FROM intersecciones WHERE interseccion_id = ?",
            (interseccion_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        # Add semaphore states
        sems = self.conn.execute(
            "SELECT semaforo_id, direccion, estado_actual FROM semaforos WHERE interseccion_id = ?",
            (interseccion_id,)
        ).fetchall()
        result["semaforos"] = [dict(s) for s in sems]
        # Add latest traffic state
        latest = self.conn.execute(
            "SELECT Q, Vp, D, vehiculos_por_minuto, estado, timestamp FROM estado_trafico WHERE interseccion_id = ? ORDER BY timestamp DESC LIMIT 1",
            (interseccion_id,)
        ).fetchone()
        result["ultimo_estado_trafico"] = dict(latest) if latest else None
        return result

    def get_all_intersections_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all intersections."""
        rows = self.conn.execute(
            "SELECT interseccion_id, estado_trafico, ultima_actualizacion FROM intersecciones ORDER BY interseccion_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_semaforos(self) -> List[Dict[str, Any]]:
        """Get all traffic light states."""
        rows = self.conn.execute(
            "SELECT semaforo_id, interseccion_id, direccion, estado_actual FROM semaforos ORDER BY semaforo_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def is_sensor_registered(self, sensor_id: str) -> bool:
        """Check if a sensor is registered and active."""
        row = self.conn.execute(
            "SELECT estado FROM sensores WHERE sensor_id = ?",
            (sensor_id,)
        ).fetchone()
        return row is not None and row["estado"] == "activo"

    def get_sensor_type(self, sensor_id: str) -> Optional[str]:
        """Get the type of a registered sensor."""
        row = self.conn.execute(
            "SELECT tipo_sensor FROM sensores WHERE sensor_id = ?",
            (sensor_id,)
        ).fetchone()
        return row["tipo_sensor"] if row else None

    def update_sensor_reading(self, sensor_id: str, timestamp: str):
        """Update last reading time for a sensor."""
        self.conn.execute(
            "UPDATE sensores SET ultima_lectura = ? WHERE sensor_id = ?",
            (timestamp, sensor_id)
        )
        self.conn.commit()

    def get_event_count(self) -> int:
        """Get total number of stored events."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM eventos").fetchone()
        return row["cnt"]
