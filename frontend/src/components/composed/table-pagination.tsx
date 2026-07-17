"use client";

import { useEffect, useState } from "react";
import { ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight, MoreHorizontal } from "lucide-react";
import { Select, SelectOption } from "@/components/ui/select";

// Umbral propio (no el de useIsMobile, pensado para el sidebar a 1024px):
// por debajo de este ancho la fila de botones de página con siblings=1 más
// los saltos a primera/última puede exceder el espacio disponible dentro de
// una card angosta, empujando el último botón fuera de la pantalla.
const NARROW_BREAKPOINT = 480;

function useIsNarrow() {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${NARROW_BREAKPOINT - 1}px)`);
    const onChange = () => setNarrow(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

/** Opciones estándar del selector de tamaño de página, iguales en todo el panel. */
export const PAGE_SIZE_OPTIONS = [10, 20, 30] as const;

interface TablePaginationProps {
  /** Total de registros que coinciden con los filtros actuales. */
  total: number;
  /** Página actual (1-indexed). */
  page: number;
  /** Registros por página. */
  pageSize: number;
  /** Registros mostrados en la página actual (por defecto, pageSize salvo en la última página). */
  shown?: number;
  onPageChange: (page: number) => void;
  /** Si se pasa, muestra el selector "Mostrar 10/20/30" junto al total. */
  onPageSizeChange?: (pageSize: number) => void;
  /** Etiqueta del tipo de registro, ej. "entradas", "conversaciones". */
  itemLabel?: string;
  className?: string;
}

/** Cuántos botones numéricos mostrar alrededor de la página actual. */
const SIBLINGS = 1;

function buildPageList(current: number, total: number, siblings: number): (number | "…")[] {
  const pages = new Set<number>([1, total, current]);
  for (let i = 1; i <= siblings; i++) {
    if (current - i >= 1) pages.add(current - i);
    if (current + i <= total) pages.add(current + i);
  }
  const sorted = [...pages].sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) out.push("…");
    out.push(sorted[i]);
  }
  return out;
}

/**
 * Pie de tabla estándar (formato datatable) para todo el panel: a la
 * izquierda "Mostrando N de Total", a la derecha
 * << < [1][2][3] > >>. Reemplaza los distintos formatos de paginación que
 * antes convivían (texto con flechas ASCII, solo iconos, indicadores
 * duplicados arriba y abajo de la tabla).
 */
export function TablePagination({
  total, page, pageSize, shown, onPageChange, onPageSizeChange, className,
}: TablePaginationProps) {
  const narrow = useIsNarrow();
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  // Sin selector de tamaño no hay nada más que mostrar en una sola página.
  if (total <= pageSize && !onPageSizeChange) return null;

  const shownCount = shown ?? Math.min(pageSize, total - (page - 1) * pageSize);
  // En pantallas angostas se omiten los siblings y los saltos a primera/
  // última página — sin eso, la fila de botones (cada uno en su propio
  // recuadro) puede ser más ancha que la card y el último botón queda
  // cortado fuera de la pantalla.
  const pageList = buildPageList(page, totalPages, narrow ? 0 : SIBLINGS);

  const navBtn = "w-7 h-7 flex items-center justify-center rounded-md border border-border bg-card text-muted-foreground shadow-xs transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-primary disabled:opacity-30 disabled:pointer-events-none disabled:hover:border-border disabled:hover:bg-card";
  const pageBtnBase = "w-7 h-7 flex items-center justify-center rounded-md border text-2xs font-semibold tabular-nums transition-colors";
  const pageBtnActive = "border-primary bg-primary text-primary-foreground shadow-xs";
  const pageBtnInactive = "border-border bg-card text-muted-foreground hover:border-primary/40 hover:bg-primary/5 hover:text-primary";

  return (
    <div className={`px-4 py-3 border-t border-border flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-muted/20 ${className ?? ""}`}>
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-2xs text-muted-foreground tabular-nums whitespace-nowrap">
          Mostrando <span className="font-semibold text-foreground">{shownCount}</span> de{" "}
          <span className="font-semibold text-foreground">{total}</span>
        </span>
        {onPageSizeChange && (
          <label className="flex items-center gap-1.5 text-2xs text-muted-foreground whitespace-nowrap">
            Mostrar
            <Select
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
              aria-label="Registros por página"
              className="h-7 text-2xs font-medium w-20"
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <SelectOption key={n} value={n}>{n}</SelectOption>
              ))}
            </Select>
          </label>
        )}
      </div>
      {total > pageSize && (
        <div className="flex items-center gap-1">
          {!narrow && (
            <button
              type="button"
              disabled={page === 1}
              onClick={() => onPageChange(1)}
              aria-label="Primera página"
              title="Primera página"
              className={navBtn}
            >
              <ChevronsLeft className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            type="button"
            disabled={page === 1}
            onClick={() => onPageChange(page - 1)}
            aria-label="Página anterior"
            title="Página anterior"
            className={navBtn}
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          {pageList.map((p, i) =>
            p === "…" ? (
              <span key={`ellipsis-${i}`} className="w-7 h-7 flex items-center justify-center text-muted-foreground select-none">
                <MoreHorizontal className="w-3.5 h-3.5" />
              </span>
            ) : (
              <button
                key={p}
                type="button"
                onClick={() => onPageChange(p)}
                aria-label={`Página ${p}`}
                aria-current={p === page ? "page" : undefined}
                className={`${pageBtnBase} ${p === page ? pageBtnActive : pageBtnInactive}`}
              >
                {p}
              </button>
            )
          )}
          <button
            type="button"
            disabled={page === totalPages}
            onClick={() => onPageChange(page + 1)}
            aria-label="Página siguiente"
            title="Página siguiente"
            className={navBtn}
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
          {!narrow && (
            <button
              type="button"
              disabled={page === totalPages}
              onClick={() => onPageChange(totalPages)}
              aria-label="Última página"
              title="Última página"
              className={navBtn}
            >
              <ChevronsRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
