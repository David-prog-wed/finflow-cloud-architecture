# ⚡ FinFlow Cloud - Arquitectura de Software Escalable

Prototipo funcional desarrollado para la **Actividad 2: Orquestando códigos: La sinfonía de los sistemas**. Implementa una arquitectura _Cloud-Native_ contenerizada para la gestión presupuestal corporativa.

## 🏗️ Arquitectura y Patrones Implementados

- **Gateway Routing & Offloading:** Proxy inverso con **Nginx** que unifica el acceso estático y enruta peticiones hacia la red interna de contenedores.
- **Health Endpoint Monitoring:** Diagnóstico automatizado en `/api/v1/health` integrado con Docker Compose `healthcheck`.
- **External Configuration Store:** Parametrización mediante variables de entorno (`MONTHLY_BUDGET_LIMIT`, `DATABASE_PATH`).
- **Repository Pattern, DTO & Dependency Injection:** Backend en **Python (FastAPI)** desacoplado en capas limpias con validación estricta mediante Pydantic.

## 🚀 Despliegue Rápido en la Nube / Local (Docker)

1. Clonar el repositorio:
   ```bash
   git clone https://github.com/David-prog-wed/finflow-cloud-architecture.git
   cd finflow-cloud-architecture
   ```
