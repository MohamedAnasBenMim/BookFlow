"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, euros, fmtDateTime, type Booking } from "@/lib/api";

const LABELS = {
  confirmed: ["Rendez-vous confirmé", "Un email de confirmation vous a été envoyé, puis un rappel la veille."],
  pending_payment: ["Paiement en attente", "Votre créneau est réservé pendant 15 minutes, le temps de finaliser le paiement."],
  cancelled: ["Rendez-vous annulé", "Ce rendez-vous a été annulé."],
} as const;

function BookingStatus() {
  const { slug, id } = useParams<{ slug: string; id: string }>();
  const token = useSearchParams().get("token") ?? "";
  const [booking, setBooking] = useState<Booking | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api<Booking>(`/public/${slug}/bookings/${id}?token=${encodeURIComponent(token)}`)
      .then(setBooking)
      .catch(() => setError(true));
  }, [slug, id, token]);

  async function cancel() {
    if (!confirm("Annuler ce rendez-vous ?")) return;
    setBooking(await api<Booking>(`/public/${slug}/bookings/${id}/cancel?token=${encodeURIComponent(token)}`, { method: "POST" }));
  }

  if (error) return <p className="p-10 text-center text-muted">Réservation introuvable.</p>;
  if (!booking) return <p className="p-10 text-center text-muted">Chargement…</p>;
  const [title, text] = LABELS[booking.status];

  return (
    <main className="mx-auto max-w-lg px-4 py-12">
      <div className="card p-6" data-testid="booking-status" data-status={booking.status}>
        <h1 className="font-display text-2xl font-semibold">{title}</h1>
        <p className="mt-2 text-muted">{text}</p>
        <dl className="mt-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted">Prestation</dt>
          <dd>{booking.service_name}</dd>
          <dt className="text-muted">Quand</dt>
          <dd className="first-letter:uppercase">{fmtDateTime(booking.start_at)}</dd>
          <dt className="text-muted">Prix</dt>
          <dd>{euros(booking.price_cents)}</dd>
          <dt className="text-muted">Au nom de</dt>
          <dd>{booking.customer_name}</dd>
        </dl>
        <div className="mt-6 flex flex-wrap gap-2">
          <Link href={`/${slug}`} className="btn-ghost">
            Nouvelle réservation
          </Link>
          {booking.status !== "cancelled" && (
            <button onClick={cancel} className="btn-ghost text-danger">
              Annuler le rendez-vous
            </button>
          )}
        </div>
      </div>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense>
      <BookingStatus />
    </Suspense>
  );
}
