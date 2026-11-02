"""
integration_failover_recovery.py - Prueba de integracion del ciclo failover + recuperacion.

Simula sin ZMQ:
  1. MainDB persiste y replica estados normales.
  2. MainDB cae; Analytics escribe directo en la replica y encola el outbox.
  3. MainDB vuelve; el outbox se reconcilia por lotes.
  4. Main y replica quedan consistentes y el replay es idempotente.

Ejecutar con: python -m tests.integration_failover_recovery
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.db_utils import DatabaseManager
from shared.models import ResyncBatch, TrafficState
from shared.constants import CONGESTION, NORMAL, ROJO, VERDE


class _FakePub:
    def __init__(self):
        self.messages = []

    def send_string(self, msg, flags=0):
        self.messages.append(msg)


def _main_service(db, session_id="session-integration"):
    from pc3.main_db import MainDBService
    service = object.__new__(MainDBService)
    service.db = db
    service.sequence_number = 0
    service.session_id = session_id
    return service


def _replica_service(db):
    from pc2.replica_db import ReplicaDBService
    service = object.__new__(ReplicaDBService)
    service.db = db
    service.session_id = ""
    service.last_sequence = 0
    return service


def _analytics_service(replica_db):
    from pc2.analytics_service import AnalyticsService
    service = object.__new__(AnalyticsService)
    service.replica_db = replica_db
    return service


def _state(message_id, event_id, estado, accion_anterior, accion_nueva):
    return TrafficState(
        interseccion="INT_C1K1",
        estado=estado,
        metricas={"Q": 7, "Vp": 20, "D": 25, "vehiculos_por_minuto": 5},
        original_event_id=event_id,
        original_sensor_id="ESP_C1K1",
        original_tipo_sensor="espira",
        original_datos=json.dumps({"vehiculos_por_minuto": 5}),
        original_timestamp="2026-01-01T00:00:00Z",
        message_id=message_id,
        acciones_tomadas=[{
            "tipo": "CAMBIO_LUZ",
            "semaforo_id": "SEM_C1K1_N",
            "estado_anterior": accion_anterior,
            "estado_nuevo": accion_nueva,
            "razon": "congestion_detectada",
            "origen": "analytics",
        }],
    )


def _snapshot(db):
    def count(table):
        return db.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]

    semaforos = {
        row["semaforo_id"]: row["estado_actual"]
        for row in db.conn.execute("SELECT semaforo_id, estado_actual FROM semaforos")
    }
    return {
        "eventos": count("eventos"),
        "estado_trafico": count("estado_trafico"),
        "acciones_semaforo": count("acciones_semaforo"),
        "semaforos": semaforos,
    }


def _replicate(main_service, replica_service, state, rep_pub):
    main_service.process_traffic_state(state, rep_pub)
    from shared.models import ReplicationMessage
    for raw in rep_pub.messages:
        payload = raw.split(" ", 1)[1]
        replica_service.apply_replication(ReplicationMessage.from_json(payload))
    rep_pub.messages.clear()


def _reconcile(main_service, replica_db, analytics_service):
    pending = replica_db.get_pending_outbox(limit=1000)
    mensajes = [{
        "message_id": row["message_id"],
        "tabla": row["tabla"],
        "operacion": row["operacion"],
        "datos": json.loads(row["datos"]),
    } for row in pending]
    batch = ResyncBatch(mensajes=mensajes)
    response = main_service.process_resync_batch(batch)
    for row in pending:
        replica_db.mark_outbox_sent(row["message_id"])
    return response, batch


def run_integration() -> bool:
    with tempfile.TemporaryDirectory() as tmpdir:
        main_db = DatabaseManager(os.path.join(tmpdir, "main.db"))
        replica_db = DatabaseManager(os.path.join(tmpdir, "replica.db"))
        main_db.connect()
        replica_db.connect()
        main_db.seed_all(1, 1, ["N", "S", "E", "W"])
        replica_db.seed_all(1, 1, ["N", "S", "E", "W"])

        main_service = _main_service(main_db)
        replica_service = _replica_service(replica_db)
        analytics_service = _analytics_service(replica_db)
        rep_pub = _FakePub()

        # 1. Operacion normal: MainDB escribe y replica aplica SYNC
        _replicate(
            main_service, replica_service,
            _state("state-1", "evt-1", CONGESTION, VERDE, ROJO), rep_pub,
        )
        _replicate(
            main_service, replica_service,
            _state("state-2", "evt-2", NORMAL, ROJO, VERDE), rep_pub,
        )
        assert _snapshot(main_db) == _snapshot(replica_db), "main y replica divergen en operacion normal"
        print("OK  operacion normal: main y replica consistentes")

        # 2. Failover: MainDB no recibe; Analytics escribe en replica y encola outbox
        failover_state = _state("state-3", "evt-3", CONGESTION, VERDE, ROJO)
        assert analytics_service._persist_to_replica(failover_state)
        assert main_db.get_event_count() == replica_db.get_event_count() - 1
        pending = replica_db.get_pending_outbox()
        assert len(pending) == 4, f"outbox esperado=4, obtenido={len(pending)}"
        print(f"OK  failover: {len(pending)} mensajes en outbox, main queda atras")

        # 3. Recuperacion: reconciliar outbox contra MainDB
        response, batch = _reconcile(main_service, replica_db, analytics_service)
        assert response.errores == 0, f"resync con errores: {response.mensaje}"
        assert _snapshot(main_db) == _snapshot(replica_db), "main y replica divergen tras resync"
        assert not replica_db.get_pending_outbox(), "outbox deberia quedar vacio"
        print(
            f"OK  recuperacion: aplicados={response.aplicados} "
            f"duplicados={response.duplicados}"
        )

        # 4. Idempotencia: reenviar el mismo lote no duplica datos
        before = _snapshot(main_db)
        second = main_service.process_resync_batch(batch)
        assert second.aplicados == 0, "replay no deberia aplicar mensajes nuevos"
        assert second.duplicados == len(batch.mensajes)
        assert _snapshot(main_db) == before, "replay altero el estado"
        print(f"OK  idempotencia: {second.duplicados} duplicados ignorados")

        # 5. Secuencia persistida en ambos lados
        main_seq = main_db.get_replication_state()["last_sequence"]
        replica_seq = replica_db.get_replication_state()["last_sequence"]
        assert main_seq > 0 and replica_seq > 0
        print(f"OK  secuencias persistidas: main={main_seq} replica={replica_seq}")

        main_db.close()
        replica_db.close()
    return True


def test_failover_recovery_consistency():
    assert run_integration()


if __name__ == "__main__":
    try:
        run_integration()
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
    print("\nINTEGRACION FAILOVER/RECUPERACION: PASS")
