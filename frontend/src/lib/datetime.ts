/** Zona horaria fija del proyecto: El Salvador (UTC-6, sin horario de verano). */
export const PROJECT_TIMEZONE = "America/El_Salvador";

/**
 * Formatea un ISO/timestamp en la zona de El Salvador, independientemente de
 * la zona del navegador del usuario. Usar para cualquier fecha del sistema
 * (auditoría, actividad, conversaciones, reportes, etc.).
 */
export function formatInProjectTz(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" },
): string {
  const d = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat("es-SV", { ...options, timeZone: PROJECT_TIMEZONE }).format(d);
}
