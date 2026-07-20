import { next } from '@vercel/edge';

// Gate every route behind HTTP Basic Auth.
// The password lives ONLY in the Vercel env var DASHBOARD_PASSWORD — never in this repo.
export const config = { matcher: '/:path*' };

export default function middleware(request) {
  const expected = process.env.DASHBOARD_PASSWORD;

  // Fail closed: if no password is configured, do not serve the dashboard.
  if (!expected) {
    return new Response('Dashboard not configured.', { status: 503 });
  }

  const auth = request.headers.get('authorization');
  if (auth && auth.startsWith('Basic ')) {
    let decoded = '';
    try {
      decoded = atob(auth.slice(6));
    } catch (_) {
      decoded = '';
    }
    // Basic auth payload is "username:password"; we only check the password.
    const password = decoded.slice(decoded.indexOf(':') + 1);
    if (password && password === expected) {
      return next();
    }
  }

  return new Response('Authentication required.', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Floori Dashboard", charset="UTF-8"',
      'Cache-Control': 'no-store',
    },
  });
}
