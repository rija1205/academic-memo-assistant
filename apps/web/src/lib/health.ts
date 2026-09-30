export type HealthState = "checking" | "ok" | "error";

export interface HealthSummary {
  state: HealthState;
  message: string;
}

export function getHealthState(response: { ok?: boolean } | null): HealthState {
  if (!response) return "error";
  return response.ok ? "ok" : "error";
}

export function getHealthMessage(state: HealthState): string {
  switch (state) {
    case "ok":
      return "Les services de l’application répondent correctement.";
    case "checking":
      return "Vérification de la connexion au backend…";
    case "error":
      return "Le backend n’est pas disponible ou la vérification a échoué.";
  }
}
