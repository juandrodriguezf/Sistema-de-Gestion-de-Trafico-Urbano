"""
sensor.py - sensor base abstracto.
Cada sensor es un proceso independiente que publica eventos al BrokerZMQ.
"""

import zmq
import json
import time
import random
import logging
import sys
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import SensorEvent
from shared.constants import sensor_topic

logger = logging.getLogger(__name__)


class Sensor(ABC):
    """
    Clase base abstracta para todos los sensores.
    Cada sensor es un proceso independiente que genera datos y
    los publica al BrokerZMQ a través de un socket ZMQ PUB.
    """

    def __init__(self, sensor_id: str, tipo_sensor: str, col: int, row: int,
                 broker_host: str, broker_port: int, frequency: float = 1.0,
                 auth_token: str = "", config: dict = None):
        self.sensor_id = sensor_id
        self.tipo_sensor = tipo_sensor
        self.col = col
        self.row = row
        self.interseccion = f"INT_C{col}K{row}"
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.frequency = frequency
        self.auth_token = auth_token
        self.config = config or {}
        self.running = False

        # ZMQ setup
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.topic = sensor_topic(tipo_sensor, col, row)

    def connect(self):
        """Connect to the BrokerZMQ frontend."""
        addr = f"tcp://{self.broker_host}:{self.broker_port}"
        self.socket.connect(addr)
        logger.info(f"[{self.sensor_id}] Conectado al broker en {addr}")
        # permite que el broker se conecte
        time.sleep(0.5)

    @abstractmethod
    def generate_data(self) -> dict:
        """
        Genera datos específicos del sensor.
        Debe ser implementado por cada subclase de sensor.
        Retorna un diccionario con el payload del sensor.
        """
        pass

    def create_event(self) -> SensorEvent:
        """Crea un SensorEvent con los datos generados."""
        datos = self.generate_data()
        return SensorEvent(
            sensor_id=self.sensor_id,
            tipo_sensor=self.tipo_sensor,
            interseccion=self.interseccion,
            datos=datos,
            auth_token=self.auth_token,
        )

    def publish(self, event: SensorEvent):
        """Publica el evento al broker con el prefijo del topic."""
        topic = self.topic
        payload = event.to_json()
        # ZMQPUB envía topic + espacio + payload
        message = f"{topic} {payload}"
        self.socket.send_string(message)
        logger.debug(f"[{self.sensor_id}] Publicado: {topic}")

    def run(self):
        """Bucle principal del sensor — genera y publica eventos periódicamente."""
        self.connect()
        self.running = True
        logger.info(f"[{self.sensor_id}] Iniciando sensor (freq={self.frequency}s)")

        try:
            while self.running:
                event = self.create_event()
                self.publish(event)
                time.sleep(self.frequency)
        except KeyboardInterrupt:
            logger.info(f"[{self.sensor_id}] Detenido por el usuario")
        finally:
            self.stop()

    def stop(self):
        """libera recursos"""
        self.running = False
        self.socket.close()
        self.context.term()
        logger.info(f"[{self.sensor_id}] Sensor detenido")
