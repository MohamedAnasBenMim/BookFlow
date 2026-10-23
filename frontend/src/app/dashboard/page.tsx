"use client";

import { useCallback, useEffect, useState } from "react";
import { api, fmtDateTime, money, type Booking, type Stats } from "@/lib/api";
import { useDashboard } from "@/components/dashboard-context";

const STATUS = {
  confirmed: ["Confirmé", "bg-accent-soft text-accent"],
  pending_payment: ["Paiement en attente", "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"],
  cancelled: ["Annulé", "bg-line text-muted"],
} as const;

export default function Bookings() {
  const { membership } = useDashboard();
  const manager = membership.role !== "staff";
  const [items, setItems] = useState<Booking[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (after: string | null) => {
    const from = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const qs = new URLSearchParams({ from, limit: "20", ...(after ? { cursor: after } : {}) });
    const page = await api<{ items: Booking[]; next_cursor: string | null }>(`/admin/bookings?${qs}`, { auth: true });
    setItems((prev) => (after ? [...prev, ...page.items] : page.items));
    setCursor(page.next_cursor);
    setLoading(false);
  }, []);

  useEffect(() => {
    load(null);
    if (manager) api<Stats>("/admin/stats", { auth: true }).then(setStats);
  }, [load, manager]);

  async function cancel(id: string) {
    if (!confirm("Annuler ce rendez-vous ? Le client sera prévenu par email.")) return;
    await api(`/admin/bookings/${id}/cancel`, { method: "POST", auth: true });
    setItems((prev) => prev.map((b) => (b.id === id ? { ...b, status: "cancelled" } : b)));
  }

  return (
    <div className="grid gap-6">
      {stats && (
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ["Rendez-vous sur 7 jours", String(stats.bookings_next_7_days)],
            ["Chiffre d'affaires (30 j)", money(stats.revenue_cents_last_30_days)],
            ["Taux d'annulation (30 j)", `${Math.round(stats.cancellation_rate_last_30_days * 100)} %`],
          ].map(([label, value]) => (
            <div key={label} className="card p-4">
              <p className="text-sm text-muted">{label}</p>
              <p className="mt-1 font-display text-2xl font-semibold">{value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm" data-testid="bookings-table">
          <thead className="border-b border-line text-left text-muted">
            <tr>
              <th className="p-3 font-medium">Quand</th>
              <th className="p-3 font-medium">Client</th>
              <th className="p-3 font-medium">Prestation</th>
              <th className="p-3 font-medium">Statut</th>
              <th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {items.map((b) => (
              <tr key={b.id} className="border-b border-line last:border-0">
                <td className="p-3 whitespace-nowrap first-letter:uppercase">{fmtDateTime(b.start_at)}</td>
                <td className="p-3">
                  <span className="block">{b.customer_name}</span>
                  <span className="text-muted">{b.customer_email}</span>
                </td>
                <td className="p-3">{b.service_name}</td>
                <td className="p-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS[b.status][1]}`}>{STATUS[b.status][0]}</span>
                </td>
                <td className="p-3 text-right">
                  {b.status !== "cancelled" && (
                    <button onClick={() => cancel(b.id)} className="text-danger hover:underline">
                      Annuler
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && items.length === 0 && <p className="p-6 text-center text-muted">Aucun rendez-vous à venir.</p>}
      </div>
      {cursor && (
        <button className="btn-ghost justify-self-center" onClick={() => load(cursor)}>
          Afficher plus
        </button>
      )}
    </div>
  );
}
