"""Motor de evaluación de reglas de escalación. Triggers como funciones puras."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.models.enums import EscalationTrigger


def _eval_no_answer(ctx: dict, cfg: dict) -> tuple[bool, str]:
    from app.services.rag.quality import is_no_answer_reply

    needed = int(cfg.get("consecutive", 2))
    answers = ctx.get("bot_answers") or []
    if not answers:
        return False, "Sin respuestas del bot en el contexto."
    streak = 0
    for answer in reversed(answers):
        if not is_no_answer_reply(answer):
            break
        streak += 1
    if streak >= needed:
        return True, f"{streak} respuestas seguidas sin la información pedida (umbral {needed})."
    return False, f"{streak} respuesta(s) seguidas sin información; umbral {needed}."


_HUMAN = r"(agente|humano|humana|persona|asesor|asesora|operador|operadora|representante|alguien|encargad[oa]|funcionari[oa])"
_ART = r"(?:(?:un|una|el|la|algun|alguna|otro|otra|a un|a una)\s+)?"
_HUMAN_REQUEST = re.compile(
    r"\b(hablar|comunicar(?:me|nos)?|contactar(?:me)?|conversar|chatear|conectar(?:me)?|pasar(?:me)?|"
    r"transferir(?:me)?|comuniqueme|comunicame|pasame|paseme|conecteme|conectame|transfierame|transfiereme)"
    rf"\s+(?:con|a)\s+{_ART}{_HUMAN}\b"
    rf"|\b(atienda|atiendan|atenderme|atiendame|responda)\s+{_ART}{_HUMAN}\b"
    r"|\b(agente|persona|ser)\s+(humano|humana|real)\b"
    rf"|\b(quiero|necesito|deseo|solicito|pido|prefiero)\s+{_ART}(agente|humano|operador|operadora|representante|asesor|asesora)\b"
    r"|\bno\s+(quiero|deseo)\s+(hablar\s+con\s+)?(un\s+)?(bot|robot|maquina)\b"
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _eval_user_request(ctx: dict, cfg: dict) -> tuple[bool, str]:
    keywords = cfg.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    msg = _normalize(ctx.get("user_message") or "")
    if not msg:
        return False, "Sin mensaje de usuario en el contexto."
    if keywords:
        matched = [k for k in keywords if re.search(rf"\b{re.escape(_normalize(k))}\b", msg)]
        if matched:
            return True, f"Keywords detectadas: {', '.join(matched)}."
        return False, "Ninguna keyword de solicitud detectada."
    match = _HUMAN_REQUEST.search(msg)
    if match:
        return True, f"Solicitud de atención humana: «{match.group(0)}»."
    return False, "No se detectó una solicitud de atención humana."


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
    msg = _normalize(ctx.get("user_message") or "")
    if not msg:
        return False, "Sin mensaje de usuario en el contexto."
    # Palabra completa, admitiendo plural: "robo" no debe saltar con "robótica".
    matched = [k for k in keywords if re.search(rf"\b{re.escape(_normalize(k.strip()))}(?:s|es)?\b", msg)]
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
    """Schema de configuración esperado para cada trigger."""
    schemas = {
        EscalationTrigger.no_answer: {
            "consecutive": {"type": "int", "default": 2, "min": 1, "max": 5,
                            "label": "Respuestas seguidas sin información"},
        },
        EscalationTrigger.user_request: {
            "keywords": {"type": "list[str]", "default": [],
                         "label": "Frases de solicitud propias (vacío = detección automática)"},
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


def validate_trigger_config(trigger_type: EscalationTrigger, config: dict[str, Any]) -> dict[str, Any]:
    """Comprueba tipos y rangos contra el esquema del disparador; lanza ValueError con el motivo."""
    schema = schema_for_trigger(trigger_type)
    unknown = sorted(set(config) - set(schema))
    if unknown:
        raise ValueError(f"Campos no válidos para este tipo de activación: {', '.join(unknown)}")
    clean: dict[str, Any] = {}
    for key, spec in schema.items():
        label = spec.get("label", key)
        if key not in config:
            if spec.get("required"):
                raise ValueError(f"Falta el campo «{label}».")
            continue
        value = config[key]
        kind = spec["type"]
        if kind == "list[str]":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"«{label}» debe ser una lista de textos.")
            value = [v.strip() for v in value if v.strip()]
            if spec.get("required") and not value:
                raise ValueError(f"«{label}» necesita al menos un valor.")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"«{label}» debe ser un número.")
            if kind == "int":
                if value != int(value):
                    raise ValueError(f"«{label}» debe ser un número entero.")
                value = int(value)
            else:
                value = float(value)
            if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
                raise ValueError(f"«{label}» debe estar entre {spec.get('min')} y {spec.get('max')}.")
        clean[key] = value
    return clean
