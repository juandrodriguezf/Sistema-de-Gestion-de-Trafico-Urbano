# Sistema de Gestión Inteligente de Tráfico Urbano

Plataforma distribuida para monitoreo y control de tráfico vehicular en tiempo real usando **ZeroMQ**.

## Arquitectura

```
PC1 (Sensores)          PC2 (Analítica)           PC3 (Monitoreo)
┌──────────────┐     ┌───────────────────┐     ┌──────────────────┐
│ Espira  ─PUB─┤     │ Analytics Service │     │ Monitoring (CLI) │
│ Cámara  ─PUB─┼──►  │   ├─ RuleEngine   │ ◄── │                  │
│ GPS     ─PUB─┤  ┌──│   └─ Validator    │     │ Main DB          │
│ BrokerZMQ    │  │  │ TrafficLightCtrl  │     │  ├─ Heartbeat     │
│ (XPUB/XSUB)─┼──┘  │ Replica DB        │ ◄── │  └─ Replication   │
└──────────────┘     └───────────────────┘     └──────────────────┘
```

## Requisitos

- Python 3.10+
- pyzmq >= 25.1.0

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecución

El sistema se puede ejecutar en un solo computador (**Simulación Local**) o en 3 computadores (**Distribución Real**). 

**Consulta la [Guía de Operación Completa](GUIA_OPERACION.md) para detalles específicos por PC.**

### Orden de Inicio:
Abrir **3 terminales** y ejecutar en este orden:

```bash
# Terminal 1 — PC3 (Base de datos + Monitoreo)
python pc3/start_pc3.py

# Terminal 2 — PC2 (Analítica + Control)
python pc2/start_pc2.py

# Terminal 3 — PC1 (Sensores + Broker)
python pc1/start_pc1.py
```

## Uso del Monitoreo (PC3)

Una vez ejecutado, el CLI muestra:

```
Monitoreo> 1 INT_C3K2          # Consultar estado de intersección
Monitoreo> 2                   # Estado general de toda la cuadrícula
Monitoreo> 3                   # Listar todos los semáforos
Monitoreo> 4 SEM_C3K2_N VERDE ambulancia   # Override manual
Monitoreo> 5                   # Salir
```

## Tests

```bash
python -m tests.test_functional    # Tests funcionales
python -m tests.test_failover      # Tests de tolerancia a fallos
```

## Configuración

Editar `config.json` para cambiar:

| Parámetro | Descripción | Default |
|-----------|-------------|---------|
| `grid.columns` / `grid.rows` | Tamaño de cuadrícula | 5x5 |
| `sensor_frequency_seconds` | Frecuencia de sensores | 1s |
| `thresholds.Q_MAX` | Cola máxima antes de congestión | 5 |
| `thresholds.VP_MIN` | Velocidad mínima antes de congestión | 35 km/h |
| `thresholds.D_MAX` | Densidad máxima antes de congestión | 20 veh/km |
| `heartbeat_interval_seconds` | Intervalo de heartbeat | 5s |
| `heartbeat_timeout_seconds` | Timeout para failover | 15s |
| `pc*_host` | IPs de cada PC | localhost |

## Estructura del Proyecto

```
entrega1_proyecto/
├── config.json              # Configuración del sistema
├── requirements.txt         # Dependencias Python
├── pc1/                     # PC1: Sensores + Broker
│   ├── sensor.py            # Clase base abstracta
│   ├── sensor_espira.py     # Sensor de conteo vehicular
│   ├── sensor_camara.py     # Sensor de cola
│   ├── sensor_gps.py        # Sensor de densidad/velocidad
│   ├── broker.py            # Proxy XPUB/XSUB
│   └── start_pc1.py         # Launcher
├── pc2/                     # PC2: Analítica + Control
│   ├── analytics_service.py # Motor de reglas
│   ├── traffic_light_controller.py  # Control de semáforos
│   ├── replica_db.py        # BD réplica
│   └── start_pc2.py         # Launcher
├── pc3/                     # PC3: Monitoreo + BD
│   ├── main_db.py           # BD principal + heartbeat
│   ├── monitoring_service.py # CLI de usuario
│   └── start_pc3.py         # Launcher
├── shared/                  # Utilidades compartidas
│   ├── constants.py         # Nomenclatura y constantes
│   ├── models.py            # Modelos de mensajes
│   ├── db_utils.py          # Gestión de BD
│   └── validation.py        # Validación de mensajes
├── tests/                   # Tests
│   ├── test_functional.py
│   ├── test_failover.py
│   └── test_data/
├── docs/                    # Documentación UML
│   ├── informe_entrega1.md
│   └── diagramas_plantUML/
│       ├── diagrama_despliegue.png
│       ├── diagrama_componentes.png
│       ├── diagrama_clases.png
│       └── diagrama_secuencia.png
└── data/                    # Datos de ejecución (runtime)
```

## Patrones ZMQ

| Comunicación | Patrón | Puerto |
|-------------|--------|--------|
| Sensores → Broker | PUB → XSUB | 5555 |
| Broker → Analytics | XPUB → SUB | 5556 |
| Analytics → MainDB | PUSH → PULL | 5557 |
| Analytics → Semáforos | PUB → SUB | 5558 |
| Monitoring ↔ Analytics | REQ → REP | 5559 |
| MainDB → ReplicaDB | PUB → SUB | 5560 |
| Heartbeat | PUB → SUB | 5561 |

## Documentación

- [Informe de Primera Entrega](docs/informe_entrega1.md)
- [Diagrama de Despliegue](docs/diagramas_plantUML/diagrama_despliegue.png)
- [Diagrama de Componentes](docs/diagramas_plantUML/diagrama_componentes.png)
- [Diagrama de Clases](docs/diagramas_plantUML/diagrama_clases.png)
- [Diagramas de Secuencia](docs/diagramas_plantUML/diagrama_secuencia.png)
