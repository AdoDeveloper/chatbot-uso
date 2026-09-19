"use client";

import { createContext, useContext } from "react";
import type { ChatbotSettings, WidgetConfig } from "@/types";

export interface AsistenteFormContextValue {
  form: ChatbotSettings;
  set: (k: keyof ChatbotSettings, v: unknown) => void;
  loadingSettings: boolean;
  widgetForm: WidgetConfig | null;
  setWidgetForm: React.Dispatch<React.SetStateAction<WidgetConfig | null>>;
  savedWidgetForm: WidgetConfig | null;
  setSavedWidgetForm: React.Dispatch<React.SetStateAction<WidgetConfig | null>>;
  widgetConfig: WidgetConfig | null;
  loadingWidget: boolean;
  isDirty: boolean;
  saving: boolean;
  handleSave: () => Promise<void>;
  handleDiscard: () => void;
  canUpdate: boolean;
}

export const AsistenteFormContext = createContext<AsistenteFormContextValue | null>(null);

export function useAsistenteForm() {
  const ctx = useContext(AsistenteFormContext);
  if (!ctx) throw new Error("useAsistenteForm debe usarse dentro de AsistenteLayout");
  return ctx;
}
