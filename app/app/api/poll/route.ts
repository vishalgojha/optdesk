import { NextResponse } from 'next/server';

export async function POST() {
  try {
    const res = await fetch('http://127.0.0.1:8000/api/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: 'Backend not running' }, { status: 500 });
  }
}