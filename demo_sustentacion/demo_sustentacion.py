"""
demo_sustentacion.py - Script único para demo de sustentación.
Cronograma en tiempo real:
  t=60s  -> Congestión en C2K2
  t=95s  -> Congestión en C4K3
  t=130s -> Ambulancia fila 1
  t=140s -> Caída BD principal
  t=150s -> Segunda ambulancia fila 1
"""

import zmq
import json
import sys
import os
import time
import threading
import subprocess
import signal
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import SensorEvent, MonitoringRequest
from shared.constants import (
    SENSOR_CAMARA, SENSOR_GPS, SENSOR_ESPIRA,
    COLUMN_LABELS, VERDE, ROJO,
    intersection_id, display_intersection,
)

# ─── Configuración ───

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

config = load_config()
grid = config["grid"]
ports = config["zmq_ports"]
pc1_host = config.get("pc1_host", "localhost")
pc2_host = config.get("pc2_host", "localhost")
auth_prefix = config.get("auth_tokens", {}).get("sensors_prefix", "")
monitor_token = config.get("auth_tokens", {}).get("monitoring", "")

# ─── Utilidades ───

def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(tag: str, msg: str):
    print(f"\033[36m[{now_str()}]\033[0m \033[1m[{tag}]\033[0m {msg}")

# ─── Conexiones ZMQ ───

context = zmq.Context()

# PUB socket -> Broker (para enviar eventos de sensores falsos)
pub_socket = context.socket(zmq.PUB)
pub_socket.connect(f"tcp://{pc1_host}:{ports['broker_frontend']}")
time.sleep(0.3)

# REQ socket -> Analytics (para overrides de ambulancia)
REQ_TIMEOUT_MS = int(config.get("monitoring_timeout_seconds", 5) * 1000)
REQ_ADDR = f"tcp://{pc2_host}:{ports['monitoring_to_analytics']}"

def _new_req_socket():
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, REQ_TIMEOUT_MS)
    socket.setsockopt(zmq.SNDTIMEO, REQ_TIMEOUT_MS)
    socket.connect(REQ_ADDR)
    return socket

req_socket = _new_req_socket()
time.sleep(0.3)

# ─── Iniciar Replica DB (necesaria para consultas históricas) ───

replica_proc = None

def is_replica_running() -> bool:
    """Detecta si replica_db.py ya esta corriendo (p. ej. lanzado por start_pc2)."""
    try:
        if sys.platform == "win32":
            ps_cmd = (
                'Get-CimInstance Win32_Process '
                '-Filter "Name=\'python.exe\' AND CommandLine LIKE \'%replica_db%\'" '
                '| Select-Object -ExpandProperty ProcessId'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return any(line.strip().isdigit() for line in result.stdout.splitlines())
        result = subprocess.run(
            ["pgrep", "-f", "replica_db.py"], capture_output=True
        )
        return result.returncode == 0
    except Exception:
        return False

def start_replica_db():
    """Inicia replica_db.py en background para que las consultas históricas funcionen."""
    global replica_proc
    if is_replica_running():
        log("INIT", "Replica DB ya esta en ejecucion; no se inicia otra instancia")
        return
    try:
        python = sys.executable
        replica_path = os.path.join(os.path.dirname(__file__), "..", "pc2", "replica_db.py")
        if sys.platform == "win32":
            replica_proc = subprocess.Popen(
                [python, replica_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            replica_proc = subprocess.Popen(
                [python, replica_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        log("INIT", "Replica DB iniciada en background")
        time.sleep(1)
    except Exception as e:
        log("ERROR", f"No se pudo iniciar Replica DB: {e}")
        log("ERROR", "  -> Las consultas históricas (cmd 5) no funcionarán")

# ─── Enviar evento de sensor falso ───

def send_sensor_event(col: int, row: int, sensor_type: str, datos: dict):
    """Envía un evento de sensor al broker para simular datos."""
    prefix_map = {SENSOR_CAMARA: "CAM", SENSOR_GPS: "GPS", SENSOR_ESPIRA: "ESP"}
    sensor_id = f"{prefix_map[sensor_type]}_C{col}K{row}"
    interseccion = f"INT_C{col}K{row}"
    token = auth_prefix + sensor_id

    event = SensorEvent(
        sensor_id=sensor_id,
        tipo_sensor=sensor_type,
        interseccion=interseccion,
        datos=datos,
        auth_token=token,
    )

    topic = f"sensor/{sensor_type}/C{col}K{row}"
    payload = event.to_json()
    message = f"{topic} {payload}"
    pub_socket.send_string(message)

# ─── Enviar override de ambulancia ───

def send_ambulance_override(col: int, row: int):
    """Envía comando OVERRIDE para poner semáforo en VERDE (ambulancia)."""
    sem_id = f"SEM_C{col}K{row}_N"
    req = MonitoringRequest(
        tipo="OVERRIDE",
        semaforo_id=sem_id,
        nuevo_estado=VERDE,
        motivo="ambulancia",
        origen="monitoring_service",
        auth_token=monitor_token,
    )
    global req_socket
    try:
        req_socket.send_string(req.to_json())
        raw = req_socket.recv_string()
    except zmq.error.Again:
        log("AMBULANCIA", "  ! Timeout esperando respuesta de Analytics")
        try:
            req_socket.close(linger=0)
        except Exception:
            pass
        req_socket = _new_req_socket()
        return False
    resp = json.loads(raw)
    return resp.get("tipo", "") == "RESPUESTA"

# ─── Matar proceso main_db.py ───

def kill_main_db():
    """Mata el proceso main_db.py para simular caída de BD principal."""
    try:
        if sys.platform == "win32":
            ps_cmd = (
                'Get-CimInstance Win32_Process '
                '-Filter "Name=\'python.exe\' AND CommandLine LIKE \'%main_db%\'" '
                '| Select-Object -ExpandProperty ProcessId'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.strip().splitlines():
                pid = line.strip()
                if pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F"],
                                   capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                    return True
        else:
            subprocess.run(["pkill", "-f", "main_db.py"], capture_output=True)
            return True
    except Exception as e:
        log("ERROR", f"No se pudo matar main_db: {e}")
        return False

# ─── Eventos de la demo ───

def demo_congestion_b2():
    """t=60s: Congestión en B2"""
    label = display_intersection(2, 2)
    log("CONGESTION", f"Enviando congestión a {label}")
    log("CONGESTION", f"  -> Sensor camara: longitud_cola=15 (umbral=5)")
    send_sensor_event(2, 2, SENSOR_CAMARA, {"longitud_cola": 15})
    time.sleep(0.1)
    log("CONGESTION", f"  -> Sensor GPS: velocidad=8, densidad=35")
    send_sensor_event(2, 2, SENSOR_GPS, {
        "densidad": 35, "velocidad_promedio": 8, "nivel_congestion": "BAJA"
    })
    time.sleep(0.1)
    log("CONGESTION", f"  -> Sensor espira: vehiculos_por_minuto=28")
    send_sensor_event(2, 2, SENSOR_ESPIRA, {"vehiculos_por_minuto": 28})
    log("CONGESTION", f"  -> Analytics debería detectar CONGESTIÓN en {label}")

def demo_congestion_d3():
    """t=95s: Congestión en D3"""
    label = display_intersection(4, 3)
    log("CONGESTION", f"Enviando congestión a {label}")
    log("CONGESTION", f"  -> Sensor camara: longitud_cola=18 (umbral=5)")
    send_sensor_event(4, 3, SENSOR_CAMARA, {"longitud_cola": 18})
    time.sleep(0.1)
    log("CONGESTION", f"  -> Sensor GPS: velocidad=5, densidad=40")
    send_sensor_event(4, 3, SENSOR_GPS, {
        "densidad": 40, "velocidad_promedio": 5, "nivel_congestion": "BAJA"
    })
    time.sleep(0.1)
    log("CONGESTION", f"  -> Sensor espira: vehiculos_por_minuto=29")
    send_sensor_event(4, 3, SENSOR_ESPIRA, {"vehiculos_por_minuto": 29})
    log("CONGESTION", f"  -> Analytics debería detectar CONGESTIÓN en {label}")

def demo_ambulancefila1():
    """t=130s: Ambulancia en fila 1"""
    log("AMBULANCIA", "Ambulancia solicitando paso en fila 1")
    for c in range(1, grid["columns"] + 1):
        label = display_intersection(c, 1)
        sem_display = f"SEM_{label}_N"
        log("AMBULANCIA", f"  -> Override VERDE en {sem_display}")
        ok = send_ambulance_override(c, 1)
        if ok:
            log("AMBULANCIA", f"    [OK] {sem_display} -> VERDE")
        else:
            log("AMBULANCIA", f"    [X] {sem_display} falló")
        time.sleep(0.2)

def demo_kill_db():
    """t=140s: Caída de BD principal"""
    log("FAILOVER", "Matando BD principal (main_db.py)...")
    ok = kill_main_db()
    if ok:
        log("FAILOVER", "  [OK] main_db.py terminado")
        timeout = config.get("heartbeat_timeout_seconds", 8)
        log("FAILOVER", f"  -> Analytics debería cambiar a BD réplica en ~{timeout}s")
        log("FAILOVER", "  -> (heartbeat timeout)")
    else:
        log("FAILOVER", "  [X] No se pudo matar main_db.py")

def demo_ambulancefila1_2():
    """t=150s: Segunda ambulancia en fila 1"""
    log("AMBULANCIA", "Segunda ambulancia solicitando paso en fila 1")
    for c in range(1, grid["columns"] + 1):
        label = display_intersection(c, 1)
        sem_display = f"SEM_{label}_N"
        log("AMBULANCIA", f"  -> Override VERDE en {sem_display}")
        ok = send_ambulance_override(c, 1)
        if ok:
            log("AMBULANCIA", f"    [OK] {sem_display} -> VERDE")
        else:
            log("AMBULANCIA", f"    [X] {sem_display} falló")
        time.sleep(0.2)

def demo_summary():
    """t=160s: Resumen de la demo"""
    b2 = display_intersection(2, 2)
    d3 = display_intersection(4, 3)
    print()
    log("RESUMEN", "=" * 60)
    log("RESUMEN", "Demo de sustentación completada")
    log("RESUMEN", "=" * 60)
    log("RESUMEN", "Eventos ejecutados:")
    log("RESUMEN", f"  t=60s   -> Congestión en {b2}")
    log("RESUMEN", f"  t=95s   -> Congestión en {d3}")
    log("RESUMEN", f"  t=130s  -> Ambulancia fila 1")
    log("RESUMEN", f"  t=140s  -> Caída BD principal (failover a réplica)")
    log("RESUMEN", f"  t=150s  -> Segunda ambulancia fila 1")
    log("RESUMEN", "=" * 60)
    log("RESUMEN", "Puedes hacer consultas desde PC3:")
    log("RESUMEN", f"  1 {b2}     -> Ver estado de {b2}")
    log("RESUMEN", f"  1 {d3}     -> Ver estado de {d3}")
    log("RESUMEN", "  3           -> Listar semáforos (fila 1 debería estar en VERDE)")
    log("RESUMEN", f"  5 {b2}     -> Consulta histórica de {b2}")
    log("RESUMEN", "=" * 60)

# ─── Cronograma ───

def run_demo():
    """Ejecuta la demo completa con cronograma en tiempo real."""
    start_time = time.time()

    # Iniciar Replica DB para que las consultas históricas funcionen
    start_replica_db()

    print()
    print("=" * 60)
    print("  DEMO DE SUSTENTACIÓN — SISTEMA DE TRÁFICO URBANO")
    print("  Grid: 5 columnas (A-E) × 3 filas (1-3)")
    print("  Duración total: ~160 segundos")
    print("=" * 60)
    print()
    log("CRONOGRAMA", "Eventos programados:")
    log("CRONOGRAMA", f"  t=60s   -> Congestión en {display_intersection(2, 2)}")
    log("CRONOGRAMA", f"  t=95s   -> Congestión en {display_intersection(4, 3)}")
    log("CRONOGRAMA", f"  t=130s  -> Ambulancia fila 1")
    log("CRONOGRAMA", f"  t=140s  -> Caída BD principal")
    log("CRONOGRAMA", f"  t=150s  -> Segunda ambulancia fila 1")
    log("CRONOGRAMA", f"  t=160s  -> Resumen")
    print()
    log("INICIO", "Esperando eventos... (Ctrl+C para cancelar)")
    print()

    # Programar eventos con threading.Timer
    timers = []

    def schedule(delay: int, func, name: str):
        def wrapper():
            elapsed = time.time() - start_time
            log(name, f"t={elapsed:.0f}s — Ejecutando {name}")
            func()
        t = threading.Timer(delay, wrapper)
        t.daemon = True
        t.start()
        timers.append(t)

    schedule(60, demo_congestion_b2, "CONGESTION-B2")
    schedule(95, demo_congestion_d3, "CONGESTION-D3")
    schedule(130, demo_ambulancefila1, "AMBULANCIA-1")
    schedule(140, demo_kill_db, "FAILOVER")
    schedule(150, demo_ambulancefila1_2, "AMBULANCIA-2")
    schedule(160, demo_summary, "RESUMEN")

    try:
        while True:
            elapsed = time.time() - start_time
            remaining = 160 - elapsed
            if remaining <= 0:
                break
            # Mostrar progreso cada 30 segundos
            next_event = None
            for delay, name in [(60, f"Congestión {display_intersection(2, 2)}"), (95, f"Congestión {display_intersection(4, 3)}"),
                                (130, "Ambulancia 1"), (140, "Caída BD"),
                                (150, "Ambulancia 2"), (160, "Resumen")]:
                if elapsed < delay:
                    next_event = (delay, name)
                    break
            if next_event:
                wait = next_event[0] - elapsed
                print(f"\r  [{elapsed:5.0f}s] Próximo evento: {next_event[1]} en {wait:.0f}s  ",
                      end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        log("CANCELADO", "Demo interrumpida por el usuario")
        for t in timers:
            t.cancel()
    finally:
        if replica_proc:
            try:
                replica_proc.terminate()
                replica_proc.wait(timeout=3)
            except Exception:
                replica_proc.kill()
        pub_socket.close()
        req_socket.close()
        context.term()

# ─── Punto de entrada ───

if __name__ == "__main__":
    run_demo()
