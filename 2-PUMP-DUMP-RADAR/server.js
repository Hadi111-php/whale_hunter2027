// Pump/Dump Lab — سرور استاتیک مینیمال + پل یک‌طرفه /api/hot
// این اپ کاملاً مستقل از Futures Scalp Lab است و هیچ وابستگی runtime به آن ندارد.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8790);
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon'
};

// آخرین snapshot نمادهای داغ که کلاینت (رادار مرورگر) با POST به‌روز می‌کند.
// اتوتریدر Futures Scalp Lab می‌تواند به‌صورت اختیاری همین endpoint را بخواند (پل یک‌طرفه).
let hotSnapshot = { updatedAt: 0, symbols: [] };

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const send = (code, body, type = 'application/json; charset=utf-8', extra = {}) => {
    res.writeHead(code, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Cache-Control': 'no-store',
      'Content-Type': type,
      ...extra
    });
    res.end(body);
  };

  if (req.method === 'OPTIONS') return send(204, '');

  if (url.pathname === '/api/hot') {
    if (req.method === 'POST') {
      let raw = '';
      req.on('data', chunk => { raw += chunk; if (raw.length > 1e6) req.destroy(); });
      req.on('end', () => {
        try {
          const body = JSON.parse(raw || '{}');
          const symbols = Array.isArray(body.symbols)
            ? body.symbols.filter(s => typeof s === 'string' && s.length < 24).slice(0, 40)
            : [];
          hotSnapshot = { updatedAt: Date.now(), symbols, active: Array.isArray(body.active) ? body.active.slice(0, 40) : [] };
          send(200, JSON.stringify({ ok: true }));
        } catch {
          send(400, JSON.stringify({ ok: false, error: 'bad json' }));
        }
      });
      return;
    }
    return send(200, JSON.stringify(hotSnapshot));
  }

  if (url.pathname === '/api/health') return send(200, JSON.stringify({ ok: true, service: 'pump-dump-lab' }));

  // Static files
  let filePath = url.pathname === '/' ? '/index.html' : url.pathname;
  filePath = path.normalize(filePath).replace(/^(\.\.[/\\])+/, '');
  const full = path.join(__dirname, filePath);
  if (!full.startsWith(__dirname)) return send(403, JSON.stringify({ error: 'forbidden' }));
  try {
    const data = await readFile(full);
    return send(200, data, MIME[path.extname(full)] || 'application/octet-stream');
  } catch {
    return send(404, JSON.stringify({ error: 'not found' }));
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`\n🚀 Pump/Dump Lab (standalone): http://localhost:${PORT}`);
  console.log('📡 Whole-market radar: Bybit → Binance → OKX | 🔊 Audio alerts | 🧭 Independent from futures autotrader\n');
});
