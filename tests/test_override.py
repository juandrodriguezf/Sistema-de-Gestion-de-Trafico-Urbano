"""
test_override.py - Override manual: parseo de semaforo_id y publicacion LightAction desde Analytics.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.constants import (
    parse_semaforo_id,
    ORIGIN_MONITORING,
    REASON_MANUAL,
    REASON_PRIORITY,
)
from shared.models import LightAction
from pc2.analytics_service import AnalyticsService


class TestParseSemaforoId(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_semaforo_id("SEM_C1K2_N"), (1, 2, "N"))
        self.assertEqual(parse_semaforo_id("SEM_C10K3_W"), (10, 3, "W"))

    def test_invalid(self):
        self.assertIsNone(parse_semaforo_id("SEM_C1K2_X"))
        self.assertIsNone(parse_semaforo_id("INT_C1K1"))
        self.assertIsNone(parse_semaforo_id(""))


class TestExecuteOverride(unittest.TestCase):
    """_execute_override publica ZMQ y hace PUSH sin levantar red."""

    def _make_service(self):
        config = {
            "grid": {"columns": 2, "rows": 2},
            "thresholds": {"Q_MAX": 5, "VP_MIN": 35, "D_MAX": 20},
            "zmq_ports": {},
            "auth_tokens": {"monitoring": "tok", "sensors_prefix": "p-"},
        }
        svc = AnalyticsService(config)
        svc.replica_db = MagicMock()
        svc.replica_db.get_semaforo_state.return_value = "ROJO"
        svc._light_pub = MagicMock()
        svc._push_socket = MagicMock()
        svc.use_replica = False
        return svc

    def test_publishes_light_action_and_push(self):
        svc = self._make_service()
        resp = svc._execute_override("SEM_C1K1_N", "VERDE", "manual")
        self.assertEqual(resp.tipo, "RESPUESTA")
        self.assertTrue(resp.datos.get("ejecutado"))

        svc._light_pub.send_string.assert_called_once()
        sent = svc._light_pub.send_string.call_args[0][0]
        self.assertTrue(sent.startswith("semaforo/cambio/C1K1 "))
        _, payload = sent.split(" ", 1)
        la = LightAction.from_json(payload)
        self.assertEqual(la.semaforo_id, "SEM_C1K1_N")
        self.assertEqual(la.nuevo_estado, "VERDE")
        self.assertEqual(la.origen, ORIGIN_MONITORING)
        self.assertEqual(la.razon, REASON_MANUAL)

        svc._push_socket.send_string.assert_called_once()
        pushed = svc._push_socket.send_string.call_args[0][0]
        self.assertIn("prioridad", pushed)
        self.assertIn("SEM_C1K1_N", pushed)

    def test_ambulancia_usa_razon_prioridad(self):
        svc = self._make_service()
        resp = svc._execute_override("SEM_C1K1_E", "VERDE", "paso ambulancia")
        self.assertEqual(resp.tipo, "RESPUESTA")
        sent = svc._light_pub.send_string.call_args[0][0]
        la = LightAction.from_json(sent.split(" ", 1)[1])
        self.assertEqual(la.razon, REASON_PRIORITY)

    def test_semaforo_id_invalido(self):
        svc = self._make_service()
        resp = svc._execute_override("no_valido", "VERDE", "x")
        self.assertEqual(resp.tipo, "ERROR")
        svc._light_pub.send_string.assert_not_called()

    def test_sin_sockets_inicializados(self):
        config = {
            "grid": {"columns": 2, "rows": 2},
            "thresholds": {"Q_MAX": 5, "VP_MIN": 35, "D_MAX": 20},
            "zmq_ports": {},
            "auth_tokens": {"monitoring": "tok", "sensors_prefix": "p-"},
        }
        svc = AnalyticsService(config)
        svc.replica_db = MagicMock()
        resp = svc._execute_override("SEM_C1K1_N", "VERDE", "manual")
        self.assertEqual(resp.tipo, "ERROR")


if __name__ == "__main__":
    unittest.main()
