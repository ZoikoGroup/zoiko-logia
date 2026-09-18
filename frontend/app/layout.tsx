import type { Metadata } from "next";
import "./globals.css";
import "katex/dist/katex.min.css";
import { AppChrome } from "@/components/layout/AppChrome";
import { AuthGuard } from "@/components/AuthGuard";
import { AuthProvider } from "@/contexts/AuthContext";
import { RoleProvider } from "@/components/shell/RoleProvider";
import { ThemeProvider } from "@/components/shell/ThemeProvider";
import { THEME_COOKIE } from "@/lib/theme";

// Resolves the theme once before first paint (no flash-of-wrong-theme), and
// on the very first visit — when no cookie exists yet — PERSISTS whatever it
// resolved to a cookie. Without that, every future load with no cookie would
// re-resolve fresh each time; if the deciding signal isn't perfectly stable
// between loads, the background flips unpredictably on refresh even though
// nothing actually changed. Once resolved, the choice is sticky until the
// user explicitly toggles it (ThemeProvider.applyTheme).
//
// Dark is the product's default rather than the OS preference: this is a
// governance console people sit in front of all day, and the dark palette is
// the one the interface was designed against. A returning user's cookie still
// wins, so anyone who has chosen light keeps it.
const THEME_INIT_SCRIPT = `(function(){try{var m=document.cookie.match(/(?:^|; )${THEME_COOKIE}=([^;]*)/);var t=m?decodeURIComponent(m[1]):null;if(!t){t='dark';document.cookie='${THEME_COOKIE}='+t+'; path=/; max-age='+(60*60*24*365);}document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;

export const metadata: Metadata = {
  title: "ZoikoLogia",
  description: "Source-governed, jurisdiction-aware, audit-ready AI governance platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex bg-bg text-ink">
        <ThemeProvider>
          <AuthProvider>
            <AuthGuard>
              <RoleProvider>
                <AppChrome>{children}</AppChrome>
              </RoleProvider>
            </AuthGuard>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
