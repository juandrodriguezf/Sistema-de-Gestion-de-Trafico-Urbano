"""
test_functional.py - Functional tests for the traffic management system.
Tests sensor events, traffic rule evaluation, and message validation.
Run with: python -m tests.test_functional (from project root)
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.constants import (
    intersection_id, sensor_id, semaforo_id, sensor_topic,
    SENSOR_ESPIRA, SENSOR_CAMARA, SENSOR_GPS,
    VERDE, ROJO, NORMAL, CONGESTION,
)
from shared.models import SensorEvent, TrafficState, LightAction, MonitoringRequest
from shared.validation import validate_sensor_event, validate_override_command, validate_query
from shared.db_utils import DatabaseManager


class TestConstants(unittest.TestCase):
    """Test naming convention generators."""

    def test_intersection_id(self):
        self.assertEqual(intersection_id(5, 3), "INT_C5K3")
        self.assertEqual(intersection_id(1, 1), "INT_C1K1")

    def test_sensor_id(self):
        self.assertEqual(sensor_id(SENSOR_ESPIRA, 5, 3), "ESP_C5K3")
        self.assertEqual(sensor_id(SENSOR_CAMARA, 2, 4), "CAM_C2K4")
        self.assertEqual(sensor_id(SENSOR_GPS, 1, 1), "GPS_C1K1")

    def test_semaforo_id(self):
        self.assertEqual(semaforo_id(5, 3, "N"), "SEM_C5K3_N")
        self.assertEqual(semaforo_id(1, 1, "E"), "SEM_C1K1_E")

    def test_sensor_topic(self):
        self.assertEqual(sensor_topic(SENSOR_ESPIRA, 5, 3), "sensor/espira/C5K3")
        self.assertEqual(sensor_topic(SENSOR_GPS, 1, 1), "sensor/gps/C1K1")


class TestModels(unittest.TestCase):
    """Test message model serialization."""

    def test_sensor_event_serialization(self):
        event = SensorEvent(
            sensor_id="ESP_C1K1",
            tipo_sensor="espira",
            interseccion="INT_C1K1",
            datos={"vehiculos_por_minuto": 12.5},
        )
        json_str = event.to_json()
        parsed = SensorEvent.from_json(json_str)
        self.assertEqual(parsed.sensor_id, "ESP_C1K1")
        self.assertEqual(parsed.datos["vehiculos_por_minuto"], 12.5)

    def test_traffic_state_serialization(self):
        state = TrafficState(
            interseccion="INT_C3K2",
            estado="congestion",
            metricas={"Q": 7, "Vp": 28, "D": 25},
        )
        json_str = state.to_json()
        parsed = TrafficState.from_json(json_str)
        self.assertEqual(parsed.estado, "congestion")
        self.assertEqual(parsed.metricas["Q"], 7)

    def test_light_action_serialization(self):
        action = LightAction(
            semaforo_id="SEM_C3K2_N",
            nuevo_estado="VERDE",
            razon="congestion_detectada",
        )
        json_str = action.to_json()
        parsed = LightAction.from_json(json_str)
        self.assertEqual(parsed.semaforo_id, "SEM_C3K2_N")
        self.assertEqual(parsed.nuevo_estado, "VERDE")


class TestValidation(unittest.TestCase):
    """Test message validation logic."""

    def test_valid_espira_event(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "ESP_C1K1",
            "tipo_sensor": "espira",
            "interseccion": "INT_C1K1",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"vehiculos_por_minuto": 10},
        }
        valid, reason = validate_sensor_event(data)
        self.assertTrue(valid, reason)

    def test_valid_gps_event(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "GPS_C3K2",
            "tipo_sensor": "gps",
            "interseccion": "INT_C3K2",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"densidad": 15.0, "velocidad_promedio": 40.0},
        }
        valid, reason = validate_sensor_event(data)
        self.assertTrue(valid, reason)

    def test_invalid_sensor_type(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "XYZ_C1K1",
            "tipo_sensor": "laser",
            "interseccion": "INT_C1K1",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"value": 5},
        }
        valid, reason = validate_sensor_event(data)
        self.assertFalse(valid)
        self.assertIn("Invalid tipo_sensor", reason)

    def test_missing_data_field(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "GPS_C1K1",
            "tipo_sensor": "gps",
            "interseccion": "INT_C1K1",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"densidad": 15.0},  # Missing velocidad_promedio
        }
        valid, reason = validate_sensor_event(data)
        self.assertFalse(valid)
        self.assertIn("velocidad_promedio", reason)

    def test_negative_value(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "ESP_C1K1",
            "tipo_sensor": "espira",
            "interseccion": "INT_C1K1",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"vehiculos_por_minuto": -5},
        }
        valid, reason = validate_sensor_event(data)
        self.assertFalse(valid)
        self.assertIn("negative", reason)

    def test_prefix_mismatch(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "CAM_C1K1",  # Camera ID with espira type
            "tipo_sensor": "espira",
            "interseccion": "INT_C1K1",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"vehiculos_por_minuto": 10},
        }
        valid, reason = validate_sensor_event(data)
        self.assertFalse(valid)
        self.assertIn("does not match", reason)

    def test_valid_override(self):
        data = {
            "tipo": "OVERRIDE",
            "semaforo_id": "SEM_C3K2_N",
            "nuevo_estado": "VERDE",
            "motivo": "ambulancia",
            "origen": "monitoring_service",
            "auth_token": "test-token",
        }
        valid, reason = validate_override_command(data, "test-token")
        self.assertTrue(valid, reason)

    def test_invalid_override_token(self):
        data = {
            "tipo": "OVERRIDE",
            "semaforo_id": "SEM_C3K2_N",
            "nuevo_estado": "VERDE",
            "motivo": "ambulancia",
            "origen": "monitoring_service",
            "auth_token": "wrong-token",
        }
        valid, reason = validate_override_command(data, "correct-token")
        self.assertFalse(valid)
        self.assertIn("auth_token", reason)

    def test_valid_query(self):
        data = {
            "tipo": "CONSULTA",
            "consulta": "ESTADO_INTERSECCION",
            "interseccion": "INT_C3K2",
        }
        valid, reason = validate_query(data)
        self.assertTrue(valid, reason)


class TestDatabase(unittest.TestCase):
    """Test database operations."""

    def setUp(self):
        """Create a temporary test DB."""
        self.db_path = os.path.join(os.path.dirname(__file__), "test_temp.db")
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.seed_all(2, 2, ["N", "S"])

    def tearDown(self):
        """Clean up test DB."""
        self.db.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_seed_intersections(self):
        rows = self.db.conn.execute("SELECT COUNT(*) as cnt FROM intersecciones").fetchone()
        self.assertEqual(rows["cnt"], 4)  # 2x2 = 4

    def test_seed_sensors(self):
        rows = self.db.conn.execute("SELECT COUNT(*) as cnt FROM sensores").fetchone()
        self.assertEqual(rows["cnt"], 12)  # 2x2x3 = 12

    def test_seed_semaforos(self):
        rows = self.db.conn.execute("SELECT COUNT(*) as cnt FROM semaforos").fetchone()
        self.assertEqual(rows["cnt"], 8)  # 2x2x2 directions = 8

    def test_insert_event(self):
        self.db.insert_event("evt-1", "ESP_C1K1", "INT_C1K1", "espira",
                             {"vehiculos_por_minuto": 10}, "2026-01-01T00:00:00Z")
        count = self.db.get_event_count()
        self.assertEqual(count, 1)

    def test_get_intersection_state(self):
        state = self.db.get_intersection_state("INT_C1K1")
        self.assertIsNotNone(state)
        self.assertEqual(state["interseccion_id"], "INT_C1K1")
        self.assertIn("semaforos", state)

    def test_sensor_registered(self):
        self.assertTrue(self.db.is_sensor_registered("ESP_C1K1"))
        self.assertFalse(self.db.is_sensor_registered("XYZ_C1K1"))

    def test_update_semaforo(self):
        self.db.update_semaforo("SEM_C1K1_N", "VERDE", "2026-01-01T00:00:00Z")
        state = self.db.get_semaforo_state("SEM_C1K1_N")
        self.assertEqual(state, "VERDE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
