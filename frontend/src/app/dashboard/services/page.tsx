"use client";

import { useEffect, useState } from "react";
import { api, euros, type Service } from "@/lib/api";
import { useDashboard } from "@/components/dashboard-context";

export default function Services() {
  const { membership } = useDashboard();
  const manager = membership.role !== "staff";
  const [services, setServices] = useState<Service[]>([]);
  const [f, setF] = useState({ name: "", duration_minutes: 30, price: "0" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Service[]>("/admin/services", { auth: true }).then(setServices);
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const s = await api<Service>("/admin/services", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ name: f.name, duration_minutes: f.duration_minutes, price_cents: Math.round(parseFloat(f.price || "0") * 100) }),
      });
      setServices([...services, s]);
      setF({ name: "", duration_minutes: 30, price: "0" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function archive(id: string) {
    await api(`/admin/services/${id}`, { method: "DELETE", auth: true });
    setServices(services.map((s) => (s.id === id ? { ...s, active: false } : s)));
  }

  return (
    <div className="grid gap-6">
      <div className="grid gap-3">
        {services.map((s) => (
          <div key={s.id} className={`card flex items-center justify-between p-4 ${s.active ? "" : "opacity-50"}`}>
            <div>
              <p className="font-medium">{s.name}</p>
              <p className="text-sm text-muted">
                {s.duration_minutes} min · {euros(s.price_cents)} {s.active ? "" : "· archivée"}
              </p>
            </div>
            {manager && s.active && (
              <button onClick={() => archive(s.id)} className="text-sm text-muted hover:text-danger">
                Archiver
              </button>
            )}
          </div>
        ))}
        {services.length === 0 && <p className="text-muted">Ajoutez votre première prestation pour ouvrir les réservations.</p>}
      </div>

      {manager && (
        <form onSubmit={create} className="card grid gap-4 p-5 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-end">
          <div>
            <label className="label" htmlFor="sname">
              Prestation
            </label>
            <input id="sname" className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor="sdur">
              Durée (min)
            </label>
            <input
              id="sdur"
              type="number"
              min={5}
              step={5}
              className="input"
              value={f.duration_minutes}
              onChange={(e) => setF({ ...f, duration_minutes: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label" htmlFor="sprice">
              Prix (€)
            </label>
            <input id="sprice" type="number" min={0} step="0.5" className="input" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} />
          </div>
          <button className="btn-primary">Ajouter</button>
          {error && <p className="text-sm text-danger sm:col-span-4">{error}</p>}
        </form>
      )}
    </div>
  );
}
