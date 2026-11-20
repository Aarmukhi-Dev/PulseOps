export type DashboardPage = "overview" | "services" | "incidents";
export type AppRoute = { kind: "landing" | "login" | "register" } | { kind: "dashboard"; page: DashboardPage };

export function routeFromPath(pathname: string): AppRoute {
  if (pathname === "/login" || pathname === "/login/") return { kind: "login" };
  if (pathname === "/register" || pathname === "/register/") return { kind: "register" };
  if (pathname === "/services") return { kind: "dashboard", page: "services" };
  if (pathname === "/incidents") return { kind: "dashboard", page: "incidents" };
  if (pathname === "/dashboard" || pathname === "/dashboard/") return { kind: "dashboard", page: "overview" };
  return { kind: "landing" };
}

export function pathForPage(page: DashboardPage): string {
  return page === "overview" ? "/dashboard" : `/${page}`;
}
