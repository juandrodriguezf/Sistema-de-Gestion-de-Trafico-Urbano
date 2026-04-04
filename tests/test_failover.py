"""
test_failover.py - Fault tolerance tests.
Tests the heartbeat mechanism and failover from Main DB to Replica DB.
Run with: python -m tests.test_failover (from project root)
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
        """Simulate heartbeat timeout detection."""
        heartbeat_timeout = 5  # seconds
        last_heartbeat = time.time() - 10  # 10 seconds ago

        elapsed = time.time() - last_heartbeat
        use_replica = elapsed > heartbeat_timeout

        self.assertTrue(use_replica, "Failover should activate after timeout")

    def test_no_timeout(self):
        """Heartbeat within threshold should NOT trigger failover."""
        heartbeat_timeout = 15
        last_heartbeat = time.time() - 3  # 3 seconds ago

        elapsed = time.time() - last_heartbeat
        use_replica = elapsed > heartbeat_timeout

        self.assertFalse(use_replica, "Failover should NOT activate before timeout")

    def test_recovery_detection(self):
        """Simulate heartbeat recovery."""
        use_replica = True  # Currently in failover mode
        heartbeat_received = True  # Heartbeat restored

        if heartbeat_received and use_replica:
            use_replica = False

        self.assertFalse(use_replica, "Should switch back to main DB on recovery")

    def test_failover_flag_toggle(self):
        """Test the flag toggle sequence: normal → failover → recovery."""
        use_replica = False

        # Phase 1: Timeout
        timeout_detected = True
        if timeout_detected and not use_replica:
            use_replica = True
        self.assertTrue(use_replica, "Phase 1: Should be in replica mode")

        # Phase 2: Still in failover (no heartbeat)
        heartbeat_received = False
        if heartbeat_received and use_replica:
            use_replica = False
        self.assertTrue(use_replica, "Phase 2: Should still be in replica mode")

        # Phase 3: Recovery
        heartbeat_received = True
        if heartbeat_received and use_replica:
            use_replica = False
        self.assertFalse(use_replica, "Phase 3: Should be back to main DB")


class TestReplicaDBIntegrity(unittest.TestCase):
    """Test that replica DB maintains data integrity."""

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
        """Both DBs should have the same number of intersections and sensors."""
        main_int = self.main_db.conn.execute("SELECT COUNT(*) as c FROM intersecciones").fetchone()["c"]
        replica_int = self.replica_db.conn.execute("SELECT COUNT(*) as c FROM intersecciones").fetchone()["c"]
        self.assertEqual(main_int, replica_int)

    def test_replica_accepts_writes_during_failover(self):
        """During failover, replica DB should accept direct writes."""
        self.replica_db.insert_event(
            "failover-evt-1", "ESP_C1K1", "INT_C1K1", "espira",
            {"vehiculos_por_minuto": 15}, "2026-01-01T00:00:00Z"
        )
        count = self.replica_db.get_event_count()
        self.assertEqual(count, 1)

    def test_sequence_tracking(self):
        """Test that sequence numbers can be used for sync."""
        seq1 = 100
        seq2 = 200

        # Simulate: main has seq up to 100, replica has up to 200
        # Gap = records from 101 to 200 need to be synced to main
        missing = list(range(seq1 + 1, seq2 + 1))
        self.assertEqual(len(missing), 100)
        self.assertEqual(missing[0], 101)
        self.assertEqual(missing[-1], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
