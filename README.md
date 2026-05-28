# Sistema de Gestión Inteligente de Tráfico Urbano

Plataforma distribuida para monitoreo y control de tráfico vehicular en tiempo real usando **ZeroMQ**.

## Arquitectura

```
PC1 (Sensores)          PC2 (Analítica)           PC3 (Monitoreo + Visores)
┌──────────────┐     ┌───────────────────┐     ┌──────────────────────┐
│ Espira  ─PUB─┤     │ Analytics Service │     │ Monitoring (CLI)    │
│ Cámara  ─PUB─┼──►  │   ├─ RuleEngine   │ ◄── │ LiveViewer (TUI)    │
│ GPS     ─PUB─┤  ┌──│   └─ Validator    │     │ TraceabilityViewer  │
│ BrokerZMQ    │  │  │ TrafficLightCtrl  │     │ Main DB             │
│ (XPUB/XSUB) ┼──┘  │ Replica DB        │ ◄── │  ├─ Heartbeat       │
│ ─o─ zmq.proxy()   └───────────────────┘     │  └─ Replication     │
│ ─o─ threaded     ──── Experimentos ────     └──────────────────────┘
│    (4 hilos)      tests/run_experiments.py
└──────────────┘
```

## Requisitos

- Python 3.9+ (recomendado 3.10+)
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
# Terminal 1 — PC3 (Base de datos + Monitoreo + Visores)
python pc3/start_pc3.py                          # solo DB + CLI monitoreo
python pc3/start_pc3.py --live                   # + dashboard TUI (LiveViewer)
python pc3/start_pc3.py --trace                  # + tabla eventos (TraceabilityViewer)
python pc3/start_pc3.py --live --trace           # ambos visores

# Terminal 2 — PC2 (Analítica + Control)
python pc2/start_pc2.py

# Terminal 3 — PC1 (Sensores + Broker)
python pc1/start_pc1.py
```

## Uso del Monitoreo (PC3)

Una vez ejecutado, el CLI muestra (ajusta IDs a tu `grid` en `config.json`; por defecto 5×3):

```
Monitoreo> 1 B2              # Consultar estado de intersección B2
Monitoreo> 2                   # Estado general de toda la cuadrícula
Monitoreo> 3                   # Listar todos los semáforos
Monitoreo> 4 SEM_B2_N VERDE ambulancia   # Override manual
Monitoreo> 5 A1                # Consulta histórica de A1
Monitoreo> 6                   # Salir
```

## Tests

```bash
python -m pytest tests/ -q         # Toda la suite (funcional, failover, override)
python tests/integration_stack_smoke.py   # Opcional: humo PC3 MainDB → PC2 → PC1 (sin TTY en hijos: no usar PIPE sin drenar)
```

## Experimentos de Rendimiento

```bash
python tests/run_experiments.py    # Ejecuta 4 combinaciones (2 escenarios × 2 diseños de broker)
```

Genera gráficas comparativas en `data/grafica_eventos.png` y `data/grafica_latencia.png`.
Resultados detallados en [Informe Segunda Entrega → Experimentos](docs/informe_entrega2.md#9-experimentos-de-rendimiento).

## Demo de Sustentación

Script automatizado que ejecuta un cronograma de 160 segundos demostrando todas las capacidades del sistema:

```bash
python demo_sustentacion/demo_sustentacion.py
```

> **Nota:** El demo se conecta al broker de PC1 vía PUB (puerto 5555). Si no se necesita el ruido de los sensores reales en la base de datos, se puede correr solo el broker sin los 45 sensores: `python pc1/broker.py` en lugar de `python pc1/start_pc1.py`.

### Cronograma

| Tiempo | Evento | Descripción |
|--------|--------|-------------|
| t=60s | Congestión B2 | Envía valores que superan umbrales en B2 |
| t=95s | Congestión D3 | Segunda congestión en D3 |
| t=130s | Ambulancia fila 1 | Override manual de todos los semáforos fila 1 |
| t=140s | Caída BD principal | Termina proceso main_db.py (failover a réplica) |
| t=150s | Segunda ambulancia | Override con failover activo |
| t=160s | Resumen | Muestra eventos ejecutados |

### Ejecución

**En 3 PCs:**
```bash
# PC1 (192.168.10.6)
python pc1/start_pc1.py --threaded

# PC2 (192.168.10.6)
python pc2/start_pc2.py

# PC3 (192.168.10.18)
python pc3/start_pc3.py --live --trace

# PC3 (después de que todos estén listos)
python demo_sustentacion/demo_sustentacion.py
```

**En 1 PC (localhost):**
```bash
# Cambiar pc1_host, pc2_host, pc3_host a "localhost" en config.json
python pc1/start_pc1.py --threaded
python pc2/start_pc2.py
python pc3/start_pc3.py --live --trace
python demo_sustentacion/demo_sustentacion.py
```

### Queries durante la demo

Desde PC3, se pueden hacer consultas mientras la demo ejecuta:
```
Monitoreo> 1 B2       # Estado de B2 después de congestión
Monitoreo> 1 D3       # Estado de D3 después de congestión
Monitoreo> 3           # Listar semáforos (fila 1 debería estar en VERDE)
Monitoreo> 5 B2       # Consulta histórica de B2
```

## Selección del Broker

El launcher `pc1/start_pc1.py` acepta un flag para elegir el broker:

```bash
python pc1/start_pc1.py                # Broker original (zmq.proxy())
python pc1/start_pc1.py --threaded     # Broker multihilos (4 hilos Poller+Queue)
```

- **original:** `zmq.proxy()` estándar, recomendado para producción.
- **threaded:** 4 hilos con `Poller` + `Queue`, útil para experimentos y demostración de escalabilidad.

## Configuración

Editar `config.json` para cambiar:

| Parámetro | Descripción | Default |
|-----------|-------------|---------|
| `grid.columns` / `grid.rows` | Tamaño de cuadrícula | 5×3 (ver `config.json`) |
| `sensor_frequency_seconds` | Frecuencia de sensores | 5s (ver `config.json`) |
| `thresholds.Q_MAX` | Cola máxima antes de congestión | 5 |
| `thresholds.VP_MIN` | Velocidad mínima antes de congestión | 35 km/h |
| `thresholds.D_MAX` | Densidad máxima antes de congestión | 20 veh/km |
| `heartbeat_interval_seconds` | Intervalo de heartbeat | 5s |
| `heartbeat_timeout_seconds` | Timeout para failover | 8s |
| `pc*_host` | IPs de cada PC | localhost |

## Estructura del Proyecto

```
entrega1_proyecto/
├── config.json              # Configuración del sistema
├── requirements.txt         # Dependencias Python
├── demo_sustentacion/        # Demo automatizada para sustentación
│   └── demo_sustentacion.py  # Cronograma de 160s
├── pc1/                     # PC1: Sensores + Broker
│   ├── sensor.py            # Clase base abstracta
│   ├── sensor_espira.py     # Sensor de conteo vehicular
│   ├── sensor_camara.py     # Sensor de cola
│   ├── sensor_gps.py        # Sensor de densidad/velocidad
│   ├── broker.py            # Proxy XPUB/XSUB (zmq.proxy())
│   ├── broker_threaded.py   # Broker multihilos (Poller + Queue)
│   └── start_pc1.py         # Launcher
├── pc2/                     # PC2: Analítica + Control
│   ├── analytics_service.py # Motor de reglas
│   ├── traffic_light_controller.py  # Control de semáforos
│   ├── replica_db.py        # BD réplica
│   └── start_pc2.py         # Launcher
├── pc3/                     # PC3: Monitoreo + BD + Visores
│   ├── main_db.py           # BD principal + heartbeat
│   ├── monitoring_service.py # CLI de usuario
│   ├── live_viewer.py       # Dashboard TUI (rich, cada 2s)
│   ├── traceability_viewer.py # Tabla `eventos` en vivo (cada 1s)
│   └── start_pc3.py         # Launcher (flags: --live, --trace)
├── shared/                  # Utilidades compartidas
│   ├── constants.py         # Nomenclatura y constantes
│   ├── models.py            # Modelos de mensajes
│   ├── db_utils.py          # Gestión de BD
│   └── validation.py        # Validación de mensajes
├── tests/                   # Tests
│   ├── test_functional.py
│   ├── test_failover.py
│   ├── test_override.py
│   ├── integration_stack_smoke.py
│   ├── run_experiments.py   # Automatización de experimentos (Tabla 1)
│   └── test_data/
├── docs/                    # Documentación
│   ├── informe_entrega1.md
│   ├── informe_entrega2.md
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

- [Informe de Primera Entrega](docs/informe_entrega1.md) — arquitectura base, patrones ZMQ, modelo de datos, failover
- [Informe de Segunda Entrega](docs/informe_entrega2.md) — trazabilidad extremo a extremo, visores, métricas de rendimiento
- [Diagrama de Despliegue](docs/diagramas_plantUML/diagrama_despliegue.png)
- [Diagrama de Componentes](docs/diagramas_plantUML/diagrama_componentes.png)
- [Diagrama de Clases](docs/diagramas_plantUML/diagrama_clases.png)
- [Diagramas de Secuencia](docs/diagramas_plantUML/diagrama_secuencia.png)
