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
    - Terminal 1: `python pc3/start_pc3.py`
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

**Cuadrícula e IDs:** El tamaño de la ciudad viene de `config.json` → `grid.columns` y `grid.rows`. Con la configuración por defecto (**2×2**), las intersecciones válidas son `INT_C1K1`, `INT_C1K2`, `INT_C2K1`, `INT_C2K2` y los semáforos siguen el formato `SEM_C{col}K{fila}_{N|S|E|W}` (por ejemplo `SEM_C1K1_N`). Si amplías la cuadrícula, ajusta los ejemplos para usar solo IDs que existan en tu `config.json`.

| Comando | Acción | Ejemplo (cuadrícula 2×2) |
| :--- | :--- | :--- |
| **1** | Consulta el estado de una intersección específica. | `1 INT_C1K1` |
| **2** | Consulta el estado general de toda la cuadrícula. | `2` |
| **3** | Lista todos los semáforos activos del sistema. | `3` |
| **4** | Fuerza un cambio de semáforo (Override manual). | `4 SEM_C1K1_N VERDE ambulancia` |
| **5** | Cierra el servicio de monitoreo de forma segura. | `5` |

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
