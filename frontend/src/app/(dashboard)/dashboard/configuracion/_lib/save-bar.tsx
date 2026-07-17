"use client";

import { Loader2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";

export function FloatingSaveBar({
 dirty, saving, onSave, onDiscard,
}: {
 dirty: boolean;
 saving: boolean;
 onSave: () => void;
 onDiscard?: () => void;
}) {
 if (!dirty) return null;
 return (
  <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-3 duration-200 pointer-events-none">
   <div className="flex items-center gap-2 bg-card border border-border rounded-2xl shadow-xl px-4 py-2.5 pointer-events-auto">
    <span className="h-1.5 w-1.5 rounded-full bg-warning animate-pulse shrink-0" />
    <span className="text-13 font-medium text-foreground whitespace-nowrap">Cambios sin guardar</span>
    {onDiscard && (
     <Button variant="ghost" size="sm" onClick={onDiscard}
      className="h-7 px-2.5 text-muted-foreground hover:text-foreground">
      Descartar
     </Button>
    )}
    <Button size="sm" onClick={onSave} disabled={saving} className="h-7 gap-1.5 rounded-xl">
     {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
     Guardar
    </Button>
   </div>
  </div>
 );
}
