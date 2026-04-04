"""
sensor_gps.py - sensor GPS.
Mide: densidad (vehículos/km) y velocidad_promedio (velocidad promedio km/h).
"""

import random
import sys
import os
import json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pc1.sensor import Sensor
from shared.constants import SENSOR_GPS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("SensorGPS")


class SensorGPS(Sensor):
    """
    Sensor GPS — mide la densidad de vehículos y la velocidad promedio.
    Simula datos de seguimiento GPS de vehículos en el área.
    """

    def __init__(self, col: int, row: int, broker_host: str, broker_port: int,
                 frequency: float = 1.0, auth_token: str = "", config: dict = None):
        sensor_id = f"GPS_C{col}K{row}"
        super().__init__(
            sensor_id=sensor_id,
            tipo_sensor=SENSOR_GPS,
            col=col, row=row,
            broker_host=broker_host,
            broker_port=broker_port,
            frequency=frequency,
            auth_token=auth_token,
            config=config,
        )
        cfg = config or {}
        dr = cfg.get("data_ranges", {})
        dens = dr.get("densidad", {})
        vel = dr.get("velocidad_promedio", {})

        self.d_min = dens.get("min", 0)
        self.d_max = dens.get("max", 50)
        self.v_min = vel.get("min", 5)
        self.v_max = vel.get("max", 60)
        self.spike_prob = cfg.get("congestion_spike_probability", 0.10)

    def generate_data(self) -> dict:
        """
        Genera datos de densidad y velocidad.
        Congestión = alta densidad + baja velocidad.
        """
        if random.random() < self.spike_prob:
            # congestión
            densidad = random.uniform(self.d_max * 0.5, self.d_max)
            velocidad = random.uniform(self.v_min, self.v_max * 0.4)
        else:
            # tráfico normal
            densidad = random.uniform(self.d_min, self.d_max * 0.4)
            velocidad = random.uniform(self.v_max * 0.5, self.v_max)
        return {
            "densidad": round(densidad, 1),
            "velocidad_promedio": round(velocidad, 1),
        }


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
    token = config.get("auth_tokens", {}).get("sensors_prefix", "") + f"GPS_C{col}K{row}"

    sensor = SensorGPS(col, row, host, port, frequency=freq, auth_token=token, config=config)
    sensor.run()
