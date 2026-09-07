"""Evalua la calidad de las respuestas del chat contra datos verificables.

Cada caso trae el dato correcto tomado del reglamento y los errores tipicos
que delatarian una invencion. Clasifica cada respuesta en:

  correcta   - contiene el dato esperado y ningun dato erroneo
  inventada  - contiene un dato que contradice el reglamento
  incompleta - no rechaza, pero tampoco da el dato pedido
  sin dato   - reconoce que no tiene la informacion

Uso:
    python scripts/bench_respuestas.py --url https://chatbot-uso.tech --key wk_...
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

DATASET = Path(__file__).parent / "bench_respuestas.json"

RECHAZO = (
    "no tengo", "no dispongo", "no cuento", "no encontr", "solo puedo",
    "no puedo ayudarte", "no esta disponible",
)


def _normaliza(s: str) -> str:
    return " ".join(s.lower().split())


def clasificar(texto: str, caso: dict) -> tuple[str, str]:
    bajo = _normaliza(texto)
    if not bajo:
        return "vacia", "sin contenido"

    # Los datos prohibidos se buscan como token completo: "9.5" aparece dentro
    # de "9.0 a 9.5" y "10 años" dentro de "9.6 a 10", asi que una busqueda por
    # subcadena marcaba como inventada una respuesta correcta.
    erroneos = [
        d for d in caso.get("no_debe_contener", [])
        if re.search(r"(?<![\w.$])%s(?![\w.])" % re.escape(d.lower()), bajo)
    ]
    if erroneos:
        return "inventada", "contiene %s" % ", ".join(erroneos)

    # Preguntas cuya respuesta no esta en el corpus: reconocerlo es lo correcto,
    # y dar un dato concreto seria inventarlo.
    if caso.get("espera_rechazo"):
        if any(r in bajo for r in RECHAZO):
            return "correcta", "reconoce no tenerlo"
        return "inventada", "responde algo que el corpus no contiene"

    esperados = caso.get("debe_contener", [])
    presentes = [d for d in esperados if d.lower() in bajo]
    completo = bool(presentes) if caso.get("cualquiera") else len(presentes) == len(esperados)
    if completo:
        return "correcta", ""

    if any(r in bajo for r in RECHAZO):
        return "sin dato", "reconoce no tenerlo"
    faltan = [d for d in esperados if d.lower() not in bajo]
    return "incompleta", "falta %s" % ", ".join(faltan)


def preguntar(url: str, key: str, pregunta: str) -> dict:
    cuerpo = json.dumps({
        "question": pregunta,
        "session_id": "bench-%d-%d" % (int(time.time()), random.randint(1000, 9999)),
        "browser": "bench-respuestas",
    }).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/api/v1/chat",
        data=cuerpo,
        headers={
            "Content-Type": "application/json",
            "X-Widget-Key": key,
            "Origin": "https://uso-demo-site.vercel.app",
        },
    )
    with urllib.request.urlopen(req, timeout=150) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://chatbot-uso.tech")
    ap.add_argument("--key", required=True, help="clave publica del widget")
    ap.add_argument("--pausa", type=float, default=8.0)
    ap.add_argument("--json", type=str, help="guarda el informe")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    casos = json.loads(DATASET.read_text(encoding="utf-8"))

    filas = []
    print("%-52s %-11s %s" % ("PREGUNTA", "VEREDICTO", "DETALLE"))
    print("-" * 104)
    for caso in casos:
        try:
            d = preguntar(args.url, args.key, caso["pregunta"])
        except Exception as exc:
            print("%-52s %-11s %s" % (caso["pregunta"][:52], "ERROR", str(exc)[:34]))
            filas.append({**caso, "veredicto": "error"})
            continue
        texto = (d.get("content") or d.get("message") or "").strip()
        veredicto, detalle = clasificar(texto, caso)
        print("%-52s %-11s %s" % (caso["pregunta"][:52], veredicto, detalle[:34]))
        if veredicto in ("inventada", "incompleta", "vacia"):
            print("      esperado: %s" % caso["nota"])
            print("      respuesta: %s" % texto[:150].replace("\n", " "))
        filas.append({
            "pregunta": caso["pregunta"],
            "veredicto": veredicto,
            "detalle": detalle,
            "respuesta": texto,
            "fragmentos": len(d.get("sources") or []),
            "ruta": d.get("rag_route"),
        })
        time.sleep(args.pausa)

    print()
    conteo: dict[str, int] = {}
    for f in filas:
        conteo[f["veredicto"]] = conteo.get(f["veredicto"], 0) + 1
    total = len(filas)
    print("RESUMEN sobre %d preguntas con respuesta verificable" % total)
    for k in ("correcta", "incompleta", "sin dato", "inventada", "vacia", "error"):
        if conteo.get(k):
            print("  %-11s %2d  (%3d%%)" % (k, conteo[k], 100 * conteo[k] // total))
    exactitud = 100 * conteo.get("correcta", 0) // total
    print()
    print("  exactitud: %d%%" % exactitud)
    print("  respuestas con datos inventados: %d" % conteo.get("inventada", 0))

    if args.json:
        Path(args.json).write_text(
            json.dumps({"resumen": conteo, "detalle": filas}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("  informe guardado en %s" % args.json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
