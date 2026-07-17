from __future__ import annotations

from pydantic import BaseModel, Field


class ChatbotSettings(BaseModel):
    """Representa la configuración del chatbot (subconjunto de global_settings)."""
    chatbot_name: str = Field("Asistente Virtual", min_length=1, max_length=80)
    welcome_message: str = Field("¡Hola! ¿En qué puedo ayudarte?", max_length=500)
    system_prompt: str = Field(
        "Eres el asistente virtual de la Universidad de Sonsonate. "
        "Responde ÚNICAMENTE con la información del contexto proporcionado.\n\n"
        "Reglas de formato:\n"
        "- Sé directo y conciso. No repitas la misma idea como título y como detalle.\n"
        "- Para pasos o listas, usa viñetas simples sin encabezados redundantes.\n"
        "- No inventes pasos ni requisitos que no estén en el contexto.\n"
        "- Si la información no está en el contexto, di claramente que no tienes esa información "
        "y sugiere a quién contactar (coordinador, secretaría, etc.).\n"
        "- Responde en español y tutea al usuario.\n"
        "- Nunca hagas referencia a secciones, tablas, anexos, páginas u otras partes del documento fuente. "
        "Da la información directamente sin remitir al usuario a consultar el documento.\n"
        "- Si el contexto contiene frases como \"ver tabla/lista/anexo al final del documento\", IGNÓRALAS "
        "por completo: nunca las repitas. Usa en su lugar cualquier dato concreto (nombre, cargo, teléfono, "
        "correo, oficina) que sí aparezca en el contexto. Si no hay ningún dato concreto disponible, di que "
        "no tienes ese contacto específico y sugiere contactar a Secretaría o Coordinación Académica.\n\n"
        "CONTEXTO:\n{context}",
        max_length=4000,
    )
    top_k: int = Field(8, ge=1, le=20)
    # 0.0 = sin filtro por umbral. La búsqueda usa RRF (Reciprocal Rank Fusion),
    # cuyos scores son pequeños (~0.015–0.03) y NO son similitud coseno 0–1. Un
    # umbral tipo coseno (p. ej. 0.30) sobre scores RRF descarta casi todo salvo
    # coincidencias casi literales, provocando "No tengo esa información" ante
    # preguntas coloquiales. Con 0.0 se confía en top_k (y el reranker/grader)
    # para limitar; el LLM filtra lo irrelevante vía el system prompt.
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(1024, ge=64, le=8192)
    use_corrective_rag: bool = True
    use_reranker: bool = False
    # Los tamaños de chunk (chunk_parent_size, chunk_child_size, *_overlap)
    # se controlan exclusivamente desde .env (CHATBOT_CHUNK_*) para garantizar
    # coherencia del índice vectorial — cambiarlos requiere reingestar todas las
    # fuentes y no deben modificarse en caliente desde el panel de administración.
    greeting_response: str = Field(
        "¡Hola! Soy el asistente virtual de la universidad. "
        "¿En qué puedo ayudarte? Puedo resolver dudas sobre trámites, "
        "requisitos, fechas, normativas y más.",
        max_length=500,
        description="Respuesta automática cuando el usuario solo saluda (hola, buenos días, gracias…).",
    )
    no_providers_message: str = Field(
        "En este momento el asistente no está disponible. Por favor, inténtalo más tarde.",
        max_length=300,
        description="Mensaje que ve el usuario final cuando el servicio no puede procesar su consulta.",
    )
    guardrail_blocked_message: str = Field(
        "No puedo procesar esa solicitud. ¿Puedo ayudarte con algo sobre la universidad?",
        max_length=300,
        description="Mensaje cuando los guardrails detectan inyección de prompt o contenido bloqueado.",
    )


class ChatbotSettingsWithWarnings(ChatbotSettings):
    """Respuesta del PUT /settings: incluye los mismos campos más advertencias de configuración."""
    warnings: list[str] = []
