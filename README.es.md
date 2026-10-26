# F1 Strategy Agent

[English](README.md)

Una plataforma de Fórmula 1 que se está reconstruyendo por fases: un pipeline que ingiere sesiones históricas de OpenF1 y las reproduce como si fueran en vivo, un simulador de estrategia con un modelo predictivo de neumáticos y tiempos de vuelta, y un asistente que responde con datos que recuperó y los cita. El plan, el estándar que sigue el código y la fase actual están en [AGENTS.md](AGENTS.md).

## Qué existe hoy

Fase 0, la base:

- **Backend** (`backend/`): Python 3.12, FastAPI, un endpoint, `GET /api/health`. En capas: dominio, aplicación y adaptadores; `import-linter` rompe el build si una capa interna importa una externa.
- **Frontend** (`frontend/`): React, Vite y TypeScript en modo estricto. Muestra el estado de la API mediante un cliente generado a partir del esquema OpenAPI del backend.
- **Infraestructura** (`infra/compose.yaml`): PostgreSQL con pgvector, MongoDB, el backend y el frontend. Las bases de datos corren, pero todavía nada lee ni escribe en ellas.
- **CI** (`.github/workflows/ci.yml`): las mismas comprobaciones que `make check` en cada pull request, una comprobación de que el cliente generado coincide con la API y una prueba de humo del stack completo.

La ingesta, el simulador y el asistente todavía no existen.

## Ejecutarlo en local

Requisitos: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22 y GNU Make.

```sh
cp .env.example .env
make up
```

Abre http://localhost:8080. `make down` detiene el stack.

## Desarrollo

```sh
make install   # dependencias del backend y del frontend
make check     # lint, formato, tipos, reglas de capas, tests con cobertura, build, contrato de la API
make format    # aplica los formateadores
make openapi   # regenera el cliente de la API del frontend tras cambiar un endpoint
```

## Cómo se construye

Las decisiones están registradas en [docs/adr/](docs/adr/README.md). Cada sesión de trabajo con el agente de IA deja una entrada en [docs/devlog/](docs/devlog/README.md).
