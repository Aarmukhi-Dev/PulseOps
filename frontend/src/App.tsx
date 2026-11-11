import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ApiError,
  createService,
  deleteService,
  getIncidentEvents,
  getIncidents,
  getMetrics,
  getServiceChecks,
  getServices,
  login,
  setAccessToken,
  setUnauthorizedHandler,
  updateService,
  type Incident,
  type IncidentEvent,
  type Metrics,
  type Service,
  type ServiceCheck,
  type ServiceInput,
} from "./api/client";
import { ResponseTimeChart } from "./components/ResponseTimeChart";
import { StatusBadge } from "./components/StatusBadge";
import { LandingPage } from "./LandingPage";
import { pathForPage, routeFromPath, type AppRoute, type DashboardPage } from "./routing";

type Page = DashboardPage;
type Notice = { kind: "error" | "success"; message: string } | null;

const numberFormat = new Intl.NumberFormat();
const localDate = (value: string | null) => value ? new Date(value).toLocaleString() : "Never";
const bytes = (value: number) => {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

export function App() {
  const [route, setRoute] = useState<AppRoute>(() => routeFromPath(window.location.pathname));
  const [authenticated, setAuthenticated] = useState(false);
  const [authError, setAuthError] = useState("");
  const navigate = useCallback((path: string) => {
    window.history.pushState({}, "", path);
    setRoute(routeFromPath(window.location.pathname));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  useEffect(() => {
    const handlePopState = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => { setAccessToken(null); setAuthenticated(false); setAuthError("Your session expired. Please log in again."); });
    return () => setUnauthorizedHandler(null);
  }, []);

  async function handleLogin(email: string, password: string) {
    setAuthError("");
    try {
      const result = await login(email, password);
      setAccessToken(result.access_token);
      setAuthenticated(true);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Unable to log in.");
    }
  }

  function handleLogout() {
    setAccessToken(null);
    setAuthenticated(false);
    navigate("/dashboard");
  }

  useEffect(() => {
    if (route.kind !== "dashboard" || !window.location.hash) return;
    const frame = window.requestAnimationFrame(() => document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ behavior: "smooth" }));
    return () => window.cancelAnimationFrame(frame);
  }, [route]);

  if (route.kind === "landing") return <LandingPage onNavigate={navigate} />;
  if (!authenticated) return <LoginPage error={authError} onLogin={handleLogin} onBack={() => navigate("/")} />;
  return <DashboardApp initialPage={route.page} onNavigate={navigate} onLogout={handleLogout} />;
}

function DashboardApp({ initialPage, onNavigate, onLogout }: { initialPage: Page; onNavigate: (path: string) => void; onLogout: () => void }) {
  const [page, setPage] = useState<Page>(initialPage);
  const [services, setServices] = useState<Service[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [checks, setChecks] = useState<ServiceCheck[]>([]);
  const [selectedServiceId, setSelectedServiceId] = useState("");
  const [eventsFor, setEventsFor] = useState<string | null>(null);
  const [events, setEvents] = useState<IncidentEvent[]>([]);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(true);
  const [apiConnected, setApiConnected] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalClosing, setModalClosing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => setPage(initialPage), [initialPage]);

  function navigateToPage(nextPage: Page) {
    setPage(nextPage);
    onNavigate(pathForPage(nextPage));
  }

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([getServices(), getMetrics(), getIncidents()]);
    setApiConnected(results.some((result) => result.status === "fulfilled"));
    const serviceResult = results[0];
    if (serviceResult.status === "fulfilled") {
      setServices(serviceResult.value);
      setSelectedServiceId((current) => current && serviceResult.value.some((s) => s.id === current)
        ? current : serviceResult.value[0]?.id ?? "");
    } else setNotice({ kind: "error", message: `Could not load services: ${serviceResult.reason instanceof Error ? serviceResult.reason.message : "API error"}` });
    if (results[1].status === "fulfilled") setMetrics(results[1].value);
    if (results[2].status === "fulfilled") setIncidents(results[2].value);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selectedServiceId) { setChecks([]); return; }
    let alive = true;
    getServiceChecks(selectedServiceId, 48)
      .then((data) => { if (alive) setChecks(data); })
      .catch(() => { if (alive) setChecks([]); });
    return () => { alive = false; };
  }, [selectedServiceId]);

  const selectedService = services.find((service) => service.id === selectedServiceId);
  const counts = useMemo(() => ({
    healthy: services.filter((s) => s.is_enabled && s.current_status === "healthy").length,
    unhealthy: services.filter((s) => s.is_enabled && s.current_status === "unhealthy").length,
    degraded: services.filter((s) => s.is_enabled && s.current_status === "unknown").length,
  }), [services]);
  const filteredServices = services.filter((service) => `${service.name} ${service.target}`.toLowerCase().includes(search.toLowerCase()));

  function closeModal() {
    setModalClosing(true);
    window.setTimeout(() => { setModalOpen(false); setModalClosing(false); }, 150);
  }

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const input: ServiceInput = {
      name: String(data.get("name")).trim(),
      description: String(data.get("description") || "").trim() || null,
      check_type: data.get("check_type") as ServiceInput["check_type"],
      target: String(data.get("target")).trim(),
      check_interval_seconds: Number(data.get("interval")),
      timeout_seconds: Number(data.get("timeout")),
      expected_status_code: data.get("check_type") === "http" ? Number(data.get("expected_status") || 200) : null,
      is_enabled: true,
    };
    setSaving(true);
    try {
      const created = await createService(input);
      setNotice({ kind: "success", message: `${created.name} was added.` });
      closeModal();
      await refresh();
      setSelectedServiceId(created.id);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Could not create service." });
    } finally { setSaving(false); }
  }

  async function toggleService(service: Service) {
    try {
      await updateService(service.id, { is_enabled: !service.is_enabled });
      await refresh();
      setNotice({ kind: "success", message: `${service.name} ${service.is_enabled ? "paused" : "enabled"}.` });
    } catch (error) { setNotice({ kind: "error", message: error instanceof Error ? error.message : "Update failed." }); }
  }

  async function removeService(service: Service) {
    if (!window.confirm(`Delete ${service.name}? Services with check or incident history are retained by the API.`)) return;
    try {
      await deleteService(service.id);
      setNotice({ kind: "success", message: `${service.name} was deleted.` });
      await refresh();
    } catch (error) { setNotice({ kind: "error", message: error instanceof ApiError ? error.message : "Could not delete service." }); }
  }

  async function showEvents(incident: Incident) {
    setEventsFor(incident.id);
    try { setEvents(await getIncidentEvents(incident.id)); }
    catch (error) { setNotice({ kind: "error", message: error instanceof Error ? error.message : "Could not load incident history." }); }
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNavOpen ? "mobile-open" : ""}`}>
        <a className="brand" href="/dashboard" onClick={(event) => { event.preventDefault(); navigateToPage("overview"); }}><span className="brand-mark">P</span><span>pulse<span className="brand-light">ops</span><small>OPERATIONS CENTER</small></span></a>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          <button className={`nav-item ${page === "overview" ? "active" : ""}`} onClick={() => { navigateToPage("overview"); setMobileNavOpen(false); }}><span>◫</span> Overview</button>
          <button className={`nav-item ${page === "services" ? "active" : ""}`} onClick={() => { navigateToPage("services"); setMobileNavOpen(false); }}><span>◈</span> Services <b>{services.length}</b></button>
          <button className={`nav-item ${page === "incidents" ? "active" : ""}`} onClick={() => { navigateToPage("incidents"); setMobileNavOpen(false); }}><span>⌁</span> Incidents <b className={incidents.some((i) => i.status !== "resolved") ? "nav-alert" : ""}>{incidents.filter((i) => i.status !== "resolved").length}</b></button>
        </nav>
        <div className="sidebar-bottom"><div className="api-state"><i className={apiConnected ? "pulse-dot" : "pulse-dot muted"} /><span>{apiConnected ? "API connected" : loading ? "Connecting to API" : "API unavailable"}</span></div><span className="sidebar-version">PULSEOPS · LOCAL</span></div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><button className="mobile-menu-toggle" aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"} aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen((open) => !open)}>{mobileNavOpen ? "×" : "☰"}</button><span>Workspace</span><span className="crumb-sep">/</span><strong>{page === "overview" ? "Overview" : page === "services" ? "Services" : "Incidents"}</strong></div>
          <div className="top-actions"><span className={`live-indicator ${apiConnected ? "connected" : "disconnected"}`}><i /> {apiConnected ? "Live data" : "API offline"}</span><button className="icon-button" aria-label="Refresh data" onClick={() => void refresh()}>↻</button><button className="text-button" onClick={onLogout}>Log out</button><div className="avatar">PO</div></div>
        </header>
        {notice && <div className={`notice ${notice.kind}`} role="status"><span>{notice.message}</span><button onClick={() => setNotice(null)} aria-label="Dismiss">×</button></div>}

        {page === "overview" && <>
          <section className="page-heading"><div><div className="eyebrow">MONITORING OVERVIEW</div><h1>Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening"} <span className="wave">✦</span></h1><p>Here’s the current state of your monitored infrastructure.</p></div><button className="primary-button" onClick={() => { navigateToPage("services"); setModalClosing(false); setModalOpen(true); }}>＋ Add service</button></section>
          <section className="stat-grid">
            <StatCard label="MONITORED SERVICES" value={services.length} sub={`${services.filter((s) => s.is_enabled).length} enabled`} icon="◈" tone="blue" />
            <StatCard label="HEALTHY" value={counts.healthy} sub="All checks passing" icon="✓" tone="green" />
            <StatCard label="DEGRADED" value={counts.degraded} sub="Awaiting first check" icon="◷" tone="amber" />
            <StatCard label="UNHEALTHY" value={counts.unhealthy} sub={`${incidents.filter((i) => i.status !== "resolved").length} active incidents`} icon="!" tone="red" />
          </section>
          <section id="monitoring" className="metric-grid">
            <MetricCard title="CPU usage" value={metrics ? `${metrics.cpu.usage_percent.toFixed(1)}%` : "—"} detail={metrics ? `${metrics.cpu.logical_cores} logical cores` : "Waiting for API"} valuePercent={metrics?.cpu.usage_percent} tone="blue" icon="⌁" />
            <MetricCard title="Memory usage" value={metrics ? `${metrics.memory.usage_percent.toFixed(1)}%` : "—"} detail={metrics ? `${bytes(metrics.memory.used_bytes)} of ${bytes(metrics.memory.total_bytes)}` : "Waiting for API"} valuePercent={metrics?.memory.usage_percent} tone="purple" icon="▤" />
            <MetricCard title="Disk usage" value={metrics ? `${metrics.disk.usage_percent.toFixed(1)}%` : "—"} detail={metrics ? `${bytes(metrics.disk.used_bytes)} of ${bytes(metrics.disk.total_bytes)}` : "Waiting for API"} valuePercent={metrics?.disk.usage_percent} tone="cyan" icon="▱" />
          </section>
          <section className="content-grid">
            <div className="panel chart-panel"><div className="panel-heading"><div><h2>Response time</h2><p>{selectedService ? selectedService.name : "Select a service to view check history"}</p></div>{services.length > 0 && <select aria-label="Select service for response time chart" value={selectedServiceId} onChange={(e) => setSelectedServiceId(e.target.value)}>{services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}</div><ResponseTimeChart checks={checks} /><div className="chart-foot"><span><i className="legend-dot" /> Response time</span><span>Last {checks.length} checks</span></div></div>
            <div className="panel incident-panel"><div className="panel-heading"><div><h2>Active incidents</h2><p>Issues that need attention</p></div><button className="text-button" onClick={() => navigateToPage("incidents")}>View all →</button></div>{incidents.filter((i) => i.status !== "resolved").slice(0, 4).length === 0 ? <EmptyState title="All clear" text="No active incidents are reported by the monitoring worker." /> : incidents.filter((i) => i.status !== "resolved").slice(0, 4).map((incident) => <button key={incident.id} className="incident-row" onClick={() => { navigateToPage("incidents"); void showEvents(incident); }}><span className="incident-icon">!</span><span className="incident-info"><strong>{incident.title}</strong><small>{incident.service_name} · {localDate(incident.started_at)}</small></span><StatusBadge status={incident.status} /></button>)}</div>
          </section>
          <section className="panel history-panel"><div className="panel-heading"><div><h2>Service monitoring</h2><p>Latest availability checks across your services</p></div><button className="text-button" onClick={() => navigateToPage("services")}>Manage services →</button></div><ServiceTable services={services.slice(0, 5)} onSelect={(id) => { setSelectedServiceId(id); navigateToPage("services"); }} onToggle={toggleService} onDelete={removeService} /></section>
        </>}

        {page === "services" && <>
          <section className="page-heading"><div><div className="eyebrow">MONITORING</div><h1>Services</h1><p>Configure and manage the endpoints PulseOps checks.</p></div><button className="primary-button" onClick={() => { setModalClosing(false); setModalOpen(true); }}>＋ Add service</button></section>
          <div className="service-toolbar"><div className="search-box"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search services or targets" /></div><span className="result-count">{filteredServices.length} services</span></div>
          <section className="panel table-panel"><ServiceTable services={filteredServices} onSelect={(id) => setSelectedServiceId(id)} onToggle={toggleService} onDelete={removeService} empty={loading ? "Loading services…" : "No services found. Add a service to begin monitoring."} /></section>
          {selectedService && <section className="panel history-panel detail-history"><div className="panel-heading"><div><h2>Monitoring history</h2><p>{selectedService.name} · recent real checks</p></div><span className="last-check">Last check: {localDate(selectedService.last_checked_at)}</span></div><ResponseTimeChart checks={checks} /><div className="check-list">{checks.slice(0, 8).map((check) => <div className="check-row" key={check.id}><span className={`check-result ${check.is_available ? "good" : "bad"}`}>{check.is_available ? "✓ Available" : "× Unavailable"}</span><span>{check.status_code ? `HTTP ${check.status_code}` : check.error_type ?? "TCP check"}</span><span>{check.response_time_ms === null ? "—" : `${check.response_time_ms} ms`}</span><time>{localDate(check.checked_at)}</time></div>)}</div></section>}
        </>}

        {page === "incidents" && <>
          <section className="page-heading"><div><div className="eyebrow">RELIABILITY</div><h1>Incidents</h1><p>Incident records and auditable event timelines from the monitoring worker.</p></div><span className="incident-total">{incidents.length} total</span></section>
          {incidents.length === 0 ? <section className="panel"><EmptyState title="No incidents recorded" text="Incidents will appear here when monitored services transition to unhealthy." /></section> : <div className="incident-list">{incidents.map((incident) => <section className="panel incident-card" key={incident.id}><div className="incident-card-head"><div className="incident-title"><span className={`incident-icon ${incident.status === "resolved" ? "resolved-icon" : ""}`}>{incident.status === "resolved" ? "✓" : "!"}</span><div><h2>{incident.title}</h2><p>{incident.service_name} · started {localDate(incident.started_at)}</p></div></div><StatusBadge status={incident.status} /></div>{incident.description && <p className="incident-description">{incident.description}</p>}<div className="incident-meta"><span className={`severity severity-${incident.severity}`}>{incident.severity}</span>{incident.resolved_at && <span>Resolved {localDate(incident.resolved_at)}</span>}<button className="text-button" onClick={() => void showEvents(incident)}>{eventsFor === incident.id ? "Refresh timeline" : "View timeline →"}</button></div>{eventsFor === incident.id && <div className="timeline">{events.length === 0 ? <p>No event details recorded.</p> : events.map((event) => <div className="timeline-event" key={event.id}><i /><div><strong>{event.event_type.replaceAll("_", " ")}</strong><time>{localDate(event.created_at)}</time><small>{Object.keys(event.payload).length ? JSON.stringify(event.payload) : "System event"}</small></div></div>)}</div>}</section>)}</div>}
        </>}
        <footer className="footer"><span>PulseOps Operations Center</span><span>Data refreshes every 30 seconds · <time>{metrics ? localDate(metrics.collected_at) : "Metrics unavailable"}</time></span></footer>
      </main>

      {modalOpen && <div className={`modal-backdrop ${modalClosing ? "closing" : ""}`} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeModal(); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="add-service-title"><div className="modal-heading"><div><div className="eyebrow">NEW MONITOR</div><h2 id="add-service-title">Add a service</h2></div><button className="icon-button" onClick={closeModal} aria-label="Close">×</button></div><form onSubmit={(e) => void onCreate(e)}><label>Service name<input name="name" required maxLength={160} placeholder="Public API" /></label><label>Description <span className="optional">Optional</span><input name="description" placeholder="Production API endpoint" /></label><div className="form-row"><label>Check type<select name="check_type"><option value="http">HTTP / HTTPS</option><option value="tcp">TCP</option></select></label><label>Expected status<input name="expected_status" type="number" min="100" max="599" defaultValue="200" /></label></div><label>Target<input name="target" required placeholder="https://api.example.com/health or host:port" /></label><div className="form-row"><label>Interval (seconds)<input name="interval" type="number" required min="1" defaultValue="60" /></label><label>Timeout (seconds)<input name="timeout" type="number" required min="1" defaultValue="10" /></label></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={closeModal}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? "Adding…" : "Add service"}</button></div></form></section></div>}
    </div>
  );
}

function LoginPage({ error, onLogin, onBack }: { error: string; onLogin: (email: string, password: string) => Promise<void>; onBack: () => void }) {
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try { await onLogin(String(data.get("email")), String(data.get("password"))); }
    finally { setBusy(false); }
  }
  return <main className="auth-page"><section className="auth-card glass-panel"><a className="brand auth-brand" href="/" onClick={(event) => { event.preventDefault(); onBack(); }}><span className="brand-mark">P</span><span>pulse<span className="brand-light">ops</span><small>OPERATIONS CENTER</small></span></a><div className="eyebrow">SECURE WORKSPACE</div><h1>Welcome back</h1><p>Sign in to access your monitored services and incident history.</p><form onSubmit={(event) => void submit(event)}><label>Email<input name="email" type="email" autoComplete="username" maxLength={320} required /></label><label>Password<input name="password" type="password" autoComplete="current-password" maxLength={1024} required /></label>{error && <div className="auth-error" role="alert">{error}</div>}<button className="primary-button" disabled={busy}>{busy ? "Signing in…" : "Log in"}</button></form><button className="auth-back" onClick={onBack}>← Back to PulseOps</button></section></main>;
}

function StatCard({ label, value, sub, icon, tone }: { label: string; value: number; sub: string; icon: string; tone: string }) {
  return <article className="stat-card glass-panel"><div className={`stat-icon ${tone}`}>{icon}</div><div className="stat-label">{label}</div><div className="stat-value"><AnimatedNumber value={value} /></div><div className="stat-sub">{sub}</div></article>;
}

function AnimatedNumber({ value }: { value: number }) {
  const [display, setDisplay] = useState(value);
  useEffect(() => {
    const start = display;
    const startedAt = performance.now();
    const duration = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 450;
    let frame = 0;
    const tick = (now: number) => {
      const progress = duration === 0 ? 1 : Math.min(1, (now - startedAt) / duration);
      const eased = 1 - (1 - progress) ** 3;
      setDisplay(Math.round(start + (value - start) * eased));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  // display is the animation's starting value; changes are driven by API value updates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return <>{numberFormat.format(display)}</>;
}

function MetricCard({ title, value, detail, valuePercent, tone, icon }: { title: string; value: string; detail: string; valuePercent?: number; tone: string; icon: string }) {
  return <article className="metric-card"><div className="metric-top"><span className={`metric-icon ${tone}`}>{icon}</span><span className="metric-period">HOST METRICS</span></div><div className="metric-label">{title}</div><div className="metric-value">{value}</div><div className="metric-progress"><span className={tone} style={{ width: `${Math.min(100, Math.max(0, valuePercent ?? 0))}%` }} /></div><div className="metric-detail">{detail}</div></article>;
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return <div className="empty-state"><span>◌</span><strong>{title}</strong><p>{text}</p></div>;
}

function ServiceTable({ services, onSelect, onToggle, onDelete, empty = "No monitored services yet." }: { services: Service[]; onSelect: (id: string) => void; onToggle: (service: Service) => void; onDelete: (service: Service) => void; empty?: string }) {
  if (services.length === 0) return <EmptyState title="Nothing to show" text={empty} />;
  return <div className="table-scroll"><table><thead><tr><th>SERVICE</th><th>STATUS</th><th>LAST RESPONSE</th><th>LAST CHECKED</th><th>INTERVAL</th><th aria-label="Actions" /></tr></thead><tbody>{services.map((service) => <tr key={service.id}><td><button className="service-cell" onClick={() => onSelect(service.id)}><span className="service-icon">{service.check_type === "http" ? "↗" : "⌘"}</span><span><strong>{service.name}</strong><small>{service.target}</small></span></button></td><td><StatusBadge service={service} /></td><td className="mono">{service.last_response_time_ms === null ? "—" : `${service.last_response_time_ms} ms`}</td><td>{localDate(service.last_checked_at)}</td><td>{service.check_interval_seconds}s</td><td><div className="row-actions"><button onClick={() => onToggle(service)} title={service.is_enabled ? "Pause service" : "Enable service"}>{service.is_enabled ? "Ⅱ" : "▶"}</button><button className="delete-action" onClick={() => onDelete(service)} title="Delete service">×</button></div></td></tr>)}</tbody></table></div>;
}
