import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NL Analytics",
  description: "Ask your CSVs questions in plain English",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
