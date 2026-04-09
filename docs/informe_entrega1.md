# Informe Primera Entrega — Gestión Inteligente de Tráfico Urbano

**Integrantes**: Juan Rodriguez, Nicolas Joya y Camila Beltran
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

Ver: [Diagrama de Despliegue](./diagramas_plantUML/diagrama_despliegue.png)

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

Ver: [Diagrama de Componentes](./diagramas_plantUML/diagrama_componentes.png)

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

- **Normal**: Main DB publica cada escritura vía PUB (puerto 5560). Replica DB suscribe y aplica.
- **Failover**: Si PC3 falla, Analytics deja de hacer PUSH a Main DB y **escribe directamente** en la SQLite réplica en PC2 (`DatabaseManager` local), no por un socket PUSH dedicado.
- **Recuperación**: Al volver el heartbeat de PC3, Analytics vuelve a modo Main (`use_replica = False`). **No** está implementado un protocolo automático de “backfill” desde Réplica → Main ni reconciliación por `sequence_number`; las réplicas pueden divergir hasta intervención manual o diseño futuro.

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

### 5.4 Tipos de Consulta del Usuario

El Servicio de Monitoreo (PC3) ofrece las siguientes operaciones al usuario a través de una CLI interactiva, comunicándose con el Analytics Service (PC2) mediante el patrón REQ/REP:

| # | Operación | Comando CLI | Descripción |
|---|-----------|-------------|-------------|
| 1 | Estado de intersección | `1 INT_C3K2` | Consulta puntual: devuelve el estado de tráfico actual de una intersección específica, incluyendo métricas (Q, Vp, D), estado de sus semáforos y último timestamp de evaluación |
| 2 | Estado general | `2` | Consulta global: devuelve un resumen del estado de tráfico de **todas** las intersecciones de la cuadrícula, permitiendo detectar zonas de congestión simultánea |
| 3 | Listar semáforos | `3` | Consulta de semaforización: lista todos los semáforos configurados en la cuadrícula con su estado actual (VERDE/ROJO), dirección e intersección asociada |
| 4 | Override manual | `4 SEM_C3K2_N VERDE ambulancia` | Indicación directa: fuerza el cambio de estado de un semáforo específico, independientemente de las reglas de tráfico |

**Ejemplos de indicaciones directas (Override):**

- **Paso de ambulancia:** `4 SEM_C1K1_N VERDE ambulancia` → Cambia el semáforo Norte de la intersección C1K1 a VERDE inmediatamente. Se registra con `razon = REASON_PRIORITY` en la tabla `acciones_semaforo`.
- **Cambio manual del operador:** `4 SEM_C3K2_E ROJO manual` → El operador fuerza el semáforo Este de C3K2 a ROJO. Se registra con `razon = REASON_MANUAL`.

Todas las operaciones imprimen por pantalla la respuesta del Analytics Service, incluyendo tipo de respuesta, mensaje descriptivo, datos JSON (cuando aplica) y timestamp.

---

## 6. Tolerancia a Fallos

### 6.1 Mecanismo de Detección (Heartbeat)

- Main DB (PC3) envía heartbeat cada **5 segundos** vía PUB/SUB
- Analytics (PC2) monitorea en un thread separado
- Si no hay heartbeat por **15 segundos** (3 beats perdidos), declara PC3 como caído

### 6.2 Protocolo de Failover

1. Analytics detecta timeout del heartbeat
2. Activa flag `use_replica = True`
3. Deja de enviar `TrafficState` por PUSH a Main DB; persiste eventos/estados (y overrides) vía **API SQLite** sobre la réplica en PC2
4. La lista de semáforos en monitoreo sigue leyendo la BD réplica (coherente con el diseño actual)
5. El sistema continúa operando; la transparencia completa frente a histórico en Main depende de no haber pérdida en el intervalo de caída

### 6.3 Protocolo de Recuperación

1. PC3 vuelve en línea y reanuda heartbeat y Main DB
2. Analytics detecta heartbeat restaurado y pone `use_replica = False`
3. Las nuevas escrituras vuelven al PUSH hacia Main DB
4. **No** hay en el código actual un paso automático que copie a Main DB todo lo escrito solo en réplica durante la caída; conviene asumir posible divergencia hasta una mejora explícita de sincronización

### 6.4 Diagrama de Secuencia del Failover

Ver: [Diagrama de Secuencia](./diagramas_plantUML/diagrama_secuencia.png) — Flujo 3.

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
- **Validación de token (sensores)**: Los eventos llevan `auth_token`; la validación estricta por token en Analytics puede ampliarse (hoy el registro en cuadrícula y prefijos son el filtro principal)
- **Validación de rango**: Datos fuera de rango físico son rechazados (ej: velocidad negativa)
- **Control de acceso**: Solo Monitoring Service puede enviar overrides

---

## 8. Inicialización de Recursos

### 8.1 Fuente de Configuración

Todos los procesos del sistema obtienen su definición inicial de recursos a partir del archivo centralizado `config.json`, ubicado en la raíz del proyecto. Cada script de arranque (`start_pc1.py`, `start_pc2.py`, `start_pc3.py`) lee este archivo al iniciar y extrae los parámetros necesarios para la creación dinámica de componentes.

### 8.2 Parámetros Configurables

| Parámetro | Clave en `config.json` | Ejemplo | Efecto |
|-----------|----------------------|---------|--------|
| Tamaño de la cuadrícula | `grid.columns`, `grid.rows` | `5, 5` | Determina N×M intersecciones |
| Frecuencia de sensores | `sensor_frequency_seconds` | `5` | Intervalo entre eventos generados (segundos) |
| Método de generación | `load_generation` | `"random"` | Generador aleatorio o desde archivo |
| Umbrales de congestión | `thresholds.Q_MAX`, `VP_MIN`, `D_MAX` | `5, 35, 20` | Parámetros del motor de reglas |
| Intervalo de heartbeat | `heartbeat_interval_seconds` | `5` | Frecuencia del latido de PC3 |
| Timeout de heartbeat | `heartbeat_timeout_seconds` | `15` | Tiempo máximo sin heartbeat para declarar fallo |
| Puertos ZMQ | `zmq_ports.*` | `5555–5561` | Puertos de cada canal de comunicación |
| Hosts de los PCs | `pc1_host`, `pc2_host`, `pc3_host` | `"localhost"` o IP | Dirección de cada nodo para modo distribuido |
| Rangos de datos | `data_ranges.*` | `{min: 0, max: 30}` | Límites para generación aleatoria de datos |
| Probabilidad de pico | `congestion_spike_probability` | `0.10` | Probabilidad de generar valores extremos de congestión |
| Tokens de autenticación | `auth_tokens.*` | — | Prefijo de tokens de sensores y token de monitoreo |

### 8.3 Proceso de Inicialización por Nodo

**PC1 — Generación de Datos:**
1. Lee `grid.columns` (N) y `grid.rows` (M) de `config.json`.
2. Inicia 1 proceso Broker (XPUB/XSUB).
3. Para cada intersección `INT_C{c}K{r}` (c ∈ [1,N], r ∈ [1,M]), genera 3 procesos sensor independientes: `ESP_CcKr`, `CAM_CcKr`, `GPS_CcKr`.
4. **Total de procesos:** 1 Broker + (N × M × 3) sensores.

**PC3 — Persistencia:**
1. Lee la configuración de cuadrícula y puertos.
2. Inicializa la base de datos principal (`main_traffic.db`) ejecutando el esquema SQL.
3. Ejecuta la función `seed_all()` que registra automáticamente:
   - N × M intersecciones en la tabla `intersecciones`.
   - N × M × 3 sensores en la tabla `sensores`.
   - N × M × 4 semáforos en la tabla `semaforos` (4 direcciones: N, S, E, W por intersección), con estados iniciales alternos (VERDE/ROJO) para evitar conflictos.
4. Inicia el servicio de Heartbeat (PUB, cada 5 segundos) y el socket PULL para recibir datos del Analytics.

**PC2 — Analítica y Control:**
1. Lee la configuración completa.
2. Inicializa la base de datos réplica (`replica_traffic.db`) con el mismo esquema y seed.
3. Conecta los sockets SUB al Broker (PC1), REP para Monitoring (PC3), PUSH para Main DB (PC3), SUB para Heartbeat, y SUB para replicación.
4. Inicia el Traffic Light Controller (SUB) y el Replica DB Service (SUB).

### 8.4 Generación de Datos de Sensores

Se utiliza **generación aleatoria** (Opción A) para la primera entrega:
- Los valores se generan con `random.uniform()` dentro de los rangos definidos en `data_ranges` de `config.json`.
- Un 10% de los eventos se generan como "picos de congestión" con valores extremos para forzar la activación de las reglas.
- La frecuencia de publicación es configurable (`sensor_frequency_seconds`, por defecto 5 segundos).
- Cada sensor genera un mensaje JSON completo con `message_id` (UUID), `sensor_id`, `timestamp`, `datos` y `auth_token`.

---

## 9. Diagramas UML

Las fuentes editables están en `docs/diagramas_plantUML/*.md` (bloques `plantuml`). Los `.png` son vistas exportadas: si cambias el texto UML, **vuelve a generar los PNG** con tu herramienta PlantUML para que coincidan con el código.

| Diagrama | Archivo | Notación |
|----------|---------|----------|
| Despliegue | [diagrama_despliegue.png](./diagramas_plantUML/diagrama_despliegue.png) | PlantUML (Renderizado) |
| Componentes | [diagrama_componentes.png](./diagramas_plantUML/diagrama_componentes.png) | PlantUML (Renderizado) |
| Clases | [diagrama_clases.png](./diagramas_plantUML/diagrama_clases.png) | PlantUML (Renderizado) |
| Secuencia (3 flujos) | [diagrama_secuencia.png](./diagramas_plantUML/diagrama_secuencia.png) | PlantUML (Renderizado) |

---

## 10. Protocolo de Pruebas

### 10.1 Pruebas Funcionales

Estas pruebas validan que cada componente del sistema opera correctamente de forma individual y en su interacción con los demás.

| ID | Prueba | Descripción | Resultado Esperado |
|----|--------|-------------|--------------------|
| F1 | Publicación de sensores | Cada sensor genera y envía un evento JSON al Broker | El Broker recibe el evento y lo reenvía sin pérdida |
| F2 | Recepción en Analytics | Analytics recibe eventos reenviados por el Broker | El evento se procesa, se valida y se evalúan las reglas |
| F3 | Detección de congestión | Se envían datos que cumplen `Q ≥ 5 O Vp ≤ 35 O D ≥ 20` | Analytics genera una acción de cambio de semáforo a VERDE |
| F4 | Tráfico normal | Se envían datos dentro de rangos normales | No se genera cambio de semáforo; estado permanece igual |
| F5 | Override manual | El usuario envía un override desde Monitoring CLI | El semáforo cambia inmediatamente y se registra en BD |
| F6 | Mensaje inválido | Se envía un evento con sensor_id inexistente o datos fuera de rango | El mensaje es rechazado y se registra en el log |
| F7 | Persistencia en BD | Analytics procesa un evento y lo envía a Main DB | El evento se almacena correctamente en la tabla `eventos` |
| F8 | Replicación normal | Main DB recibe un dato y publica la réplica | Replica DB recibe y aplica el dato; ambas BDs son consistentes |
| F9 | Consulta de intersección | El usuario consulta estado de una intersección específica | Se devuelve estado de tráfico, métricas y semáforos actuales |
| F10 | Consulta general | El usuario solicita estado general | Se devuelve resumen de todas las intersecciones |

### 10.2 Pruebas de Tolerancia a Fallos

Estas pruebas verifican que el sistema continúa operando correctamente ante la falla de PC3.

| ID | Prueba | Descripción | Resultado Esperado |
|----|--------|-------------|--------------------|
| FT1 | Detección de caída | Se apaga el proceso de PC3 (Main DB) | Analytics detecta la ausencia de heartbeat tras 15 segundos y activa `use_replica = True` |
| FT2 | Operación en failover | Se envían eventos con PC3 caído | Analytics persiste datos directamente en la BD réplica de PC2; el sistema continúa operando |
| FT3 | Consulta durante failover | El usuario realiza una consulta desde Monitoring | La consulta se responde correctamente usando datos de la BD réplica |
| FT4 | Recuperación de PC3 | Se reinicia PC3 y reanuda heartbeat | Analytics detecta el heartbeat restaurado y pone `use_replica = False`; las nuevas escrituras van a Main DB |
| FT5 | Transparencia al usuario | El usuario opera la CLI antes, durante y después del failover | Las respuestas mantienen el mismo formato; la funcionalidad no se ve afectada |

**Nota sobre la ejecución de FT3 y FT5:** Dado que `start_pc3.py` lanza tanto Main DB como el Monitoring CLI en un mismo script, al cerrar PC3 completamente se perdería también la interfaz de usuario. Para ejecutar estas pruebas, se lanzan los procesos de PC3 en **terminales independientes** en lugar de usar el launcher:

```bash
# Terminal A — Main DB (este es el proceso que se matará para simular la falla)
python pc3/main_db.py

# Terminal B — Monitoring CLI (permanece activo durante todo el failover)
python pc3/monitoring_service.py
```

La falla simulada consiste en cerrar únicamente la **Terminal A** (`main_db.py`). Como el Monitoring CLI se conecta directamente a Analytics (PC2) vía REQ/REP y no depende de Main DB, la Terminal B permanece operativa y permite realizar consultas durante el failover. Analytics detecta la ausencia de heartbeat y responde las consultas usando la BD réplica de PC2.

---

## 11. Obtención de Métricas de Rendimiento

### 11.1 Métrica 1: Solicitudes Almacenadas en BD en 2 Minutos

**Definición:** Cantidad total de registros insertados en la tabla `eventos` de la base de datos durante un intervalo fijo de 2 minutos de ejecución del sistema.

**Metodología de medición:**
1. Antes de iniciar la prueba, se ejecuta `SELECT COUNT(*) FROM eventos` para obtener el conteo base (`count_inicio`).
2. Se inician los 3 PCs y se deja el sistema operando durante exactamente 120 segundos. El tiempo se controla con la librería `time` de Python (`time.time()` para marcas de inicio y fin).
3. Al finalizar los 120 segundos, se detienen los sensores y se ejecuta nuevamente `SELECT COUNT(*) FROM eventos` para obtener `count_fin`.
4. **Resultado:** `solicitudes_almacenadas = count_fin - count_inicio`.
5. Se repite el experimento 3 veces por escenario y se reporta el promedio.

**Herramientas:**
- `time.time()` de Python para control de intervalos.
- Consultas SQL directas sobre la base de datos SQLite (`db_utils.get_event_count()`).
- Script de prueba automatizado en `tests/` que orquesta el arranque, espera y conteo.

### 11.2 Métrica 2: Tiempo de Respuesta de Override (Latencia End-to-End)

**Definición:** Tiempo transcurrido desde que el usuario envía un comando de override desde el Monitoring Service hasta que el Traffic Light Controller confirma el cambio de estado del semáforo.

**Metodología de medición:**
1. Se registra el timestamp de alta resolución (`time.perf_counter()`) justo **antes** de enviar el mensaje REQ desde el Monitoring Service.
2. Se registra el timestamp justo **después** de recibir la respuesta REP del Analytics Service (que confirma que el override fue procesado y el comando de cambio fue enviado al Controller).
3. **Resultado:** `latencia_ms = (t_respuesta - t_envio) * 1000`.
4. Se realizan al menos 10 overrides por escenario y se reportan: promedio, mínimo, máximo y desviación estándar.

**Herramientas:**
- `time.perf_counter()` de Python para medición de alta resolución (microsegundos).
- Logging con timestamps en cada componente para trazabilidad del recorrido del mensaje.
- Script de prueba en `tests/` que envía overrides programáticos y mide la latencia.

### 11.3 Presentación de Resultados

Los resultados se presentarán en:
- **Tablas comparativas** con el formato de la Tabla 1 del enunciado (diseño original vs. diseño multihilos).
- **Gráficos de barras** comparando solicitudes almacenadas por escenario.
- **Gráficos de líneas** mostrando la latencia de override en función de la carga.
- **Análisis escrito** comentando los resultados, identificando cuellos de botella y justificando cuál diseño es más escalable.

---

## 12. Código Fuente

### 12.1 Descripción de Módulos

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

### 12.2 Instrucciones de Ejecución

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
python -m pytest tests/ -q
```

---

## 13. Conclusiones

### 13.1 Decisiones de Diseño Tomadas

- **ZeroMQ** como middleware de comunicación por su ligereza y soporte de múltiples patrones
- **SQLite** para persistencia por su simplicidad y replicabilidad
- **Procesos independientes** para sensores, garantizando aislamiento de fallos
- **Heartbeat + failover automático** para tolerancia a fallos (lectura/escritura en réplica; recuperación sin backfill automático hacia Main)
- **Configuración centralizada** en `config.json` para flexibilidad

### 13.2 Preparación para Segunda Entrega

El diseño actual está preparado para la segunda entrega (multithreading):
- El Broker XPUB/XSUB puede reemplazarse con un broker ROUTER/DEALER con threads
- El Analytics Service puede extenderse con un pool de workers para procesamiento paralelo
- La comparación de rendimiento single-thread vs multi-thread es directa gracias a la modularidad
