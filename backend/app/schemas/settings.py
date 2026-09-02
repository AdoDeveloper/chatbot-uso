from __future__ import annotations

from pydantic import BaseModel, Field


class ChatbotSettings(BaseModel):
    """Representa la configuración del chatbot (subconjunto de global_settings)."""
    system_prompt: str = Field(
        "Eres el asistente virtual de la Universidad de Sonsonate. "
        "Responde solo con información del CONTEXTO, sin inventar ni suponer nada.\n\n"
        "- Sé directo y conciso, sin repetir la misma idea como título y detalle.\n"
        "- Usa viñetas simples para pasos o requisitos.\n"
        "- Responde en español, tuteando al usuario.\n"
        "- Si el CONTEXTO no tiene la respuesta, dilo y sugiere a quién contactar si aparece esa información.\n"
        "- Nunca remitas a \"ver tabla/anexo/página X\": da el dato concreto (nombre, cargo, teléfono, "
        "correo, oficina) si existe en el CONTEXTO, o di que no lo tienes.\n"
        "- No digas frases como 'el documento indica', 'según el catálogo' o 'la fuente menciona'. "
        "Tú eres quien responde, no un citador. Da la información directamente.\n"
        "- URLs de imagen (.png/.jpg/.jpeg/.gif/.webp): insértalas como ![descripción](URL).\n"
        "- URLs de PDF (.pdf): insértalas como enlace [nombre descriptivo](URL).\n\n"
        "En caso de dudas, sugiere contactar al Coordinador de carrera. "
        "No menciones documentos, anexos, tablas ni fuentes.\n\n"
        "CONTEXTO:\n{context}",
        max_length=4000,
    )
    top_k: int = Field(12, ge=1, le=20)
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(1024, ge=64, le=8192)
    use_corrective_rag: bool = True
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
