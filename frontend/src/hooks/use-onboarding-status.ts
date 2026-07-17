"use client";

import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";

export interface OnboardingStatus {
  step: number | "done";
  providers_configured: boolean;
  providers_active: boolean;
  sources_uploaded: boolean;
  sources_approved: boolean;
  messages_sent: number;
  dismissed: boolean;
}

export function useOnboardingStatus() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    api.get<OnboardingStatus>("/auth/onboarding-status")
      .then(({ data }) => setStatus(data))
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function dismiss() {
    const snapshot = status;
    setStatus((s) => (s ? { ...s, dismissed: true } : s));
    try {
      await api.post("/auth/onboarding-dismiss");
    } catch {
      setStatus(snapshot);
    }
  }

  const shouldShow = !!status && !status.dismissed && status.step !== "done";

  return { status, loading, shouldShow, refresh, dismiss };
}
