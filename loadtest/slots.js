// Charge en lecture : des visiteurs consultent les créneaux de plusieurs prestations sur 14 jours.
// k6 run -e API=http://localhost:8000 -e SLUG=studio-zen loadtest/slots.js
import http from "k6/http";
import { check } from "k6";

const API = __ENV.API || "http://localhost:8000";
const SLUG = __ENV.SLUG || "studio-zen";

export const options = {
  scenarios: {
    visitors: { executor: "constant-vus", vus: Number(__ENV.VUS || 50), duration: __ENV.DURATION || "30s" },
  },
  thresholds: { http_req_failed: ["rate<0.01"] },
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "max"],
};

export function setup() {
  const tenant = http.get(`${API}/public/${SLUG}`).json();
  const days = [];
  const d = new Date();
  for (let i = 0; i < 14; i++) days.push(new Date(d.getFullYear(), d.getMonth(), d.getDate() + i).toISOString().slice(0, 10));
  return { services: tenant.services.map((s) => s.id), days };
}

export default function (data) {
  const service = data.services[Math.floor(Math.random() * data.services.length)];
  const day = data.days[Math.floor(Math.random() * data.days.length)];
  const res = http.get(`${API}/public/${SLUG}/slots?service_id=${service}&date=${day}`, { tags: { name: "slots" } });
  check(res, { "200": (r) => r.status === 200 });
}
