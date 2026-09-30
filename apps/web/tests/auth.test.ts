import { describe, expect, it } from "vitest";
import { getSafeNext } from "@/lib/api";

describe("authentication helpers", () => {
  it("keeps internal redirect paths", () => {
    expect(getSafeNext("/profile?tab=security")).toBe("/profile?tab=security");
  });

  it("rejects external redirect paths", () => {
    expect(getSafeNext("https://evil.example")).toBe("/dashboard");
    expect(getSafeNext("//evil.example")).toBe("/dashboard");
    expect(getSafeNext(null)).toBe("/dashboard");
  });
});
