import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Providers } from "./providers";
import { Sidebar } from "@/components/shell/sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Facet", template: "%s · Facet" },
  description: "SQL-powered analytics workspace",
};

// Applied before paint to avoid a light/dark flash.
const themeScript = `try{var t=localStorage.getItem('facet-theme');if(!t){t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="font-sans">
        <Providers>
          <div className="flex h-dvh overflow-hidden">
            <Sidebar />
            <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
