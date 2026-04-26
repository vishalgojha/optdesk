import { NextResponse } from 'next/server';

export async function GET() {
  try {
    const res = await fetch('http://127.0.0.1:8000/api/status');
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ is_open: false, sgx_nifty: null, current_time_ist: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }), next_open: '09:15 IST' });
  }
}