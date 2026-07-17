"use client";

import { useEffect, useRef, useState } from "react";

interface ScrollShadowProps {
  children: React.ReactNode;
  className?: string;
  /** Color del que parte el degradado — debe coincidir con el fondo real
   * detrás del contenido (bg-card en tarjetas, bg-background en el fondo de
   * página). Por defecto "card". */
  fadeFrom?: "card" | "background";
}

/**
 * Envuelve contenido con scroll horizontal (tablas anchas, filas de tabs)
 * y muestra una sombra en el borde derecho/izquierdo cuando hay más
 * contenido fuera de vista — evita que se corte sin ningún indicio de que
 * hay más a un lado (antes: tablas y tabs se veían truncados sin aviso).
 */
export function ScrollShadow({ children, className, fadeFrom = "card" }: ScrollShadowProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [showLeft, setShowLeft] = useState(false);
  const [showRight, setShowRight] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    function update() {
      if (!el) return;
      setShowLeft(el.scrollLeft > 2);
      setShowRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
    }
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener("resize", update);
    return () => {
      el.removeEventListener("scroll", update);
      ro.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);

  return (
    <div className="relative">
      <div ref={ref} className={`overflow-x-auto overflow-y-hidden ${className ?? ""}`}>
        {children}
      </div>
      <div
        aria-hidden="true"
        style={{ boxShadow: showLeft ? "inset 8px 0 6px -6px rgb(0 0 0 / 0.18)" : "none" }}
        className={`pointer-events-none absolute inset-y-0 left-0 w-6 bg-gradient-to-r ${fadeFrom === "card" ? "from-card" : "from-background"} to-transparent transition-opacity ${showLeft ? "opacity-100" : "opacity-0"}`}
      />
      <div
        aria-hidden="true"
        style={{ boxShadow: showRight ? "inset -8px 0 6px -6px rgb(0 0 0 / 0.18)" : "none" }}
        className={`pointer-events-none absolute inset-y-0 right-0 w-6 bg-gradient-to-l ${fadeFrom === "card" ? "from-card" : "from-background"} to-transparent transition-opacity ${showRight ? "opacity-100" : "opacity-0"}`}
      />
    </div>
  );
}
