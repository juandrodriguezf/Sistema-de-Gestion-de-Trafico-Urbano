# 🚦 Guía de Operación — Gestión Inteligente de Tráfico Urbano

Este documento detalla la configuración y ejecución del sistema distribuido de control de tráfico para la evaluación del proyecto.

## 🛠️ Requisitos Previos

- **Python 3.9+** instalado en las 3 máquinas o entornos virtuales.
- **Librería ZeroMQ**: Instalable mediante `pip install pyzmq`. 
- **Acceso de Red:** Asegurar que los puertos definidos en `config.json` estén abiertos (Default: 5555-5561).

---

## 🖥️ Distribución de Archivos por Nodo (PC)

Para que el sistema funcione de forma distribuida, cada PC debe contener la carpeta del proyecto, pero solo ejecutará programas específicos. **Todos los nodos necesitan la carpeta `shared/` y el archivo `config.json`**.

### **PC1: Ingesta y Broker**
- **Carpeta `pc1/`**: Contiene dos versiones del Broker (XPUB/XSUB):
  - `broker.py` — Original con `zmq.proxy()` (por defecto).
  - `broker_threaded.py` — Versión multihilos con `Poller` + `Queue`.
- **Carpeta `shared/`**: Lógica de validación y modelos.
- **Archivo `config.json`**: Direcciones IP de los otros nodos y selección de broker.
*   **Ejecución:**
    ```bash
    python pc1/start_pc1.py                # Broker original (zmq.proxy())
    python pc1/start_pc1.py --threaded     # Broker multihilos
    ```

### **PC2: Analítica y Control (PC de Respaldo)**
- **Carpeta `pc2/`**: Contiene el motor de reglas de analítica, el controlador de semáforos y la **Base de Datos de Réplica**.
- **Carpeta `shared/`**: Lógica de DB y validación.
- **Archivo `config.json`**.
*   **Ejecución:** `python pc2/start_pc2.py`

### **PC3: Persistencia, Monitoreo y Visores (Nodo Maestro)**
- **Carpeta `pc3/`**: Contiene la **Base de Datos Principal**, el servicio de Monitoreo (CLI), el **LiveViewer** (dashboard TUI) y el **TraceabilityViewer** (tabla `eventos` en vivo).
- **Carpeta `shared/`**: Motor de base de datos.
- **Archivo `config.json`**.
*   **Ejecución:**
    ```bash
    python pc3/start_pc3.py                          # solo DB + CLI monitoreo
    python pc3/start_pc3.py --live                   # + dashboard TUI
    python pc3/start_pc3.py --trace                  # + tabla eventos en vivo
    python pc3/start_pc3.py --live --trace           # ambos visores
    ```

---

## 🎮 Escenarios de Simulación

Puedes ejecutar este sistema en dos modalidades dependiendo de tu entorno de prueba:

### **Opción A: Simulación en un solo computador (Local)**
Ideal para desarrollo o pruebas rápidas. Los 3 servicios ("PCs") correrán como procesos independientes en la misma máquina.
1.  **Configuración:** Abre `config.json` y asegúrate de que los hosts sean `"localhost"`:
    ```json
    "pc1_host": "localhost",
    "pc2_host": "localhost",
    "pc3_host": "localhost"
    ```
2.  **Ejecución:** Abre **3 terminales** diferentes y ejecuta los scripts en el orden establecido:
    - Terminal 1: `python pc3/start_pc3.py` (opcional: `--live`, `--trace`)
    - Terminal 2: `python pc2/start_pc2.py`
    - Terminal 3: `python pc1/start_pc1.py`
    
    *Si automatizas el arranque con `subprocess` en Python, no uses `stdout=PIPE` sin consumir la salida: el volumen de logs puede llenar el buffer y bloquear los procesos.*

### **Opción B: Simulación en 3 computadores (Distribuida)**
Requerida para la sustentación final y pruebas de red.
1.  **Red Local:** Asegúrate de que los 3 computadores estén en la misma red Wi-Fi/LAN y se puedan hacer `ping` entre ellos.
2.  **Configuración:** En cada PC, edita el archivo `config.json` con las **IPs reales** asignadas:
    ```json
    "pc1_host": "192.168.1.10",  // IP del PC de Sensores
    "pc2_host": "192.168.1.11",  // IP del PC de Analítica
    "pc3_host": "192.168.1.12"   // IP del PC de Persistencia
    ```
    *Nota: El archivo `config.json` debe ser idéntico en las 3 máquinas.*
3.  **Ejecución:** Sigue el mismo orden de encendido en cada máquina física.

---

## 🚀 Orden de Ejecución (¡IMPORTANTE!)

Para evitar errores de conexión inicial, el sistema debe encenderse en este orden:

1.  **PC3 (Persistencia):** Debe estar listo para recibir datos históricos y emitir el Heartbeat.
2.  **PC2 (Analítica):** Se conecta a PC3 para verificar el estado de la base de datos principal.
3.  **PC1 (Datos):** Una vez los servicios de procesamiento están listos, se enciende el Broker y se inician las mediciones de los sensores.

---

## 🎮 Uso del Servicio de Monitoreo (CLI en PC3)

El programa en PC3 abrirá una interfaz de línea de comandos tras iniciar la base de datos. Comandos disponibles:

**Cuadrícula e IDs:** El tamaño de la ciudad viene de `config.json` → `grid.columns` y `grid.rows`. Con la configuración por defecto (**5×3**), las intersecciones válidas son `A1`, `B2`, `C3`, `D4`, `E5` (columna + fila). Los semáforos siguen el formato `SEM_{letra}{fila}_{N|S|E|W}` (por ejemplo `SEM_A1_N`). Si amplías la cuadrícula, ajusta los ejemplos para usar solo IDs que existan en tu `config.json`.

| Comando | Acción | Ejemplo (cuadrícula 5×3) |
| :--- | :--- | :--- |
| **1** | Consulta el estado de una intersección específica. | `1 B2` |
| **2** | Consulta el estado general de toda la cuadrícula. | `2` |
| **3** | Lista todos los semáforos activos del sistema. | `3` |
| **4** | Fuerza un cambio de semáforo (Override manual). | `4 SEM_B2_N VERDE ambulancia` |
| **5** | Consulta histórica de una intersección. | `5 A1` |
| **6** | Cierra el servicio de monitoreo de forma segura. | `6` |

---

## 📺 Visores en Vivo (PC3)

PC3 incluye dos visores opcionales que se lanzan con flags en `start_pc3.py`:

### LiveViewer (`--live`)
Dashboard TUI con **Rich** que se actualiza cada 2 segundos. Muestra tres paneles:
- Eventos recientes de sensores (con hora local)
- Estado actual de cada intersección
- Estado de todos los semáforos

### TraceabilityViewer (`--trace`)
Tabla que refleja **literalmente** la tabla `eventos` de SQLite, actualizada cada 1 segundo. Cada fila nueva aparece resaltada en verde. El `evento_id` se trunca a 8 caracteres para coincidir con el ID mostrado en los logs de PC1.

**Nota:** Ambos visores convierten automáticamente los timestamps UTC almacenados en la BD a la hora local del sistema.

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
├── pc1/ (start_pc1.py, broker.py, broker_threaded.py, sensor_*.py)
├── pc2/ (start_pc2.py, analytics_service.py, traffic_light_controller.py, replica_db.py)
├── pc3/ (start_pc3.py, main_db.py, monitoring_service.py, live_viewer.py, traceability_viewer.py)
├── shared/ (db_utils.py, validation.py, models.py, constants.py)
├── tests/ (test_functional.py, run_experiments.py, ...)
├── data/ (Bases de datos SQLite + gráficas de experimentos)
├── docs/ (Diagramas UML + informes)
└── config.json (Configuración de IPs y Puertos)
```
