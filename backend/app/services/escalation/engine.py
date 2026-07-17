"""Motor de evaluación de reglas de escalación. Triggers como funciones puras."""
from __future__ import annotations

from typing import Any

from app.models.enums import EscalationTrigger


# Tipo de contexto
# {
#   "user_message": str,                 # último mensaje del usuario
#   "bot_answers": list[str],            # últimas respuestas del bot (orden cronológico)
#   "rag_scores": list[float],           # confianza de las últimas respuestas (mismo orden)
#   "no_answer_seconds": int | None,     # segundos sin respuesta del bot a una pregunta
#   "feedback_negative_ratio": float|None, # 0..1 — proporción de 👎 en la sesión
# }


def _eval_no_answer(ctx: dict, cfg: dict) -> tuple[bool, str]:
    wait = int(cfg.get("wait_seconds", 120))
    elapsed = ctx.get("no_answer_seconds")
    if elapsed is None:
        return False, "No hay tiempo de espera registrado en el contexto."
    if elapsed >= wait:
        return True, f"Sin respuesta por {elapsed}s (umbral {wait}s)."
    return False, f"Tiempo de espera {elapsed}s aún no supera el umbral {wait}s."


def _eval_user_request(ctx: dict, cfg: dict) -> tuple[bool, str]:
    keywords = cfg.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    msg = (ctx.get("user_message") or "").lower()
    if not msg:
        return False, "Sin mensaje de usuario en el contexto."
    if not keywords:
        keywords = ["agente", "humano", "persona", "asesor", "operador"]
    matched = [k for k in keywords if k.lower() in msg]
    if matched:
        return True, f"Keywords detectadas: {', '.join(matched)}."
    return False, "Ninguna keyword de solicitud detectada."


def _eval_negative_feedback(ctx: dict, cfg: dict) -> tuple[bool, str]:
    threshold = float(cfg.get("threshold", 0.5))
    ratio = ctx.get("feedback_negative_ratio")
    if ratio is None:
        return False, "Sin métrica de valoraciones negativas en el contexto."
    if ratio >= threshold:
        return True, f"Valoraciones negativas {ratio:.0%} ≥ umbral {threshold:.0%}."
    return False, f"Valoraciones negativas {ratio:.0%} bajo el umbral {threshold:.0%}."


def _eval_keyword_detected(ctx: dict, cfg: dict) -> tuple[bool, str]:
    keywords = cfg.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keywords:
        return False, "La regla no tiene keywords configuradas."
    msg = (ctx.get("user_message") or "").lower()
    if not msg:
        return False, "Sin mensaje de usuario en el contexto."
    matched = [k for k in keywords if k.lower() in msg]
    if matched:
        return True, f"Keyword crítica detectada: {', '.join(matched)}."
    return False, "Ninguna keyword crítica encontrada."


def _eval_confidence_below(ctx: dict, cfg: dict) -> tuple[bool, str]:
    threshold = float(cfg.get("threshold", 0.02))
    consecutive = int(cfg.get("consecutive", 2))
    scores = ctx.get("rag_scores") or []
    if len(scores) < consecutive:
        return False, f"Solo hay {len(scores)} respuestas; se necesitan {consecutive} consecutivas."
    last_n = scores[-consecutive:]
    if all(s < threshold for s in last_n):
        return True, f"Últimas {consecutive} respuestas con confianza < {threshold:.2f}: {[round(s, 2) for s in last_n]}."
    return False, f"Confianza reciente OK: {[round(s, 2) for s in last_n]}."


def _eval_loop_detected(ctx: dict, cfg: dict) -> tuple[bool, str]:
    threshold = int(cfg.get("repetitions", 2))
    answers = ctx.get("bot_answers") or []
    if len(answers) < threshold + 1:
        return False, f"Solo hay {len(answers)} respuestas del bot; se necesitan al menos {threshold + 1}."
    # Buscar la respuesta más reciente y contar repeticiones consecutivas hacia atrás
    last = (answers[-1] or "").strip().lower()
    if not last:
        return False, "Última respuesta del bot vacía."
    count = 1
    for prev in reversed(answers[:-1]):
        if (prev or "").strip().lower() == last:
            count += 1
        else:
            break
    if count >= threshold + 1:
        return True, f"Misma respuesta repetida {count} veces consecutivas (umbral {threshold + 1})."
    return False, f"Respuesta repetida solo {count} vez(es); umbral {threshold + 1}."


_EVALUATORS = {
    EscalationTrigger.no_answer: _eval_no_answer,
    EscalationTrigger.user_request: _eval_user_request,
    EscalationTrigger.negative_feedback: _eval_negative_feedback,
    EscalationTrigger.keyword_detected: _eval_keyword_detected,
    EscalationTrigger.confidence_below: _eval_confidence_below,
    EscalationTrigger.loop_detected: _eval_loop_detected,
}


def evaluate_rule(
    *,
    trigger_type: EscalationTrigger,
    trigger_config: dict[str, Any],
    context: dict[str, Any],
) -> tuple[bool, str]:
    """Evalúa una regla contra un contexto. Retorna (matches, detail)."""
    fn = _EVALUATORS.get(trigger_type)
    if not fn:
        return False, f"Trigger no soportado: {trigger_type}"
    return fn(context, trigger_config or {})


def schema_for_trigger(trigger_type: EscalationTrigger) -> dict[str, Any]:
    """Schema de configuración esperado para cada trigger.

    Útil para la UI dinámica del formulario y validación.
    """
    schemas = {
        EscalationTrigger.no_answer: {
            "wait_seconds": {"type": "int", "default": 120, "min": 10, "max": 3600,
                             "label": "Tiempo de espera (segundos)"},
        },
        EscalationTrigger.user_request: {
            "keywords": {"type": "list[str]", "default": [],
                         "label": "Palabras clave de solicitud (vacío = defaults)"},
        },
        EscalationTrigger.negative_feedback: {
            "threshold": {"type": "float", "default": 0.5, "min": 0, "max": 1, "step": 0.05,
                          "label": "Umbral de valoraciones negativas (0–1)"},
        },
        EscalationTrigger.keyword_detected: {
            "keywords": {"type": "list[str]", "default": [], "required": True,
                         "label": "Palabras o frases críticas (urgente, denuncia, queja…)"},
        },
        EscalationTrigger.confidence_below: {
            "threshold": {"type": "float", "default": 0.02, "min": 0, "max": 0.1, "step": 0.005,
                          "label": "Confianza RAG mínima (score RRF, típico 0.015–0.033)"},
            "consecutive": {"type": "int", "default": 2, "min": 1, "max": 10,
                            "label": "N respuestas consecutivas"},
        },
        EscalationTrigger.loop_detected: {
            "repetitions": {"type": "int", "default": 2, "min": 2, "max": 5,
                            "label": "N repeticiones para detectar bucle"},
        },
    }
    return schemas.get(trigger_type, {})
