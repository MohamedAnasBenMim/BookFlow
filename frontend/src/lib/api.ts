// Client typé de l'API BookFlow.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Service = {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  price_cents: number;
  active: boolean;
};

export type PublicTenant = { slug: string; name: string; timezone: string; currency: string; services: Service[] };
export type Slot = { start: string; staff_ids: string[] };
export type BookingStatus = "pending_payment" | "confirmed" | "cancelled";

export type Booking = {
  id: string;
  service_id: string;
  service_name: string;
  staff_id: string;
  customer_name: string;
  customer_email: string;
  start_at: string;
  end_at: string;
  status: BookingStatus;
  price_cents: number;
};

export type Membership = { tenant_slug: string; tenant_name: string; role: "owner" | "admin" | "staff" };
export type Me = { id: string; email: string; name: string; memberships: Membership[] };
export type Rule = { weekday: number; start_time: string; end_time: string };
export type Stats = { bookings_next_7_days: number; revenue_cents_last_30_days: number; cancellation_rate_last_30_days: number };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "bookflow.token";
const TENANT_KEY = "bookflow.tenant";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export const session = {
  token: () => storage()?.getItem(TOKEN_KEY) ?? null,
  tenant: () => storage()?.getItem(TENANT_KEY) ?? null,
  save: (token: string) => storage()?.setItem(TOKEN_KEY, token),
  setTenant: (slug: string) => storage()?.setItem(TENANT_KEY, slug),
  clear: () => {
    storage()?.removeItem(TOKEN_KEY);
    storage()?.removeItem(TENANT_KEY);
  },
};

export async function api<T>(path: string, init: RequestInit & { auth?: boolean } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.auth) {
    const token = session.token();
    const tenant = session.tenant();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (tenant) headers.set("X-Tenant", tenant);
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const money = (cents: number, currency = "eur") =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);

// Prix d'une prestation : « Gratuit » plutôt que « 0,00 € »
export const euros = (cents: number, currency = "eur") => (cents === 0 ? "Gratuit" : money(cents, currency));

export const fmtTime = (iso: string, tz: string) =>
  new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(iso));

export const fmtDateTime = (iso: string, tz = "Europe/Paris") =>
  new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: tz }).format(
    new Date(iso),
  );
