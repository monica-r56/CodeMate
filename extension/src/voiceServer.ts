import * as http from 'http';
import * as path from 'path';
import * as fs from 'fs';

export type VoiceServerConfig = {
  vapiPublicKey: string;
  assistantId: string;
  context?: Record<string, any>;
};

export type VoiceServerEvent =
  | { type: 'transcript'; text: string }
  | { type: 'response'; text: string }
  | { type: 'status'; text: string }
  | { type: 'error'; text: string }
  | { type: 'diff'; filePath: string; diff: string; newContent: string; speech?: string }
  | { type: 'navigate'; filePath: string; line?: number; speech?: string }
  | { type: 'output'; output: string; speech?: string };

function readJsonBody(req: http.IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 2_000_000) {
        reject(new Error('Body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function send(res: http.ServerResponse, status: number, body: string, contentType: string) {
  res.writeHead(status, {
    'Content-Type': contentType,
    'Cache-Control': 'no-store'
  });
  res.end(body);
}

export class VoiceServer {
  private readonly extensionRoot: string;
  private readonly onEvent: (event: VoiceServerEvent) => void;

  private server: http.Server | undefined;
  private port: number | undefined;
  private config: VoiceServerConfig | undefined;
  private pendingCommand: { type: 'stop' } | undefined;

  constructor(extensionRootFsPath: string, onEvent: (event: VoiceServerEvent) => void) {
    this.extensionRoot = extensionRootFsPath;
    this.onEvent = onEvent;
  }

  setConfig(config: VoiceServerConfig) {
    this.config = config;
  }

  requestStop() {
    this.pendingCommand = { type: 'stop' };
  }

  async ensureStarted(): Promise<string> {
    if (this.server && this.port) {
      return `http://127.0.0.1:${this.port}/`;
    }

    this.server = http.createServer(async (req, res) => {
      try {
        const url = new URL(req.url || '/', 'http://127.0.0.1');
        if (req.method === 'GET' && url.pathname === '/') {
          return send(res, 200, this.renderHtml(), 'text/html; charset=utf-8');
        }
        if (req.method === 'GET' && url.pathname === '/vapi.js') {
          const vapiPath = path.join(this.extensionRoot, 'media', 'vapi.js');
          const js = fs.readFileSync(vapiPath, 'utf8');
          return send(res, 200, js, 'application/javascript; charset=utf-8');
        }
        if (req.method === 'GET' && url.pathname === '/config') {
          const cfg = this.config || { vapiPublicKey: '', assistantId: '', context: {} };
          return send(res, 200, JSON.stringify(cfg), 'application/json; charset=utf-8');
        }
        if (req.method === 'GET' && url.pathname === '/command') {
          const cmd = this.pendingCommand;
          this.pendingCommand = undefined;
          return send(res, 200, JSON.stringify(cmd || { type: 'noop' }), 'application/json; charset=utf-8');
        }
        if (req.method === 'POST' && url.pathname === '/event') {
          const body = await readJsonBody(req);
          this.routeEvent(body);
          return send(res, 200, JSON.stringify({ ok: true }), 'application/json; charset=utf-8');
        }
        return send(res, 404, 'Not Found', 'text/plain; charset=utf-8');
      } catch (e: any) {
        this.onEvent({ type: 'error', text: e?.message || String(e) });
        return send(res, 500, 'Internal Server Error', 'text/plain; charset=utf-8');
      }
    });

    await new Promise<void>((resolve, reject) => {
      this.server!.listen(0, '127.0.0.1', () => resolve());
      this.server!.on('error', reject);
    });

    const addr = this.server.address();
    if (!addr || typeof addr === 'string') {
      throw new Error('Voice server failed to bind');
    }
    this.port = addr.port;
    return `http://127.0.0.1:${this.port}/`;
  }

  dispose() {
    try {
      this.server?.close();
    } catch {
      // ignore
    }
    this.server = undefined;
    this.port = undefined;
    this.pendingCommand = undefined;
  }

  private routeEvent(body: any) {
    // We keep this intentionally tolerant: Vapi message schemas can evolve.
    const kind = body?.kind || body?.type;
    const payload = body?.payload ?? body?.data ?? body;

    if (kind === 'status') {
      this.onEvent({ type: 'status', text: payload?.text || payload?.status || ' ' });
      return;
    }

    if (kind === 'error') {
      this.onEvent({ type: 'error', text: payload?.message || payload?.error || String(payload) });
      return;
    }

    if (kind === 'transcript') {
      const text = payload?.transcript || payload?.text || '';
      const role = String(payload?.role || payload?.speaker || payload?.from || '').toLowerCase();
      if (text) {
        if (role.includes('assistant') || role.includes('ai') || role.includes('bot')) {
          this.onEvent({ type: 'response', text });
        } else {
          this.onEvent({ type: 'transcript', text });
        }
      }
      return;
    }

    if (kind === 'response') {
      const text = payload?.text || payload?.message || payload?.content || '';
      if (typeof text === 'string' && text.trim()) {
        this.onEvent({ type: 'response', text });
      }
      return;
    }

    if (kind === 'message') {
      const action = payload?.action;
      const speech = payload?.speech;

      if (typeof speech === 'string' && speech.trim()) {
        this.onEvent({ type: 'response', text: speech });
      }

      if (action === 'diff' && payload?.diff && payload?.file_path && payload?.new_content) {
        this.onEvent({
          type: 'diff',
          filePath: payload.file_path,
          diff: payload.diff,
          newContent: payload.new_content,
          speech: typeof speech === 'string' ? speech : undefined
        });
        return;
      }

      if (action === 'navigate' && payload?.file_path) {
        this.onEvent({
          type: 'navigate',
          filePath: payload.file_path,
          line: payload?.line,
          speech: typeof speech === 'string' ? speech : undefined
        });
        return;
      }

      if (action === 'show_output' && payload?.output) {
        this.onEvent({
          type: 'output',
          output: payload.output,
          speech: typeof speech === 'string' ? speech : undefined
        });
        return;
      }

      // Best-effort: surface assistant text if present.
      const candidate =
        payload?.text ||
        payload?.message?.content ||
        payload?.message ||
        payload?.content ||
        '';
      if (typeof candidate === 'string' && candidate.trim()) {
        this.onEvent({ type: 'response', text: candidate });
      }
      return;
    }
  }

  private renderHtml(): string {
    // Runs in the user's default browser (localhost), so microphone permissions work.
    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PairVoice Voice Session</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 24px; }
    .row { display: flex; gap: 12px; align-items: center; }
    button { padding: 10px 14px; border-radius: 10px; border: 1px solid #ddd; background: #111; color: #fff; cursor: pointer; }
    button.secondary { background: #fff; color: #111; }
    pre { white-space: pre-wrap; background: #f6f6f6; padding: 12px; border-radius: 10px; }
    .muted { color: #666; font-size: 12px; }
  </style>
</head>
<body>
  <h2>PairVoice Voice Session</h2>
  <div class="row">
    <button id="startBtn">Start</button>
    <button id="stopBtn" class="secondary">Stop</button>
    <span id="status" class="muted">Loading…</span>
  </div>
  <h3>You said</h3>
  <pre id="transcript"></pre>
  <h3>Assistant</h3>
  <pre id="response"></pre>

  <script src="/vapi.js"></script>
  <script>
    const statusEl = document.getElementById('status');
    const transcriptEl = document.getElementById('transcript');
    const responseEl = document.getElementById('response');
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    let client = null;
    let cfg = null;

    async function postEvent(kind, payload) {
      try {
        await fetch('/event', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ kind, payload })
        });
      } catch {}
    }

    function setStatus(text) {
      statusEl.textContent = text;
      postEvent('status', { text });
    }

    function attach() {
      if (!client) return;
      client.on('speech-start', () => setStatus('Listening…'));
      client.on('speech-end', () => setStatus('Processing…'));
      client.on('call-start', () => setStatus('Call started'));
      client.on('call-end', () => setStatus('Call ended'));
      client.on('error', (e) => postEvent('error', e));
      client.on('message', (msg) => {
        // Forward everything to the extension; also render best-effort.
        if (msg && msg.type === 'transcript') {
          const t = msg.transcript || msg.text || '';
          const role = String(msg.role || msg.speaker || msg.from || '').toLowerCase();
          if (role.includes('assistant') || role.includes('ai') || role.includes('bot')) {
            responseEl.textContent = t;
            postEvent('response', { text: t });
          } else {
            transcriptEl.textContent = t;
            postEvent('transcript', { text: t, role: 'user' });
          }
        } else {
          postEvent('message', msg);
          const t = (msg && (msg.text || msg.content || (msg.message && msg.message.content))) || '';
          if (typeof t === 'string' && t.trim()) responseEl.textContent = t;
        }
      });
    }

    async function start() {
      if (!window.Vapi) {
        setStatus('Vapi SDK failed to load');
        return;
      }
      if (!cfg) {
        cfg = await (await fetch('/config')).json();
      }
      if (!cfg.vapiPublicKey || !cfg.assistantId) {
        setStatus('Missing Vapi configuration');
        return;
      }
      if (!client) {
        client = new window.Vapi(cfg.vapiPublicKey);
        attach();
      }
      setStatus('Starting…');
      client.start(cfg.assistantId, { variableValues: cfg.context || {} });
    }

    async function stop() {
      try {
        if (client && client.stop) await client.stop();
      } catch {}
      setStatus('Stopped');
    }

    async function pollCommand() {
      try {
        const cmd = await (await fetch('/command')).json();
        if (cmd && cmd.type === 'stop') await stop();
      } catch {}
      setTimeout(pollCommand, 500);
    }

    startBtn.addEventListener('click', start);
    stopBtn.addEventListener('click', stop);
    setStatus('Ready');
    pollCommand();
    // The user initiated this flow from the extension's mic button; start immediately.
    start().catch(() => {});
  </script>
</body>
</html>`;
  }
}
