import ollama

from src.config import settings


class OllamaClient:
    """Wrapper sobre el cliente Ollama para generación de texto y embeddings."""

    def __init__(self) -> None:
        self._client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        self._chat_model = settings.OLLAMA_CHAT_MODEL
        self._embed_model = settings.OLLAMA_EMBED_MODEL

    def generate(self, prompt: str, system: str = "") -> str:
        """Genera texto usando el modelo de chat."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat(model=self._chat_model, messages=messages)
        return response.message.content

    def embed(self, text: str) -> list[float]:
        """Genera un embedding de 768 dims para el texto dado."""
        response = self._client.embeddings(model=self._embed_model, prompt=text)
        return response.embedding
