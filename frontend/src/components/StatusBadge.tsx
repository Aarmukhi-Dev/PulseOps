import type { Service } from "../api/client";

type StatusBadgeProps = {
  service?: Service;
  status?: "open" | "acknowledged" | "resolved";
};

export function StatusBadge({ service, status }: StatusBadgeProps) {
  if (service) {
    if (!service.is_enabled) return <span className="badge badge-paused"><span />Paused</span>;
    if (service.current_status === "healthy") return <span className="badge badge-healthy"><span />Healthy</span>;
    if (service.current_status === "unhealthy") return <span className="badge badge-unhealthy"><span />Unhealthy</span>;
    return <span className="badge badge-degraded"><span />Degraded · awaiting check</span>;
  }

  const labels = { open: "Open", acknowledged: "Acknowledged", resolved: "Resolved" };
  return <span className={`badge badge-${status ?? "paused"}`}><span />{status ? labels[status] : "Unknown"}</span>;
}
