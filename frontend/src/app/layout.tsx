import type { Metadata } from "next";
// Polices auto-hébergées (fontsource) : aucune dépendance réseau au build
import "@fontsource-variable/inter";
import "@fontsource-variable/fraunces";
import "./globals.css";

export const metadata: Metadata = {
  title: "BookFlow",
  description: "La prise de rendez-vous en ligne pour les indépendants et les petites entreprises.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
