"use client"

import * as React from "react"
import { DateRangeFilter } from "@/components/composed/date-range-filter"

interface PeriodFilterProps {
  dateFrom: string
  dateTo: string
  onDateFromChange: (value: string) => void
  onDateToChange: (value: string) => void
  maxDate?: string
  ariaLabel?: string
}

function PeriodFilter({
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  maxDate,
  ariaLabel = "Período",
}: PeriodFilterProps) {
  return (
    <DateRangeFilter
      size="sm"
      from={dateFrom}
      to={dateTo}
      onFromChange={onDateFromChange}
      onToChange={onDateToChange}
      maxDate={maxDate}
      fromLabel={`${ariaLabel} desde`}
      toLabel={`${ariaLabel} hasta`}
    />
  )
}

export { PeriodFilter }
export type { PeriodFilterProps }
