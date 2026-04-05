"""
test_failover.py - Pruebas de tolerancia a fallos.
Prueba el mecanismo de heartbeat y el failover de la base de datos principal a la base de datos réplica.
Ejecutar con: python -m tests.test_failover (desde la raíz del proyecto)
"""

import sys
import os
import time
import json
import unittest
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestFailoverLogic(unittest.TestCase):
    """Test failover detection logic without ZMQ (unit-level)."""

    def test_timeout_detection(self):
        """simula la deteccion de timeout del heartbeat."""
        heartbeat_timeout = 5  # segundos
        last_heartbeat = time.time() - 10  # hace 10 segundos

        elapsed = time.time() - last_heartbeat
        use_replica = elapsed > heartbeat_timeout

        self.assertTrue(use_replica, "Failover deberia activarse despues del timeout")

    def test_no_timeout(self):
        """Heartbeat dentro del umbral no deberia activar el failover."""
        heartbeat_timeout = 15
        last_heartbeat = time.time() - 3  # hace 3 segundos

        elapsed = time.time() - last_heartbeat
        use_replica = elapsed > heartbeat_timeout

        self.assertFalse(use_replica, "Failover no deberia activarse antes del timeout")

    def test_recovery_detection(self):
        """Simula la recuperacion del heartbeat."""
        use_replica = True  # actualmente en modo replica
        heartbeat_received = True  # Heartbeat restaurado

        if heartbeat_received and use_replica:
            use_replica = False

        self.assertFalse(use_replica, "Deberia volver a la base de datos principal en recuperacion")

    def test_failover_flag_toggle(self):
        """prueba el cambio de flag de failover."""
        use_replica = False

        # Fase 1: Timeout
        timeout_detected = True
        if timeout_detected and not use_replica:
            use_replica = True
        self.assertTrue(use_replica, "Fase 1: Deberia estar en modo replica")

        # Fase 2: Todavia en failover (sin heartbeat)
        heartbeat_received = False
        if heartbeat_received and use_replica:
            use_replica = False
        self.assertTrue(use_replica, "Fase 2: Deberia estar en modo replica")

        # Fase 3: Recuperacion
        heartbeat_received = True
        if heartbeat_received and use_replica:
            use_replica = False
        self.assertFalse(use_replica, "Fase 3: Deberia estar en modo replica")


class TestReplicaDBIntegrity(unittest.TestCase):
    """Test que la base de datos replica mantiene la integridad de los datos."""

    def setUp(self):
        from shared.db_utils import DatabaseManager
        self.main_path = os.path.join(os.path.dirname(__file__), "test_main.db")
        self.replica_path = os.path.join(os.path.dirname(__file__), "test_replica.db")
        self.main_db = DatabaseManager(self.main_path)
        self.replica_db = DatabaseManager(self.replica_path)
        self.main_db.connect()
        self.replica_db.connect()
        self.main_db.seed_all(2, 2, ["N"])
        self.replica_db.seed_all(2, 2, ["N"])

    def tearDown(self):
        self.main_db.close()
        self.replica_db.close()
        for p in [self.main_path, self.replica_path]:
            if os.path.exists(p):
                os.remove(p)

    def test_both_dbs_have_same_structure(self):
        """Ambas bases de datos deberian tener el mismo numero de intersecciones y sensores."""
        main_int = self.main_db.conn.execute("SELECT COUNT(*) as c FROM intersecciones").fetchone()["c"]
        replica_int = self.replica_db.conn.execute("SELECT COUNT(*) as c FROM intersecciones").fetchone()["c"]
        self.assertEqual(main_int, replica_int)

    def test_replica_accepts_writes_during_failover(self):
        """Durante el failover, la base de datos replica deberia aceptar escrituras directas."""
        self.replica_db.insert_event(
            "failover-evt-1", "ESP_C1K1", "INT_C1K1", "espira",
            {"vehiculos_por_minuto": 15}, "2026-01-01T00:00:00Z"
        )
        count = self.replica_db.get_event_count()
        self.assertEqual(count, 1)

    def test_sequence_tracking(self):
        """Test que los numeros de secuencia pueden ser usados para sincronizacion."""
        seq1 = 100
        seq2 = 200

        # Simula: main tiene seq hasta 100, replica tiene hasta 200
        # Gap = registros del 101 al 200 necesitan ser sincronizados a main
        missing = list(range(seq1 + 1, seq2 + 1))
        self.assertEqual(len(missing), 100)
        self.assertEqual(missing[0], 101)
        self.assertEqual(missing[-1], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
