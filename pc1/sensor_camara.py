"""
sensor_camara.py - Camera sensor.
Measures: longitud_cola (queue length — vehicles waiting at intersection).
"""

import random
import sys
import os
import json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pc1.sensor import Sensor
from shared.constants import SENSOR_CAMARA

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("SensorCamara")


class SensorCamara(Sensor):
    """
    Sensor de cámara — mide la longitud de la cola (vehículos esperando en el semáforo).
    Simula la detección visual de colas de vehículos.
    """

    def __init__(self, col: int, row: int, broker_host: str, broker_port: int,
                 frequency: float = 1.0, auth_token: str = "", config: dict = None):
        sensor_id = f"CAM_C{col}K{row}"
        super().__init__(
            sensor_id=sensor_id,
            tipo_sensor=SENSOR_CAMARA,
            col=col, row=row,
            broker_host=broker_host,
            broker_port=broker_port,
            frequency=frequency,
            auth_token=auth_token,
            config=config,
        )
        ranges = (config or {}).get("data_ranges", {}).get("longitud_cola", {})
        self.min_val = ranges.get("min", 0)
        self.max_val = ranges.get("max", 20)
        self.spike_prob = (config or {}).get("congestion_spike_probability", 0.10)

    def generate_data(self) -> dict:
        """Generate queue length data with occasional congestion spikes."""
        if random.random() < self.spike_prob:
            # Congestion spike — long queue
            value = random.randint(int(self.max_val * 0.5), self.max_val)
        else:
            # Normal traffic — short queue
            value = random.randint(self.min_val, int(self.max_val * 0.3))
        return {"longitud_cola": value}


if __name__ == "__main__":
    col = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    row = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    host = sys.argv[3] if len(sys.argv) > 3 else "localhost"
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 5555

    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    freq = config.get("sensor_frequency_seconds", 1)
    token = config.get("auth_tokens", {}).get("sensors_prefix", "") + f"CAM_C{col}K{row}"

    sensor = SensorCamara(col, row, host, port, frequency=freq, auth_token=token, config=config)
    sensor.run()
