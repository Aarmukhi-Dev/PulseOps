export type DashboardPage = "overview" | "services" | "incidents";
export type AppRoute = { kind: "landing" } | { kind: "dashboard"; page: DashboardPage };

export function routeFromPath(pathname: string): AppRoute {
  if (pathname === "/services") return { kind: "dashboard", page: "services" };
  if (pathname === "/incidents") return { kind: "dashboard", page: "incidents" };
  if (pathname === "/dashboard" || pathname === "/dashboard/") return { kind: "dashboard", page: "overview" };
  return { kind: "landing" };
}

export function pathForPage(page: DashboardPage): string {
  return page === "overview" ? "/dashboard" : `/${page}`;
}
