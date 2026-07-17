"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";

export function CollapsibleCard({
 title, description, preview, defaultOpen = false, children,
}: {
 title: string;
 description?: React.ReactNode;
 preview?: string;
 defaultOpen?: boolean;
 children: React.ReactNode;
}) {
 const [open, setOpen] = useState(defaultOpen);
 return (
  <div className="bg-card border border-border rounded-xl shadow-sm overflow-x-auto">
   <button
    type="button"
    onClick={() => setOpen((o) => !o)}
    className="w-full flex items-start justify-between gap-4 px-6 py-3 text-left hover:bg-muted/40 transition-colors"
   >
    <div className="min-w-0 flex-1">
     <h3 className="text-15 font-semibold tracking-tight">{title}</h3>
     {description && <p className="text-2xs text-muted-foreground mt-1">{description}</p>}
     {!open && preview && (
      <p className="text-2xs text-muted-foreground/80 mt-1.5 truncate font-mono">{preview}</p>
     )}
    </div>
    <ChevronRight
     className={`w-4 h-4 text-muted-foreground shrink-0 mt-1 transition-transform ${open ? "rotate-90" : ""}`}
    />
   </button>
   {open && <div className="px-6 pb-6 pt-1 border-t border-border">{children}</div>}
  </div>
 );
}
