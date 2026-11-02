"""
test_functional.py - Pruebas funcionales para el sistema de gestion de trafico.
Prueba los eventos de los sensores, la evaluacion de reglas de trafico y la validacion de mensajes.
Ejecutar con: python -m tests.test_functional (desde la raiz del proyecto)
"""

import sys
import os
import json
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.constants import (
    intersection_id, sensor_id, semaforo_id, sensor_topic,
    SENSOR_ESPIRA, SENSOR_CAMARA, SENSOR_GPS,
    VERDE, ROJO, NORMAL, CONGESTION,
)
from shared.models import (
    SensorEvent, TrafficState, LightAction, MonitoringRequest, ResyncBatch,
    ReplicationMessage,
)
from shared.validation import validate_sensor_event, validate_override_command, validate_query
from shared.db_utils import DatabaseManager


class TestConstants(unittest.TestCase):
    """test de convenciones de nombres"""

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
    """test de serializacion de modelos de mensajes"""

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

    def test_traffic_state_actions_serialization(self):
        accion = {
            "tipo": "CAMBIO_LUZ",
            "semaforo_id": "SEM_C3K2_N",
            "estado_anterior": "ROJO",
            "estado_nuevo": "VERDE",
        }
        state = TrafficState(
            interseccion="INT_C3K2",
            estado="congestion",
            metricas={"Q": 7},
            accion_tomada=accion,
            acciones_tomadas=[accion],
        )
        parsed = TrafficState.from_json(state.to_json())
        self.assertEqual(len(parsed.acciones_tomadas), 1)
        self.assertEqual(parsed.acciones_tomadas[0]["semaforo_id"], "SEM_C3K2_N")
        self.assertEqual(parsed.accion_tomada["semaforo_id"], "SEM_C3K2_N")

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
        self.assertEqual(parsed.origen, "analytics")

    def test_light_action_from_json_sin_origen_usa_default(self):
        raw = '{"semaforo_id": "SEM_C1K1_N", "nuevo_estado": "ROJO", "razon": "manual", "comando": "CAMBIO_LUZ", "prioridad": false, "message_id": "x", "timestamp": "2026-01-01T00:00:00Z"}'
        parsed = LightAction.from_json(raw)
        self.assertEqual(parsed.origen, "analytics")


class TestValidation(unittest.TestCase):
    """test de validacion de mensajes"""

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
            "datos": {"densidad": 15.0, "velocidad_promedio": 40.0, "nivel_congestion": "NORMAL"},
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
            "datos": {"densidad": 15.0},  # no hay velocidad_promedio
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
            "sensor_id": "CAM_C1K1",  # ID de camara con tipo de espira
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

    def test_sensor_intersection_mismatch(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "ESP_C1K1",
            "tipo_sensor": "espira",
            "interseccion": "INT_C2K2",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"vehiculos_por_minuto": 10},
        }
        valid, reason = validate_sensor_event(data)
        self.assertFalse(valid)
        self.assertIn("belongs to", reason)

    def test_sensor_outside_grid(self):
        data = {
            "message_id": "test-id",
            "sensor_id": "ESP_C99K99",
            "tipo_sensor": "espira",
            "interseccion": "INT_C99K99",
            "timestamp": "2026-01-01T00:00:00Z",
            "datos": {"vehiculos_por_minuto": 10},
        }
        valid, reason = validate_sensor_event(data, grid={"columns": 5, "rows": 3})
        self.assertFalse(valid)
        self.assertIn("outside grid", reason)

    def test_override_outside_grid(self):
        data = {
            "tipo": "OVERRIDE",
            "semaforo_id": "SEM_C99K99_N",
            "nuevo_estado": "VERDE",
            "motivo": "ambulancia",
            "origen": "monitoring_service",
            "auth_token": "test-token",
        }
        valid, reason = validate_override_command(
            data, "test-token", grid={"columns": 5, "rows": 3}
        )
        self.assertFalse(valid)
        self.assertIn("outside grid", reason)

    def test_override_invalid_direction(self):
        data = {
            "tipo": "OVERRIDE",
            "semaforo_id": "SEM_C1K1_X",
            "nuevo_estado": "VERDE",
            "motivo": "ambulancia",
            "origen": "monitoring_service",
            "auth_token": "test-token",
        }
        valid, reason = validate_override_command(data, "test-token")
        self.assertFalse(valid)
        self.assertIn("Invalid semaforo_id", reason)


class _FakePub:
    """Socket PUB mínimo para probar process_traffic_state sin ZMQ."""

    def __init__(self):
        self.messages = []

    def send_string(self, msg, flags=0):
        self.messages.append(msg)


class _FakeTimer:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class TestMainDBEventSeparation(unittest.TestCase):
    """Verifica que solo los eventos reales lleguen a la tabla eventos."""

    def setUp(self):
        from pc3.main_db import MainDBService
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, "main.db"))
        self.db.connect()
        self.db.seed_all(1, 1, ["N", "S", "E", "W"])
        self.service = object.__new__(MainDBService)
        self.service.db = self.db
        self.service.sequence_number = 0

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_synthetic_state_does_not_create_event(self):
        state = TrafficState(
            interseccion="INT_C1K1",
            estado=NORMAL,
            metricas={"Q": 1, "Vp": 40, "D": 5, "vehiculos_por_minuto": 3},
        )
        self.service.process_traffic_state(state, _FakePub())

        self.assertEqual(self.db.get_event_count(), 0)
        row = self.db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM estado_trafico"
        ).fetchone()
        self.assertEqual(row["cnt"], 1)

    def test_all_actions_are_persisted_and_noops_skipped(self):
        acciones = [
            {
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_N",
                "estado_anterior": "ROJO", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            },
            {
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_S",
                "estado_anterior": "ROJO", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            },
            {
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_E",
                "estado_anterior": "VERDE", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            },
        ]
        state = TrafficState(
            interseccion="INT_C1K1",
            estado=CONGESTION,
            metricas={"Q": 7, "Vp": 20, "D": 25, "vehiculos_por_minuto": 5},
            acciones_tomadas=acciones,
        )
        self.service.process_traffic_state(state, _FakePub())

        row = self.db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM acciones_semaforo"
        ).fetchone()
        self.assertEqual(row["cnt"], 2)
        self.assertEqual(self.db.get_semaforo_state("SEM_C1K1_N"), VERDE)
        self.assertEqual(self.db.get_semaforo_state("SEM_C1K1_S"), VERDE)

    def test_legacy_single_action_is_persisted(self):
        state = TrafficState(
            interseccion="INT_C1K1",
            estado=CONGESTION,
            metricas={"Q": 7, "Vp": 20, "D": 25, "vehiculos_por_minuto": 5},
            accion_tomada={
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_N",
                "estado_anterior": "ROJO", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            },
        )
        self.service.process_traffic_state(state, _FakePub())

        row = self.db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM acciones_semaforo"
        ).fetchone()
        self.assertEqual(row["cnt"], 1)

    def test_real_event_persists_sensor_timestamp(self):
        state = TrafficState(
            interseccion="INT_C1K1",
            estado=NORMAL,
            metricas={"Q": 1, "Vp": 40, "D": 5, "vehiculos_por_minuto": 3},
            original_event_id="evt-real",
            original_sensor_id="ESP_C1K1",
            original_tipo_sensor=SENSOR_ESPIRA,
            original_datos=json.dumps({"vehiculos_por_minuto": 3}),
            original_timestamp="2026-01-01T00:00:00Z",
            timestamp="2026-01-01T00:00:01Z",
        )
        self.service.process_traffic_state(state, _FakePub())

        row = self.db.conn.execute(
            "SELECT * FROM eventos WHERE evento_id = 'evt-real'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["timestamp"], "2026-01-01T00:00:01Z")
        self.assertEqual(row["timestamp_sensor"], "2026-01-01T00:00:00Z")


class TestMainDBResync(unittest.TestCase):
    """Verifica que el endpoint de resync sea idempotente."""

    def setUp(self):
        from pc3.main_db import MainDBService
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, "main.db"))
        self.db.connect()
        self.db.seed_all(1, 1, ["N", "S", "E", "W"])
        self.service = object.__new__(MainDBService)
        self.service.db = self.db
        self.service.sequence_number = 0

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def _batch(self):
        return ResyncBatch(mensajes=[
            {
                "tabla": "eventos", "operacion": "INSERT",
                "datos": {
                    "evento_id": "evt-1", "sensor_id": "ESP_C1K1",
                    "interseccion_id": "INT_C1K1", "tipo_sensor": "espira",
                    "datos": {"vehiculos_por_minuto": 5},
                    "timestamp": "2026-01-01T00:00:01Z",
                    "timestamp_sensor": "2026-01-01T00:00:00Z",
                },
            },
            {
                "tabla": "estado_trafico", "operacion": "INSERT",
                "datos": {
                    "interseccion_id": "INT_C1K1", "Q": 1, "Vp": 40, "D": 5,
                    "vehiculos_por_minuto": 5, "estado": "normal",
                    "timestamp": "2026-01-01T00:00:01Z", "message_id": "st-1",
                },
            },
            {
                "tabla": "acciones_semaforo", "operacion": "INSERT",
                "datos": {
                    "accion_id": "ac-1", "semaforo_id": "SEM_C1K1_N",
                    "estado_anterior": "VERDE", "estado_nuevo": "ROJO",
                    "razon": "normal", "origen": "analytics",
                    "timestamp": "2026-01-01T00:00:01Z",
                },
            },
            {
                "tabla": "semaforos", "operacion": "UPDATE",
                "datos": {
                    "semaforo_id": "SEM_C1K1_N", "estado_actual": "ROJO",
                    "timestamp": "2026-01-01T00:00:01Z",
                },
            },
        ])

    def test_resync_batch_is_idempotent(self):
        first = self.service.process_resync_batch(self._batch())
        self.assertEqual(first.recibidos, 4)
        self.assertEqual(first.aplicados, 4)
        self.assertEqual(first.duplicados, 0)
        self.assertEqual(first.errores, 0)

        second = self.service.process_resync_batch(self._batch())
        self.assertEqual(second.aplicados, 0)
        self.assertEqual(second.duplicados, 4)
        self.assertEqual(second.errores, 0)

        self.assertEqual(self.db.get_event_count(), 1)
        count = self.db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM estado_trafico"
        ).fetchone()["cnt"]
        self.assertEqual(count, 1)
        count = self.db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM acciones_semaforo"
        ).fetchone()["cnt"]
        self.assertEqual(count, 1)

    def test_resync_reports_unsupported_message(self):
        batch = ResyncBatch(mensajes=[
            {"tabla": "desconocida", "operacion": "INSERT", "datos": {}},
        ])
        response = self.service.process_resync_batch(batch)
        self.assertEqual(response.recibidos, 1)
        self.assertEqual(response.errores, 1)


class TestAnalyticsReplicaActions(unittest.TestCase):
    """Verifica que Analytics registre todas las acciones al escribir en la replica."""

    def setUp(self):
        from pc2.analytics_service import AnalyticsService
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, "replica.db"))
        self.db.connect()
        self.db.seed_all(1, 1, ["N", "S", "E", "W"])
        self.service = object.__new__(AnalyticsService)
        self.service.replica_db = self.db

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def _state(self):
        return TrafficState(
            interseccion="INT_C1K1",
            estado=CONGESTION,
            metricas={"Q": 7, "Vp": 20, "D": 25, "vehiculos_por_minuto": 5},
            original_event_id="evt-out",
            original_sensor_id="ESP_C1K1",
            original_tipo_sensor=SENSOR_ESPIRA,
            original_datos=json.dumps({"vehiculos_por_minuto": 5}),
            original_timestamp="2026-01-01T00:00:00Z",
            acciones_tomadas=[{
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_N",
                "estado_anterior": "ROJO", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            }],
        )

    def test_persist_to_replica_populates_outbox(self):
        self.assertTrue(self.service._persist_to_replica(self._state()))
        pending = self.db.get_pending_outbox()
        tablas = {row["tabla"] for row in pending}
        self.assertEqual(tablas, {"eventos", "estado_trafico", "acciones_semaforo", "semaforos"})
        self.assertEqual(len(pending), 4)

    def test_flush_outbox_marks_messages_sent(self):
        from shared.models import ResyncResponse

        class _FakeReq:
            def __init__(self, response):
                self.response = response
                self.sent = []

            def send_string(self, msg):
                self.sent.append(msg)

            def poll(self, timeout):
                return True

            def recv_string(self):
                return self.response.to_json()

        self.service._persist_to_replica(self._state())
        self.service.use_replica = True
        self.service._failover_lock = threading.RLock()
        self.service.resync_batch_size = 100
        self.service.resync_timeout = 1
        self.service._resync_req = _FakeReq(ResyncResponse(
            recibidos=4, aplicados=4, duplicados=0, errores=0
        ))

        self.assertTrue(self.service._flush_outbox())
        self.assertEqual(len(self.db.get_pending_outbox()), 0)

    def test_flush_outbox_timeout_keeps_pending(self):
        class _TimeoutReq:
            def send_string(self, msg):
                pass

            def poll(self, timeout):
                return False

            def recv_string(self):
                raise AssertionError("no deberia recibir respuesta")

        self.service._persist_to_replica(self._state())
        self.service.use_replica = True
        self.service._failover_lock = threading.RLock()
        self.service.resync_batch_size = 100
        self.service.resync_timeout = 1
        self.service._resync_req = _TimeoutReq()

        self.assertFalse(self.service._flush_outbox())
        pending = self.db.get_pending_outbox()
        self.assertEqual(len(pending), 4)
        self.assertTrue(all(row["attempts"] == 1 for row in pending))

    def test_persist_to_replica_records_all_actions(self):
        acciones = [
            {
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_N",
                "estado_anterior": "ROJO", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            },
            {
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_S",
                "estado_anterior": "ROJO", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            },
            {
                "tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_E",
                "estado_anterior": "VERDE", "estado_nuevo": "VERDE",
                "razon": "congestion_detectada", "origen": "analytics",
            },
        ]
        state = TrafficState(
            interseccion="INT_C1K1",
            estado=CONGESTION,
            metricas={"Q": 7, "Vp": 20, "D": 25, "vehiculos_por_minuto": 5},
            acciones_tomadas=acciones,
        )
        self.assertTrue(self.service._persist_to_replica(state))

        row = self.db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM acciones_semaforo"
        ).fetchone()
        self.assertEqual(row["cnt"], 2)
        self.assertEqual(self.db.get_semaforo_state("SEM_C1K1_N"), VERDE)
        self.assertEqual(self.db.get_semaforo_state("SEM_C1K1_S"), VERDE)


class TestReplicationSession(unittest.TestCase):
    """Verifica la persistencia de sesion/secuencia y el dedupe en la replica."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, "db.sqlite"))
        self.db.connect()
        self.db.seed_all(1, 1, ["N", "S", "E", "W"])

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_main_sequence_is_persisted(self):
        from pc3.main_db import MainDBService
        service = object.__new__(MainDBService)
        service.db = self.db
        service.sequence_number = 0
        service.session_id = "session-main"

        self.assertEqual(service._next_sequence(), 1)
        self.assertEqual(service._next_sequence(), 2)
        self.assertEqual(self.db.get_replication_state()["last_sequence"], 2)

    def test_replica_ignores_duplicate_sequence(self):
        from pc2.replica_db import ReplicaDBService
        service = object.__new__(ReplicaDBService)
        service.db = self.db
        service.session_id = "session-main"
        service.last_sequence = 0

        msg = ReplicationMessage(
            tabla="eventos", operacion="INSERT",
            datos={
                "evento_id": "evt-1", "sensor_id": "ESP_C1K1",
                "interseccion_id": "INT_C1K1", "tipo_sensor": "espira",
                "datos": {"vehiculos_por_minuto": 5},
                "timestamp": "2026-01-01T00:00:00Z",
            },
            sequence_number=1,
            session_id="session-main",
        )
        service.apply_replication(msg)
        service.apply_replication(msg)

        self.assertEqual(self.db.get_event_count(), 1)
        self.assertEqual(service.last_sequence, 1)
        self.assertEqual(self.db.get_replication_state()["last_sequence"], 1)

    def test_replica_accepts_new_session_epoch(self):
        from pc2.replica_db import ReplicaDBService
        service = object.__new__(ReplicaDBService)
        service.db = self.db
        service.session_id = "session-old"
        service.last_sequence = 50

        msg = ReplicationMessage(
            tabla="eventos", operacion="INSERT",
            datos={
                "evento_id": "evt-2", "sensor_id": "ESP_C1K1",
                "interseccion_id": "INT_C1K1", "tipo_sensor": "espira",
                "datos": {"vehiculos_por_minuto": 5},
                "timestamp": "2026-01-01T00:00:00Z",
            },
            sequence_number=1,
            session_id="session-new",
        )
        service.apply_replication(msg)

        self.assertEqual(self.db.get_event_count(), 1)
        self.assertEqual(service.session_id, "session-new")
        self.assertEqual(service.last_sequence, 1)
        state = self.db.get_replication_state()
        self.assertEqual(state["session_id"], "session-new")
        self.assertEqual(state["last_sequence"], 1)


class TestPriorityHold(unittest.TestCase):
    """Verifica que un override de prioridad no sea revertido por timers normales."""

    def setUp(self):
        from pc2.analytics_service import AnalyticsService
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, "replica.db"))
        self.db.connect()
        self.db.seed_all(1, 1, ["N", "S", "E", "W"])
        self.db.update_semaforo("SEM_C1K1_N", ROJO, "2026-01-01T00:00:00Z")

        self.service = object.__new__(AnalyticsService)
        self.service.replica_db = self.db
        self.service.intersection_metrics = {
            "INT_C1K1": {"Q": 1, "Vp": 40, "D": 5, "vehiculos_por_minuto": 3}
        }
        self.service._return_lock = threading.RLock()
        self.service._return_timers = {}
        self.service._priority_holds = {}
        self.service._priority_timers = {}
        self.service.priority_hold_seconds = 30
        self.service.use_replica = False
        self.service._failover_lock = threading.RLock()
        self.service._push_socket = _FakePub()
        self.service._light_pub = _FakePub()

    def tearDown(self):
        for timer in self.service._priority_timers.values():
            timer.cancel()
        self.db.close()
        self.tmpdir.cleanup()

    def test_priority_override_cancels_normal_timer_and_sets_hold(self):
        normal_timer = _FakeTimer()
        self.service._return_timers["INT_C1K1"] = normal_timer

        response = self.service._execute_override(
            "SEM_C1K1_N", VERDE, "ambulancia"
        )

        self.assertTrue(response.datos["ejecutado"])
        self.assertTrue(normal_timer.cancelled)
        self.assertNotIn("INT_C1K1", self.service._return_timers)
        self.assertTrue(self.service._is_priority_held("SEM_C1K1_N"))
        self.assertIn("SEM_C1K1_N", self.service._priority_timers)

    def test_normal_return_not_scheduled_during_priority_hold(self):
        self.service._priority_holds["SEM_C1K1_N"] = time.time() + 60

        self.service._schedule_normal_return(1, 1, self.service._light_pub)

        self.assertNotIn("INT_C1K1", self.service._return_timers)

    def test_priority_expiry_reverts_to_red_and_clears_hold(self):
        self.db.update_semaforo("SEM_C1K1_N", VERDE, "2026-01-01T00:00:01Z")
        self.service._priority_holds["SEM_C1K1_N"] = time.time() + 60
        self.service._priority_timers["SEM_C1K1_N"] = _FakeTimer()

        self.service._revert_priority(1, 1, "SEM_C1K1_N")

        self.assertFalse(self.service._is_priority_held("SEM_C1K1_N"))
        self.assertTrue(any('"ROJO"' in msg for msg in self.service._light_pub.messages))
        self.assertTrue(any('"ROJO"' in msg for msg in self.service._push_socket.messages))


class TestDatabase(unittest.TestCase):
    """Test database operations."""

    def setUp(self):
        """Crear una base de datos de prueba temporal."""
        self.db_path = os.path.join(os.path.dirname(__file__), "test_temp.db")
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.seed_all(2, 2, ["N", "S"])

    def tearDown(self):
        """Limpiar la base de datos de prueba."""
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
        self.assertEqual(rows["cnt"], 8)  # 2x2x2 direcciones = 8

    def test_insert_event(self):
        self.db.insert_event("evt-1", "ESP_C1K1", "INT_C1K1", "espira",
                             {"vehiculos_por_minuto": 10}, "2026-01-01T00:00:00Z")
        count = self.db.get_event_count()
        self.assertEqual(count, 1)

    def test_insert_event_stores_sensor_timestamp(self):
        self.db.insert_event(
            "evt-ts", "ESP_C1K1", "INT_C1K1", "espira",
            {"vehiculos_por_minuto": 10}, "2026-01-01T00:00:05Z",
            timestamp_sensor="2026-01-01T00:00:00Z",
        )
        row = self.db.conn.execute(
            "SELECT timestamp, timestamp_sensor FROM eventos WHERE evento_id = 'evt-ts'"
        ).fetchone()
        self.assertEqual(row["timestamp"], "2026-01-01T00:00:05Z")
        self.assertEqual(row["timestamp_sensor"], "2026-01-01T00:00:00Z")

    def test_schema_has_timestamp_sensor_column(self):
        columns = {
            row["name"]
            for row in self.db.conn.execute("PRAGMA table_info(eventos)")
        }
        self.assertIn("timestamp_sensor", columns)

    def test_schema_has_outbox_and_replication_state(self):
        tables = {
            row["name"]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertIn("failover_outbox", tables)
        self.assertIn("replication_state", tables)

    def test_traffic_state_message_id_is_idempotent(self):
        for _ in range(2):
            self.db.insert_traffic_state(
                "INT_C1K1", 1, 40, 5, 3, NORMAL, "2026-01-01T00:00:00Z",
                message_id="msg-1",
            )
        row = self.db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM estado_trafico WHERE message_id = 'msg-1'"
        ).fetchone()
        self.assertEqual(row["cnt"], 1)

    def test_outbox_dedupes_by_message_id(self):
        self.assertTrue(self.db.enqueue_outbox(
            "out-1", "estado_trafico", "INSERT", {"interseccion_id": "INT_C1K1"}
        ))
        self.assertFalse(self.db.enqueue_outbox(
            "out-1", "estado_trafico", "INSERT", {"interseccion_id": "INT_C1K1"}
        ))
        self.assertEqual(len(self.db.get_pending_outbox()), 1)

        self.db.mark_outbox_sent("out-1")
        self.assertEqual(len(self.db.get_pending_outbox()), 0)

    def test_replication_state_roundtrip(self):
        self.assertEqual(self.db.get_replication_state()["last_sequence"], 0)
        self.db.set_replication_state(session_id="session-a", last_sequence=42)
        state = self.db.get_replication_state()
        self.assertEqual(state["session_id"], "session-a")
        self.assertEqual(state["last_sequence"], 42)

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
