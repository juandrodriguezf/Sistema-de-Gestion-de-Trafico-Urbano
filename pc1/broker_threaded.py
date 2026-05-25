import zmq
import sys
import os
import json
import time
import logging
import threading
from queue import Queue

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [BrokerThreaded] %(levelname)s: %(message)s")
logger = logging.getLogger("BrokerThreaded")


class BrokerThreaded:
    """
    Proxy broker con hilos, reemplazo funcional de zmq.proxy().

    Flujo de datos (PUBs → XSUB → ... → XPUB → SUBs):
      - Reader hilo:     recibe del frontend (XSUB) y pone en input_queue.
      - Worker hilos:    toman de input_queue y ponen en output_queue.
      - Writer hilo:     toma de output_queue y envía al backend (XPUB).

    Flujo de suscripciones (SUBs → XPUB → ... → XSUB → PUBs):
      - SubReader hilo:  recibe suscripciones del backend (XPUB) y pone en sub_queue.
      - SubWriter hilo:  toma de sub_queue y envía al frontend (XSUB).

    Ambos flujos son necesarios para que zmq.XSUB/XPUB funcione correctamente.
    """

    def __init__(self, frontend_port: int = 5555, backend_port: int = 5556,
                 bind_address: str = "0.0.0.0", num_workers: int = 2):
        self.frontend_port = frontend_port
        self.backend_port = backend_port
        self.bind_address = bind_address
        self.num_workers = num_workers
        self.running = False

        self.context = zmq.Context()

        self.frontend = self.context.socket(zmq.XSUB)
        self.backend = self.context.socket(zmq.XPUB)

        self.input_queue: Queue = Queue(maxsize=10000)
        self.output_queue: Queue = Queue(maxsize=10000)
        self.sub_queue: Queue = Queue(maxsize=1000)

        self._data_count = 0
        self._lock = threading.Lock()

    # ── flujo de datos (PUB → XSUB → colas → XPUB → SUB) ──

    def _reader(self):
        """Lee mensajes de datos del frontend (XSUB)."""
        logger.info("Reader hilo iniciado")
        while self.running:
            try:
                msg = self.frontend.recv_multipart()
                self.input_queue.put(msg)
            except zmq.ZMQError:
                if self.running:
                    time.sleep(0.01)

    def _worker(self, wid: int):
        """Transfiere mensajes de input_queue a output_queue."""
        logger.info(f"Worker-{wid} hilo iniciado")
        while self.running:
            try:
                msg = self.input_queue.get(timeout=0.5)
                self.output_queue.put(msg)
            except Exception:
                pass

    def _writer(self):
        """Lee de output_queue y envía al backend (XPUB)."""
        logger.info("Writer hilo iniciado")
        while self.running:
            try:
                msg = self.output_queue.get(timeout=0.5)
                self.backend.send_multipart(msg)
                with self._lock:
                    self._data_count += 1
                    if self._data_count % 500 == 0:
                        logger.info(f"Reenviados {self._data_count} mensajes de datos")
            except Exception:
                pass

    # ── flujo de suscripciones (SUB → XPUB → cola → XSUB → PUB) ──

    def _sub_reader(self):
        """Lee suscripciones del backend (XPUB)."""
        logger.info("SubReader hilo iniciado")
        while self.running:
            try:
                msg = self.backend.recv_multipart()
                self.sub_queue.put(msg)
            except zmq.ZMQError:
                if self.running:
                    time.sleep(0.01)

    def _sub_writer(self):
        """Toma suscripciones de sub_queue y las envía al frontend (XSUB)."""
        logger.info("SubWriter hilo iniciado")
        while self.running:
            try:
                msg = self.sub_queue.get(timeout=0.5)
                self.frontend.send_multipart(msg)
            except Exception:
                pass

    # ── ciclo de vida ──

    def start(self):
        frontend_addr = f"tcp://{self.bind_address}:{self.frontend_port}"
        backend_addr = f"tcp://{self.bind_address}:{self.backend_port}"

        self.frontend.bind(frontend_addr)
        self.backend.bind(backend_addr)

        self.running = True

        threads = []

        t = threading.Thread(target=self._reader, daemon=True)
        t.start()
        threads.append(t)

        for i in range(self.num_workers):
            t = threading.Thread(target=self._worker, args=(i,), daemon=True)
            t.start()
            threads.append(t)

        t = threading.Thread(target=self._writer, daemon=True)
        t.start()
        threads.append(t)

        t = threading.Thread(target=self._sub_reader, daemon=True)
        t.start()
        threads.append(t)

        t = threading.Thread(target=self._sub_writer, daemon=True)
        t.start()
        threads.append(t)

        logger.info(f"Broker multihilos iniciado")
        logger.info(f"  Frontend (XSUB): {frontend_addr}")
        logger.info(f"  Backend  (XPUB): {backend_addr}")
        logger.info(f"  Workers: {self.num_workers}")

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Broker detenido por el usuario")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        time.sleep(0.5)
        self.frontend.close()
        self.backend.close()
        self.context.term()
        logger.info(f"Broker apagado. Total mensajes de datos: {self._data_count}")


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    ports = config.get("zmq_ports", {})
    frontend_port = ports.get("broker_frontend", 5555)
    backend_port = ports.get("broker_backend", 5556)

    broker = BrokerThreaded(frontend_port=frontend_port, backend_port=backend_port)
    broker.start()
