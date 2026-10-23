"use client";

import { useEffect, useState } from "react";
import { api, type Rule } from "@/lib/api";

const DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
type Day = { open: boolean; start: string; end: string };

export default function Availability() {
  const [week, setWeek] = useState<Day[] | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api<Rule[]>("/admin/availability", { auth: true }).then((rules) => {
      setWeek(
        DAYS.map((_, i) => {
          const r = rules.filter((x) => x.weekday === i);
          return r.length
            ? { open: true, start: r[0].start_time.slice(0, 5), end: r[r.length - 1].end_time.slice(0, 5) }
            : { open: false, start: "09:00", end: "18:00" };
        }),
      );
    });
  }, []);

  async function save() {
    if (!week) return;
    const rules = week.flatMap((d, i) => (d.open ? [{ weekday: i, start_time: d.start, end_time: d.end }] : []));
    await api("/admin/availability", { method: "PUT", auth: true, body: JSON.stringify(rules) });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  if (!week) return <p className="text-muted">Chargement…</p>;
  const update = (i: number, patch: Partial<Day>) => setWeek(week.map((d, j) => (j === i ? { ...d, ...patch } : d)));

  return (
    <div className="card grid gap-3 p-5">
      <p className="text-sm text-muted">Vos horaires de disponibilité, chaque semaine. Les clients ne voient que les créneaux libres dans ces plages.</p>
      {week.map((d, i) => (
        <div key={DAYS[i]} className="flex flex-wrap items-center gap-3">
          <label className="flex w-32 items-center gap-2">
            <input type="checkbox" checked={d.open} onChange={(e) => update(i, { open: e.target.checked })} />
            {DAYS[i]}
          </label>
          {d.open ? (
            <>
              <input type="time" className="input w-auto" value={d.start} onChange={(e) => update(i, { start: e.target.value })} />
              <span className="text-muted">à</span>
              <input type="time" className="input w-auto" value={d.end} onChange={(e) => update(i, { end: e.target.value })} />
            </>
          ) : (
            <span className="text-muted">Fermé</span>
          )}
        </div>
      ))}
      <div className="mt-2 flex items-center gap-3">
        <button className="btn-primary" onClick={save}>
          Enregistrer
        </button>
        {saved && <span className="text-sm text-accent">Enregistré</span>}
      </div>
    </div>
  );
}
