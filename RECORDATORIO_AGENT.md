# RECORDATORIO_AGENT — Gestión Inteligente de Tráfico Urbano

Este archivo contiene el contexto completo del proyecto desarrollado para la **Primera Entrega** de Sistemas Distribuidos (Semana 10). Sirve como memoria operativa para retomar el trabajo en futuras sesiones.

## 📌 Resumen del Proyecto
Sistema distribuido de gestión de tráfico mediante una cuadrícula de intersecciones inteligente, utilizando **ZeroMQ** para comunicación asíncrona y robusta.

- **Arquitectura:** 3 PCs (Nodos distribuibles).
- **Middleware:** ZeroMQ (pyzmq).
- **Persistencia:** SQLite (Main DB + Replica DB).
- **Tolerancia a Fallos:** Heartbeat + Failover automático + Replicación.

---

## 🏗️ Arquitectura y Nodos

### PC1: Generación de Datos
- **Broker (XPUB/XSUB):** Centraliza la mensajería de sensores hacia el motor de analítica.
- **Sensores:** Procesos independientes para `Espira`, `Cámara` y `GPS`.
  - Notación: `TIPO_CxKy` (ej: `ESP_C1K1`).
  - Publican en: `sensor/tipo/CxKy`.

### PC2: Analítica y Control
- **Analytics Service:** Motor de reglas (Q, Vp, D), validación de mensajes y failover.
- **Traffic Light Controller:** Administra los semáforos (`SEM_CxKy_DIR`).
- **Replica DB:** Actúa como respaldo activo cuando PC3 falla.

### PC3: Monitoreo y Persistencia
- **Main DB:** Almacenamiento histórico, envía Heartbeat cada 5s.
- **Monitoring Service (CLI):** Interfaz para consultas (`REQ/REP`) y overrides manuales.

---

## 📂 Estructura de Archivos

```
entrega1_proyecto/
├── pc1/                # Broker + Sensores
├── pc2/                # Analytics + Controller + ReplicaDB
├── pc3/                # MainDB + Monitoring
├── shared/             # Modelos (dataclasses), Constantes, DB Utils, Validación
├── tests/              # Functional (23 tests) + Failover (7 tests)
├── docs/               # Diagramas Mermaid (UML) e Informe
├── data/               # Bases de datos .db (ignorado por git usualmente)
├── config.json         # Configuración central del sistema
└── README.md           # Guía rápida de uso
```

---

## 🛠️ Detalles Técnicos Clave

### Patrones ZMQ
- **PUB/SUB:** Sensores → Broker, Analytics → Controller, Replicación, Heartbeat.
- **PUSH/PULL:** Analytics → DB (Asíncrono).
- **REQ/REP:** Monitoring ↔ Analytics (Síncrono).
- **XPUB/XSUB:** Broker Proxy.

### Lógica de Failover
1. **Detección:** Analytics espera `Heartbeat` de MainDB (PC3).
2. **Timeout:** Si pasan >15s sin beat, activa `use_replica = True`.
3. **Acción:** Analytics empieza a escribir directamente en la base de datos de réplica en PC2.
4. **Recuperación:** Al volver el heartbeat, la Réplica sincroniza los datos faltantes con la MainDB.

### Notación Estricta
- **Intersección:** `INT_CxKy` (C=Columna, K=Calle/Row).
- **Semáforo:** `SEM_CxKy_DIR` (DIR=N, S, E, W).
- **Sensor:** `ESP_CxKy`, `CAM_CxKy`, `GPS_CxKy`.

---

## 🎨 Documentación y Visualización (Nueva Versión)
Se ha migrado toda la documentación visual de Mermaid a **PlantUML** para mayor flexibilidad y estética profesional.

- **Ubicación:** `docs/diagramas_plantUML/`
- **Estética:** Tema `cerulean-outline` con paleta de colores corporativa.
- **Diagramas Disponibles:** Despliegue, Clases, Componentes y Secuencia (Normal, Override, Failover).
- **Exportación HD:** 
  - Usar comando `PlantUML: Export Current Diagram` en VS Code.
  - Para alta resolución (PNG/SVG), asegurar `skinparam dpi 300` en el código.

### Correcciones de Arquitectura Realizadas:
- **Replica DB:** Confirmada su ejecución en **PC2** (no PC3) para garantizar persistencia local durante caídas de red/PC3.
- **Topología Heartbeat:** Se eliminó la conexión errónea hacia `MonitoringService`. El heartbeat de PC3 es consumido únicamente por **PC2 (Analytics)** para el failover.
- **Ubicación Clases Shared:** `DatabaseManager` y `MessageValidator` se encuentran en el paquete `shared/` (`db_utils.py` y `validation.py`).

---

## 🚀 Cómo Iniciar el Sistema (3 Terminales)

1. **PC3:** `python pc3/start_pc3.py` (Inicia DB y abre el CLI de Monitoreo).
2. **PC2:** `python pc2/start_pc2.py` (Inicia motor de analítica y controlador).
3. **PC1:** `python pc1/start_pc1.py` (Inicia broker y sensores).

### Verificación (Tests)
- `python -m tests.test_functional`
- `python -m tests.test_failover`

---

## ⏭️ Próximos Pasos (Segunda Entrega)
- [ ] **Multithreading:** Implementar `ThreadPoolExecutor` en el Analytics Service.
- [ ] **Performance:** Medir latencia (End-to-End) desde sensor hasta cambio de semáforo.
- [ ] **Escalabilidad:** Estresar el Broker con cuadrículas mayores (ej: 5x5 o 10x10).

---
*Ultima actualización: 2026-04-02 — Migración exitosa a PlantUML y validación de consistencia técnica.*
