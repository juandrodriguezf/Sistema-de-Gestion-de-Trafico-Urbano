"""
sensor.py - Abstract base sensor process.
Each sensor is an independent process that publishes events to the BrokerZMQ.
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
    Abstract base class for all sensors.
    Each sensor runs as an independent process, generating data and
    publishing it to the BrokerZMQ via a ZMQ PUB socket.
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
        # Allow time for connection to establish
        time.sleep(0.5)

    @abstractmethod
    def generate_data(self) -> dict:
        """
        Generate sensor-specific data.
        Must be implemented by each sensor subclass.
        Returns a dict with the sensor payload.
        """
        pass

    def create_event(self) -> SensorEvent:
        """Create a SensorEvent with generated data."""
        datos = self.generate_data()
        return SensorEvent(
            sensor_id=self.sensor_id,
            tipo_sensor=self.tipo_sensor,
            interseccion=self.interseccion,
            datos=datos,
            auth_token=self.auth_token,
        )

    def publish(self, event: SensorEvent):
        """Publish event to ZMQ with topic prefix."""
        topic = self.topic
        payload = event.to_json()
        # ZMQ PUB sends topic + space + payload
        message = f"{topic} {payload}"
        self.socket.send_string(message)
        logger.debug(f"[{self.sensor_id}] Publicado: {topic}")

    def run(self):
        """Main sensor loop — generate and publish events periodically."""
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
        """Clean up resources."""
        self.running = False
        self.socket.close()
        self.context.term()
        logger.info(f"[{self.sensor_id}] Sensor detenido")
