---
name: smart-traffic-system-designer
description: Design, implement, and document a distributed intelligent traffic management system using ZeroMQ. Use this skill whenever the user needs to design architecture, define components, create UML diagrams, implement services, establish traffic rules, define data models, configure communication patterns, build fault tolerance, define testing protocols, security models, load generation, performance metrics, or generate the academic report for the first delivery of the distributed systems project.
---

# Smart Traffic System Designer

This skill ensures a complete, evaluable academic design AND implementation for a distributed intelligent traffic system using ZeroMQ (ZMQ). It covers the **first delivery** (Semana 10 — 15%) which requires: system models, UML diagrams, and functional source code for PC1 and PC2 services.

---

# 1. System Understanding

Always define:

- Grid size (NxM) — default: 5x5
- Number of sensors per type per intersection
- Event frequency (configurable, default: 1 event/second per sensor)
- Source of data (MANDATORY: see Section 12)

## Sensor Types

| Sensor | Metric | Variable | Unit |
|--------|--------|----------|------|
| Espira Inductiva | Conteo vehicular | veh/min | vehículos/minuto |
| Cámara | Longitud de cola | Q | vehículos en espera |
| GPS | Densidad | D = N_veh / L_via | vehículos/km |
| GPS | Velocidad promedio | Vp | km/h |

## Constraints from PDF

- All streets are **one-way** (sentido único)
- Traffic lights have ONLY **RED and GREEN** (no yellow)
- Each intersection can have multiple traffic lights (one per direction)

---

# 2. Grid Notation and Identifiers

> **CRITICAL**: The PDF defines strict naming conventions. ALL code and diagrams MUST use this notation.

## Intersection Naming

Format: `INT_C{column}K{row}`

Example for a 5x5 grid:
```
INT_C1K1  INT_C2K1  INT_C3K1  INT_C4K1  INT_C5K1
INT_C1K2  INT_C2K2  INT_C3K2  INT_C4K2  INT_C5K2
INT_C1K3  INT_C2K3  INT_C3K3  INT_C4K3  INT_C5K3
INT_C1K4  INT_C2K4  INT_C3K4  INT_C4K4  INT_C5K4
INT_C1K5  INT_C2K5  INT_C3K5  INT_C4K5  INT_C5K5
```

## Sensor Naming

Format: `{TYPE}_{INTERSECTION_ID}`

| Sensor Type | Prefix | Example |
|-------------|--------|---------|
| Espira Inductiva | ESP | `ESP_C5K3` |
| Cámara | CAM | `CAM_C5K3` |
| GPS | GPS | `GPS_C5K3` |

## Traffic Light Naming

Format: `SEM_{INTERSECTION}_{DIRECTION}`

Directions: N (North), S (South), E (East), W (West)

Example: `SEM_C5K3_N` → traffic light controlling northbound traffic at intersection C5K3

## Topic Naming for ZMQ PUB/SUB

Format: `sensor/{type}/{intersection_id}`

Examples:
- `sensor/espira/C5K3`
- `sensor/camara/C5K3`
- `sensor/gps/C5K3`
- `semaforo/cambio/C5K3`
- `alerta/prioridad/C5K3`

---

# 3. Architecture Design

## PC1 – Data Generation and Distribution

Components:
- **Sensor Processes** (independent processes, one per sensor)
- **BrokerZMQ** (proxy process)

Behavior:
- Each sensor is a **separate process** (NOT a thread)
- Sensors connect to the Broker via ZMQ `PUB` sockets
- Broker acts as a **XPUB/XSUB proxy** that forwards all messages to subscribers
- Broker binds on two ports: one for PUB (frontend) and one for SUB (backend)

## PC2 – Analytics and Control

Components:
- **Analytics Service** (subscribes to Broker, processes events, applies rules)
- **Traffic Light Controller** (receives commands from Analytics, changes light states)
- **Replica DB** (asynchronous backup of main DB)

Behavior:
- Analytics subscribes to Broker topics via `SUB` socket
- Analytics evaluates traffic rules per intersection
- Analytics sends actions to Traffic Light Controller via `PUB/SUB`
- Analytics sends data to DB via `PUSH` socket
- Analytics responds to Monitoring queries via `REP` socket
- Replica DB receives sync data from Main DB via `SUB` or `PULL`

## PC3 – Monitoring and Persistence

Components:
- **Monitoring and Query Service** (user interface for queries and manual overrides)
- **Main Database** (stores all historical data)

Behavior:
- Monitoring sends queries/commands to Analytics via `REQ` socket
- Main DB receives data from Analytics via `PULL` socket
- Main DB publishes sync updates to Replica DB via `PUB`

---

# 4. Communication Patterns (ZMQ)

| Flow | Source | Destination | ZMQ Pattern | Port (suggested) |
|------|--------|-------------|-------------|------------------|
| Sensor → Broker (frontend) | PC1 Sensors | PC1 Broker | PUB → XSUB | 5555 |
| Broker (backend) → Analytics | PC1 Broker | PC2 Analytics | XPUB → SUB | 5556 |
| Analytics → Main DB | PC2 Analytics | PC3 Main DB | PUSH → PULL | 5557 |
| Analytics → Traffic Lights | PC2 Analytics | PC2 Lights | PUB → SUB | 5558 |
| Monitoring ↔ Analytics | PC3 Monitoring | PC2 Analytics | REQ → REP | 5559 |
| Main DB → Replica DB (sync) | PC3 Main DB | PC2 Replica DB | PUB → SUB | 5560 |
| Monitoring → Lights (override) | PC3 Monitoring | PC2 Analytics | REQ → REP | 5559 (same) |

### Broker Proxy Implementation (XPUB/XSUB)

```
               PC1
  [Sensor1]──PUB──┐
  [Sensor2]──PUB──┤   ┌───XSUB───[BrokerZMQ]───XPUB───┐
  [Sensor3]──PUB──┘   │          (proxy)               │
                       └────────────────────────────────┘
                                                        │
               PC2                                      │
  [Analytics]──SUB──────────────────────────────────────┘
```

---

# 5. Message Formats (JSON)

> **CRITICAL**: All ZMQ messages use JSON. Every message MUST include `timestamp` and `source_id`.

## 5.1 Sensor Event Message (Sensor → Broker)

```json
{
  "message_id": "uuid-v4",
  "sensor_id": "ESP_C5K3",
  "tipo_sensor": "espira",
  "interseccion": "INT_C5K3",
  "timestamp": "2026-04-01T22:00:00.000Z",
  "datos": {
    "vehiculos_por_minuto": 12
  },
  "auth_token": "sensor-token-abc123"
}
```

### By sensor type:

**Espira:**
```json
{ "datos": { "vehiculos_por_minuto": 12 } }
```

**Cámara:**
```json
{ "datos": { "longitud_cola": 7 } }
```

**GPS:**
```json
{ "datos": { "densidad": 25.3, "velocidad_promedio": 32.5 } }
```

## 5.2 Traffic Analysis Result (Analytics → DB)

```json
{
  "message_id": "uuid-v4",
  "interseccion": "INT_C5K3",
  "timestamp": "2026-04-01T22:00:05.000Z",
  "estado": "congestion",
  "metricas": {
    "Q": 7,
    "Vp": 28.5,
    "D": 25.3,
    "vehiculos_por_minuto": 12
  },
  "accion_tomada": {
    "tipo": "CAMBIO_LUZ",
    "semaforo_id": "SEM_C5K3_N",
    "estado_anterior": "ROJO",
    "estado_nuevo": "VERDE"
  }
}
```

## 5.3 Traffic Light Command (Analytics → Lights)

```json
{
  "comando": "CAMBIO_LUZ",
  "semaforo_id": "SEM_C5K3_N",
  "nuevo_estado": "VERDE",
  "razon": "congestion_detectada",
  "prioridad": false,
  "timestamp": "2026-04-01T22:00:05.000Z"
}
```

## 5.4 Monitoring Query (Monitoring → Analytics)

```json
{
  "tipo": "CONSULTA",
  "consulta": "ESTADO_INTERSECCION",
  "interseccion": "INT_C5K3",
  "timestamp": "2026-04-01T22:00:10.000Z"
}
```

## 5.5 Manual Override (Monitoring → Analytics)

```json
{
  "tipo": "OVERRIDE",
  "semaforo_id": "SEM_C5K3_N",
  "nuevo_estado": "VERDE",
  "motivo": "ambulancia",
  "origen": "monitoring_service",
  "auth_token": "monitor-token-xyz789",
  "timestamp": "2026-04-01T22:00:10.000Z"
}
```

## 5.6 DB Replication Message (Main DB → Replica DB)

```json
{
  "tipo": "SYNC",
  "tabla": "eventos",
  "operacion": "INSERT",
  "datos": { "...row data..." },
  "sequence_number": 12345,
  "timestamp": "2026-04-01T22:00:06.000Z"
}
```

---

# 6. Traffic Rules

## Formulas

| Variable | Formula | Description |
|----------|---------|-------------|
| Q | Direct from camera | Queue length (vehicles waiting) |
| Vp | Direct from GPS | Average speed (km/h) |
| D | N_veh / L_via | Density (vehicles/km) |
| veh/min | Direct from espira | Vehicle flow rate |

## Rule Definitions

### Normal Traffic
```
Q < 5 AND Vp > 35 AND D < 20
```
→ Action: No change needed. Maintain current light state.

### Congestion Detected
```
Q >= 5 OR Vp <= 35 OR D >= 20
```
→ Action: Change traffic light to GREEN for the congested direction. Change conflicting direction to RED.

### Priority Override
```
Manual command from Monitoring Service (e.g., ambulance)
```
→ Action: Immediately set specified traffic light to GREEN. Set all conflicting lights to RED.

### Thresholds (CONFIGURABLE)

```python
THRESHOLDS = {
    "Q_MAX": 5,        # max queue before congestion
    "VP_MIN": 35,      # min speed before congestion (km/h)
    "D_MAX": 20,       # max density before congestion (veh/km)
}
```

These thresholds MUST be configurable via a config file or environment variables.

---

# 7. Data Model

## 7.1 Table: `sensores`

| Column | Type | Description |
|--------|------|-------------|
| sensor_id | VARCHAR PK | e.g., ESP_C5K3 |
| tipo_sensor | VARCHAR | espira, camara, gps |
| interseccion_id | VARCHAR FK | e.g., INT_C5K3 |
| estado | VARCHAR | activo, inactivo |
| ultima_lectura | TIMESTAMP | Last reading time |

## 7.2 Table: `intersecciones`

| Column | Type | Description |
|--------|------|-------------|
| interseccion_id | VARCHAR PK | e.g., INT_C5K3 |
| columna | INT | Column in grid |
| fila | INT | Row in grid |
| estado_trafico | VARCHAR | normal, congestion, prioridad |
| ultima_actualizacion | TIMESTAMP | Last state update |

## 7.3 Table: `eventos`

| Column | Type | Description |
|--------|------|-------------|
| evento_id | VARCHAR PK | UUID |
| sensor_id | VARCHAR FK | Source sensor |
| interseccion_id | VARCHAR FK | Related intersection |
| tipo_sensor | VARCHAR | espira, camara, gps |
| datos | JSON/TEXT | Raw sensor data |
| timestamp | TIMESTAMP | Event time |

## 7.4 Table: `estado_trafico`

| Column | Type | Description |
|--------|------|-------------|
| id | INT PK AUTO | Sequential |
| interseccion_id | VARCHAR FK | Related intersection |
| Q | FLOAT | Queue length |
| Vp | FLOAT | Average speed |
| D | FLOAT | Density |
| vehiculos_por_minuto | FLOAT | Flow rate |
| estado | VARCHAR | normal, congestion |
| timestamp | TIMESTAMP | Evaluation time |

## 7.5 Table: `semaforos`

| Column | Type | Description |
|--------|------|-------------|
| semaforo_id | VARCHAR PK | e.g., SEM_C5K3_N |
| interseccion_id | VARCHAR FK | Related intersection |
| direccion | VARCHAR | N, S, E, W |
| estado_actual | VARCHAR | VERDE, ROJO |
| ultima_accion | TIMESTAMP | Last change time |

## 7.6 Table: `acciones_semaforo`

| Column | Type | Description |
|--------|------|-------------|
| accion_id | VARCHAR PK | UUID |
| semaforo_id | VARCHAR FK | Related traffic light |
| estado_anterior | VARCHAR | VERDE or ROJO |
| estado_nuevo | VARCHAR | VERDE or ROJO |
| razon | VARCHAR | congestion, prioridad, manual |
| origen | VARCHAR | analytics, monitoring |
| timestamp | TIMESTAMP | Action time |

## 7.7 Replication Schema

The following tables are replicated from PC3 (Main DB) to PC2 (Replica DB):
- `eventos` (full replication)
- `estado_trafico` (full replication)
- `acciones_semaforo` (full replication)
- `semaforos` (full replication)

Static tables (`sensores`, `intersecciones`) are initialized on both DBs at startup.

---

# 8. Fault Tolerance (PC3 Failure)

## 8.1 Detection Mechanism

- **Heartbeat**: Main DB (PC3) sends periodic heartbeat messages to Analytics (PC2)
- **Interval**: Every 5 seconds (configurable)
- **Timeout**: If no heartbeat received for 15 seconds (3 missed beats), declare PC3 as DOWN
- **ZMQ Pattern**: Heartbeat uses `PUB/SUB` on a dedicated port (e.g., 5561)

## 8.2 Failover Protocol

```
1. Analytics detects PC3 timeout (no heartbeat for 15s)
2. Analytics sets flag: USE_REPLICA = True
3. All PUSH messages redirect to Replica DB (PC2) instead of Main DB (PC3)
4. Monitoring Service queries route to Replica DB
5. Log the failover event with timestamp
6. System continues operating transparently
```

## 8.3 Recovery Protocol

```
1. PC3 comes back online, resumes heartbeat
2. Analytics detects heartbeat restored
3. Replica DB sends accumulated data to Main DB (re-sync)
4. Once sync confirmed, Analytics sets: USE_REPLICA = False
5. Normal operation resumes
6. Log the recovery event with timestamp
```

## 8.4 Transparency

- The user (via Monitoring Service) should NOT notice the failover
- All queries and responses maintain the same format
- A status indicator may show "REPLICA MODE" but functionality is unchanged

---

# 9. Replication Protocol (Main DB ↔ Replica DB)

## 9.1 Normal Operation (PC3 alive)

- Main DB publishes every write operation via `PUB` socket (port 5560)
- Replica DB subscribes and applies writes locally
- Each sync message includes a `sequence_number` for ordering
- Replica tracks `last_applied_sequence` to detect gaps

## 9.2 During PC3 Failure

- Replica DB accepts direct writes from Analytics via `PULL` socket
- Replica DB continues incrementing local sequence numbers
- All writes during failure are tagged with `source: "replica_direct"`

## 9.3 Re-synchronization (PC3 Recovery)

```
1. PC3 sends its last_sequence_number to Replica DB
2. Replica DB sends all records with sequence > last_sequence_number
3. Main DB applies the missing records
4. Both DBs confirm sync with matching sequence numbers
5. Normal PUB/SUB replication resumes
```

---

# 10. Security Model

## 10.1 Threats

- Message spoofing (fake sensor data)
- Data tampering (modified values in transit)
- Unauthorized commands (fake ambulance override)

## 10.2 Mechanisms

### Message Validation (at Analytics Service - PC2)
- Validate `sensor_id` exists in registered sensors
- Validate `tipo_sensor` matches sensor registration
- Validate JSON schema structure
- Validate data ranges (e.g., Vp cannot be negative)
- Reject and log invalid messages

### Authentication (lightweight)
- Each sensor has a unique `auth_token` assigned at initialization
- Analytics validates token against registered sensor list
- Monitoring Service has a separate admin token for overrides

### Integrity
- Optional: include SHA-256 hash of `datos` field
- Analytics can verify hash before processing

### Access Control
- Only Monitoring Service can send override commands
- Analytics verifies `origen` field matches authorized sources
- Override commands require valid `auth_token`

### On Invalid Data
- Log the invalid message with details
- Increment error counter per sensor
- If error rate exceeds threshold, flag sensor as suspicious
- Do NOT process invalid data into traffic rules

---

# 11. Testing Protocol

## 11.1 Functional Tests

| Test | Description | Expected Result |
|------|-------------|-----------------|
| F1 | Sensor sends event to Broker | Broker receives and forwards |
| F2 | Analytics receives from Broker | Analytics processes event |
| F3 | Congestion rule triggers | Traffic light changes to GREEN |
| F4 | Normal traffic rule | No light change |
| F5 | Manual override via Monitoring | Light changes immediately |
| F6 | Invalid sensor message | Message rejected, logged |
| F7 | DB write from Analytics | Event stored in Main DB |

## 11.2 Fault Tolerance Tests

| Test | Description | Expected Result |
|------|-------------|-----------------|
| FT1 | Kill PC3 process | System switches to Replica DB |
| FT2 | Restore PC3 process | System re-syncs and returns to Main DB |
| FT3 | Send query during failover | Query returns from Replica DB |

## 11.3 Performance Tests (Design for 2nd delivery)

| Test | Description | Metric |
|------|-------------|--------|
| P1 | Single-thread Broker, 2 min run | Total requests stored in DB |
| P2 | Multi-thread Broker, 2 min run | Total requests stored in DB |
| P3 | User override response time (single-thread) | Time from command to light change |
| P4 | User override response time (multi-thread) | Time from command to light change |

### Performance Variables
- Grid size: 3x3, 5x5, 10x10
- Sensor frequency: 1/s, 5/s, 10/s
- Number of concurrent sensors: 9, 25, 100

---

# 12. Load Generation Mechanism

You MUST explicitly define how sensors generate data:

## Option A: Random Generator (RECOMMENDED for first delivery)
- Random values within realistic ranges
- Ranges:
  - `vehiculos_por_minuto`: 0–30
  - `Q` (cola): 0–20
  - `Vp` (velocidad): 5–60 km/h
  - `D` (densidad): 0–50 veh/km
- Good for: stress testing, covering edge cases, variability
- Include occasional congestion spikes (10% probability of extreme values)

## Option B: File-based Input (for reproducible tests)
- Read events from JSON or CSV file
- Each line = one sensor event with timestamp
- Good for: reproducibility, regression testing, demos

## REQUIRED:
Always specify:
- Which option is used and why
- How configurable it is (config file or env vars)
- How to switch between options

---

# 13. Multithreading Consideration (Design for 2nd delivery)

Even if not implemented in first delivery:

## Design MUST allow:
- Broker scalability via threading (replace `zmq.proxy()` with threaded message handling)
- Parallel message handling in Analytics
- Thread-safe DB writes

## Current design supports this because:
- Broker is isolated as a proxy process (can be replaced with threaded version)
- Analytics processes events sequentially but can be extended with worker threads
- DB writes use PUSH/PULL which supports multiple workers

## For 2nd delivery — implement:
- `zmq.ROUTER/DEALER` pattern for load-balanced Broker
- Thread pool for Analytics event processing
- Compare performance: single-thread vs multi-thread

---

# 14. Technology Stack

## Language: Python 3.10+

## Libraries:

| Library | Purpose |
|---------|---------|
| `pyzmq` | ZeroMQ bindings |
| `json` | Message serialization |
| `sqlite3` | Database (Main and Replica) |
| `uuid` | Unique message IDs |
| `datetime` | Timestamps |
| `threading` | Future: multithreaded Broker |
| `logging` | Event logging for metrics and debugging |
| `time` | Intervals and timing |
| `random` | Sensor data generation (Option A) |
| `os` / `sys` | Configuration and process management |

## Database: SQLite

- Lightweight, no server setup needed
- File-based: easy to replicate
- Main DB: `main_traffic.db` (PC3)
- Replica DB: `replica_traffic.db` (PC2)

## Configuration: `config.json`

```json
{
  "grid": { "columns": 5, "rows": 5 },
  "sensor_frequency_seconds": 1,
  "load_generation": "random",
  "thresholds": { "Q_MAX": 5, "VP_MIN": 35, "D_MAX": 20 },
  "heartbeat_interval_seconds": 5,
  "heartbeat_timeout_seconds": 15,
  "zmq_ports": {
    "broker_frontend": 5555,
    "broker_backend": 5556,
    "analytics_to_db": 5557,
    "analytics_to_lights": 5558,
    "monitoring_to_analytics": 5559,
    "db_replication": 5560,
    "heartbeat": 5561
  },
  "pc1_host": "192.168.1.10",
  "pc2_host": "192.168.1.20",
  "pc3_host": "192.168.1.30"
}
```

---

# 15. Project Folder Structure

```
entrega1_proyecto/
├── config.json                  # System configuration
├── README.md                    # Project documentation
├── requirements.txt             # Python dependencies
│
├── pc1/                         # PC1 - Data Generation
│   ├── sensor.py                # Generic sensor process
│   ├── sensor_espira.py         # Espira sensor implementation
│   ├── sensor_camara.py         # Camera sensor implementation
│   ├── sensor_gps.py            # GPS sensor implementation
│   ├── broker.py                # ZMQ XPUB/XSUB proxy broker
│   └── start_pc1.py             # Launcher for all PC1 processes
│
├── pc2/                         # PC2 - Analytics and Control
│   ├── analytics_service.py     # Event processing and rule engine
│   ├── traffic_light_controller.py  # Traffic light state manager
│   ├── replica_db.py            # Replica database manager
│   └── start_pc2.py             # Launcher for all PC2 services
│
├── pc3/                         # PC3 - Monitoring and Persistence
│   ├── monitoring_service.py    # User query and override interface
│   ├── main_db.py               # Main database manager
│   └── start_pc3.py             # Launcher for all PC3 services
│
├── shared/                      # Shared utilities
│   ├── models.py                # Data classes and message schemas
│   ├── db_utils.py              # Database initialization and helpers
│   ├── validation.py            # Message validation logic
│   └── constants.py             # Naming conventions, states
│
├── tests/                       # Test scripts
│   ├── test_functional.py       # Functional tests
│   ├── test_failover.py         # Fault tolerance tests
│   └── test_data/               # Sample data files (Option B)
│       └── sample_events.json
│
├── docs/                        # Documentation and diagrams
│   ├── informe_entrega1.md      # First delivery report
│   ├── diagrama_despliegue.md   # Deployment diagram (Mermaid)
│   ├── diagrama_componentes.md  # Components diagram (Mermaid)
│   ├── diagrama_clases.md       # Class diagram (Mermaid)
│   └── diagrama_secuencia.md    # Sequence diagrams (Mermaid)
│
└── data/                        # Runtime data
    ├── main_traffic.db          # Main DB (PC3, created at runtime)
    └── replica_traffic.db       # Replica DB (PC2, created at runtime)
```

---

# 16. Required UML Diagrams

Generate each diagram using Mermaid notation in markdown files.

## 16.1 Deployment Diagram

Must show:
- 3 nodes: PC1, PC2, PC3
- Artifacts deployed on each node (processes/services)
- Communication channels between nodes with ZMQ patterns and ports
- Database files on PC2 and PC3

## 16.2 Components Diagram

Must show:
- Subsystems: SensorSubsystem, BrokerSubsystem, AnalyticsSubsystem, ControlSubsystem, MonitoringSubsystem, PersistenceSubsystem
- Interfaces between components (ZMQ sockets)
- Dependencies between components

## 16.3 Class Diagram

Must show classes:
- `Sensor` (abstract), `SensorEspira`, `SensorCamara`, `SensorGPS`
- `BrokerZMQ`
- `AnalyticsService` (with rule evaluation methods)
- `TrafficLightController`
- `MonitoringService`
- `DatabaseManager` (abstract), `MainDB`, `ReplicaDB`
- `MessageValidator`
- Data classes: `SensorEvent`, `TrafficState`, `LightAction`

## 16.4 Sequence Diagrams

Must include at least 3 flows:
1. **Normal flow**: Sensor → Broker → Analytics → DB (with light change)
2. **Manual override**: User → Monitoring → Analytics → Light Controller
3. **Failover flow**: PC3 fails → heartbeat timeout → switch to Replica DB → PC3 recovers → re-sync

---

# 17. First Delivery Report Structure

The report (`docs/informe_entrega1.md`) must contain:

```
1. Introducción
   - Descripción del problema
   - Objetivos del sistema

2. Arquitectura del Sistema
   - Descripción de componentes (PC1, PC2, PC3)
   - Justificación de decisiones de diseño
   - Diagrama de despliegue

3. Modelo de Comunicación
   - Patrones ZMQ utilizados y justificación
   - Diagrama de componentes
   - Formato de mensajes

4. Modelo de Datos
   - Esquema de base de datos
   - Protocolo de replicación

5. Reglas de Tráfico
   - Definición formal de reglas
   - Umbrales configurables
   - Manejo de prioridades

6. Tolerancia a Fallos
   - Mecanismo de detección (heartbeat)
   - Protocolo de failover
   - Protocolo de recuperación
   - Diagrama de secuencia del failover

7. Seguridad
   - Modelo de amenazas
   - Mecanismos de validación y autenticación

8. Diagramas UML
   - Despliegue
   - Componentes
   - Clases
   - Secuencia (3 flujos)

9. Código Fuente
   - Descripción de módulos implementados
   - Instrucciones de ejecución

10. Conclusiones
    - Decisiones de diseño tomadas
    - Preparación para segunda entrega (multithreading)
```

---

# 18. Initialization Strategy

## 18.1 Grid Initialization
- Read grid size from `config.json`
- Generate all intersection IDs: `INT_C{c}K{r}` for c in 1..N, r in 1..M
- Register intersections in DB

## 18.2 Sensor Distribution
- Each intersection gets 3 sensors: ESP, CAM, GPS
- Total sensors for NxM grid: N * M * 3
- Each sensor is a separate process

## 18.3 Traffic Light Initialization
- Each intersection gets traffic lights based on one-way street directions
- Initial state: alternate GREEN/RED to avoid all-green or all-red
- Register in `semaforos` table

## 18.4 Startup Order
```
1. Start databases (PC3 Main DB, then PC2 Replica DB)
2. Initialize DB schemas and seed data
3. Start BrokerZMQ (PC1)
4. Start Analytics Service (PC2)
5. Start Traffic Light Controller (PC2)
6. Start Monitoring Service (PC3)
7. Start Sensor processes (PC1) — last, so all consumers are ready
```

---

# 19. Output Structure

When designing or implementing, always respond with sections in this order:

1. System Overview (grid size, sensor count, constraints)
2. Grid Notation and Identifiers
3. Architecture (PC1, PC2, PC3 with all components)
4. Communication Patterns (ZMQ with ports)
5. Message Formats (JSON examples)
6. Traffic Rules (formulas, thresholds, actions)
7. Data Model (all tables with columns)
8. Fault Tolerance (heartbeat, failover, recovery)
9. Replication Protocol
10. Security Model
11. Load Generation (option chosen, configuration)
12. Testing Protocol
13. Performance Metrics
14. Multithreading Readiness
15. UML Diagrams (4 types)
16. Report Structure

---

# Best Practices

- Use asynchronous communication everywhere
- Validate ALL inputs at the Analytics Service
- Log ALL events with timestamps for metrics
- Keep system modular (each service is independent)
- Design for scalability and fault tolerance
- Use configuration files, NOT hardcoded values
- Follow the naming conventions strictly
- Include error handling in every service
- Document every design decision in the report
- Use type hints in Python code
- Include docstrings in all classes and functions