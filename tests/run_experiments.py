"""
run_experiments.py - Automatiza los experimentos de la Tabla 1.
Ejecuta cada combinación (2 escenarios × 2 diseños) 3 veces y reporta
promedio, desviación estándar, min y max para eventos y latencia.
"""

import subprocess
import sys
import os
import json
import time
import shutil
import zmq
import statistics
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.db_utils import DatabaseManager
from shared.models import MonitoringRequest
from shared.constants import CMD_CONSULTA, CMD_ESTADO_INTERSECCION

PYTHON = sys.executable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
CONFIG_BACKUP_PATH = CONFIG_PATH + ".bak"
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

BASE_CONFIG = {
    "grid": {"columns": 1, "rows": 1},
    "sensor_frequency_seconds": 10,
    "load_generation": "random",
    "thresholds": {"Q_MAX": 5, "VP_MIN": 35, "D_MAX": 20},
    "heartbeat_interval_seconds": 5,
    "heartbeat_timeout_seconds": 15,
    "zmq_ports": {
        "broker_frontend": 5555, "broker_backend": 5556,
        "analytics_to_db": 5557, "analytics_to_lights": 5558,
        "monitoring_to_analytics": 5559, "db_replication": 5560,
        "heartbeat": 5561,
    },
    "pc1_host": "localhost", "pc2_host": "localhost", "pc3_host": "localhost",
    "data_ranges": {
        "vehiculos_por_minuto": {"min": 0, "max": 30},
        "longitud_cola": {"min": 0, "max": 20},
        "velocidad_promedio": {"min": 5, "max": 60},
        "densidad": {"min": 0, "max": 50},
    },
    "congestion_spike_probability": 0.10,
    "auth_tokens": {"sensors_prefix": "sensor-token-", "monitoring": "monitor-token-admin-2026"},
    "logging": {"level": "INFO", "file": "data/system.log"},
}

SCENARIOS = [
    {"name": "1sensor_10s", "grid": {"columns": 1, "rows": 1}, "frequency": 10, "desc": "1 sensor c/u @10s"},
    {"name": "2sensores_5s", "grid": {"columns": 1, "rows": 2}, "frequency": 5, "desc": "2 sensores c/u @5s"},
]

BROKER_TYPES = [
    {"name": "original", "script": "broker.py", "desc": "zmq.proxy()"},
    {"name": "threaded", "script": "broker_threaded.py", "desc": "multihilos"},
]

NUM_RUNS = 3
DURATION_SECONDS = 120
WARMUP_SECONDS = 15


def backup_config():
    if os.path.exists(CONFIG_PATH):
        shutil.copy2(CONFIG_PATH, CONFIG_BACKUP_PATH)


def restore_config():
    if os.path.exists(CONFIG_BACKUP_PATH):
        shutil.move(CONFIG_BACKUP_PATH, CONFIG_PATH)


def write_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


def clean_db():
    for f in os.listdir(DATA_DIR):
        if f.endswith(".db") or f.endswith(".db-journal") or f.endswith(".db-wal") or f.endswith(".db-shm"):
            try:
                os.remove(os.path.join(DATA_DIR, f))
            except PermissionError:
                pass


def kill_process_tree(proc, name=""):
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def wait_for_ports_free(ports: list, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5
            )
        except Exception:
            time.sleep(1)
            continue
        busy = []
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                local_addr = parts[1]
                port_part = local_addr.rsplit(":", 1)[-1]
                if port_part.isdigit() and int(port_part) in ports:
                    busy.append(port_part)
        if not busy:
            return True
        time.sleep(0.5)
    return False


def count_db_events() -> int:
    db_path = os.path.join(DATA_DIR, "main_traffic.db")
    if not os.path.exists(db_path):
        return 0
    try:
        db = DatabaseManager(db_path)
        db.connect()
        count = db.get_event_count()
        db.close()
        return count
    except Exception:
        return 0


def measure_override_latency(monitoring_port: int) -> float:
    """Mide tiempo de REQ/REP del override (Monitoreo → Analytics → PUB → respuesta)."""
    try:
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.connect(f"tcp://localhost:{monitoring_port}")
        req = MonitoringRequest(
            tipo="OVERRIDE",
            semaforo_id="SEM_C1K1_N",
            nuevo_estado="VERDE",
            motivo="experimento",
            origen="monitoring_service",
            auth_token=BASE_CONFIG["auth_tokens"]["monitoring"],
        )
        start = time.perf_counter()
        sock.send_string(req.to_json())
        sock.recv_string()
        elapsed = time.perf_counter() - start
        sock.close()
        ctx.term()
        return elapsed
    except Exception as e:
        print(f"    Error midiendo latencia: {e}")
        return -1.0


def start_process(script_path, label, procs):
    p = subprocess.Popen(
        [PYTHON, script_path],
        cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    procs.append((label, p))
    return p


def run_single(scenario: dict, broker: dict) -> dict:
    """Ejecuta una sola corrida de un escenario × broker y devuelve resultados."""
    print(f"    Corrida en progreso...")
    clean_db()

    cfg = dict(BASE_CONFIG)
    cfg["grid"] = scenario["grid"]
    cfg["sensor_frequency_seconds"] = scenario["frequency"]
    write_config(cfg)

    procs = []

    # 1. PC3: MainDB
    print("      Iniciando MainDB...")
    start_process(os.path.join(PROJECT_ROOT, "pc3", "main_db.py"), "MainDB", procs)
    time.sleep(2)

    # 2. PC3: ReplicaDB
    print("      Iniciando ReplicaDB...")
    start_process(os.path.join(PROJECT_ROOT, "pc2", "replica_db.py"), "ReplicaDB", procs)
    time.sleep(1)

    # 3. PC2: Analytics
    print("      Iniciando Analytics...")
    start_process(os.path.join(PROJECT_ROOT, "pc2", "analytics_service.py"), "Analytics", procs)
    time.sleep(1)

    # 4. PC2: TrafficLights
    print("      Iniciando TrafficLights...")
    start_process(os.path.join(PROJECT_ROOT, "pc2", "traffic_light_controller.py"), "TrafficLights", procs)
    time.sleep(1)

    # 5. PC1: Broker
    print("      Iniciando Broker...")
    broker_script = os.path.join(PROJECT_ROOT, "pc1", broker["script"])
    start_process(broker_script, "Broker", procs)
    time.sleep(1)

    # 6. PC1: Sensores
    grid = scenario["grid"]
    sensor_scripts = {
        "espira": os.path.join(PROJECT_ROOT, "pc1", "sensor_espira.py"),
        "camara": os.path.join(PROJECT_ROOT, "pc1", "sensor_camara.py"),
        "gps": os.path.join(PROJECT_ROOT, "pc1", "sensor_gps.py"),
    }
    broker_port = cfg["zmq_ports"]["broker_frontend"]
    for c in range(1, grid["columns"] + 1):
        for r in range(1, grid["rows"] + 1):
            for _, script in sensor_scripts.items():
                p = subprocess.Popen(
                    [PYTHON, script, str(c), str(r), "localhost", str(broker_port)],
                    cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                procs.append(("Sensor", p))

    # Warmup
    print(f"      Warmup {WARMUP_SECONDS}s...")
    time.sleep(WARMUP_SECONDS)

    initial_count = count_db_events()

    # Medición
    print(f"      Midiendo {DURATION_SECONDS}s...")
    time.sleep(DURATION_SECONDS)

    final_count = count_db_events()
    events_in_2min = final_count - initial_count

    # Latencia (3 muestras, promedio)
    print("      Midiendo latencia (3 muestras)...")
    latencies = []
    mon_port = cfg["zmq_ports"]["monitoring_to_analytics"]
    for i in range(3):
        lat = measure_override_latency(mon_port)
        if lat >= 0:
            latencies.append(lat)
        print(f"        Muestra {i+1}: {lat*1000:.1f}ms" if lat >= 0 else f"        Muestra {i+1}: error")
        time.sleep(1)

    avg_lat = sum(latencies) / len(latencies) if latencies else -1.0

    # Verifica que el override se haya persistido (end-to-end check)
    print("      Verificando persistencia del override...")
    try:
        db_check = DatabaseManager(os.path.join(DATA_DIR, "main_traffic.db"))
        db_check.connect()
        acciones = db_check.get_light_actions_between_dates(
            "INT_C1K1", "2026-01-01T00:00:00Z", "2030-01-01T00:00:00Z"
        )
        if acciones:
            ultima = acciones[-1]
            print(f"        Override verificado: {ultima.get('semaforo_id', 'N/A')} → {ultima.get('estado_nuevo', 'N/A')} ({ultima.get('razon', 'N/A')})")
        else:
            print("        [ADVERTENCIA] No se encontraron acciones de override en la BD")
        db_check.close()
    except Exception as e:
        print(f"        [ADVERTENCIA] No se pudo verificar override: {e}")

    # Cleanup
    print("      Deteniendo procesos...")
    for name, proc in reversed(procs):
        kill_process_tree(proc, name)
    time.sleep(2)
    clean_db()

    return {
        "events_2min": events_in_2min,
        "avg_latency_ms": round(avg_lat * 1000, 1),
    }


def run_experiment(scenario: dict, broker: dict) -> dict:
    """Ejecuta NUM_RUNS corridas y retorna estadísticas."""
    print(f"\n  Escenario: {scenario['desc']}")
    print(f"  Broker:     {broker['desc']}")
    print(f"  Corridas:   {NUM_RUNS}")

    raw_events = []
    raw_latency = []

    for run_idx in range(1, NUM_RUNS + 1):
        print(f"\n  --- Corrida {run_idx}/{NUM_RUNS} ---")
        result = run_single(scenario, broker)
        print(f"    → {result['events_2min']} eventos, {result['avg_latency_ms']}ms")
        raw_events.append(result["events_2min"])
        raw_latency.append(result["avg_latency_ms"])

    events_mean = statistics.mean(raw_events)
    events_std = statistics.stdev(raw_events) if NUM_RUNS > 1 else 0
    events_min = min(raw_events)
    events_max = max(raw_events)

    lat_mean = statistics.mean(raw_latency)
    lat_std = statistics.stdev(raw_latency) if NUM_RUNS > 1 else 0
    lat_min = min(raw_latency)
    lat_max = max(raw_latency)

    print(f"\n  Resultados ({NUM_RUNS} corridas):")
    print(f"    Eventos/2min:  μ={events_mean:.0f}  σ={events_std:.1f}  [{events_min}-{events_max}]")
    print(f"    Latencia (ms): μ={lat_mean:.1f}  σ={lat_std:.1f}  [{lat_min}-{lat_max}]")

    return {
        "scenario": scenario["name"],
        "scenario_desc": scenario["desc"],
        "broker": broker["name"],
        "broker_desc": broker["desc"],
        "events_mean": round(events_mean, 1),
        "events_std": round(events_std, 1),
        "events_min": events_min,
        "events_max": events_max,
        "lat_mean": round(lat_mean, 1),
        "lat_std": round(lat_std, 1),
        "lat_min": round(lat_min, 1),
        "lat_max": round(lat_max, 1),
    }


def print_table(results: list):
    print()
    print("=" * 130)
    header = f"{'Escenario':<25} {'Broker':<15} {'Eventos μ':<10} {'σ':<8} {'[min-max]':<18} {'Lat μ(ms)':<12} {'σ':<8} {'[min-max]':<18}"
    print(header)
    print("-" * 130)
    for r in results:
        ev_range = f"[{r['events_min']}-{r['events_max']}]"
        lat_range = f"[{r['lat_min']}-{r['lat_max']}]"
        print(f"{r['scenario_desc']:<25} {r['broker_desc']:<15} {r['events_mean']:<10} {r['events_std']:<8} {ev_range:<18} {r['lat_mean']:<12} {r['lat_std']:<8} {lat_range:<18}")
    print("=" * 130)
    print()


def generate_graphs(results: list):
    scenarios_order = ["1sensor_10s", "2sensores_5s"]
    broker_order = ["original", "threaded"]
    x = np.arange(len(scenarios_order))
    width = 0.3
    palette = {"original": "#3498db", "threaded": "#e67e22"}

    # --- Eventos ---
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, b in enumerate(broker_order):
        vals = []
        yerr = []
        for s in scenarios_order:
            match = [r for r in results if r["scenario"] == s and r["broker"] == b]
            if match:
                vals.append(match[0]["events_mean"])
                yerr.append(match[0]["events_std"])
            else:
                vals.append(0)
                yerr.append(0)
        offset = (i - 0.5) * width
        bars = ax.bar(x + offset, vals, width, label=b, color=palette[b], yerr=yerr, capsize=4)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    str(int(v)), ha="center", va="bottom", fontsize=9)

    scenario_labels = ["1 sensor/u @10s", "2 sensores/u @5s"]
    ax.set_xticks(x)
    ax.set_xticklabels(scenario_labels)
    ax.set_ylabel("Eventos almacenados (2 min)")
    ax.set_title("Rendimiento: Eventos en BD (promedio de 3 corridas)")
    ax.legend(title="Diseño Broker")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PROJECT_ROOT, "data", "grafica_eventos.png"), dpi=150)
    plt.close(fig)
    print("  [OK] Gráfico guardado: data/grafica_eventos.png")

    # --- Latencia ---
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, b in enumerate(broker_order):
        vals = []
        yerr = []
        for s in scenarios_order:
            match = [r for r in results if r["scenario"] == s and r["broker"] == b]
            if match:
                vals.append(match[0]["lat_mean"])
                yerr.append(match[0]["lat_std"])
            else:
                vals.append(0)
                yerr.append(0)
        offset = (i - 0.5) * width
        bars = ax.bar(x + offset, vals, width, label=b, color=palette[b], yerr=yerr, capsize=4)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                    f"{v:.1f}", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(scenario_labels)
    ax.set_ylabel("Latencia (ms)")
    ax.set_title("Rendimiento: Latencia de Override (promedio de 3 corridas)")
    ax.legend(title="Diseño Broker")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PROJECT_ROOT, "data", "grafica_latencia.png"), dpi=150)
    plt.close(fig)
    print("  [OK] Gráfico guardado: data/grafica_latencia.png")


def main():
    print("=" * 60)
    print("  EXPERIMENTOS DE RENDIMIENTO - Tabla 1")
    print(f"  {NUM_RUNS} corridas por combinación | {DURATION_SECONDS}s duración | {WARMUP_SECONDS}s warmup")
    print("=" * 60)

    os.makedirs(DATA_DIR, exist_ok=True)

    # Eliminar procesos zombie
    print("  Limpiando procesos residuales...")
    for proc_name in ("main_db.py", "replica_db.py", "analytics_service.py",
                      "traffic_light_controller.py", "broker.py", "broker_threaded.py"):
        subprocess.run(
            ["taskkill", "/F", "/IM", "python.exe", "/FI", f"WINDOWTITLE eq *{proc_name}*"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
    time.sleep(2)

    ports = list(BASE_CONFIG["zmq_ports"].values())
    if not wait_for_ports_free(ports, timeout=15):
        print("  [ADVERTENCIA] No se pudieron liberar todos los puertos, continuando...")

    clean_db()
    backup_config()

    all_results = []
    try:
        for broker in BROKER_TYPES:
            for scenario in SCENARIOS:
                result = run_experiment(scenario, broker)
                all_results.append(result)
    finally:
        restore_config()

    print_table(all_results)
    generate_graphs(all_results)

    print("\n  Resumen para el informe:")
    print("  " + "-" * 50)
    for r in all_results:
        print(f"  {r['scenario_desc']} | {r['broker_desc']}:")
        print(f"    Eventos/2min: μ={r['events_mean']} σ={r['events_std']} [{r['events_min']}-{r['events_max']}]")
        print(f"    Latencia:     μ={r['lat_mean']}ms σ={r['lat_std']} [{r['lat_min']}-{r['lat_max']}]ms")
    print()


if __name__ == "__main__":
    main()
