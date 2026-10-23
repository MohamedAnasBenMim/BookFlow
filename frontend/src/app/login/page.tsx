"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Logo } from "@/components/Logo";
import { api, ApiError, session, type Me } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const demo = useSearchParams().get("demo") === "1";
  const [email, setEmail] = useState(demo ? "demo@bookflow.dev" : "");
  const [password, setPassword] = useState(demo ? "demo1234" : "");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const { access_token } = await api<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      session.save(access_token);
      const me = await api<Me>("/me", { auth: true });
      if (me.memberships[0]) session.setTenant(me.memberships[0].tenant_slug);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? "Trop de tentatives, réessayez dans une minute." : "Email ou mot de passe incorrect.");
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm px-4 py-16">
      <Logo />
      <h1 className="mt-8 font-display text-2xl font-semibold">Connexion</h1>
      {demo && <p className="mt-2 text-sm text-muted">Identifiants du compte de démonstration pré-remplis.</p>}
      <form onSubmit={submit} className="mt-6 grid gap-4">
        <div>
          <label className="label" htmlFor="email">
            Email
          </label>
          <input id="email" type="email" className="input" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="password">
            Mot de passe
          </label>
          <input id="password" type="password" className="input" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        <button className="btn-primary" disabled={loading}>
          Se connecter
        </button>
      </form>
      <p className="mt-6 text-sm text-muted">
        Pas encore de compte ?{" "}
        <Link href="/register" className="text-accent underline">
          Créer mon espace
        </Link>
      </p>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
