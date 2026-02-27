"""
Agente F1 con LangGraph.

Arquitectura del grafo:
    START → retrieve → generate → END

Nodos:
  - retrieve: convierte la pregunta en embedding y busca los resúmenes
              más similares en race_summaries usando pgvector (cosine distance).
  - generate: construye un prompt con el contexto recuperado y llama a Ollama
              para generar la respuesta final.

Estado:
  - query:    pregunta del usuario
  - context:  lista de textos recuperados de la DB (race summaries)
  - answer:   respuesta generada por el LLM
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session as DBSession

from src.infrastructure.clients.ollama_client import OllamaClient
from src.infrastructure.database.repositories.race_summary_repo import (
    search_similar_summaries,
)

SYSTEM_PROMPT = (
    "You are an expert Formula 1 analyst assistant. "
    "Answer the user's question using ONLY the race summaries provided as context. "
    "If the context doesn't contain enough information, say so clearly. "
    "Be concise and specific."
)


class AgentState(TypedDict):
    query: str
    context: list[str]
    answer: str


class F1Agent:
    """Agente RAG para consultas sobre carreras de F1.

    Uso:
        agent = F1Agent(db=db, llm=OllamaClient())
        result = agent.run("Who won the 2024 Monaco Grand Prix?")
        print(result["answer"])
    """

    def __init__(self, db: DBSession, llm: OllamaClient) -> None:
        self._db = db
        self._llm = llm
        self._graph = self._build_graph()

    def run(self, query: str) -> AgentState:
        """Ejecuta el agente y retorna el estado final con la respuesta."""
        return self._graph.invoke({"query": query, "context": [], "answer": ""})

    # ------------------------------------------------------------------
    # Nodos del grafo
    # ------------------------------------------------------------------

    def _retrieve(self, state: AgentState) -> AgentState:
        """Genera el embedding de la query y recupera los resúmenes más relevantes."""
        query_embedding = self._llm.embed(state["query"])
        summaries = search_similar_summaries(self._db, query_embedding, top_k=3)
        return {"context": [s.content for s in summaries]}

    def _generate(self, state: AgentState) -> AgentState:
        """Genera la respuesta usando el contexto recuperado."""
        if not state["context"]:
            return {"answer": "I don't have enough race data to answer that question."}

        context_text = "\n\n---\n\n".join(state["context"])
        prompt = (
            f"Race summaries (context):\n{context_text}\n\n"
            f"Question: {state['query']}"
        )
        answer = self._llm.generate(prompt=prompt, system=SYSTEM_PROMPT)
        return {"answer": answer}

    # ------------------------------------------------------------------
    # Construcción del grafo
    # ------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)

        graph.add_node("retrieve", self._retrieve)
        graph.add_node("generate", self._generate)

        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "generate")
        graph.add_edge("generate", END)

        return graph.compile()
