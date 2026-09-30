import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AuthProvider } from "@/components/auth/auth-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Academic Memo Assistant",
  description: "Assistant de recherche et de rédaction académique fondé sur les sources.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="fr">
      <body><AuthProvider>{children}</AuthProvider></body>
    </html>
  );
}
