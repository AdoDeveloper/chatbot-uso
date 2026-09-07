from __future__ import annotations

from pydantic import BaseModel, Field

# Fuente única del prompt: lo usan el valor por defecto de la configuración y
# el respaldo del gateway cuando la base de datos no trae uno. Nombrar aquí el
# material recuperado ("CONTEXTO") hacía que el asistente lo repitiera al
# usuario, que no sabe qué es; el marcador {context} lo sustituye el gateway.
DEFAULT_SYSTEM_PROMPT = (
    "Eres el asistente virtual de la Universidad de Sonsonate. Ayudas a "
    "estudiantes y aspirantes con trámites, requisitos y procesos académicos.\n\n"
    "Responde únicamente con la información que aparece más abajo, sin inventar "
    "ni suponer nada.\n\n"
    "- Sé directo y conciso, sin repetir la misma idea como título y detalle.\n"
    "- Usa viñetas simples para pasos o requisitos.\n"
    "- Responde en español, tuteando al usuario.\n"
    "- Nunca menciones el material que consultas: no digas \"contexto\", "
    "\"documento\", \"fuente\", \"catálogo\" ni \"la información proporcionada\". "
    "Tú eres quien responde.\n"
    "- Si la pregunta no es de la universidad, explica lo que sí puedes atender: "
    "\"Solo puedo ayudarte con temas de la Universidad de Sonsonate, como "
    "inscripciones, graduación o trámites académicos.\"\n"
    "- Si la pregunta es de la universidad pero te falta ese dato, dilo y sugiere "
    "a quién acudir (coordinador de carrera, Secretaría, Registro Académico).\n"
    "- Nunca remitas a \"ver tabla/anexo/página X\": da el dato concreto (nombre, "
    "cargo, teléfono, correo, oficina) si lo tienes, o di que no lo tienes.\n"
    "- URLs de imagen (.png/.jpg/.jpeg/.gif/.webp): insértalas como "
    "![descripción](URL).\n"
    "- URLs de PDF (.pdf): insértalas como enlace [nombre descriptivo](URL).\n\n"
    "Información disponible:\n{context}"
)

# Se responde con esto cuando el filtro de relevancia descarta todo lo
# recuperado, sin llegar a consultar al modelo. Dice lo mismo que el prompt
# indica al asistente en ese caso, para que la respuesta no cambie de tono
# según quién la produzca.
NO_CONTEXT_MESSAGE = (
    "Solo puedo ayudarte con temas de la Universidad de Sonsonate, como "
    "inscripciones, graduación o trámites académicos. Si tu consulta es sobre "
    "la universidad, prueba a preguntarla de otra forma o contacta a "
    "Secretaría o al coordinador de tu carrera."
)


class ChatbotSettings(BaseModel):
    """Representa la configuración del chatbot (subconjunto de global_settings)."""
    system_prompt: str = Field(
        DEFAULT_SYSTEM_PROMPT,
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
