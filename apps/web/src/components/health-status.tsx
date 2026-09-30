"use client";

import { useEffect, useState } from "react";
import { getHealthMessage, getHealthState, type HealthState } from "@/lib/health";

export function HealthStatus() {
  const [state, setState] = useState<HealthState>("checking");

  useEffect(() => {
    let active = true;

    fetch("/api/health", { cache: "no-store" })
      .then((response) => {
        if (active) setState(getHealthState(response));
      })
      .catch(() => {
        if (active) setState("error");
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="status" role="status" aria-live="polite">
      <span className={`status-dot status-dot--${state === "ok" ? "ok" : state === "error" ? "error" : ""}`} />
      <span>{getHealthMessage(state)}</span>
    </div>
  );
}
