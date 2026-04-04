# Informe Primera Entrega — Gestión Inteligente de Tráfico Urbano

**Asignatura:** Sistemas Distribuidos  
**Universidad:** Pontificia Universidad Javeriana  
**Semestre:** 2026-10  
**Entrega:** Primera (Semana 10 — 15%)

---

## 1. Introducción

### 1.1 Descripción del Problema

El crecimiento del tráfico vehicular en ciudades modernas genera congestiones que afectan la movilidad, incrementan tiempos de desplazamiento y aumentan la contaminación. Se requiere un sistema inteligente capaz de monitorear el tráfico en tiempo real, detectar congestiones automáticamente y actuar sobre los semáforos para optimizar el flujo vehicular.

### 1.2 Objetivos del Sistema

- **Monitorear** el tráfico urbano en tiempo real mediante sensores distribuidos
- **Analizar** datos de tráfico para detectar congestiones usando reglas configurables
- **Controlar** semáforos automáticamente basándose en el análisis de datos
- **Permitir** intervención manual del operador (ej: prioridad para ambulancias)
- **Garantizar** tolerancia a fallos mediante replicación de base de datos
- **Diseñar** para escalabilidad futura con soporte para multithreading

---

## 2. Arquitectura del Sistema

### 2.1 Descripción de Componentes

El sistema se despliega en **3 máquinas (PCs)** con roles específicos:

#### PC1 — Generación de Datos
- **Sensores**: Procesos independientes que simulan 3 tipos de sensores:
  - **Espira Inductiva (ESP)**: Conteo vehicular (vehículos/minuto)
  - **Cámara (CAM)**: Longitud de cola (vehículos en espera)
  - **GPS**: Densidad (veh/km) y velocidad promedio (km/h)
- **BrokerZMQ**: Proxy XPUB/XSUB que reenvía mensajes de sensores a suscriptores

#### PC2 — Analítica y Control
- **Analytics Service**: Motor de reglas que evalúa el tráfico y genera acciones
- **Traffic Light Controller**: Gestor de estados de semáforos
- **Replica DB**: Base de datos réplica para tolerancia a fallos

#### PC3 — Monitoreo y Persistencia
- **Monitoring Service**: Interfaz CLI para consultas y overrides manuales
- **Main DB**: Base de datos principal con almacenamiento histórico

### 2.2 Justificación de Decisiones de Diseño

| Decisión | Justificación |
|----------|---------------|
| Sensores como procesos independientes | Aislamiento de fallos, escalabilidad, simulación realista |
| Broker XPUB/XSUB | Desacopla publishers de subscribers, facilita escalado |
| PUSH/PULL para DB | Asíncrono, no bloquea al Analytics, balanceo de carga futuro |
| REQ/REP para Monitoring | Síncrono necesario para consultas interactivas del usuario |
| SQLite | Ligera, sin servidor, archivo replicable, suficiente para prototipo |
| JSON para mensajes | Legible, extensible, soporte nativo en Python |

### 2.3 Diagrama de Despliegue

Ver: [diagrama_despliegue.md](./diagrama_despliegue.md)

---

## 3. Modelo de Comunicación

### 3.1 Patrones ZMQ Utilizados

| Flujo | Patrón | Justificación |
|-------|--------|---------------|
| Sensor → Broker | PUB/XSUB | Múltiples publishers, un punto de distribución |
| Broker → Analytics | XPUB/SUB | Múltiples subscribers posibles, filtro por topic |
| Analytics → Main DB | PUSH/PULL | Asíncrono, no bloquea procesamiento de eventos |
| Analytics → Semáforos | PUB/SUB | Broadcasting de comandos a múltiples controladores |
| Monitoring ↔ Analytics | REQ/REP | Consultas síncronas del usuario |
| Main DB → Replica DB | PUB/SUB | Replicación asíncrona, no bloquea Main DB |
| Heartbeat | PUB/SUB | Detección de fallos, ligero, periódico |

### 3.2 Formato de Mensajes

Todos los mensajes usan JSON con campos obligatorios `message_id` y `timestamp`.

**Ejemplo — Evento de sensor:**
```json
{
  "message_id": "uuid-v4",
  "sensor_id": "ESP_C5K3",
  "tipo_sensor": "espira",
  "interseccion": "INT_C5K3",
  "timestamp": "2026-04-01T22:00:00.000Z",
  "datos": {"vehiculos_por_minuto": 12},
  "auth_token": "sensor-token-ESP_C5K3"
}
```

Ver formato completo de todos los mensajes en la skill de diseño (Sección 5).

### 3.3 Diagrama de Componentes

Ver: [diagrama_componentes.md](./diagrama_componentes.md)

---

## 4. Modelo de Datos

### 4.1 Esquema de Base de Datos

El sistema utiliza 6 tablas SQLite:

| Tabla | Descripción | Registros por cuadrícula 5x5 |
|-------|-------------|------------------------------|
| `intersecciones` | Estado de cada intersección | 25 |
| `sensores` | Registro de sensores activos | 75 (3 por intersección) |
| `semaforos` | Estado actual de cada semáforo | 100 (4 por intersección) |
| `eventos` | Datos históricos de sensores | Creciente |
| `estado_trafico` | Evaluaciones de tráfico | Creciente |
| `acciones_semaforo` | Historial de cambios de luz | Creciente |

### 4.2 Protocolo de Replicación

- **Normal**: Main DB publica cada escritura vía PUB (port 5560). Replica DB suscribe y aplica.
- **Failover**: Si PC3 falla, Analytics escribe directamente en Replica DB.
- **Recuperación**: Replica DB envía datos faltantes a Main DB al recuperarse (basado en `sequence_number`).

---

## 5. Reglas de Tráfico

### 5.1 Definición Formal

**Tráfico Normal:**
```
Q < Q_MAX  AND  Vp > VP_MIN  AND  D < D_MAX
```

**Congestión Detectada:**
```
Q >= Q_MAX  OR  Vp <= VP_MIN  OR  D >= D_MAX
```

Donde:
- `Q` = Longitud de cola (vehículos en espera, dato de cámara)
- `Vp` = Velocidad promedio (km/h, dato de GPS)
- `D` = Densidad = N_veh / L_vía (veh/km, dato de GPS)

### 5.2 Umbrales Configurables

| Variable | Umbral | Valor por defecto | Configurable en |
|----------|--------|-------------------|-----------------|
| Q_MAX | Cola máxima | 5 vehículos | `config.json` |
| VP_MIN | Velocidad mínima | 35 km/h | `config.json` |
| D_MAX | Densidad máxima | 20 veh/km | `config.json` |

### 5.3 Manejo de Prioridades

- Override manual desde Monitoring Service (ej: paso de ambulancia)
- Requiere autenticación (`auth_token`) y verificación de origen
- El semáforo cambia inmediatamente a VERDE para la dirección solicitada

---

## 6. Tolerancia a Fallos

### 6.1 Mecanismo de Detección (Heartbeat)

- Main DB (PC3) envía heartbeat cada **5 segundos** vía PUB/SUB
- Analytics (PC2) monitorea en un thread separado
- Si no hay heartbeat por **15 segundos** (3 beats perdidos), declara PC3 como caído

### 6.2 Protocolo de Failover

1. Analytics detecta timeout del heartbeat
2. Activa flag `use_replica = True`
3. Redirige escrituras PUSH a Replica DB (PC2)
4. Monitoring queries se sirven desde Replica DB
5. El sistema continúa operando transparentemente

### 6.3 Protocolo de Recuperación

1. PC3 vuelve en línea, reanuda heartbeat
2. Analytics detecta heartbeat restaurado
3. Replica DB envía datos acumulados durante la falla a Main DB
4. Re-sincronización basada en `sequence_number`
5. `use_replica = False`, operación normal restaurada

### 6.4 Diagrama de Secuencia del Failover

Ver: [diagrama_secuencia.md](./diagrama_secuencia.md) — Flujo 3.

---

## 7. Seguridad

### 7.1 Modelo de Amenazas

| Amenaza | Impacto | Mitigación |
|---------|---------|------------|
| Suplantación de sensor | Datos falsos → decisiones incorrectas | Validación de `sensor_id` + `auth_token` |
| Manipulación de datos | Valores alterados en tránsito | Validación de rangos de datos |
| Comandos no autorizados | Override falso (ej: ambulancia falsa) | `auth_token` de admin + verificación de `origen` |

### 7.2 Mecanismos de Validación

- **Validación de esquema**: Verificación de campos obligatorios y tipos
- **Validación de identidad**: `sensor_id` debe existir en registro de sensores activos
- **Validación de token**: Cada sensor tiene un `auth_token` único
- **Validación de rango**: Datos fuera de rango físico son rechazados (ej: velocidad negativa)
- **Control de acceso**: Solo Monitoring Service puede enviar overrides

---

## 8. Diagramas UML

| Diagrama | Archivo | Notación |
|----------|---------|----------|
| Despliegue | [diagrama_despliegue.md](./diagrama_despliegue.md) | Mermaid |
| Componentes | [diagrama_componentes.md](./diagrama_componentes.md) | Mermaid |
| Clases | [diagrama_clases.md](./diagrama_clases.md) | Mermaid |
| Secuencia (3 flujos) | [diagrama_secuencia.md](./diagrama_secuencia.md) | Mermaid |

---

## 9. Código Fuente

### 9.1 Descripción de Módulos

| Módulo | Archivo | Responsabilidad |
|--------|---------|-----------------|
| Sensor Base | `pc1/sensor.py` | Clase abstracta para sensores |
| Sensor Espira | `pc1/sensor_espira.py` | Sensor de conteo vehicular |
| Sensor Cámara | `pc1/sensor_camara.py` | Sensor de longitud de cola |
| Sensor GPS | `pc1/sensor_gps.py` | Sensor de densidad y velocidad |
| Broker | `pc1/broker.py` | Proxy XPUB/XSUB |
| Analytics | `pc2/analytics_service.py` | Motor de reglas y procesamiento |
| Semáforos | `pc2/traffic_light_controller.py` | Control de estados de semáforos |
| Replica DB | `pc2/replica_db.py` | Servicio de BD réplica |
| Main DB | `pc3/main_db.py` | Servicio de BD principal |
| Monitoring | `pc3/monitoring_service.py` | CLI de consultas y overrides |
| Modelos | `shared/models.py` | Clases de datos para mensajes |
| Validación | `shared/validation.py` | Validación de mensajes |
| BD Utils | `shared/db_utils.py` | Gestión de base de datos |
| Constantes | `shared/constants.py` | Nomenclatura y constantes |

### 9.2 Instrucciones de Ejecución

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Iniciar PC3 (en terminal 1)
python pc3/start_pc3.py

# 3. Iniciar PC2 (en terminal 2)
python pc2/start_pc2.py

# 4. Iniciar PC1 (en terminal 3)
python pc1/start_pc1.py

# 5. Ejecutar tests
python -m tests.test_functional
python -m tests.test_failover
```

---

## 10. Conclusiones

### 10.1 Decisiones de Diseño Tomadas

- **ZeroMQ** como middleware de comunicación por su ligereza y soporte de múltiples patrones
- **SQLite** para persistencia por su simplicidad y replicabilidad
- **Procesos independientes** para sensores, garantizando aislamiento de fallos
- **Heartbeat + failover automático** para tolerancia a fallos transparente
- **Configuración centralizada** en `config.json` para flexibilidad

### 10.2 Preparación para Segunda Entrega

El diseño actual está preparado para la segunda entrega (multithreading):
- El Broker XPUB/XSUB puede reemplazarse con un broker ROUTER/DEALER con threads
- El Analytics Service puede extenderse con un pool de workers para procesamiento paralelo
- La comparación de rendimiento single-thread vs multi-thread es directa gracias a la modularidad
