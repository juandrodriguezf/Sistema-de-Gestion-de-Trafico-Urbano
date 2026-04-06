"""
Smoke test: MainDB (PC3) -> start_pc2 -> start_pc1, luego REQ a Analytics.
Ejecutar desde la raiz: python tests/integration_stack_smoke.py
No forma parte de pytest por defecto (evita paralelismo con otros tests).
"""

import json
import os
import subprocess
import sys
import time

import zmq

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from shared.models import MonitoringRequest, MonitoringResponse
from shared.constants import CMD_CONSULTA, CMD_ESTADO_GENERAL, CMD_OVERRIDE


def load_config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_config()
    ports = cfg["zmq_ports"]
    pc2 = cfg.get("pc2_host", "localhost")
    token = cfg.get("auth_tokens", {}).get("monitoring", "")

    py = sys.executable
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # No usar PIPE: el volumen de logs de broker/sensores llena el buffer y bloquea hijos.
    out = subprocess.DEVNULL

    print("[smoke] Iniciando MainDB (PC3)...")
    main_db = subprocess.Popen(
        [py, os.path.join(ROOT, "pc3", "main_db.py")],
        cwd=ROOT,
        stdout=out,
        stderr=out,
        env=env,
    )
    time.sleep(3)

    print("[smoke] Iniciando PC2 (launcher)...")
    pc2_launch = subprocess.Popen(
        [py, os.path.join(ROOT, "pc2", "start_pc2.py")],
        cwd=ROOT,
        stdout=out,
        stderr=out,
        env=env,
    )
    time.sleep(6)

    print("[smoke] Iniciando PC1 (launcher)...")
    pc1_launch = subprocess.Popen(
        [py, os.path.join(ROOT, "pc1", "start_pc1.py")],
        cwd=ROOT,
        stdout=out,
        stderr=out,
        env=env,
    )
    time.sleep(14)

    errors = []
    addr = f"tcp://{pc2}:{ports['monitoring_to_analytics']}"
    ctx = zmq.Context()

    def req_roundtrip(label: str, request: MonitoringRequest) -> MonitoringResponse:
        """Un socket REQ por peticion evita estados raros REQ/REP en algunos entornos."""
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, 15000)
        sock.setsockopt(zmq.SNDTIMEO, 15000)
        try:
            sock.connect(addr)
            sock.send_string(request.to_json())
            raw = sock.recv_string()
            return MonitoringResponse.from_json(raw)
        finally:
            sock.close(0)

    try:
        print(f"[smoke] REQ {addr} (una conexion por peticion)")
        r1 = MonitoringRequest(tipo=CMD_CONSULTA, consulta=CMD_ESTADO_GENERAL)
        resp = req_roundtrip("g", r1)
        print(f"[smoke] ESTADO_GENERAL: {resp.tipo} {resp.mensaje[:80]}...")
        if resp.tipo == "ERROR":
            errors.append(f"ESTADO_GENERAL: {resp.mensaje}")

        r2 = MonitoringRequest(
            tipo=CMD_OVERRIDE,
            semaforo_id="SEM_C1K1_N",
            nuevo_estado="VERDE",
            motivo="smoke_test",
            auth_token=token,
        )
        resp2 = req_roundtrip("o", r2)
        print(f"[smoke] OVERRIDE: {resp2.tipo} {resp2.mensaje}")
        if resp2.tipo == "ERROR":
            errors.append(f"OVERRIDE: {resp2.mensaje}")

        ctx.term()
    except Exception as e:
        errors.append(f"ZMQ/cliente: {e}")
        print(f"[smoke] EXCEPCION: {e}")
        try:
            ctx.term()
        except Exception:
            pass

    print("[smoke] Deteniendo procesos (arbol)...")
    for proc, name in (
        (pc1_launch, "PC1"),
        (pc2_launch, "PC2"),
        (main_db, "MainDB"),
    ):
        if proc.poll() is not None:
            print(f"[smoke] {name} ya termino (exit={proc.returncode})")
            if proc.returncode not in (0, None):
                errors.append(f"{name} proceso termino prematuramente exit={proc.returncode}")
        else:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                )
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    if errors:
        print("[smoke] FALLOS:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("[smoke] OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
