"""
monitoring_service.py - servicio de monitoreo y control.
"""

import zmq
import json
import sys
import os
import re
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import MonitoringRequest, MonitoringResponse
from shared.constants import (
    CMD_CONSULTA, CMD_OVERRIDE,
    CMD_ESTADO_INTERSECCION, CMD_ESTADO_GENERAL, CMD_LISTAR_SEMAFOROS, CMD_CONSULTA_HISTORICA,
    intersection_id, parse_display_intersection, display_intersection,
    parse_display_semaforo, display_semaforo,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Monitoring] %(levelname)s: %(message)s")
logger = logging.getLogger("MonitoringService")


class MonitoringService:
    """
    Servicio de monitoreo y control.
    envia mensajes a Analytics y muestra respuestas.
    soporta consultas y overrides manuales (e.g., ambulancia priority).
    """

    def __init__(self, config: dict):
        self.config = config
        self.ports = config["zmq_ports"]
        self.auth_token = config.get("auth_tokens", {}).get("monitoring", "")
        self.grid = config["grid"]

        # ZMQ
        self.context = zmq.Context()
        self.req_socket = self.context.socket(zmq.REQ)

    def connect(self):
        """Conecta al socket REP de Analytics."""
        pc2_host = self.config.get("pc2_host", "localhost")
        addr = f"tcp://{pc2_host}:{self.ports['monitoring_to_analytics']}"
        self.req_socket.connect(addr)
        logger.info(f"Conectado a Analytics en {addr}")

    def send_request(self, request: MonitoringRequest) -> MonitoringResponse:
        """envia una solicitud y espera respuesta"""
        self.req_socket.send_string(request.to_json())
        raw = self.req_socket.recv_string()
        return MonitoringResponse.from_json(raw)

    def query_intersection(self, interseccion: str):
        """Consulta el estado de una interseccion especifica"""
        req = MonitoringRequest(
            tipo=CMD_CONSULTA,
            consulta=CMD_ESTADO_INTERSECCION,
            interseccion=interseccion,
        )
        resp = self.send_request(req)
        return resp

    def query_general(self):
        """Consulta el estado general de todas las intersecciones"""
        req = MonitoringRequest(
            tipo=CMD_CONSULTA,
            consulta=CMD_ESTADO_GENERAL,
        )
        resp = self.send_request(req)
        return resp

    def query_semaforos(self):
        """Lista todos los semaforos"""
        req = MonitoringRequest(
            tipo=CMD_CONSULTA,
            consulta=CMD_LISTAR_SEMAFOROS,
        )
        resp = self.send_request(req)
        return resp

    def query_historical(self, interseccion: str, inicio: str, fin: str):
        """Consulta histórica de una intersección entre dos fechas."""
        req = MonitoringRequest(
            tipo=CMD_CONSULTA,
            consulta=CMD_CONSULTA_HISTORICA,
            interseccion=interseccion,
            fecha_inicio=inicio,
            fecha_fin=fin,
        )
        resp = self.send_request(req)
        return resp

    def send_override(self, semaforo_id: str, nuevo_estado: str, motivo: str = "manual"):
        """envia un comando de override manual"""
        req = MonitoringRequest(
            tipo=CMD_OVERRIDE,
            semaforo_id=semaforo_id,
            nuevo_estado=nuevo_estado,
            motivo=motivo,
            auth_token=self.auth_token,
        )
        resp = self.send_request(req)
        return resp

    _RE_INT = re.compile(r"^INT_C(\d+)K(\d+)$")
    _RE_SEM = re.compile(r"^SEM_C(\d+)K(\d+)_(N|S|E|W)$")

    def _to_display(self, obj):
        if isinstance(obj, str):
            m = self._RE_INT.match(obj)
            if m:
                return display_intersection(int(m.group(1)), int(m.group(2)))
            m = self._RE_SEM.match(obj)
            if m:
                return display_semaforo(int(m.group(1)), int(m.group(2)), m.group(3))
            return obj
        if isinstance(obj, dict):
            return {self._to_display(k): self._to_display(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._to_display(i) for i in obj]
        return obj

    def print_response(self, resp: MonitoringResponse):
        """Imprime la respuesta de forma bonita"""
        print(f"\n{'='*60}")
        print(f"  Tipo: {resp.tipo}")
        print(f"  Mensaje: {self._to_display(resp.mensaje)}")
        if resp.datos:
            print(f"  Datos:")
            print(json.dumps(self._to_display(resp.datos), indent=4, ensure_ascii=False))
        print(f"  Timestamp: {resp.timestamp}")
        print(f"{'='*60}\n")

    def run_cli(self):
        """Interfaz de linea de comandos para monitoreo"""
        self.connect()

        print("\n" + "="*60)
        print("  SISTEMA DE MONITOREO DE TRÁFICO URBANO")
        print("  Plataforma de Gestión Inteligente")
        print("="*60)
        print("\nComandos disponibles:")
        print("  1. Estado de intersección  (ej: 1 B2)")
        print("  2. Estado general")
        print("  3. Listar semáforos")
        print("  4. Override manual         (ej: 4 SEM_B2_N VERDE ambulancia)")
        print("  5. Consulta histórica      (ej: 5 A1)")
        print("  6. Salir")
        print()

        while True:
            try:
                user_input = input("Monitoreo> ").strip()
                if not user_input:
                    continue

                parts = user_input.split()
                cmd = parts[0]

                if cmd == "1":
                    if len(parts) < 2:
                        label = input("  Intersección (ej: B2): ").strip()
                    else:
                        label = parts[1]
                    # Convertir de display (B2) a interno (INT_C2K2)
                    col, row = parse_display_intersection(label)
                    int_id = intersection_id(col, row)
                    resp = self.query_intersection(int_id)
                    self.print_response(resp)

                elif cmd == "2":
                    resp = self.query_general()
                    self.print_response(resp)

                elif cmd == "3":
                    resp = self.query_semaforos()
                    self.print_response(resp)

                elif cmd == "4":
                    if len(parts) >= 3:
                        sem_label = parts[1]
                        estado = parts[2]
                        motivo = parts[3] if len(parts) > 3 else "manual"
                    else:
                        sem_label = input("  Semáforo ID (ej: SEM_B2_N): ").strip()
                        estado = input("  Nuevo estado (VERDE/ROJO): ").strip()
                        motivo = input("  Motivo (manual/ambulancia): ").strip() or "manual"
                    # Convertir de display (SEM_B2_N) a interno (SEM_C2K2_N)
                    parsed = parse_display_semaforo(sem_label)
                    if parsed:
                        col, row, direction = parsed
                        sem_id = f"SEM_C{col}K{row}_{direction}"
                    else:
                        sem_id = sem_label
                    resp = self.send_override(sem_id, estado, motivo)
                    self.print_response(resp)

                elif cmd == "5":
                    label = input("  Intersección (ej: A1): ").strip()
                    # Convertir de display (A1) a interno (INT_C1K1)
                    col, row = parse_display_intersection(label)
                    int_id = intersection_id(col, row)
                    print("  Deja en blanco para usar valores por defecto (última hora)")
                    inicio = input("  Fecha inicio (ISO 8601, ej: 2026-05-24T00:00:00): ").strip()
                    fin = input("  Fecha fin (ISO 8601, ej: 2026-05-24T23:59:59): ").strip()
                    if not inicio:
                        from datetime import datetime, timezone, timedelta
                        inicio = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
                    if not fin:
                        from datetime import datetime, timezone
                        fin = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    resp = self.query_historical(int_id, inicio, fin)
                    self.print_response(resp)

                elif cmd == "6" or cmd.lower() in ("exit", "quit", "salir"):
                    print("Cerrando monitoreo...")
                    break

                else:
                    print("  Comando no reconocido. Use 1-6.")

            except EOFError:
                print("\nCerrando monitoreo (EOF)...")
                break
            except KeyboardInterrupt:
                print("\nCerrando monitoreo...")
                break
            except Exception as e:
                print(f"  Error: {e}")

        self.req_socket.close()
        self.context.term()


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    with open(config_path) as f:
        config = json.load(f)

    service = MonitoringService(config)
    service.run_cli()
