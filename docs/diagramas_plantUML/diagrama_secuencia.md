# Diagramas de Secuencia (PlantUML)

## Sistema de Gestión Inteligente de Tráfico Urbano

---

## 1. Flujo Normal: Sensor → Broker → Analytics → DB

```plantuml
@startuml
!theme cerulean-outline
skinparam backgroundColor #fcfcfc
skinparam roundcorner 10
skinparam shadowing false
skinparam handwritten false

participant "SensorEspira\n(PC1)" as S #EA4335
participant "BrokerZMQ\n(PC1)" as B #EA4335
participant "AnalyticsService\n(PC2)" as A #1A73E8
participant "TrafficLightController\n(PC2)" as T #34A853
participant "MainDB\n(PC3)" as M #5F6368
participant "ReplicaDB\n(PC2)" as R #5F6368

autonumber

S -[#EA4335]> B: PUB sensor/espira/C3K2\n{"vehiculos_por_minuto": 25}
B -[#EA4335]> A: XPUB→SUB forward\nsensor/espira/C3K2

activate A
    note over A: 1. Validar mensaje\n2. Actualizar métricas\n3. Evaluar reglas
    
    A -> A: evaluate_traffic("INT_C3K2")\nQ=8, Vp=20, D=30 → CONGESTION

    A -[#34A853]> T: PUB semaforo/cambio/C3K2\n{"semaforo_id": "SEM_C3K2_N",\n"nuevo_estado": "VERDE"}
    
    activate T
        note over T: Cambiar luz:\nSEM_C3K2_N: ROJO → VERDE
    deactivate T

    A -[#FBBC05]> M: PUSH TrafficState\n{"estado": "congestion",\n"accion_tomada": {...}}
deactivate A

activate M
    note over M: 1. Insertar evento\n2. Insertar estado_trafico\n3. Insertar accion_semaforo

    M -[#5F6368]> R: PUB sync/eventos INSERT
    M -[#5F6368]> R: PUB sync/estado_trafico INSERT
    M -[#5F6368]> R: PUB sync/acciones_semaforo INSERT
    
    activate R
        note over R: Aplicar replicación
    deactivate R
deactivate M

@enduml
```

---

## 2. Override Manual: Usuario → Monitoring → Analytics → Semáforo

```plantuml
@startuml
!theme cerulean-outline
skinparam backgroundColor #fcfcfc
skinparam roundcorner 10
skinparam shadowing false
skinparam handwritten false

actor "Usuario\n(CLI)" as U
participant "MonitoringService\n(PC3)" as MO #4285F4
participant "AnalyticsService\n(PC2)" as A #1A73E8
participant "TrafficLightController\n(PC2)" as T #34A853

U -> MO: Comando: "4 SEM_C5K3_N VERDE ambulancia"
activate MO

MO -> A: REQ {"tipo": "OVERRIDE",\n"semaforo_id": "SEM_C5K3_N",\n"nuevo_estado": "VERDE",\n"motivo": "ambulancia",\n"auth_token": "monitor-token-..."}
activate A

note over A: 1. Validar comando\n2. Verificar auth_token\n3. Verificar origen

alt Token válido
    A -[#34A853]> T: PUB semaforo/cambio/C5K3\n{"prioridad": true,\n"nuevo_estado": "VERDE"}
    activate T
        note over T: SEM_C5K3_N: ROJO → VERDE\n(prioridad ambulancia)
    deactivate T
    A -> MO: REP {"tipo": "RESPUESTA",\n"ejecutado": true}
else Token inválido
    A -> MO: REP {"tipo": "ERROR",\n"mensaje": "Invalid auth_token"}
end
deactivate A

MO -> U: Mostrar resultado en CLI
deactivate MO

@enduml
```

---

## 3. Flujo de Failover: Caída de PC3 → Replica DB → Recuperación

```plantuml
@startuml
!theme cerulean-outline
skinparam backgroundColor #fcfcfc
skinparam roundcorner 10
skinparam shadowing false
skinparam handwritten false

participant "MainDB\n(PC3)" as M #5F6368
participant "AnalyticsService\n(PC2)" as A #1A73E8
participant "ReplicaDB\n(PC2)" as R #5F6368
participant "Sensor\n(PC1)" as S #EA4335

== OPERACIÓN NORMAL ==

loop Cada 5 segundos
    M -[#FBBC05]> A: PUB heartbeat\n{"status": "alive"}
end

S -[#EA4335]> A: Evento sensor
A -[#FBBC05]> M: PUSH datos → Main DB

== FALLO DE PC3 ==

hnote over M #EA4335: ⚡ PC3 FALLA ⚡\n(proceso se detiene)

... Sin heartbeat por 15s ...

A -> A: use_replica = True\nLOG: "Failover activated"

== MODO FAILOVER ==

S -[#EA4335]> A: Evento sensor

note over A: PUSH redirigido a Replica DB

A -[#FBBC05]> R: Write directo a Replica DB\n{"source": "replica_direct"}

== RECUPERACIÓN ==

hnote over M #34A853: 🔄 PC3 SE RECUPERA 🔄

M -[#FBBC05]> A: PUB heartbeat\n{"status": "alive"}

activate A
    note over A: Heartbeat detectado!\nuse_replica = False
    A -> A: LOG: "Recovery - back to Main DB"
deactivate A

R -[#5F6368]> M: Re-sync: enviar datos\nfaltantes (seq > last_seq)

activate M
    note over M: Aplicar datos faltantes
    M -[#FBBC05]> A: Confirmar sync completo
deactivate M

== OPERACIÓN NORMAL RESTAURADA ==

loop Cada 5 segundos
    M -[#FBBC05]> A: PUB heartbeat
end

S -[#EA4335]> A: Evento sensor
A -[#FBBC05]> M: PUSH datos → Main DB

@enduml
```
