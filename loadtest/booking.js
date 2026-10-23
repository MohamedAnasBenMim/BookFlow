// Contention : 100 clients tentent de réserver les 5 mêmes créneaux en même temps.
// Attendu : exactement 5 réservations réussies, toutes les autres en 409, aucune erreur 5xx.
// Lancer l'API avec RATE_LIMIT_BOOKINGS_PER_MINUTE élevé (toutes les requêtes viennent de la même IP).
import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const API = __ENV.API || "http://localhost:8000";
const SLUG = __ENV.SLUG || "barber-lyon";
const created = new Counter("bookings_created");
const conflicts = new Counter("bookings_conflict");

export const options = {
  scenarios: { rush: { executor: "per-vu-iterations", vus: 100, iterations: 1, maxDuration: "30s" } },
  thresholds: { "http_req_failed{expected_response:true}": ["rate<0.01"] },
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "max"],
};

export function setup() {
  const tenant = http.get(`${API}/public/${SLUG}`).json();
  const service = tenant.services[0].id;
  const d = new Date();
  for (let i = 3; i < 20; i++) {
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate() + i).toISOString().slice(0, 10);
    const r = http.get(`${API}/public/${SLUG}/slots?service_id=${service}&date=${day}`).json();
    if (r.slots.length >= 20) return { service, starts: r.slots.filter((_, i) => i % 4 === 0).slice(0, 5).map((s) => s.start) };
  }
  throw new Error("pas assez de créneaux");
}

export default function (data) {
  const start = data.starts[__VU % data.starts.length];
  const res = http.post(
    `${API}/public/${SLUG}/bookings`,
    JSON.stringify({ service_id: data.service, start, customer_name: `VU ${__VU}`, customer_email: `vu${__VU}@loadtest.example.com` }),
    { headers: { "Content-Type": "application/json" }, responseCallback: http.expectedStatuses(201, 409) },
  );
  if (res.status === 201) created.add(1);
  if (res.status === 409) conflicts.add(1);
  check(res, { "201 ou 409": (r) => r.status === 201 || r.status === 409 });
}
