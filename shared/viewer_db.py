"""
viewer_db.py - Seleccion de la base de datos para los visores.
Permite mostrar la BD principal y caer a la replica cuando esta tiene datos mas recientes.
"""

import os
import sqlite3


def latest_event_timestamp(db_path: str) -> str:
    """Devuelve el timestamp del evento mas reciente o "" si no se puede leer."""
    if not db_path or not os.path.exists(db_path):
        return ""
    try:
        conn = sqlite3.connect(db_path, timeout=1)
        try:
            row = conn.execute("SELECT MAX(timestamp) FROM eventos").fetchone()
            return (row[0] or "") if row else ""
        finally:
            conn.close()
    except Exception:
        return ""


def select_viewer_db(main_path: str, replica_path: str):
    """Elige la BD con el evento mas reciente. Retorna (ruta, etiqueta)."""
    main_ts = latest_event_timestamp(main_path)
    replica_ts = latest_event_timestamp(replica_path)
    if replica_ts and (not main_ts or replica_ts > main_ts):
        return replica_path, "replica"
    return main_path, "main"
