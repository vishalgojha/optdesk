import { NextResponse } from 'next/server';

export async function GET(_req: Request, { params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/signal/${symbol}`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: 'Backend not running. Start: python C:\\optdesk\\web_ui.py' }, { status: 500 });
  }
}