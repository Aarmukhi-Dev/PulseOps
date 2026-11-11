import { isBackendHealthy } from "./health";

describe("isBackendHealthy", () => {
  it("accepts a live API and database", () => {
    expect(isBackendHealthy({ status: "ok", database: "ok" })).toBe(true);
  });

  it("rejects a degraded database", () => {
    expect(isBackendHealthy({ status: "degraded", database: "unavailable" })).toBe(false);
  });
});
