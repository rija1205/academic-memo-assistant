import { describe, expect, it } from "vitest";
import { getHealthMessage, getHealthState } from "@/lib/health";

describe("health helpers", () => {
  it("marks a successful response as healthy", () => {
    expect(getHealthState({ ok: true })).toBe("ok");
    expect(getHealthMessage("ok")).toContain("répondent");
  });

  it("marks a missing response as unavailable", () => {
    expect(getHealthState(null)).toBe("error");
    expect(getHealthMessage("error")).toContain("pas disponible");
  });
});
