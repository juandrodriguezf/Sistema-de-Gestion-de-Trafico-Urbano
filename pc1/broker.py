"""
broker.py - ZeroMQ XPUB/XSUB Proxy Broker.
Actua como un puente entre los sensores (PC1) y los servicios suscriptores (PC2 Analytics).
"""

import zmq
import sys
import os
import json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [BrokerZMQ] %(levelname)s: %(message)s")
logger = logging.getLogger("BrokerZMQ")


class BrokerZMQ:
    """
    proxy broker usando XPUB/XSUB pattern.
    
    Frontend (XSUB): Sensores se conectan aquí con sockets PUB.
    Backend (XPUB): Suscriptores (Analytics) se conectan aquí con sockets SUB.
    
    El proxy reenvía transparentemente todos los mensajes de los publicadores a los suscriptores.
    El diseño permite el reemplazo futuro con un broker en hilos para la 2da entrega.
    """

    def __init__(self, frontend_port: int = 5555, backend_port: int = 5556,
                 bind_address: str = "0.0.0.0"):
        self.frontend_port = frontend_port
        self.backend_port = backend_port
        self.bind_address = bind_address

        self.context = zmq.Context()
        # XSUB recibe de los publicadores (sensores)
        self.frontend = self.context.socket(zmq.XSUB)
        # XPUB envía a los suscriptores (analytics)
        self.backend = self.context.socket(zmq.XPUB)

    def start(self):
        """
        empieza el proxy
        """
        frontend_addr = f"tcp://{self.bind_address}:{self.frontend_port}"
        backend_addr = f"tcp://{self.bind_address}:{self.backend_port}"

        self.frontend.bind(frontend_addr)
        self.backend.bind(backend_addr)

        logger.info(f"Broker iniciado")
        logger.info(f"  Frontend (XSUB - sensores):   {frontend_addr}")
        logger.info(f"  Backend  (XPUB - analytics): {backend_addr}")
        logger.info(f"  Reenviando mensajes...")

        try:
            # zmq.proxy es un forwarder de mensajes incorporado
            # Bloquea y reenvía mensajes entre frontend y backend
            zmq.proxy(self.frontend, self.backend)
        except KeyboardInterrupt:
            logger.info("Broker detenido por el usuario")
        finally:
            self.stop()

    def stop(self):
        """apaga el broker"""
        self.frontend.close()
        self.backend.close()
        self.context.term()
        logger.info("Broker apagado")


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    ports = config.get("zmq_ports", {})
    frontend_port = ports.get("broker_frontend", 5555)
    backend_port = ports.get("broker_backend", 5556)

    broker = BrokerZMQ(frontend_port=frontend_port, backend_port=backend_port)
    broker.start()
