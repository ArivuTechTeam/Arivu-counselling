import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";

// Plus Jakarta Sans is the ArivuPro brand typeface. Exposed as `--font-sans`,
// which shadcn/ui's Tailwind config reads.
const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Quiz Generator",
  description: "AI-powered quiz generator for educational institutions",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={cn(jakarta.variable)}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
