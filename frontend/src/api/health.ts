export type HealthResponse = {
  status: string;
  database: string;
};

export function isBackendHealthy(health: HealthResponse): boolean {
  return health.status === "ok" && health.database === "ok";
}
