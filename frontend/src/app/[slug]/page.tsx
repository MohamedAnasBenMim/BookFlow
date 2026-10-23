"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Logo } from "@/components/Logo";
import { api, ApiError, euros, fmtTime, type Booking, type PublicTenant, type Service, type Slot } from "@/lib/api";

type Created = { booking: Booking; access_token: string; checkout_url: string | null };

function nextDays(n: number): Date[] {
  const today = new Date();
  return Array.from({ length: n }, (_, i) => new Date(today.getFullYear(), today.getMonth(), today.getDate() + i));
}

const isoDate = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export default function BookingPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [tenant, setTenant] = useState<PublicTenant | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [service, setService] = useState<Service | null>(null);
  const days = useMemo(() => nextDays(14), []);
  const [day, setDay] = useState<Date>(days[0]);
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [slot, setSlot] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", email: "" });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api<PublicTenant>(`/public/${slug}`)
      .then(setTenant)
      .catch(() => setNotFound(true));
  }, [slug]);

  const loadSlots = useCallback(() => {
    if (!service) return;
    setSlots(null);
    setSlot(null);
    api<{ slots: Slot[] }>(`/public/${slug}/slots?service_id=${service.id}&date=${isoDate(day)}`)
      .then((r) => setSlots(r.slots))
      .catch(() => setSlots([]));
  }, [service, day, slug]);

  useEffect(loadSlots, [loadSlots]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!service || !slot) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api<Created>(`/public/${slug}/bookings`, {
        method: "POST",
        body: JSON.stringify({ service_id: service.id, start: slot, customer_name: form.name, customer_email: form.email }),
      });
      if (res.checkout_url) window.location.href = res.checkout_url;
      else router.push(`/${slug}/booking/${res.booking.id}?token=${res.access_token}`);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409 ? "Ce créneau vient d'être réservé. Choisissez-en un autre." : "La réservation a échoué.");
      loadSlots();
      setSubmitting(false);
    }
  }

  if (notFound) return <p className="p-10 text-center text-muted">Cette page de réservation n&apos;existe pas.</p>;
  if (!tenant) return <p className="p-10 text-center text-muted">Chargement…</p>;

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <header className="mb-8">
        <h1 className="font-display text-3xl font-semibold">{tenant.name}</h1>
        <p className="mt-1 text-muted">Réservez votre rendez-vous en ligne.</p>
      </header>

      <section aria-labelledby="step-service">
        <h2 id="step-service" className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          1. Prestation
        </h2>
        <div className="grid gap-3">
          {tenant.services.map((s) => (
            <button
              key={s.id}
              onClick={() => setService(s)}
              className={`card flex items-center justify-between p-4 text-left transition hover:border-accent ${service?.id === s.id ? "border-accent ring-2 ring-accent/20" : ""}`}
            >
              <span>
                <span className="block font-medium">{s.name}</span>
                <span className="text-sm text-muted">
                  {s.duration_minutes} min{s.description ? ` · ${s.description}` : ""}
                </span>
              </span>
              <span className="ml-4 font-medium whitespace-nowrap">{euros(s.price_cents, tenant.currency)}</span>
            </button>
          ))}
        </div>
      </section>

      {service && (
        <section className="mt-8" aria-labelledby="step-date">
          <h2 id="step-date" className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
            2. Date et heure
          </h2>
          <div className="flex gap-2 overflow-x-auto pb-2">
            {days.map((d) => (
              <button
                key={d.toISOString()}
                onClick={() => setDay(d)}
                className={`min-w-16 rounded-lg border px-3 py-2 text-center text-sm ${isoDate(d) === isoDate(day) ? "border-accent bg-accent text-accent-fg" : "border-line bg-surface"}`}
              >
                <span className="block capitalize">{d.toLocaleDateString("fr-FR", { weekday: "short" })}</span>
                <span className="block text-lg font-semibold">{d.getDate()}</span>
              </button>
            ))}
          </div>
          <div className="mt-4">
            {slots === null ? (
              <p className="text-muted">Recherche des créneaux…</p>
            ) : slots.length === 0 ? (
              <p className="text-muted">Aucun créneau ce jour-là.</p>
            ) : (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-5" data-testid="slots">
                {slots.map((s) => (
                  <button
                    key={s.start}
                    onClick={() => setSlot(s.start)}
                    className={`rounded-lg border py-2 text-sm font-medium ${slot === s.start ? "border-accent bg-accent text-accent-fg" : "border-line bg-surface hover:border-accent"}`}
                  >
                    {fmtTime(s.start, tenant.timezone)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {service && slot && (
        <form onSubmit={submit} className="card mt-8 grid gap-4 p-5" aria-labelledby="step-info">
          <h2 id="step-info" className="text-sm font-semibold uppercase tracking-wide text-muted">
            3. Vos coordonnées
          </h2>
          <div>
            <label className="label" htmlFor="name">
              Nom
            </label>
            <input id="name" className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              className="input"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
          <button className="btn-primary" disabled={submitting}>
            {service.price_cents > 0 ? `Réserver et payer ${euros(service.price_cents, tenant.currency)}` : "Confirmer la réservation"}
          </button>
        </form>
      )}

      <footer className="mt-12 text-center text-sm text-muted">
        Propulsé par <Logo />
      </footer>
    </main>
  );
}
