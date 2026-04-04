# Diagrama de Despliegue

## Sistema de Gestión Inteligente de Tráfico Urbano

```mermaid
graph TB
    subgraph PC1["PC1 — Generación de Datos"]
        direction TB
        S1["Sensor Espira<br/>(proceso)"]
        S2["Sensor Cámara<br/>(proceso)"]
        S3["Sensor GPS<br/>(proceso)"]
        BRK["BrokerZMQ<br/>(proxy XPUB/XSUB)"]
        
        S1 -->|"PUB :5555"| BRK
        S2 -->|"PUB :5555"| BRK
        S3 -->|"PUB :5555"| BRK
    end

    subgraph PC2["PC2 — Analítica y Control"]
        direction TB
        ANA["Analytics Service"]
        TLC["Traffic Light Controller"]
        RDB[("Replica DB<br/>replica_traffic.db")]
        
        ANA -->|"PUB :5558"| TLC
        ANA -.->|"Write (failover)"| RDB
    end

    subgraph PC3["PC3 — Monitoreo y Persistencia"]
        direction TB
        MON["Monitoring Service<br/>(CLI)"]
        MDB[("Main DB<br/>main_traffic.db")]
    end

    BRK ==>|"XPUB :5556<br/>SUB"| ANA
    ANA ==>|"PUSH :5557<br/>PULL"| MDB
    MON -->|"REQ :5559<br/>REP"| ANA
    MDB ==>|"PUB :5560<br/>SUB (sync)"| RDB
    MDB -->|"Heartbeat<br/>PUB :5561"| ANA

    style PC1 fill:#1a1a2e,stroke:#e94560,color:#fff
    style PC2 fill:#16213e,stroke:#0f3460,color:#fff
    style PC3 fill:#0f3460,stroke:#533483,color:#fff
    style BRK fill:#e94560,stroke:#fff,color:#fff
    style ANA fill:#0f3460,stroke:#e94560,color:#fff
    style MDB fill:#533483,stroke:#fff,color:#fff
    style RDB fill:#533483,stroke:#fff,color:#fff
```

## Descripción de Nodos

| Nodo | Host | Componentes | Artefactos |
|------|------|-------------|------------|
| PC1 | `pc1_host` | Sensor Espira, Sensor Cámara, Sensor GPS, BrokerZMQ | `sensor_espira.py`, `sensor_camara.py`, `sensor_gps.py`, `broker.py` |
| PC2 | `pc2_host` | Analytics Service, Traffic Light Controller, Replica DB | `analytics_service.py`, `traffic_light_controller.py`, `replica_db.py`, `replica_traffic.db` |
| PC3 | `pc3_host` | Monitoring Service, Main DB | `monitoring_service.py`, `main_db.py`, `main_traffic.db` |

## Canales de Comunicación

| Canal | Protocolo | Puerto | Patrón ZMQ |
|-------|-----------|--------|------------|
| Sensores → Broker | TCP | 5555 | PUB → XSUB |
| Broker → Analytics | TCP | 5556 | XPUB → SUB |
| Analytics → Main DB | TCP | 5557 | PUSH → PULL |
| Analytics → Semáforos | TCP | 5558 | PUB → SUB |
| Monitoring ↔ Analytics | TCP | 5559 | REQ → REP |
| Main DB → Replica DB | TCP | 5560 | PUB → SUB |
| Main DB → Analytics (heartbeat) | TCP | 5561 | PUB → SUB |
