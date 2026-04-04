# Diagrama de Componentes

## Sistema de Gestión Inteligente de Tráfico Urbano

```mermaid
graph LR
    subgraph SensorSubsystem["Subsistema de Sensores"]
        SE["SensorEspira"]
        SC["SensorCamara"]
        SG["SensorGPS"]
    end

    subgraph BrokerSubsystem["Subsistema de Distribución"]
        BRK["BrokerZMQ<br/>(XPUB/XSUB Proxy)"]
    end

    subgraph AnalyticsSubsystem["Subsistema de Analítica"]
        ANA["AnalyticsService"]
        VAL["MessageValidator"]
        RUL["RuleEngine"]
        ANA --> VAL
        ANA --> RUL
    end

    subgraph ControlSubsystem["Subsistema de Control"]
        TLC["TrafficLightController"]
    end

    subgraph MonitoringSubsystem["Subsistema de Monitoreo"]
        MON["MonitoringService"]
    end

    subgraph PersistenceSubsystem["Subsistema de Persistencia"]
        MDB["MainDB"]
        RDB["ReplicaDB"]
        HBM["HeartbeatMonitor"]
        MDB --> HBM
    end

    SE -->|"PUB"| BRK
    SC -->|"PUB"| BRK
    SG -->|"PUB"| BRK
    BRK -->|"SUB"| ANA
    ANA -->|"PUB"| TLC
    ANA -->|"PUSH"| MDB
    ANA -.->|"PUSH (failover)"| RDB
    MON -->|"REQ/REP"| ANA
    MDB -->|"PUB (sync)"| RDB
    HBM -->|"PUB"| ANA

    style SensorSubsystem fill:#1a1a2e,stroke:#e94560,color:#fff
    style BrokerSubsystem fill:#e94560,stroke:#fff,color:#fff
    style AnalyticsSubsystem fill:#16213e,stroke:#0f3460,color:#fff
    style ControlSubsystem fill:#0f3460,stroke:#e94560,color:#fff
    style MonitoringSubsystem fill:#533483,stroke:#fff,color:#fff
    style PersistenceSubsystem fill:#0f3460,stroke:#533483,color:#fff
```

## Interfaces entre Componentes

| Interfaz | Proveedor | Consumidor | Tipo |
|----------|-----------|------------|------|
| ISensorPublish | Sensor* | BrokerZMQ | ZMQ PUB |
| IBrokerForward | BrokerZMQ | AnalyticsService | ZMQ XPUB/SUB |
| IEventValidation | MessageValidator | AnalyticsService | Método interno |
| IRuleEvaluation | RuleEngine | AnalyticsService | Método interno |
| ILightCommand | AnalyticsService | TrafficLightController | ZMQ PUB/SUB |
| IDataPersist | AnalyticsService | MainDB | ZMQ PUSH/PULL |
| IMonitorQuery | MonitoringService | AnalyticsService | ZMQ REQ/REP |
| IReplication | MainDB | ReplicaDB | ZMQ PUB/SUB |
| IHeartbeat | MainDB | AnalyticsService | ZMQ PUB/SUB |
| IFailoverWrite | AnalyticsService | ReplicaDB | Direct DB write |

## Dependencias

- **AnalyticsService** depende de: BrokerZMQ, MessageValidator, RuleEngine, MainDB/ReplicaDB
- **TrafficLightController** depende de: AnalyticsService (comandos)
- **MonitoringService** depende de: AnalyticsService (consultas)
- **ReplicaDB** depende de: MainDB (replicación), AnalyticsService (failover)
