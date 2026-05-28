"""
traceability_viewer.py - Muestra la tabla `eventos` en vivo.
Cada fila nueva de PC1 aparece como una nueva fila en la tabla.
"""

import sys
import os
import time
import json
import sqlite3
import argparse
from datetime import datetime, timezone
from threading import Thread, Event

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.constants import parse_intersection, display_intersection
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Console
from rich import box

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "main_traffic.db")


def fmt_time(ts: str) -> str:
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


def _abbrev_uuid(u: str) -> str:
    return u[:8] if u and len(u) > 8 else u


def fmt_intersection(int_id: str) -> str:
    """Convierte INT_C2K2 → B2 para display."""
    try:
        col, row = parse_intersection(int_id)
        return display_intersection(col, row)
    except Exception:
        return int_id


def build_events_table(cursor) -> Table:
    """Construye una tabla literal de la BD `eventos`, fila más reciente primero."""
    table = Table(
        title="Tabla `eventos` (BD principal)",
        box=box.SQUARE,
        title_style="bold cyan",
        header_style="bold white on #0055aa",
        border_style="cyan",
        show_lines=True,
    )
    table.add_column("evento_id", width=10, no_wrap=True)
    table.add_column("sensor_id", width=10, no_wrap=True)
    table.add_column("interseccion_id", width=11, no_wrap=True)
    table.add_column("tipo_sensor", width=8, no_wrap=True)
    table.add_column("datos", width=50, overflow="fold")
    table.add_column("timestamp", width=24, no_wrap=True)

    try:
        cursor.execute(
            "SELECT evento_id, sensor_id, interseccion_id, tipo_sensor, datos, timestamp "
            "FROM eventos ORDER BY timestamp DESC LIMIT 20"
        )
        rows = cursor.fetchall()
    except Exception:
        rows = []

    for i, r in enumerate(rows):
        eid_short = _abbrev_uuid(r["evento_id"])
        try:
            d = json.loads(r["datos"]) if isinstance(r["datos"], str) else r["datos"]
        except Exception:
            d = r["datos"]
        payload = json.dumps(d, ensure_ascii=False)[:48]

        style = "bold green" if i == 0 else ""

        table.add_row(
            Text(eid_short, style=style),
            Text(r["sensor_id"], style=style),
            Text(fmt_intersection(r["interseccion_id"]), style=style),
            Text(r["tipo_sensor"], style=style),
            Text(payload, style=style),
            Text(fmt_time(r["timestamp"]), style=style),
        )

    return table


def build_view(cursor, count: int) -> Panel:
    """Panel completo: header + tabla."""
    now = datetime.now().strftime("%H:%M:%S")
    header = f"EVENTOS EN VIVO    Total en BD: {count}    Última actualización: {now}"
    table = build_events_table(cursor)
    return Panel(
        table,
        title=Text(header, style="bold cyan", justify="center"),
        subtitle=Text("Ctrl+C para salir  |  Actualizando cada 1s", style="dim white"),
        style="bold green",
        padding=(1, 1),
    )


def main():
    parser = argparse.ArgumentParser(description="Traceability Viewer — tabla eventos")
    parser.add_argument("--db-path", default=DB_PATH)
    args = parser.parse_args()

    console = Console()
    stop_event = Event()
    last_count = -1

    def poll_loop():
        nonlocal last_count
        conn = None
        while not stop_event.is_set():
            if conn is None:
                try:
                    conn = sqlite3.connect(args.db_path, timeout=10)
                    conn.row_factory = sqlite3.Row
                    conn.execute("SELECT 1")
                    console.print("[green]BD conectada[/]")
                except sqlite3.OperationalError as e:
                    console.print(f"[dim yellow]Esperando BD... ({e})[/]")
                    time.sleep(1)
                    continue

            cursor = conn.cursor()
            try:
                with Live(console=console, refresh_per_second=4, screen=True) as live:
                    while not stop_event.is_set():
                        try:
                            cursor.execute("SELECT 1")
                            cursor.execute("SELECT COUNT(*) FROM eventos")
                            count = cursor.fetchone()[0]
                            if count != last_count:
                                last_count = count
                            live.update(build_view(cursor, count))
                        except sqlite3.OperationalError:
                            raise
                        except Exception:
                            pass
                        time.sleep(1)
            except sqlite3.OperationalError:
                console.print("[yellow]BD desconectada, reconectando...[/]")
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None

    thread = Thread(target=poll_loop, daemon=True)
    thread.start()

    try:
        while thread.is_alive():
            thread.join(1)
    except KeyboardInterrupt:
        stop_event.set()
        console.print("\n[bold yellow]Traceability Viewer detenido[/]")
        os._exit(0)


if __name__ == "__main__":
    main()
