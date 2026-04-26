import { NextResponse } from 'next/server';

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const message = searchParams.get('message') || '';
  const history = searchParams.get('history') || '[]';

  try {
    const res = await fetch(`http://127.0.0.1:8000/api/chat?message=${encodeURIComponent(message)}&history=${encodeURIComponent(history)}`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: 'Backend not running. Start: python C:\\optdesk\\web_ui.py' }, { status: 500 });
  }
}