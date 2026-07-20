import { next } from '@vercel/edge';

// Lightweight PIN gate — no login, no accounts. Anyone with the PIN can view.
// The PIN lives ONLY in the Vercel env var DASHBOARD_PIN — never in this repo.
// On a correct PIN we set an HttpOnly cookie holding a HASH of the PIN (never the raw PIN),
// so the dashboard stays unlocked for ~30 days without re-entering it.

const COOKIE = 'floori_dash';

export default async function middleware(request) {
  const pin = process.env.DASHBOARD_PIN || process.env.DASHBOARD_PASSWORD;
  const url = new URL(request.url);

  // Fail closed: if no PIN is configured, serve nothing.
  if (!pin) {
    return new Response('Dashboard not configured yet.', { status: 503 });
  }

  const token = await sha256(pin + '::floori-dash-v1');

  // 1) PIN submission.
  if (request.method === 'POST' && url.pathname === '/__auth') {
    let entered = '';
    try {
      const form = await request.formData();
      entered = (form.get('pin') || '').toString().trim();
    } catch (_) {}
    if (entered && entered === pin) {
      const headers = new Headers({ Location: '/' });
      headers.append(
        'Set-Cookie',
        `${COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`
      );
      return new Response(null, { status: 303, headers });
    }
    return pinPage(true);
  }

  // 2) Already unlocked via cookie?
  const cookies = (request.headers.get('cookie') || '').split(/;\s*/);
  if (cookies.includes(`${COOKIE}=${token}`)) {
    return next();
  }

  // 3) Locked — show the PIN screen.
  return pinPage(false);
}

async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function pinPage(error) {
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Floori · Locked</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background:#0b0d12; color:#e7e9ee; }
  .card { width:min(92vw,360px); background:#12151d; border:1px solid #232833; border-radius:16px;
    padding:32px 28px; text-align:center; box-shadow:0 20px 60px rgba(0,0,0,.45); }
  .lock { font-size:34px; margin-bottom:6px; }
  h1 { font-size:18px; margin:0 0 4px; font-weight:600; }
  p { font-size:13px; color:#8b93a5; margin:0 0 22px; }
  input { width:100%; padding:14px 16px; font-size:22px; letter-spacing:.35em; text-align:center;
    background:#0b0d12; border:1px solid #2b3140; border-radius:10px; color:#fff; outline:none; }
  input:focus { border-color:#5b8cff; }
  button { width:100%; margin-top:14px; padding:13px; font-size:15px; font-weight:600;
    background:#5b8cff; color:#fff; border:none; border-radius:10px; cursor:pointer; }
  button:hover { background:#4a7bf0; }
  .err { color:#ff6b6b; font-size:13px; margin-top:14px; min-height:18px; }
</style>
</head>
<body>
  <form class="card" method="POST" action="/__auth" autocomplete="off">
    <div class="lock">🔒</div>
    <h1>Floori Dashboard</h1>
    <p>Enter the PIN to continue</p>
    <input name="pin" type="password" inputmode="numeric" autofocus aria-label="PIN" />
    <button type="submit">Unlock</button>
    <div class="err">${error ? 'Incorrect PIN — try again.' : ''}</div>
  </form>
</body>
</html>`;
  return new Response(html, {
    status: error ? 401 : 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}
