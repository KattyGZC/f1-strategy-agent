# F1 Strategy Agent

[English](README.md)

Una plataforma de Fórmula 1 que se está reconstruyendo por fases: un pipeline que ingiere sesiones históricas de OpenF1 y las reproduce como si fueran en vivo, un simulador de estrategia con un modelo predictivo de neumáticos y tiempos de vuelta, y un asistente que responde con datos que recuperó y los cita. El plan, el estándar que sigue el código y la fase actual están en [AGENTS.md](AGENTS.md).

## Qué existe hoy

Fase 0, la base:

- **Backend** (`backend/`): Python 3.12, FastAPI, un endpoint, `GET /api/health`. En capas: dominio, aplicación y adaptadores; `import-linter` rompe el build si una capa interna importa una externa.
- **Frontend** (`frontend/`): React, Vite y TypeScript en modo estricto. Muestra el estado de la API mediante un cliente generado a partir del esquema OpenAPI del backend.
- **Infraestructura** (`infra/compose.yaml`): PostgreSQL con pgvector, MongoDB, el backend y el frontend. Las bases de datos corren, pero todavía nada lee ni escribe en ellas.
- **CI** (`.github/workflows/ci.yml`): las mismas comprobaciones que `make check` en cada pull request, una comprobación de que el cliente generado coincide con la API y una prueba de humo del stack completo.

Fase 1, la ingesta:

- **Datos crudos de OpenF1 en MongoDB**: cada respuesta de las sesiones de carrera y clasificación de una temporada, un documento por petición, identificado por el endpoint y sus parámetros. Una sesión se ingiere cuando terminó hace al menos `SESSION_SETTLE_H` horas (6 por defecto), así que también funciona con la temporada en curso: lánzalo de nuevo tras un fin de semana de carrera y añade solo las sesiones nuevas. El cliente respeta el límite gratuito de OpenF1 (3 peticiones por segundo, 30 por minuto) y solo reintenta los errores que pueden salir bien al repetir.
- **Telemetría del coche** (`car_data`, `location`) del último Gran Premio asentado, por piloto en ventanas de 30 minutos. Solo se guarda la telemetría de una sesión: cuando una nueva queda guardada completa, se borra la anterior, porque cada carrera pesa unos 150 MB y el plan gratuito de MongoDB tiene 512 MB ([ADR 0007](docs/adr/0007-telemetry-of-the-latest-grand-prix.md)).

El modelo limpio, el replay, el simulador y el asistente todavía no existen.

## Ejecutarlo en local

Requisitos: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22 y GNU Make.

```sh
cp .env.example .env
make up
```

Abre http://localhost:8080. `make down` detiene el stack.

Con el stack levantado, ingiere datos crudos:

```sh
make ingest YEAR=2026              # sesiones de carrera y clasificación asentadas, unos 20 minutos por temporada completa
make ingest-telemetry              # car_data y location del último Gran Premio asentado
make ingest-telemetry SESSION=9472 # o de otra sesión (carrera de Baréin 2024); cualquiera reemplaza la telemetría guardada
```

Si una ejecución falla, termina con código 1 y una línea que dice qué petición falló. Vuelve a lanzar el mismo comando: lo ya guardado se salta y la ejecución sigue desde ahí.

## Desarrollo

```sh
make install   # dependencias del backend y del frontend
make check     # lint, formato, tipos, reglas de capas, tests con cobertura, build, contrato de la API
make format    # aplica los formateadores
make openapi   # regenera el cliente de la API del frontend tras cambiar un endpoint
```

## Cómo se construye

Las decisiones están registradas en [docs/adr/](docs/adr/README.md). Cada sesión de trabajo con el agente de IA deja una entrada en [docs/devlog/](docs/devlog/README.md).
