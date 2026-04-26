import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'NSE Option Chain Signals',
  description: 'Real-time NSE Nifty option chain analysis with AI-powered signals',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "'Segoe UI', system-ui, sans-serif", background: "#0a0a1a", color: "#e0e0f0", minHeight: "100vh" }}>
        {children}
      </body>
    </html>
  );
}