# 🚦 Guía de Operación — Gestión Inteligente de Tráfico Urbano (Entrega 1)

Este documento detalla la configuración y ejecución del sistema distribuido de control de tráfico para la evaluación del proyecto.

## 🛠️ Requisitos Previos

- **Python 3.9+** instalado en las 3 máquinas o entornos virtuales.
- **Librería ZeroMQ**: Instalable mediante `pip install pyzmq`. 
- **Acceso de Red:** Asegurar que los puertos definidos en `config.json` estén abiertos (Default: 5555-5562).

---

## 🖥️ Distribución de Archivos por Nodo (PC)

Para que el sistema funcione de forma distribuida, cada PC debe contener la carpeta del proyecto, pero solo ejecutará programas específicos. **Todos los nodos necesitan la carpeta `shared/` y el archivo `config.json`**.

### **PC1: Ingesta y Broker**
- **Carpeta `pc1/`**: Contiene el Broker (XPUB/XSUB) y los procesos de simulación de sensores.
- **Carpeta `shared/`**: Lógica de validación y modelos.
- **Archivo `config.json`**: Direcciones IP de los otros nodos.
*   **Ejecución:** `python pc1/start_pc1.py`

### **PC2: Analítica y Control (PC de Respaldo)**
- **Carpeta `pc2/`**: Contiene el motor de reglas de analítica, el controlador de semáforos y la **Base de Datos de Réplica**.
- **Carpeta `shared/`**: Lógica de DB y validación.
- **Archivo `config.json`**.
*   **Ejecución:** `python pc2/start_pc2.py`

### **PC3: Persistencia y Monitoreo (Nodo Maestro)**
- **Carpeta `pc3/`**: Contiene la **Base de Datos Principal** y el servicio de Monitoreo (CLI).
- **Carpeta `shared/`**: Motor de base de datos.
- **Archivo `config.json`**.
*   **Ejecución:** `python pc3/start_pc3.py`

---

## 🚀 Orden de Ejecución (¡IMPORTANTE!)

Para evitar errores de conexión inicial, el sistema debe encenderse en este orden:

1.  **PC3 (Persistencia):** Debe estar listo para recibir datos históricos y emitir el Heartbeat.
2.  **PC2 (Analítica):** Se conecta a PC3 para verificar el estado de la base de datos principal.
3.  **PC1 (Datos):** Una vez los servicios de procesamiento están listos, se enciende el Broker y se inician las mediciones de los sensores.

---

## 🎮 Uso del Servicio de Monitoreo (CLI en PC3)

El programa en PC3 abrirá una interfaz de línea de comandos tras iniciar la base de datos. Comandos disponibles:

| Comando | Acción |
| :--- | :--- |
| `status` | Consulta el estado general de todas las intersecciones. |
| `history [INT_ID]` | Muestra los registros históricos de una intersección específica (ej: `history INT_A1`). |
| `override [SEM_ID] [STATE]` | Fuerza un cambio de semáforo (ej: `override SEM_A1_N GREEN`). |
| `exit` | Cierra el servicio de monitoreo de forma segura. |

---

## 🛡️ Escenario de Fallo (Failover)

Para demostrar la tolerancia a fallos exigida en la rúbrica:

1.  Mantén el sistema funcionando y observa la terminal de **PC2 (Analytics)**; verás el mensaje `"Recibiendo Heartbeat de PC3..."`.
2.  Detén manualmente el proceso de **PC3** (Ctrl+C).
3.  Tras 15 segundos (configurable), **PC2** detectará la falta de heartbeat y activará la `Replica DB` local.

---

## 📂 Estructura de Carpetas

```text
entrega1_proyecto/
├── pc1/ (start_pc1.py, broker.py, sensor_*.py)
├── pc2/ (start_pc2.py, analytics_service.py, traffic_light_controller.py, replica_db.py)
├── pc3/ (start_pc3.py, main_db.py, monitoring_service.py)
├── shared/ (db_utils.py, validation.py, models.py, constants.py)
├── data/ (Carpeta para bases de datos SQLite)
├── docs/ (Diagramas UML de diseño)
└── config.json (Configuración de IPs y Puertos)
```
