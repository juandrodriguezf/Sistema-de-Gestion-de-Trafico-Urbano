# Diagramas de Secuencia

## Sistema de Gestión Inteligente de Tráfico Urbano

---

## 1. Flujo Normal: Sensor → Broker → Analytics → DB

Flujo completo cuando un sensor detecta congestión y se cambia un semáforo.

```mermaid
sequenceDiagram
    participant S as SensorEspira<br/>(PC1)
    participant B as BrokerZMQ<br/>(PC1)
    participant A as AnalyticsService<br/>(PC2)
    participant T as TrafficLightController<br/>(PC2)
    participant M as MainDB<br/>(PC3)
    participant R as ReplicaDB<br/>(PC2)

    S->>B: PUB sensor/espira/C3K2<br/>{"vehiculos_por_minuto": 25}
    B->>A: XPUB→SUB forward<br/>sensor/espira/C3K2
    
    Note over A: 1. Validar mensaje<br/>2. Actualizar métricas<br/>3. Evaluar reglas
    
    A->>A: evaluate_traffic("INT_C3K2")<br/>Q=8, Vp=20, D=30 → CONGESTION

    A->>T: PUB semaforo/cambio/C3K2<br/>{"semaforo_id": "SEM_C3K2_N",<br/>"nuevo_estado": "VERDE"}
    
    Note over T: Cambiar luz:<br/>SEM_C3K2_N: ROJO → VERDE

    A->>M: PUSH TrafficState<br/>{"estado": "congestion",<br/>"accion_tomada": {...}}

    Note over M: 1. Insertar evento<br/>2. Insertar estado_trafico<br/>3. Insertar accion_semaforo

    M->>R: PUB sync/eventos INSERT
    M->>R: PUB sync/estado_trafico INSERT
    M->>R: PUB sync/acciones_semaforo INSERT
    
    Note over R: Aplicar replicación
```

---

## 2. Override Manual: Usuario → Monitoring → Analytics → Semáforo

Flujo cuando un operador envía un comando de prioridad (ej: ambulancia).

```mermaid
sequenceDiagram
    participant U as Usuario<br/>(CLI)
    participant MO as MonitoringService<br/>(PC3)
    participant A as AnalyticsService<br/>(PC2)
    participant T as TrafficLightController<br/>(PC2)

    U->>MO: Comando: "4 SEM_C5K3_N VERDE ambulancia"
    
    MO->>A: REQ {"tipo": "OVERRIDE",<br/>"semaforo_id": "SEM_C5K3_N",<br/>"nuevo_estado": "VERDE",<br/>"motivo": "ambulancia",<br/>"auth_token": "monitor-token-..."}

    Note over A: 1. Validar comando<br/>2. Verificar auth_token<br/>3. Verificar origen

    alt Token válido
        A->>T: PUB semaforo/cambio/C5K3<br/>{"prioridad": true,<br/>"nuevo_estado": "VERDE"}
        Note over T: SEM_C5K3_N: ROJO → VERDE<br/>(prioridad ambulancia)
        A->>MO: REP {"tipo": "RESPUESTA",<br/>"ejecutado": true}
    else Token inválido
        A->>MO: REP {"tipo": "ERROR",<br/>"mensaje": "Invalid auth_token"}
    end

    MO->>U: Mostrar resultado en CLI
```

---

## 3. Flujo de Failover: Caída de PC3 → Replica DB → Recuperación

Flujo completo del mecanismo de tolerancia a fallos.

```mermaid
sequenceDiagram
    participant M as MainDB<br/>(PC3)
    participant A as AnalyticsService<br/>(PC2)
    participant R as ReplicaDB<br/>(PC2)
    participant S as Sensor<br/>(PC1)

    Note over M,A: === OPERACIÓN NORMAL ===
    
    loop Cada 5 segundos
        M->>A: PUB heartbeat<br/>{"status": "alive"}
    end

    S->>A: Evento sensor
    A->>M: PUSH datos → Main DB

    Note over M: ⚡ PC3 FALLA ⚡<br/>(proceso se detiene)

    Note over A: Sin heartbeat por 15s...<br/>last_heartbeat + 15s < now

    A->>A: use_replica = True<br/>LOG: "Failover activated"

    Note over M,A: === MODO FAILOVER ===

    S->>A: Evento sensor
    
    Note over A: PUSH redirigido a Replica DB

    A->>R: Write directo a Replica DB<br/>{"source": "replica_direct"}

    Note over M: 🔄 PC3 SE RECUPERA 🔄

    Note over M,A: === RECUPERACIÓN ===

    M->>A: PUB heartbeat<br/>{"status": "alive"}
    
    Note over A: Heartbeat detectado!<br/>use_replica = False

    A->>A: LOG: "Recovery - back to Main DB"

    R->>M: Re-sync: enviar datos<br/>faltantes (seq > last_seq)
    
    Note over M: Aplicar datos faltantes

    M->>A: Confirmar sync completo

    Note over M,A: === OPERACIÓN NORMAL RESTAURADA ===
    
    loop Cada 5 segundos
        M->>A: PUB heartbeat
    end
    S->>A: Evento sensor
    A->>M: PUSH datos → Main DB
```

---

## Resumen de Patrones ZMQ por Flujo

| Flujo | Patrón | Dirección |
|-------|--------|-----------|
| Sensor → Broker | PUB → XSUB | Unidireccional |
| Broker → Analytics | XPUB → SUB | Unidireccional |
| Analytics → DB | PUSH → PULL | Unidireccional |
| Analytics → Semáforos | PUB → SUB | Unidireccional |
| Monitoring ↔ Analytics | REQ → REP | Bidireccional (síncrono) |
| Main DB → Replica DB | PUB → SUB | Unidireccional |
| Heartbeat | PUB → SUB | Unidireccional (periódico) |
