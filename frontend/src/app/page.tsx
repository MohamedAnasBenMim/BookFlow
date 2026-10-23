import Link from "next/link";
import { Logo } from "@/components/Logo";

const features = [
  ["Votre page de réservation", "Une adresse à partager : vos clients voient vos créneaux libres et réservent en 30 secondes."],
  ["Paiement à la réservation", "Encaissement par carte via Stripe. Un créneau non payé est libéré automatiquement après 15 minutes."],
  ["Rappels automatiques", "Confirmation immédiate et rappel la veille par email : moins de rendez-vous oubliés."],
  ["Toute votre équipe", "Chaque membre a ses horaires ; les clients sont répartis automatiquement sur les personnes libres."],
];

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <nav className="flex items-center justify-between">
        <Logo />
        <div className="flex gap-2">
          <Link href="/login" className="btn-ghost">
            Connexion
          </Link>
          <Link href="/register" className="btn-primary">
            Créer mon espace
          </Link>
        </div>
      </nav>

      <section className="py-16 sm:py-24">
        <p className="mb-4 text-sm font-medium text-accent">Prise de rendez-vous en ligne</p>
        <h1 className="max-w-3xl font-display text-4xl leading-tight font-semibold sm:text-6xl">
          Vos clients réservent. Vous vous occupez du reste.
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-muted">
          BookFlow donne à chaque indépendant, salon ou cabinet sa page de réservation, avec paiement, rappels et planning d&apos;équipe.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/studio-zen" className="btn-primary">
            Voir une page de démo
          </Link>
          <Link href="/login?demo=1" className="btn-ghost">
            Tester le tableau de bord
          </Link>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        {features.map(([title, text]) => (
          <div key={title} className="card p-6">
            <h2 className="font-display text-lg font-semibold">{title}</h2>
            <p className="mt-2 text-muted">{text}</p>
          </div>
        ))}
      </section>

      <footer className="mt-16 border-t border-line py-6 text-sm text-muted">
        Projet de démonstration — paiements en mode test, aucune transaction réelle.
      </footer>
    </main>
  );
}
