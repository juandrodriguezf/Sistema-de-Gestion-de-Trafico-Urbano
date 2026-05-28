"""
live_viewer.py - Visualizador en tiempo real de la base de datos de tráfico.
Usa rich para mostrar una terminal UI que se actualiza cada 2s.
"""

import sys
import os
import time
import json
import sqlite3
import argparse
import logging
from datetime import datetime, timezone
from threading import Thread, Event

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.constants import parse_intersection, display_intersection, parse_semaforo_id, display_semaforo
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.console import Console
from rich import box

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("LiveViewer")


def fmt_time(ts: str) -> str:
    """Abrevia timestamp ISO a HH:MM:SS en hora local."""
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_local = dt.astimezone()
        return dt_local.strftime("%H:%M:%S")
    except Exception:
        return ts[-8:] if len(ts) >= 8 else ts


def fmt_intersection(int_id: str) -> str:
    """Convierte INT_C2K2 → B2 para display."""
    try:
        col, row = parse_intersection(int_id)
        return display_intersection(col, row)
    except Exception:
        return int_id


def fmt_semaforo(sem_id: str) -> str:
    """Convierte SEM_C2K2_N → SEM_B2_N para display."""
    try:
        parsed = parse_semaforo_id(sem_id)
        if parsed:
            col, row, direction = parsed
            return display_semaforo(col, row, direction)
    except Exception:
        pass
    return sem_id


def build_tables(cursor) -> Layout:
    """Construye el layout completo con datos actuales de la BD."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )

    # ─── Header ───
    try:
        count = cursor.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
    except Exception:
        count = 0
    try:
        active = cursor.execute("SELECT COUNT(*) FROM sensores WHERE estado='activo'").fetchone()[0]
    except Exception:
        active = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = Panel(
        Text(f"LIVE TRAFFIC DASHBOARD  |  Eventos: {count}  |  Sensores: {active}  |  {now}",
             style="bold cyan", justify="center"),
        style="bold green",
    )
    layout["header"].update(header)

    # ─── Body: eventos + intersecciones + semaforos ───
    body = Layout()
    body.split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=1),
    )
    body["left"].split_column(
        Layout(name="events", ratio=2),
        Layout(name="intersections", ratio=1),
    )
    body["right"].update(_build_lights_table(cursor))

    body["events"].update(_build_events_table(cursor))
    body["intersections"].update(_build_intersections_table(cursor))

    layout["body"].update(body)

    # ─── Footer ───
    footer_text = Text("Ctrl+C para salir  |  Actualizando cada 2s", style="dim white", justify="center")
    layout["footer"].update(Panel(footer_text, style="bold blue"))
    return layout


def _build_events_table(cursor) -> Panel:
    """Tabla de eventos recientes."""
    table = Table(title="Eventos Recientes", box=box.MINIMAL_HEAVY_HEAD, title_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Sensor", width=12)
    table.add_column("Intersecc", width=10)
    table.add_column("Tipo", width=8)
    table.add_column("Payload", width=30, overflow="ellipsis")
    table.add_column("Hora", width=8)

    try:
        rows = cursor.execute(
            "SELECT sensor_id, interseccion_id, tipo_sensor, datos, timestamp "
            "FROM eventos ORDER BY timestamp DESC LIMIT 15"
        ).fetchall()
    except Exception:
        rows = []

    for i, r in enumerate(rows, 1):
        datos = r["datos"]
        try:
            d = json.loads(datos) if isinstance(datos, str) else datos
            payload = str(d)[:28]
        except Exception:
            payload = str(datos)[:28]
        table.add_row(
            str(i),
            r["sensor_id"],
            fmt_intersection(r["interseccion_id"]),
            r["tipo_sensor"],
            payload,
            fmt_time(r["timestamp"]),
        )
    return Panel(table, style="bold blue")


def _build_intersections_table(cursor) -> Panel:
    """Tabla de estado de intersecciones."""
    table = Table(title="Estado de Intersecciones", box=box.MINIMAL_HEAVY_HEAD, title_style="bold cyan")
    table.add_column("Intersecc", width=10)
    table.add_column("Estado", width=10)
    table.add_column("Q", width=6)
    table.add_column("Vp", width=6)
    table.add_column("D", width=6)
    table.add_column("V/min", width=6)
    table.add_column("Actualización", width=8)

    try:
        ints = cursor.execute(
            "SELECT interseccion_id, estado_trafico, ultima_actualizacion "
            "FROM intersecciones ORDER BY interseccion_id"
        ).fetchall()
    except Exception:
        ints = []

    for r in ints:
        int_id = r["interseccion_id"]
        estado = r["estado_trafico"]
        try:
            last = cursor.execute(
                "SELECT Q, Vp, D, vehiculos_por_minuto FROM estado_trafico "
                "WHERE interseccion_id = ? ORDER BY timestamp DESC LIMIT 1",
                (int_id,)
            ).fetchone()
        except Exception:
            last = None

        color = "red" if estado == "congestion" else "green"
        table.add_row(
            fmt_intersection(int_id),
            Text(estado, style=f"bold {color}"),
            f"{last['Q']:.1f}" if last else "-",
            f"{last['Vp']:.1f}" if last else "-",
            f"{last['D']:.1f}" if last else "-",
            f"{last['vehiculos_por_minuto']:.1f}" if last else "-",
            fmt_time(r["ultima_actualizacion"]),
        )
    return Panel(table, style="bold blue")


def _build_lights_table(cursor) -> Panel:
    """Tabla de semáforos."""
    table = Table(title="Semáforos", box=box.MINIMAL_HEAVY_HEAD, title_style="bold cyan")
    table.add_column("ID", width=14)
    table.add_column("Dir", width=4)
    table.add_column("Estado", width=6)
    table.add_column("Últ. Acción", width=8)

    try:
        rows = cursor.execute(
            "SELECT semaforo_id, interseccion_id, direccion, estado_actual, ultima_accion "
            "FROM semaforos ORDER BY semaforo_id"
        ).fetchall()
    except Exception:
        rows = []

    for r in rows:
        color = "green" if r["estado_actual"] == "VERDE" else "red"
        table.add_row(
            fmt_semaforo(r["semaforo_id"]),
            r["direccion"],
            Text(r["estado_actual"], style=f"bold {color}"),
            fmt_time(r["ultima_accion"]),
        )
    return Panel(table, style="bold blue")


def main():
    parser = argparse.ArgumentParser(description="Live Traffic Database Viewer")
    parser.add_argument("--db-path", default=None,
                        help="Ruta a la base de datos SQLite (default: data/main_traffic.db)")
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        db_path = os.path.join(project_root, "data", "main_traffic.db")

    console = Console()
    console.print(f"[bold yellow]Live Viewer iniciado — BD: {db_path}[/]")

    stop_event = Event()

    def poll_loop():
        conn = None
        while not stop_event.is_set():
            if conn is None:
                try:
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM eventos")
                    console.print("[green]BD conectada[/]")
                except sqlite3.OperationalError as e:
                    console.print(f"[dim yellow]Esperando BD... ({e})[/]")
                    time.sleep(2)
                    continue

            try:
                with Live(console=console, refresh_per_second=0.5, screen=True) as live:
                    while not stop_event.is_set():
                        conn.commit()
                        layout = build_tables(cursor)
                        live.update(layout)
                        time.sleep(2)
            except sqlite3.OperationalError:
                console.print("[yellow]BD desconectada, reconectando...[/]")
                conn.close()
                conn = None
            except Exception as e:
                console.print(f"[red]Error: {e}[/]")
                time.sleep(2)
                conn = None

    thread = Thread(target=poll_loop, daemon=True)
    thread.start()

    try:
        while thread.is_alive():
            thread.join(1)
    except KeyboardInterrupt:
        stop_event.set()
        console.print("\n[bold yellow]Live Viewer detenido[/]")
        os._exit(0)


if __name__ == "__main__":
    main()
