"""
monitoring_service.py - servicio de monitoreo y control.
Provides a CLI interface for users to query intersection states,
list traffic lights, and send manual override commands.
"""

import zmq
import json
import sys
import os
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import MonitoringRequest, MonitoringResponse
from shared.constants import (
    CMD_CONSULTA, CMD_OVERRIDE,
    CMD_ESTADO_INTERSECCION, CMD_ESTADO_GENERAL, CMD_LISTAR_SEMAFOROS,
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
        """Connect to Analytics REP socket."""
        pc2_host = self.config.get("pc2_host", "localhost")
        addr = f"tcp://{pc2_host}:{self.ports['monitoring_to_analytics']}"
        self.req_socket.connect(addr)
        logger.info(f"Connected to Analytics at {addr}")

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

    def print_response(self, resp: MonitoringResponse):
        """Imprime la respuesta de forma bonita"""
        print(f"\n{'='*60}")
        print(f"  Tipo: {resp.tipo}")
        print(f"  Mensaje: {resp.mensaje}")
        if resp.datos:
            print(f"  Datos:")
            print(json.dumps(resp.datos, indent=4, ensure_ascii=False))
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
        print("  1. Estado de intersección  (ej: 1 INT_C3K2)")
        print("  2. Estado general")
        print("  3. Listar semáforos")
        print("  4. Override manual         (ej: 4 SEM_C3K2_N VERDE ambulancia)")
        print("  5. Salir")
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
                        int_id = input("  Intersección (ej: INT_C3K2): ").strip()
                    else:
                        int_id = parts[1]
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
                        sem_id = parts[1]
                        estado = parts[2]
                        motivo = parts[3] if len(parts) > 3 else "manual"
                    else:
                        sem_id = input("  Semáforo ID (ej: SEM_C3K2_N): ").strip()
                        estado = input("  Nuevo estado (VERDE/ROJO): ").strip()
                        motivo = input("  Motivo (manual/ambulancia): ").strip() or "manual"
                    resp = self.send_override(sem_id, estado, motivo)
                    self.print_response(resp)

                elif cmd == "5" or cmd.lower() in ("exit", "quit", "salir"):
                    print("Cerrando monitoreo...")
                    break

                else:
                    print("  Comando no reconocido. Use 1-5.")

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
