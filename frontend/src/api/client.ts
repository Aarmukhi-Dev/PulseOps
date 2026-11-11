export type ServiceStatus = "unknown" | "healthy" | "unhealthy";
export type CheckType = "http" | "tcp";

export type Service = {
  id: string;
  name: string;
  description: string | null;
  check_type: CheckType;
  target: string;
  check_interval_seconds: number;
  timeout_seconds: number;
  expected_status_code: number | null;
  is_enabled: boolean;
  current_status: ServiceStatus;
  last_checked_at: string | null;
  last_response_time_ms: number | null;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type ServiceInput = {
  name: string;
  description: string | null;
  check_type: CheckType;
  target: string;
  check_interval_seconds: number;
  timeout_seconds: number;
  expected_status_code: number | null;
  is_enabled: boolean;
};

export type AuthUser = { id: string; email: string; display_name: string };
let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
export function setAccessToken(token: string | null): void { accessToken = token; }
export function setUnauthorizedHandler(handler: (() => void) | null): void { unauthorizedHandler = handler; }
export async function login(email: string, password: string): Promise<{ access_token: string; user: AuthUser }> {
  return request("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
}

export type Metrics = {
  collected_at: string;
  cpu: { usage_percent: number; logical_cores: number; physical_cores: number | null };
  memory: { total_bytes: number; used_bytes: number; available_bytes: number; usage_percent: number };
  disk: { mountpoint: string; total_bytes: number; used_bytes: number; free_bytes: number; usage_percent: number };
};

export type ServiceCheck = {
  id: string;
  service_id: string;
  checked_at: string;
  is_available: boolean;
  response_time_ms: number | null;
  status_code: number | null;
  error_type: string | null;
};

export type Incident = {
  id: string;
  service_id: string;
  service_name: string;
  title: string;
  description: string | null;
  severity: "low" | "medium" | "high" | "critical";
  status: "open" | "acknowledged" | "resolved";
  started_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type IncidentEvent = {
  id: string;
  incident_id: string;
  actor_user_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

const apiBaseUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError("The PulseOps API could not be reached.", 0);
  }

  if (!response.ok) {
    if (response.status === 401 && accessToken) unauthorizedHandler?.();
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Use the HTTP status message when the API response is not JSON.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getServices(): Promise<Service[]> {
  return request<Service[]>("/api/services");
}

export function getMetrics(): Promise<Metrics> {
  return request<Metrics>("/api/v1/metrics/current");
}

export function getServiceChecks(serviceId: string, limit = 48): Promise<ServiceCheck[]> {
  return request<ServiceCheck[]>(`/api/services/${encodeURIComponent(serviceId)}/checks?limit=${limit}`);
}

export function getIncidents(status?: Incident["status"]): Promise<Incident[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<Incident[]>(`/api/incidents${query}`);
}

export function getIncidentEvents(incidentId: string): Promise<IncidentEvent[]> {
  return request<IncidentEvent[]>(`/api/incidents/${encodeURIComponent(incidentId)}/events`);
}

export function createService(input: ServiceInput): Promise<Service> {
  return request<Service>("/api/services", { method: "POST", body: JSON.stringify(input) });
}

export function updateService(serviceId: string, input: Partial<ServiceInput>): Promise<Service> {
  return request<Service>(`/api/services/${encodeURIComponent(serviceId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteService(serviceId: string): Promise<void> {
  return request<void>(`/api/services/${encodeURIComponent(serviceId)}`, { method: "DELETE" });
}
