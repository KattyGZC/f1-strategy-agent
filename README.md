# F1 Strategy Agent
## Project Objective
F1 Strategy Agent is an AI-powered assistant designed to transform how fans and analysts interact with Formula 1 data. The core mission is to provide a platform where complex telemetry, historical results, and FIA technical regulations can be queried in natural language, delivering precise and context-aware insights in real-time.

Once in production, the system will enable:

- Real-Time Race Analysis: Query lap times and gaps between drivers as the action unfolds.
- Intelligent Historical Queries: Ask about specific milestones (e.g., "What was Franco Colapinto's position progress in his last race?") and receive a detailed breakdown.
- Strategy Insights: Understand why a team made a pit-stop decision based on tire degradation and historical data.
- Seamless Interaction: A chat interface with instant (streaming) responses for a dynamic and modern user experience.

## Technical Highlights

- Agentic Architecture: Implementation of complex decision flows using LangGraph to orchestrate multiple retrieval tools.
- Advanced RAG: Information retrieval system using PostgreSQL with pgvector for semantic search over regulations and historical data.
- Scalable Backend: API built with FastAPI using asynchronous patterns, dependency injection, and strict data validation with Pydantic V2.
- Real-Time Streaming: Efficient communication via Server-Sent Events (SSE) for word-by-word response delivery.
- Infrastructure: Cloud-native design using Docker containers, ready for AWS deployment


## Objetivo del Proyecto
F1 Strategy Agent es un asistente inteligente diseñado para transformar la manera en que los aficionados y analistas interactúan con los datos de la Fórmula 1. El objetivo principal es proporcionar una plataforma donde se pueda consultar, en lenguaje natural, información compleja sobre telemetría, resultados históricos y normativas técnicas de la FIA, obteniendo respuestas precisas y contextualizadas en tiempo real.

Una vez en producción, el sistema permitirá:

- Analizar Carreras en Tiempo Real: Consultar tiempos de vuelta y brechas entre pilotos mientras sucede la acción.
- Consultas Históricas Inteligentes: Preguntar sobre hitos específicos (ej. "¿Cómo fue el progreso de posiciones de Franco Colapinto en su última carrera?") y recibir un análisis detallado.
- Explicación de Estrategias: Entender por qué un equipo tomó una decisión de boxes basada en el desgaste de neumáticos y datos históricos.
- Interacción Fluida: Chat con respuestas instantáneas (streaming) que permiten una experiencia de usuario dinámica y moderna.

## Detalles Técnicos (Highlights)
- Arquitectura de Agentes: Implementación de flujos de decisión complejos utilizando LangGraph para orquestar múltiples herramientas de consulta.
- RAG Avanzado: Sistema de recuperación de información utilizando PostgreSQL con pgvector para búsquedas semánticas sobre reglamentos y datos históricos.
- Backend Escalable: API construida con FastAPI bajo patrones asíncronos, inyección de dependencias y validación estricta de datos con Pydantic V2.
- Streaming en Tiempo Real: Comunicación eficiente mediante Server-Sent Events (SSE) para una entrega de respuestas palabra por palabra.
- Infraestructura: Diseño preparado para la nube (Cloud-Native) utilizando contenedores Docker y preparado para despliegue en AWS.