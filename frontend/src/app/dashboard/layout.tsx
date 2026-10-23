"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { DashboardContext, type DashboardCtx as Ctx } from "@/components/dashboard-context";
import { api, session, type Me } from "@/lib/api";

const NAV = [
  ["/dashboard", "Réservations"],
  ["/dashboard/services", "Prestations"],
  ["/dashboard/availability", "Horaires"],
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [ctx, setCtx] = useState<Ctx | null>(null);

  useEffect(() => {
    if (!session.token()) {
      router.replace("/login");
      return;
    }
    api<Me>("/me", { auth: true })
      .then((me) => {
        const membership = me.memberships.find((m) => m.tenant_slug === session.tenant()) ?? me.memberships[0];
        if (!membership) throw new Error("aucune entreprise");
        session.setTenant(membership.tenant_slug);
        setCtx({ me, membership });
      })
      .catch(() => {
        session.clear();
        router.replace("/login");
      });
  }, [router]);

  if (!ctx) return <p className="p-10 text-center text-muted">Chargement…</p>;

  return (
    <DashboardContext.Provider value={ctx}>
      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <Logo href="/dashboard" />
          <div className="flex items-center gap-3 text-sm">
            <select
              aria-label="Entreprise"
              className="input w-auto py-1.5"
              value={ctx.membership.tenant_slug}
              onChange={(e) => {
                session.setTenant(e.target.value);
                window.location.reload();
              }}
            >
              {ctx.me.memberships.map((m) => (
                <option key={m.tenant_slug} value={m.tenant_slug}>
                  {m.tenant_name}
                </option>
              ))}
            </select>
            <Link href={`/${ctx.membership.tenant_slug}`} className="text-accent underline" target="_blank">
              Ma page publique
            </Link>
            <button
              className="text-muted hover:text-fg"
              onClick={() => {
                session.clear();
                router.push("/");
              }}
            >
              Déconnexion
            </button>
          </div>
        </header>
        <nav className="mt-6 flex gap-1 border-b border-line">
          {NAV.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${path === href ? "border-accent font-medium" : "border-transparent text-muted hover:text-fg"}`}
            >
              {label}
            </Link>
          ))}
        </nav>
        <div className="py-6">{children}</div>
      </div>
    </DashboardContext.Provider>
  );
}
