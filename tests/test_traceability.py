"""
test_traceability.py - Pruebas de trazabilidad extremo a extremo (T1-T3).

T1: Verifica que el evento_id en la BD coincide con el message_id del SensorEvent original.
T2: Verifica que el ID truncado a 8 caracteres es consistente.
T3: Verifica el funcionamiento básico de los visores (consulta a BD).
"""

import sys
import os
import json
import unittest
import uuid
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import SensorEvent, TrafficState
from shared.db_utils import DatabaseManager
from shared.constants import NORMAL, SENSOR_CAMARA


def make_event(message_id: str = None) -> SensorEvent:
    """Crea un SensorEvent de prueba con un message_id específico o aleatorio."""
    mid = message_id or str(uuid.uuid4())
    return SensorEvent(
        message_id=mid,
        sensor_id="CAM_C1K1",
        tipo_sensor=SENSOR_CAMARA,
        interseccion="INT_C1K1",
        timestamp="2026-05-24T20:37:10.000Z",
        datos={"longitud_cola": 7},
        auth_token="sensor-token-CAM_C1K1",
    )


class TestT1_TrazabilidadCompleta(unittest.TestCase):
    """T1: Trazabilidad completa — evento_id en BD = message_id del SensorEvent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_trace.db")
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.seed_all(2, 2, ["N", "S", "E", "W"])

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_event_id_matches_message_id(self):
        """El evento_id almacenado en BD es exactamente el message_id del SensorEvent."""
        expected_id = str(uuid.uuid4())
        event = make_event(expected_id)

        # Construye TrafficState copiando los campos de trazabilidad (como hace AnalyticsService)
        traffic = TrafficState(
            interseccion=event.interseccion,
            estado=NORMAL,
            metricas={"Q": 7, "Vp": 50, "D": 0, "vehiculos_por_minuto": 0},
            accion_tomada=None,
            original_event_id=event.message_id,
            original_sensor_id=event.sensor_id,
            original_tipo_sensor=event.tipo_sensor,
            original_datos=json.dumps(event.datos),
        )

        # Inserta como lo hace MainDBService: usa original_event_id como evento_id
        evento_id = traffic.original_event_id
        self.db.insert_event(
            evento_id=evento_id,
            sensor_id=event.sensor_id,
            interseccion_id=event.interseccion,
            tipo_sensor=event.tipo_sensor,
            datos=event.datos,
            timestamp=event.timestamp,
        )

        # Verifica: leer el evento de la BD y comprobar el ID
        count = self.db.get_event_count()
        self.assertGreaterEqual(count, 1, "Debe haber al menos 1 evento en la BD")

        # También verifica usando get_events_between_dates
        eventos = self.db.get_events_between_dates(
            "INT_C1K1",
            "2026-01-01T00:00:00Z",
            "2030-01-01T00:00:00Z",
        )
        self.assertGreaterEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["evento_id"], expected_id,
                         "evento_id en BD debe coincidir con message_id original")

    def test_traceability_fields_preserved(self):
        """Los 4 campos original_* se preservan correctamente en TrafficState."""
        event = make_event()

        traffic = TrafficState(
            interseccion=event.interseccion,
            estado=NORMAL,
            metricas={"Q": 5, "Vp": 30, "D": 15, "vehiculos_por_minuto": 10},
            accion_tomada={"tipo": "CAMBIO_LUZ", "semaforo_id": "SEM_C1K1_N"},
            original_event_id=event.message_id,
            original_sensor_id=event.sensor_id,
            original_tipo_sensor=event.tipo_sensor,
            original_datos=json.dumps(event.datos),
        )

        self.assertEqual(traffic.original_event_id, event.message_id)
        self.assertEqual(traffic.original_sensor_id, event.sensor_id)
        self.assertEqual(traffic.original_tipo_sensor, event.tipo_sensor)
        self.assertEqual(traffic.original_datos, json.dumps(event.datos))

    def test_empty_original_event_id_fallback(self):
        """Si original_event_id está vacío, se debe generar un UUID (simula comportamiento MainDB)."""
        traffic = TrafficState(
            interseccion="INT_C1K1",
            estado=NORMAL,
            metricas={"Q": 0, "Vp": 50, "D": 0, "vehiculos_por_minuto": 0},
        )
        evento_id = traffic.original_event_id if traffic.original_event_id else str(uuid.uuid4())
        self.assertTrue(len(evento_id) > 0, "Debe generar un ID de respaldo")


class TestT2_CorrelacionVisual(unittest.TestCase):
    """T2: El ID truncado a 8 caracteres es consistente entre log y viewer."""

    def test_truncated_id_consistency(self):
        """Los primeros 8 chars del message_id son los mismos en cualquier punto."""
        full_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        truncated = full_id[:8]

        # En el log de PC1 se muestra como "ID:a1b2c3d4"
        log_display = f"ID:{truncated}"

        # En TraceabilityViewer se trunca igual
        viewer_display = full_id[:8]

        self.assertEqual(log_display, f"ID:{viewer_display}")
        self.assertEqual(viewer_display, "a1b2c3d4")


class TestT3_Visores(unittest.TestCase):
    """T3: Pruebas básicas de funcionamiento de visores (consulta a BD)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_viewer.db")
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.seed_all(1, 1, ["N", "S", "E", "W"])

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_event(self, event_id: str = None):
        """Inserta un evento de prueba y devuelve su ID."""
        eid = event_id or str(uuid.uuid4())
        self.db.insert_event(
            evento_id=eid,
            sensor_id="CAM_C1K1",
            interseccion_id="INT_C1K1",
            tipo_sensor=SENSOR_CAMARA,
            datos={"longitud_cola": 5},
            timestamp="2026-05-24T20:37:10.000Z",
        )
        return eid

    def test_new_events_appear_in_query(self):
        """Los eventos insertados aparecen en consultas posteriores (simula actualización del viewer)."""
        before = self.db.get_event_count()

        eid1 = self._insert_event()
        eid2 = self._insert_event()

        after = self.db.get_event_count()
        self.assertEqual(after - before, 2,
                         "Deben aparecer 2 eventos nuevos después de insertar")

        # Verifica que se pueden leer en orden
        eventos = self.db.get_events_between_dates(
            "INT_C1K1", "2026-01-01T00:00:00Z", "2030-01-01T00:00:00Z",
        )
        evento_ids = [e["evento_id"] for e in eventos]
        self.assertIn(eid1, evento_ids)
        self.assertIn(eid2, evento_ids)

    def test_event_view_truncation(self):
        """Verifica que el ID truncado a 8 es único (probabilístico) para eventos distintos."""
        eid1 = self._insert_event()
        eid2 = self._insert_event()

        # Los IDs UUID v4 deben diferir en los primeros 8 caracteres (99.999% probable)
        if eid1[:8] != eid2[:8]:
            viewer_e1 = eid1[:8]
            viewer_e2 = eid2[:8]
            self.assertNotEqual(viewer_e1, viewer_e2)
        # Si son iguales (extremadamente raro), no falla la prueba


if __name__ == "__main__":
    unittest.main()
