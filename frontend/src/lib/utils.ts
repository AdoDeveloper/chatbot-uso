import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "Nunca"
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60_000)
  if (min < 1) return "ahora"
  if (min < 60) return `hace ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `hace ${h}h`
  const d = Math.floor(h / 24)
  if (d === 1) return "ayer"
  if (d < 7) return `hace ${d} días`
  return new Date(iso).toLocaleDateString("es-ES", { day: "2-digit", month: "short" })
}
