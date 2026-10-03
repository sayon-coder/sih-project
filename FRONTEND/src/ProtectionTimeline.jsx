import { useEffect, useState } from "react";

const LEFT_EVENTS = [
  { icon: "🔬", label: "Research developed", sublabel: "18 months of work" },
  { icon: "🎤", label: "Conference presentation", sublabel: "Disclosed publicly — no protection in place" },
  { icon: "📄", label: "Journal submitted", sublabel: "Now fully public" },
  { icon: "⚠️", label: "Foreign company files patent", sublabel: "Germany — 14 months after disclosure", danger: true },
  { icon: "❌", label: "IP lost permanently", sublabel: "Prior art destroyed — opposition not possible", danger: true, big: true },
];

const RIGHT_EVENTS = [
  { icon: "🔬", label: "Research developed", sublabel: "18 months of work" },
  { icon: "🛡️", label: "IP-SAKTI Interview — 4 minutes", sublabel: "Knowledge Fingerprint created · SHA-256 timestamp", teal: true },
  { icon: "📄", label: "Disclosure Record generated", sublabel: "Dated evidence exists — safe to present", good: true },
  { icon: "🎤", label: "Conference presentation", sublabel: "Safe — prior art already documented" },
  { icon: "📄", label: "Journal submitted", sublabel: "Safe — protection predates disclosure" },
  { icon: "⚠️", label: "Foreign company files patent", sublabel: "Germany — same timing as left track" },
  { icon: "✅", label: "Opposition filed successfully", sublabel: "IP-SAKTI record establishes prior date — protection upheld", good: true, big: true },
];

const CSS = `
.pt-event { opacity: 0; transform: translateY(20px); animation: pt-in 0.4s ease forwards; }
@keyframes pt-in { to { opacity: 1; transform: translateY(0); } }
`;

function TimelineColumn({ title, headerColor, events, baseDelay }) {
  return (
    <div style={{ flex: 1, minWidth: "280px" }}>
      <div style={{ background: headerColor, color: "#fff", fontWeight: 700, textAlign: "center", padding: "10px", borderRadius: "8px 8px 0 0" }}>
        {title}
      </div>
      <div style={{ border: "1px solid #E7DFCE", borderTop: "none", borderRadius: "0 0 8px 8px", padding: "12px" }}>
        {events.map((e, i) => (
          <div
            key={i}
            className="pt-event"
            style={{ animationDelay: `${baseDelay + i * 500}ms`, display: "flex", gap: "12px", alignItems: "flex-start", padding: "10px 0", borderBottom: i < events.length - 1 ? "1px solid #F3EEE1" : "none" }}
          >
            <div style={{
              width: e.big ? 48 : 40, height: e.big ? 48 : 40, borderRadius: "50%",
              background: e.danger ? "#fef2f2" : e.good ? "#f0fdf4" : e.teal ? "#f0fdfa" : "#FAF5EC",
              border: `2px solid ${e.danger ? "#b91c1c" : e.good ? "#15803d" : e.teal ? "#0d9488" : "#C9C1AE"}`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: e.big ? "24px" : "20px", flexShrink: 0,
            }}>
              {e.icon}
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: e.big ? "16px" : "14px", color: e.danger ? "#b91c1c" : e.good ? "#15803d" : "#111827" }}>
                {e.label}
              </div>
              <div style={{ fontSize: "12.5px", color: "#5B6670" }}>{e.sublabel}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ProtectionTimeline() {
  const [started, setStarted] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setStarted(true), 50);
    return () => clearTimeout(t);
  }, []);

  return (
    <div>
      <style>{CSS}</style>
      <p style={{ color: "#5B6670", margin: "0 0 16px", fontSize: "14px" }}>
        Illustrative scenario — same research, two different choices.
      </p>
      {started && (
        <div style={{ display: "flex", gap: "24px", flexWrap: "wrap" }}>
          <TimelineColumn title="WITHOUT IP-SAKTI SAHAYAK" headerColor="#b91c1c" events={LEFT_EVENTS} baseDelay={0} />
          <TimelineColumn title="WITH IP-SAKTI SAHAYAK" headerColor="#15803d" events={RIGHT_EVENTS} baseDelay={200} />
        </div>
      )}
      <p style={{ textAlign: "center", fontFamily: "Georgia, \"Palatino Linotype\", \"Times New Roman\", serif", fontWeight: 600, fontSize: "19px", lineHeight: 1.4, color: "#1C2420", margin: "28px 0 16px" }}>
        Every other tool responds after you have a problem. IP-SAKTI Sahayak protects you before the problem can occur.
      </p>
    </div>
  );
}
