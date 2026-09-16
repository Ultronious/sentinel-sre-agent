const scenarios = [
  {
    id: "single_slow_request",
    fixture: "incident_1151.json",
    incident: "TargetResponseTime reached 2.001781s at 11:51:00 UTC; alarm transitioned OK → ALARM at 11:54:47 UTC.",
    evidence: [
      ["Requests", "42 total; /health 40× HTTP 200"],
      ["Slow request", "/slow · HTTP 200 · 2000.59ms"],
      ["ALB", "TargetResponseTime 2.001781s"],
      ["ECS", "CPU 0.235% → 0.265%; memory ~6.64%"]
    ],
    correlations: [
      "The /slow request and ALB latency spike occur at the same timestamp.",
      "The request duration (2000.59ms) closely matches the ALB metric (2001.78ms).",
      "Historical alarm history shows recurring latency spikes."
    ],
    hypotheses: [
      "The /slow request may have been the source of the elevated latency.",
      "The /slow endpoint may have performance characteristics contributing to latency."
    ],
    unknowns: [
      "Whether the /slow request caused the latency or was coincidental.",
      "Whether /slow is intentionally slow or malfunctioning.",
      "What caused the other historical spikes.",
      "Whether infrastructure changes occurred."
    ],
    explanation: "Strong temporal and magnitude correlation exists, but the available evidence does not directly establish causation."
  },
  {
    id: "cpu_pressure",
    fixture: "cpu_pressure.json",
    incident: "TargetResponseTime rose to 3.2s at 08:10:00 UTC while ECS CPU rose from 18% to 91%.",
    evidence: [
      ["ALB", "0.15s → 3.2s → 2.8s"],
      ["Application", "12× /api requests · all HTTP 200 · avg 3200ms"],
      ["CPU", "18% → 91% → 88%"],
      ["Memory", "Stable at 35–37%"]
    ],
    correlations: [
      "CPU utilization and TargetResponseTime rise together at the incident timestamp.",
      "Both remain elevated into the following minute.",
      "Memory remains flat and shows no comparable pressure."
    ],
    hypotheses: [
      "CPU contention may be related to the latency spike.",
      "External workload or an upstream dependency may have driven both signals.",
      "An application-level CPU-intensive operation may have occurred."
    ],
    unknowns: [
      "What caused the CPU spike.",
      "Whether high CPU caused latency or both reflected another cause.",
      "Whether recent infrastructure changes occurred."
    ],
    explanation: "The correlation is strong, but the evidence does not establish causal direction."
  },
  {
    id: "missing_logs",
    fixture: "missing_logs.json",
    incident: "TargetResponseTime increased from 0.12s to 4.5s at 09:20:00 UTC; application telemetry is unavailable.",
    evidence: [
      ["ALB", "0.12s → 4.5s → 4.1s"],
      ["ECS CPU", "22% → 24% → 23%"],
      ["ECS memory", "40% → 41% → 40%"],
      ["Application", "No request count, duration, or path telemetry"]
    ],
    correlations: [
      "The latency spike temporally aligns with the incident window.",
      "ECS resource utilization shows no significant pressure.",
      "Missing application telemetry prevents request-level correlation."
    ],
    hypotheses: [
      "A downstream dependency may have contributed to the slowdown.",
      "A network condition may have affected requests.",
      "An application-level delay cannot be characterized from the available evidence."
    ],
    unknowns: [
      "Which endpoints experienced elevated latency.",
      "Which requests or dependencies were involved.",
      "Whether infrastructure/configuration changes occurred."
    ],
    explanation: "The investigation is blocked by missing application-level evidence, so causal attribution is not possible."
  },
  {
    id: "historical_task_attribution",
    fixture: "historical_task.json",
    incident: "TargetResponseTime reached 2.8s at 10:30:00 UTC; the historical task spans the incident window.",
    evidence: [
      ["ALB", "0.18s → 2.8s → 0.25s"],
      ["/slow", "3 requests · avg 2775.2ms"],
      ["Historical task", "historical-task-001 active 10:10–10:40"],
      ["Current task", "current-task-999 was not active during incident"]
    ],
    correlations: [
      "The /slow requests correlate with the ALB spike in time and magnitude.",
      "The /slow sample count matches the incident sample count.",
      "Historical task attribution matches the incident window."
    ],
    hypotheses: [
      "Traffic to /slow may have contributed to the spike.",
      "A backend dependency may have introduced delay.",
      "A transient network condition may have affected the requests."
    ],
    unknowns: [
      "Why /slow requests took ~2.8s.",
      "Whether an upstream dependency was slow.",
      "Whether configuration changes occurred."
    ],
    explanation: "The historical task is correctly attributed, but correlation between /slow and latency still does not prove causation."
  },
  {
    id: "cloudtrail_gap",
    fixture: "cloudtrail_gap.json",
    incident: "TargetResponseTime reached 1.9s at 11:15:00 UTC and recovered the following minute.",
    evidence: [
      ["ALB", "0.11s → 1.9s → 0.14s"],
      ["Application", "4× /api requests · one request at 1900ms"],
      ["ECS", "CPU 12% → 13%; memory 30% → 30.5%"],
      ["CloudTrail", "0 RunTask / 0 StopTask observed"]
    ],
    correlations: [
      "One 1900ms request aligns with the 1.9s ALB spike.",
      "CPU and memory vary minimally during the event.",
      "The spike is transient and recovers after one minute."
    ],
    hypotheses: [
      "A downstream dependency may have delayed one request.",
      "A transient network issue may have contributed.",
      "Application logic may have caused a single slow request."
    ],
    unknowns: [
      "The specific operation behind the slow request.",
      "Downstream dependency behavior.",
      "Detailed tracing information.",
      "Whether unobserved infrastructure changes occurred outside the queried CloudTrail event types."
    ],
    explanation: "The incident is well correlated with one slow request, but the available evidence cannot identify the causal mechanism."
  }
];

const list = document.getElementById('scenario-list');
const title = document.getElementById('report-title');
const bar = document.getElementById('incident-bar');
const evidence = document.getElementById('evidence');
const correlations = document.getElementById('correlations');
const hypotheses = document.getElementById('hypotheses');
const unknowns = document.getElementById('unknowns');
const rootExplanation = document.getElementById('root-explanation');

function esc(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderScenario(s) {
  title.textContent = s.id;
  bar.textContent = `${s.fixture} · ${s.incident}`;
  evidence.innerHTML = s.evidence.map(([k,v]) => `<div class="fact"><div class="fact-label">${esc(k)}</div><div class="fact-value">${esc(v)}</div></div>`).join('');
  correlations.innerHTML = s.correlations.map(x => `<li>${esc(x)}</li>`).join('');
  hypotheses.innerHTML = s.hypotheses.map(x => `<li>${esc(x)}</li>`).join('');
  unknowns.innerHTML = s.unknowns.map(x => `<li>${esc(x)}</li>`).join('');
  rootExplanation.textContent = s.explanation;
  document.querySelectorAll('.scenario-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.id === s.id));
}

scenarios.forEach(s => {
  const btn = document.createElement('button');
  btn.className = 'scenario-btn';
  btn.dataset.id = s.id;
  btn.innerHTML = `<div class="scenario-name">${s.id}</div><div class="scenario-meta">${s.fixture} · PASS</div>`;
  btn.addEventListener('click', () => renderScenario(s));
  list.appendChild(btn);
});

renderScenario(scenarios[0]);
