"use client";

// Indicador sutil de recarga de datos, pegado justo debajo del header
// sticky del dashboard (h-14). No usar `absolute` con offset negativo
// dentro del contenido de la página — en pantallas donde el contenido
// empieza más abajo (o en mobile, donde el layout cambia), un offset
// relativo al contenedor local queda flotando en medio del body en vez
// de pegado al header real.
export function RefetchProgressBar({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div
      className="sticky top-14 left-0 right-0 h-0.5 overflow-hidden bg-primary/10 z-20"
      aria-hidden="true"
    >
      <div className="h-full w-1/3 bg-primary animate-indeterminate" />
    </div>
  );
}
