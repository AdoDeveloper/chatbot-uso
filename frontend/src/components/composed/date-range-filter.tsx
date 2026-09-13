"use client"

import * as React from "react"
import { Calendar } from "lucide-react"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"

interface DateRangeFilterProps {
  from: string
  to: string
  onFromChange: (value: string) => void
  onToChange: (value: string) => void
  minDate?: string
  maxDate?: string
  size?: "sm" | "default"
  fromLabel?: string
  toLabel?: string
  className?: string
  showLabels?: boolean
}

const SIZE_CLASS = {
  sm: "h-7 text-xs pl-2 pr-7",
  default: "h-9 text-13 pl-3 pr-8",
}

// input[type=date] nativo no soporta placeholder (se ignora por spec) y su
// formato de despliegue depende del locale del SO del usuario, no del lang
// del documento - en Firefox/Safari ni siquiera el atributo lang lo fuerza.
// Único modo confiable de mostrar siempre dd/mm/aaaa en cualquier navegador:
// un input de texto propio que controla el formato, con el date picker
// nativo montado invisible encima del ícono de calendario (mismo valor,
// showPicker() al hacer clic) para no perder el selector visual del SO.
function isoToDisplay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return ""
  return `${m[3]}/${m[2]}/${m[1]}`
}

function displayToIso(display: string): string | null {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(display.trim())
  if (!m) return null
  const [, dd, mm, yyyy] = m
  const iso = `${yyyy}-${mm}-${dd}`
  const d = new Date(iso)
  if (Number.isNaN(d.getTime()) || d.getUTCDate() !== Number(dd) || d.getUTCMonth() + 1 !== Number(mm)) return null
  return iso
}

function DateField({
  value, onChange, min, max, label, ariaLabel, inputClass, showLabel, labelClass,
}: {
  value: string
  onChange: (iso: string) => void
  min?: string
  max?: string
  label: string
  ariaLabel: string
  inputClass: string
  showLabel: boolean
  labelClass: string
}) {
  const [text, setText] = React.useState(() => isoToDisplay(value))
  const nativeRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    setText(isoToDisplay(value))
  }, [value])

  function handleTextChange(raw: string) {
    // Autoformatea mientras se escribe: conserva solo dígitos y reinserta
    // las barras en las posiciones dd/mm/aaaa.
    const digits = raw.replace(/\D/g, "").slice(0, 8)
    let next = digits
    if (digits.length > 4) next = `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
    else if (digits.length > 2) next = `${digits.slice(0, 2)}/${digits.slice(2)}`
    setText(next)
    const iso = displayToIso(next)
    if (iso) onChange(iso)
  }

  function handleBlur() {
    // Si quedó a medias o inválida, no se inventa una fecha - se refleja
    // de vuelta el último valor válido conocido (o vacío).
    setText(isoToDisplay(value))
  }

  function openNativePicker() {
    nativeRef.current?.showPicker?.()
  }

  return (
    <div className="min-w-0">
      {showLabel && <label className={labelClass}>{label}</label>}
      <div className="relative">
        <Input
          type="text"
          inputMode="numeric"
          aria-label={ariaLabel}
          value={text}
          placeholder="dd/mm/aaaa"
          onChange={(e) => handleTextChange(e.target.value)}
          onBlur={handleBlur}
          className={inputClass}
        />
        <button
          type="button"
          onClick={openNativePicker}
          aria-label={`Abrir calendario - ${ariaLabel}`}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        >
          <Calendar className="w-3.5 h-3.5" />
        </button>
        <input
          ref={nativeRef}
          type="date"
          tabIndex={-1}
          aria-hidden="true"
          value={value}
          min={min}
          max={max}
          onChange={(e) => onChange(e.target.value)}
          className="absolute inset-0 w-full h-full opacity-0 pointer-events-none"
        />
      </div>
    </div>
  )
}

function DateRangeFilter({
  from,
  to,
  onFromChange,
  onToChange,
  minDate,
  maxDate,
  size = "default",
  fromLabel = "Desde",
  toLabel = "Hasta",
  className,
  showLabels = true,
}: DateRangeFilterProps) {
  // Estándar: grid de 2 columnas fijas (nunca flex+separador, que rompía el
  // layout en mobile) - cada input ocupa su celda al 100%, sin desbordes.
  const inputClass = cn(SIZE_CLASS[size], "w-full min-w-0")
  const labelClass = "text-2xs font-medium text-muted-foreground block mb-1"
  const visibleFrom = fromLabel.length > 12 ? "Desde" : fromLabel
  const visibleTo = toLabel.length > 12 ? "Hasta" : toLabel

  return (
    <div className={cn("grid grid-cols-2 gap-2 w-full sm:w-auto", className)}>
      <DateField
        value={from}
        onChange={onFromChange}
        min={minDate}
        max={to || maxDate}
        label={visibleFrom}
        ariaLabel={fromLabel}
        inputClass={inputClass}
        showLabel={showLabels}
        labelClass={labelClass}
      />
      <DateField
        value={to}
        onChange={onToChange}
        min={from || minDate}
        max={maxDate}
        label={visibleTo}
        ariaLabel={toLabel}
        inputClass={inputClass}
        showLabel={showLabels}
        labelClass={labelClass}
      />
    </div>
  )
}

export { DateRangeFilter }
export type { DateRangeFilterProps }
