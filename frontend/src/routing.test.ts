import { pathForPage, routeFromPath } from "./routing";

describe("PulseOps routes", () => {
  it("uses the public landing page at the root", () => {
    expect(routeFromPath("/")).toEqual({ kind: "landing" });
  });

  it.each([
    ["/dashboard", "overview"],
    ["/dashboard/", "overview"],
    ["/services", "services"],
    ["/incidents", "incidents"],
  ] as const)("maps %s to the existing %s dashboard view", (path, page) => {
    expect(routeFromPath(path)).toEqual({ kind: "dashboard", page });
  });

  it.each([
    ["overview", "/dashboard"],
    ["services", "/services"],
    ["incidents", "/incidents"],
  ] as const)("generates the URL for the %s dashboard view", (page, path) => {
    expect(pathForPage(page)).toBe(path);
  });
});
