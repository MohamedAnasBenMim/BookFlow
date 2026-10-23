"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Logo } from "@/components/Logo";
import { api, session } from "@/lib/api";

const slugify = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);

export default function Register() {
  const router = useRouter();
  const [f, setF] = useState({ name: "", email: "", password: "", business_name: "", slug: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const { access_token } = await api<{ access_token: string }>("/auth/register", { method: "POST", body: JSON.stringify(f) });
      session.save(access_token);
      session.setTenant(f.slug);
      router.push("/dashboard/services");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Inscription impossible.");
      setLoading(false);
    }
  }

  const field = (key: keyof typeof f, label: string, type = "text") => (
    <div>
      <label className="label" htmlFor={key}>
        {label}
      </label>
      <input
        id={key}
        type={type}
        className="input"
        required
        minLength={type === "password" ? 8 : undefined}
        value={f[key]}
        onChange={(e) => setF({ ...f, [key]: e.target.value, ...(key === "business_name" ? { slug: slugify(e.target.value) } : {}) })}
      />
    </div>
  );

  return (
    <main className="mx-auto max-w-sm px-4 py-16">
      <Logo />
      <h1 className="mt-8 font-display text-2xl font-semibold">Créer mon espace</h1>
      <form onSubmit={submit} className="mt-6 grid gap-4">
        {field("name", "Votre nom")}
        {field("email", "Email", "email")}
        {field("password", "Mot de passe (8 caractères min.)", "password")}
        {field("business_name", "Nom de votre activité")}
        {field("slug", "Adresse de votre page")}
        <p className="-mt-2 text-xs text-muted">bookflow.app/{f.slug || "mon-activite"}</p>
        {error && <p className="text-sm text-danger">{error}</p>}
        <button className="btn-primary" disabled={loading}>
          Créer mon espace
        </button>
      </form>
    </main>
  );
}
