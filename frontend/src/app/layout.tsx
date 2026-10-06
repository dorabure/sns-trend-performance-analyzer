import type { Metadata } from "next";
import "./globals.css";
import { ProjectScopeProvider } from '../components/project-scope';
import { LocaleProvider } from '../i18n/react';

export const metadata: Metadata = {
  title: "SNS Trend & Performance Analyzer",
  description: "Phase 1 development environment health check",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ja" suppressHydrationWarning><body className="bg-slate-100 text-slate-900"><LocaleProvider><ProjectScopeProvider>{children}</ProjectScopeProvider></LocaleProvider></body></html>;
}
