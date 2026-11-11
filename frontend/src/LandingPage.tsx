import { useState } from "react";
import "./styles/landing.css";

type LandingPageProps = { onNavigate: (path: string) => void };

const artworkVideo = "https://d2ol7oe51mr4n9.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/435a4fe7-e43b-4e7c-af78-0be083e73569.mp4";
const artworkPoster = "https://d2ol7oe51mr4n9.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/782a4a52-4c1e-4471-bb0c-aa232927f4a6.webp";

export function LandingPage({ onNavigate }: LandingPageProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);

  const navigate = (path: string) => {
    setMenuOpen(false);
    onNavigate(path);
  };

  return (
    <main className="landing-shell">
      <header className="landing-nav">
        <a className="landing-brand" href="/" onClick={(event) => { event.preventDefault(); navigate("/"); }} aria-label="PulseOps home">
          <span className="landing-brand-mark" aria-hidden="true"><svg viewBox="0 0 34 34"><path d="M4 18h6l3-8 5 16 4-11 3 3h5" /></svg></span>
          <span>pulseops</span>
        </a>
        <button className="landing-menu-toggle" onClick={() => setMenuOpen((open) => !open)} aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen}>{menuOpen ? "×" : "☰"}</button>
        <nav className={`landing-links ${menuOpen ? "is-open" : ""}`} aria-label="Landing page navigation">
          <a href="/dashboard" onClick={(event) => { event.preventDefault(); navigate("/dashboard"); }}>Overview</a>
          <a href="#features" onClick={() => setMenuOpen(false)}>Features</a>
          <a href="/dashboard#monitoring" onClick={(event) => { event.preventDefault(); navigate("/dashboard#monitoring"); }}>Monitoring</a>
          <a href="/incidents" onClick={(event) => { event.preventDefault(); navigate("/incidents"); }}>Incidents</a>
        </nav>
        <div className="landing-nav-actions">
          <button className="landing-login" onClick={() => navigate("/dashboard")}>Log in</button>
          <button className="landing-get-started" onClick={() => navigate("/dashboard")}>Get Started <span aria-hidden="true">↗</span></button>
        </div>
      </header>

      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="hero-copy">
          <div className="hero-eyebrow"><span className="eyebrow-spark" aria-hidden="true">✳</span> INFRASTRUCTURE MONITORING PLATFORM</div>
          <h1 id="landing-title"><span className="hero-line"><span>Know your systems.</span></span><span className="hero-line"><span className="gradient-words">Before they fail.</span></span></h1>
          <p className="hero-subtitle">Monitor your infrastructure, track service health, and detect issues before they impact your users.</p>
          <div className="hero-actions">
            <button className="hero-primary" onClick={() => navigate("/dashboard")}>Explore Dashboard <span aria-hidden="true">↗</span></button>
            <a className="hero-secondary" href="#features">Discover Features <span aria-hidden="true">↓</span></a>
          </div>
          <div className="hero-proof"><span className="proof-mark"><i /><i /><i /></span><span>Clarity for every layer of your stack</span></div>
        </div>

        <div className="hero-art" aria-label="Abstract animated infrastructure visualization">
          <div className="artwork-glow" aria-hidden="true" />
          {videoFailed ? (
            <img className="artwork-fallback" src={artworkPoster} alt="Abstract illuminated infrastructure network" />
          ) : (
            <video
              className="artwork-video"
              src={artworkVideo}
              poster={artworkPoster}
              autoPlay
              muted
              loop
              playsInline
              controls={false}
              disablePictureInPicture
              disableRemotePlayback
              controlsList="nodownload noplaybackrate noremoteplayback"
              tabIndex={-1}
              preload="auto"
              onCanPlay={(event) => {
                if (event.currentTarget.paused) {
                  void event.currentTarget.play().catch((error: unknown) => {
                    console.warn("PulseOps hero artwork autoplay was blocked by the browser.", error);
                  });
                }
              }}
              onError={() => setVideoFailed(true)}
              aria-label="Abstract animated infrastructure network"
            />
          )}
          <div className="art-card art-card-benchmark">
            <span className="art-card-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 18V9m5 9V5m5 13v-6m5 6V7M2 20h20" /></svg></span>
            <span><strong>Benchmarking</strong><small>Real-time service health and performance monitoring.</small></span>
            <span className="card-signal" aria-hidden="true"><i /><i /><i /><i /><i /></span>
          </div>
          <div className="art-card art-card-incidents">
            <span className="art-card-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3 3.7 18a1.4 1.4 0 0 0 1.2 2.1h14.2a1.4 1.4 0 0 0 1.2-2.1L12 3Z"/><path d="M12 9v4m0 3h.01"/></svg></span>
            <span><strong>Incident Detection</strong><small>Identify infrastructure issues before they affect users.</small></span>
            <span className="incident-pulse" aria-hidden="true"><i /></span>
          </div>
        </div>
      </section>

      <section id="features" className="landing-feature-strip" aria-label="PulseOps capabilities">
        <span className="feature-pill"><i /> Availability monitoring</span><span className="feature-pill"><i /> Real-time system metrics</span><span className="feature-pill"><i /> Incident timelines</span>
      </section>

      <footer className="landing-trust">
        <p>Built for reliable infrastructure</p>
        <div className="logo-marquee" aria-label="PulseOps and trusted infrastructure tools">
          <div className="logo-track">
            {[0, 1].map((copy) => <div className="logo-set" key={copy} aria-hidden={copy === 1}>
              <span className="trust-logo trust-pulse"><i>◉</i> PulseOps</span><span className="trust-logo"><i>◌</i> CloudSync</span><span className="trust-logo trust-nexora"><i>✳</i> Nexora</span><span className="trust-logo trust-stack"><i>▦</i> StackFlow</span>
            </div>)}
          </div>
        </div>
      </footer>
    </main>
  );
}
