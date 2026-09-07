"""Banco de pruebas del pipeline RAG contra el corpus indexado.

Mide el recuperador con las métricas habituales de recuperación de
información (Hit@k, MRR, Precision@k, Recall@k) y el filtro de relevancia
por separado, sobre un conjunto de consultas con relevancia anotada a mano.

Las preguntas fuera de dominio comprueban lo contrario: que el filtro no
apruebe nada, porque el recuperador siempre devuelve sus k mejores
candidatos aunque ninguno venga a cuento.

Uso:
    python scripts/bench_rag.py [--k 12] [--json informe.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import decrypt_secret  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.llm_provider import LLMProvider  # noqa: E402
from app.services.ai.embedding import embed_texts_async  # noqa: E402
from app.services.ai.llm_gateway import grade_documents  # noqa: E402
from app.services.ingestion import vector_store  # noqa: E402

DATASET = Path(__file__).parent / "bench_dataset.json"

# Pausa entre llamadas al evaluador. El proveedor limita por tokens en una
# ventana de un minuto (8000 en el plan gratuito) y cada evaluación de k=12
# fragmentos gasta unos 1700, así que se espacian para no agotarla: de otro
# modo el filtro abre en true y el informe mide la degradación, no el juicio.
PAUSA_LLM = 30.0


def _es_relevante(texto: str, marcas: list[str]) -> bool:
    bajo = texto.lower()
    return any(m.lower() in bajo for m in marcas)


def _metricas(relevantes: list[bool], total_esperado: int) -> dict:
    """Hit@k, MRR, Precision@k y Recall@k de una lista ordenada."""
    aciertos = sum(relevantes)
    primer = next((i + 1 for i, r in enumerate(relevantes) if r), None)
    return {
        "hit": 1.0 if aciertos else 0.0,
        "mrr": 1.0 / primer if primer else 0.0,
        "precision": aciertos / len(relevantes) if relevantes else 0.0,
        "recall": min(aciertos / total_esperado, 1.0) if total_esperado else 0.0,
    }


async def _recuperar(consulta: str, k: int) -> tuple[list[dict], float]:
    inicio = time.perf_counter()
    emb = (await embed_texts_async([consulta], prefix="query: "))[0]
    docs = await vector_store.hybrid_search(
        query_dense=emb["dense"],
        query_sparse={
            "indices": emb["sparse_indices"],
            "values": emb["sparse_values"],
        },
        source_ids=None,
        top_k=k,
        score_threshold=0.0,
    )
    return docs[:k], (time.perf_counter() - inicio) * 1000


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=12, help="fragmentos a recuperar")
    ap.add_argument("--json", type=str, help="guarda el informe en un archivo")
    ap.add_argument("--sin-evaluador", action="store_true", help="omite el filtro por LLM")
    ap.add_argument("--dataset", type=str, help="ruta a otro conjunto de consultas")
    args = ap.parse_args()

    casos = json.loads(Path(args.dataset or DATASET).read_text(encoding="utf-8"))
    en_dominio = [c for c in casos if c["marcas"]]
    fuera = [c for c in casos if not c["marcas"]]

    provider = api_key = None
    if not args.sin_evaluador:
        async with AsyncSessionLocal() as db:
            provider = (await db.execute(
                select(LLMProvider).where(LLMProvider.is_active == True)  # noqa: E712
            )).scalars().first()
        if provider is not None:
            api_key = decrypt_secret(provider.api_key_encrypted) if provider.api_key_encrypted else None

    print("Banco de pruebas RAG  |  k=%d  |  %d consultas (%d en dominio, %d fuera)" % (
        args.k, len(casos), len(en_dominio), len(fuera),
    ))
    print("evaluador: %s" % (provider.model_name if provider is not None else "desactivado"))
    print()

    filas, latencias = [], []
    for caso in casos:
        docs, ms = await _recuperar(caso["pregunta"], args.k)
        latencias.append(ms)
        textos = [d.get("text", "") for d in docs]
        rel = [_es_relevante(t, caso["marcas"]) for t in textos]
        m = _metricas(rel, caso.get("relevantes_esperados", 1)) if caso["marcas"] else {}

        # grade_documents abre en true si la llamada falla (un 429 del proveedor,
        # por ejemplo). Aprobar los k de golpe delata esa degradación, no un
        # juicio: contarla como resultado falsearía el informe.
        aprobados = degradado = None
        if provider is not None and docs:
            for intento in range(3):
                grades = await grade_documents(caso["pregunta"], docs, provider, api_key)
                degradado = len(docs) > 1 and all(grades)
                if not degradado:
                    break
                # Reintenta tras la ventana del límite antes de darlo por perdido.
                if intento < 2:
                    await asyncio.sleep(PAUSA_LLM * 2)
            aprobados = None if degradado else [d for d, g in zip(docs, grades) if g]
            await asyncio.sleep(PAUSA_LLM)

        filas.append({
            "pregunta": caso["pregunta"],
            "en_dominio": bool(caso["marcas"]),
            "latencia_ms": round(ms, 1),
            "recuperados": len(docs),
            "aprobados": len(aprobados) if aprobados is not None else None,
            "evaluador_degradado": bool(degradado),
            **m,
        })

    print("%-46s %-7s %-6s %-6s %-6s %s" % (
        "CONSULTA", "HIT", "MRR", "P@k", "R@k", "APROBADOS",
    ))
    print("-" * 100)
    for f in filas:
        if f["en_dominio"]:
            print("%-46s %-7.0f %-6.2f %-6.2f %-6.2f %s" % (
                f["pregunta"][:46], f["hit"], f["mrr"], f["precision"], f["recall"],
                "degradado" if f["evaluador_degradado"] else (
                    "-" if f["aprobados"] is None else f["aprobados"]
                ),
            ))
    print()
    print("%-46s %s" % ("CONSULTA FUERA DE DOMINIO", "APROBADOS (debe ser 0)"))
    print("-" * 100)
    for f in filas:
        if not f["en_dominio"]:
            print("%-46s %s" % (
                f["pregunta"][:46],
                "degradado" if f["evaluador_degradado"] else (
                    "-" if f["aprobados"] is None else f["aprobados"]
                ),
            ))
    print()

    dentro = [f for f in filas if f["en_dominio"]]
    resumen = {
        "k": args.k,
        "consultas": len(filas),
        "hit_rate": statistics.mean(f["hit"] for f in dentro),
        "mrr": statistics.mean(f["mrr"] for f in dentro),
        "precision_at_k": statistics.mean(f["precision"] for f in dentro),
        "recall_at_k": statistics.mean(f["recall"] for f in dentro),
        "latencia_p50_ms": round(statistics.median(latencias), 1),
        "latencia_max_ms": round(max(latencias), 1),
    }
    afuera = [f for f in filas if not f["en_dominio"] and f["aprobados"] is not None]
    if afuera:
        resumen["falsos_positivos_fuera_dominio"] = sum(1 for f in afuera if f["aprobados"] > 0)
        resumen["consultas_fuera_dominio"] = len(afuera)
    degradadas = sum(1 for f in filas if f["evaluador_degradado"])
    if degradadas:
        resumen["consultas_con_evaluador_degradado"] = degradadas

    print("RESUMEN")
    print("  Hit@%-2d          %.3f   (alguna consulta sin recuperar nada útil baja esto)" % (
        args.k, resumen["hit_rate"],
    ))
    print("  MRR             %.3f   (1.0 = el fragmento correcto siempre primero)" % resumen["mrr"])
    print("  Precision@%-2d    %.3f   (proporción de los k que son pertinentes)" % (
        args.k, resumen["precision_at_k"],
    ))
    print("  Recall@%-2d       %.3f   (cuánto de lo esperado se recupera)" % (
        args.k, resumen["recall_at_k"],
    ))
    print("  latencia        p50 %.0f ms, máx %.0f ms" % (
        resumen["latencia_p50_ms"], resumen["latencia_max_ms"],
    ))
    if afuera:
        print("  fuera de dominio con contexto aprobado: %d de %d (debe ser 0)" % (
            resumen["falsos_positivos_fuera_dominio"], resumen["consultas_fuera_dominio"],
        ))
    if degradadas:
        print("  consultas sin juicio del evaluador (proveedor degradado): %d" % degradadas)
        print("  repita con menos carga: esos resultados no cuentan como aprobación")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"resumen": resumen, "detalle": filas}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print()
        print("informe guardado en %s" % args.json)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
