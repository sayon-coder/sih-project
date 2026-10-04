import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import ProtectionTimeline from "./ProtectionTimeline.jsx";

const CSS = `
.lp { background: #FAF5EC; color: #1C2420; font-family: "Times New Roman", Times, serif; text-align: left; width: 100vw; margin-left: calc(50% - 50vw); position: relative; overflow-x: clip; }
.lp h1, .lp h2, .lp h3 { color: #1C2420; }
.lp p { margin: 0; }
.lp .lp-band h2 { color: #F2ECDF; }
.lp::before {
  content: ""; position: absolute; inset: 0; pointer-events: none; z-index: 0; opacity: 0.5;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3CfeColorMatrix values='0 0 0 0 0.35 0 0 0 0 0.32 0 0 0 0 0.27 0 0 0 0.05 0'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E");
}
.lp > * { position: relative; z-index: 1; }
.lp-serif { font-family: "Times New Roman", Times, serif; }
.lp-wrap { max-width: 1200px; margin: 0 auto; padding: 0 32px; }
.lp-nav { position: sticky; top: 0; z-index: 20; background: #FAF5EC; border-bottom: 1px solid #E4DACA; }
.lp-nav-inner { display: flex; align-items: center; justify-content: space-between; height: 64px; }
.lp-brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1C2420; font-weight: 700; letter-spacing: 0.02em; }
.lp-links { display: flex; align-items: center; gap: 28px; }
.lp-links a { text-decoration: none; color: #43524A; font-size: 14px; font-weight: 500; }
.lp-links a:hover { color: #1C2420; }
.lp-btn { display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 0 22px; border-radius: 999px; font-size: 15px; font-weight: 600; text-decoration: none; cursor: pointer; transition: background 180ms ease, color 180ms ease, border-color 180ms ease; }
.lp a.lp-btn-primary { background: #1E3A2F; color: #FAF5EC; border: 1px solid #1E3A2F; }
.lp a.lp-btn-primary:hover { background: #152A22; }
.lp a.lp-btn-ghost { background: transparent; color: #1E3A2F; border: 1px solid #B9AC93; }
.lp a.lp-btn-ghost:hover { border-color: #1E3A2F; }
.lp-btn-sm { min-height: 40px; padding: 0 18px; font-size: 14px; }
.lp-btn:focus-visible, .lp-links a:focus-visible { outline: 3px solid #B98A2F; outline-offset: 2px; }
.lp-hero { padding: 96px 0 88px; }
.lp-hero .lp-h1 { color: #1C2420; }
.lp-hero .lp-h1 em { color: #1E3A2F; }
.lp-hero .lp-sub { color: #43524A; }
.lp-cta-row { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 44px; }
.lp-eyebrow { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: #6B5E43; }
.lp-eyebrow::before { content: ""; width: 28px; height: 1px; background: #B98A2F; }
.lp-h1 { font-size: clamp(40px, 6vw, 68px); line-height: 1.04; font-weight: 400; letter-spacing: -0.01em; margin: 20px 0 20px; max-width: 16ch; }
.lp-h1 em { font-style: italic; color: #1E3A2F; }
.lp-sub { font-size: 18px; line-height: 1.65; color: #43524A; max-width: 58ch; margin: 0 0 32px; }
.lp-cta-row { display: flex; gap: 12px; flex-wrap: wrap; }
.lp-proof { margin-top: 28px; font-size: 13px; color: #6B7280; letter-spacing: 0.02em; }
.lp-rule { border: none; border-top: 1px solid #E4DACA; margin: 0; }
.lp-section { padding: 72px 0; }
.lp-kicker { font-size: 13px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: #6B5E43; margin: 0 0 12px; }
.lp-h2 { font-size: clamp(28px, 3.4vw, 40px); line-height: 1.12; font-weight: 400; margin: 0 0 16px; max-width: 22ch; }
.lp-lede { font-size: 17px; line-height: 1.65; color: #43524A; max-width: 64ch; margin: 0; }
.lp-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 40px; }
.lp-stat { background: #F3ECDD; border: 1px solid #E0D4BC; border-radius: 6px; padding: 20px; }
.lp-stat b { display: block; font-size: 30px; font-weight: 600; letter-spacing: -0.01em; }
.lp-stat span { font-size: 14px; color: #43524A; line-height: 1.5; display: block; margin-top: 4px; }
.lp-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: #E4DACA; border: 1px solid #E4DACA; margin-top: 40px; }
.lp-cell { background: #FAF5EC; padding: 28px; }
.lp-cell h3 { font-size: 18px; margin: 14px 0 8px; font-weight: 600; }
.lp-cell p { font-size: 15px; line-height: 1.6; color: #43524A; margin: 0; }
.lp-cell .n { font-size: 12px; font-weight: 700; letter-spacing: 0.12em; color: #B98A2F; }
.lp-steps { margin: 40px 0 0; padding: 0; list-style: none; }
.lp-steps li { display: grid; grid-template-columns: 56px 1fr; gap: 20px; padding: 20px 0; border-top: 1px solid #E4DACA; }
.lp-steps li:last-child { border-bottom: 1px solid #E4DACA; }
.lp-step-n { width: 40px; height: 40px; border-radius: 50%; border: 1px solid #B9AC93; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; color: #1E3A2F; }
.lp-steps b { font-size: 17px; }
.lp-steps p { margin: 4px 0 0; font-size: 15px; line-height: 1.6; color: #43524A; max-width: 68ch; }
.lp-band { background: #1E3A2F; color: #F2ECDF; border-radius: 4px; padding: 56px; margin-top: 8px; }
.lp-band h2 { font-size: clamp(26px, 3vw, 36px); line-height: 1.15; font-weight: 400; margin: 0 0 12px; max-width: 24ch; }
.lp-band p { color: #C9CFC6; font-size: 16px; line-height: 1.6; max-width: 60ch; margin: 0 0 28px; }
.lp a.lp-btn-cream { background: #F2ECDF; color: #1E3A2F; border: 1px solid #F2ECDF; }
.lp a.lp-btn-cream:hover { background: #fff; }
.lp a.lp-btn-outline-cream { background: transparent; color: #F2ECDF; border: 1px solid #7A8B7E; }
.lp a.lp-btn-outline-cream:hover { border-color: #F2ECDF; }
.lp-disc { font-size: 13px; line-height: 1.7; color: #6B7280; border-left: 2px solid #B98A2F; padding-left: 16px; margin-top: 40px; max-width: 72ch; }
.lp-footer { padding: 32px 0 48px; display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; font-size: 13px; color: #6B7280; }
.lp-reveal { opacity: 0; transform: translateY(16px); transition: opacity 0.5s ease, transform 0.5s ease; }
.lp-reveal.on { opacity: 1; transform: none; }
@media (prefers-reduced-motion: reduce) { .lp-reveal { opacity: 1; transform: none; transition: none; } }
@media (max-width: 860px) {
  .lp-hero { padding: 64px 0 48px; }
  .lp-stats { grid-template-columns: repeat(2, 1fr); }
  .lp-grid { grid-template-columns: 1fr; }
  .lp-band { padding: 36px 24px; }
  .lp-links a:not(.lp-btn) { display: none; }
}
`;

function Reveal({ children }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.classList.add("on");
      return;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && e.target.classList.add("on")),
      { threshold: 0.12 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return <div ref={ref} className="lp-reveal">{children}</div>;
}

function LeafMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <circle cx="13" cy="13" r="12" stroke="#1E3A2F" strokeWidth="1.5" />
      <path d="M13 19 C13 13 13 9 19 6 C19 12 17 17 13 19 Z" fill="#1E3A2F" />
      <path d="M13 19 C13 14 11 11 7 10 C8 14 10 17 13 19 Z" fill="#B98A2F" />
    </svg>
  );
}

const FEATURES = [
  ["01", "Ayurvedic Product Passport", "One persistent record per product — ingredients, formulation, claims, evidence and markets — versioned, hashed with SHA-256, and never silently rewritten."],
  ["02", "Source-cited answers", "Every assistant response carries citations to retrieved passages. If the verified corpus lacks evidence, it says so instead of inventing sources."],
  ["03", "IP route mapping", "Nine routes — patent, trademark, copyright, design, GI, trade secret, plant variety, traditional knowledge, biodiversity — derived from recorded data with careful, review-oriented labels."],
  ["04", "Change-impact comparison", "Compare any two versions and see ranked differences, from cultivated-to-wild sourcing shifts to new therapeutic claims, with review questions attached."],
  ["05", "Timestamped disclosure", "Record conference, publication or launch events with a SHA-256 hash and a verifiable ID, before you disclose — not after."],
  ["06", "Expert review workflow", "A full DRAFT-to-REVIEWED state machine. Only a completed expert review can promote a claim to verified — AI output stays distinguishable."],
];

const STEPS = [
  ["Record", "Build the Product Passport: botanicals, origin, extraction process, claims as user-provided data — never as established fact."],
  ["Screen", "Run patent, biodiversity/ABS and traditional-knowledge screens against public records. Demo corpus is labelled; restricted sources like TKDL are never touched."],
  ["Disclose safely", "Generate a timestamped disclosure record first, then present or publish with dated evidence in hand."],
  ["Review", "Hand the package to an expert. Corrections round-trip through the workflow until the review is complete and archived."],
];

const STATS = [
  ["9", "IP routes assessed from recorded product data"],
  ["4", "Screening outcomes — never a legal conclusion"],
  ["3", "Interface languages: English, Hindi, Bengali"],
  ["0", "Invented citations. Unverified claims stay unverified."],
];

export default function Landing() {
  return (
    <div className="lp">
      <style>{CSS}</style>

      <header className="lp-nav">
        <div className="lp-wrap lp-nav-inner">
          <Link to="/" className="lp-brand" aria-label="IP-SAKTI Sahayak home">
            <LeafMark />
            <span>IP-SAKTI Sahayak</span>
          </Link>
          <nav className="lp-links" aria-label="Primary">
            <a href="#platform">Platform</a>
            <a href="#method">Method</a>
            <Link to="/overview">Overall product view</Link>
            <Link to="/login">Sign in</Link>
            <Link to="/register" className="lp-btn lp-btn-primary lp-btn-sm">Get access</Link>
          </nav>
        </div>
      </header>

      <main>
        <section className="lp-hero">
          <div className="lp-wrap">
          <h1 className="lp-h1 lp-serif">Protect Ayurvedic knowledge <em>before</em> you disclose it.</h1>
          <p className="lp-sub">
            IP-SAKTI Sahayak is a source-backed workspace for Ayurveda products: a persistent
            Product Passport, evidence-linked claims, patent and biodiversity screening, timestamped
            disclosure records, and expert review — in English, Hindi and Bengali.
          </p>
          <div className="lp-cta-row">
            <Link to="/register" className="lp-btn lp-btn-primary">Start a product passport</Link>
            <Link to="/overview" className="lp-btn lp-btn-ghost">See the overall product view</Link>
          </div>
          </div>
        </section>

        <hr className="lp-rule" />

        <section className="lp-wrap lp-section" id="platform">
          <Reveal>
            <p className="lp-kicker">The platform</p>
            <h2 className="lp-h2 lp-serif">One record, from first ingredient to expert sign-off.</h2>
            <p className="lp-lede">Everything attaches to a versioned Product Passport, so history is never rewritten and every answer traces to a source.</p>
          </Reveal>
          <div className="lp-grid">
            {FEATURES.map(([n, t, d]) => (
              <div className="lp-cell" key={n}>
                <span className="n">{n}</span>
                <h3>{t}</h3>
                <p>{d}</p>
              </div>
            ))}
          </div>
          <div className="lp-stats">
            {STATS.map(([v, l]) => (
              <div className="lp-stat" key={l}><b className="lp-serif">{v}</b><span>{l}</span></div>
            ))}
          </div>
        </section>

        <hr className="lp-rule" />

        <section className="lp-wrap lp-section" id="method">
          <Reveal>
            <p className="lp-kicker">How it works</p>
            <h2 className="lp-h2 lp-serif">A calm, ordered path from research to protection.</h2>
          </Reveal>
          <ol className="lp-steps">
            {STEPS.map(([t, d], i) => (
              <li key={t}>
                <span className="lp-step-n" aria-hidden="true">{i + 1}</span>
                <div><b>{t}</b><p>{d}</p></div>
              </li>
            ))}
          </ol>
        </section>

        <section className="lp-wrap lp-section" id="timeline" style={{ paddingTop: 0 }}>
          <Reveal>
            <p className="lp-kicker">Protection timeline</p>
            <h2 className="lp-h2 lp-serif">Four minutes of foresight, or eighteen months of work lost.</h2>
          </Reveal>
          <ProtectionTimeline />
        </section>

        <section className="lp-wrap lp-section" style={{ paddingTop: 0 }}>
          <p className="lp-disc">
            This platform provides preliminary, source-backed information and decision support. It does not
            constitute legal, patent, regulatory, medical, or government advice or approval. Patent outputs
            are not determinations of patentability, validity, infringement, or priority.
          </p>
        </section>
      </main>

      <hr className="lp-rule" />
      <footer className="lp-wrap lp-footer">
        <span>© 2026 IP-SAKTI Sahayak</span>
        <span><Link to="/login" style={{ color: "inherit" }}>Sign in</Link> · EN / HI / BN</span>
      </footer>
    </div>
  );
}
