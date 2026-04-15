"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.PairVoicePanel = void 0;
const vscode = __importStar(require("vscode"));
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
function getNonce() {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let nonce = '';
    for (let i = 0; i < 32; i++) {
        nonce += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return nonce;
}
class PairVoicePanel {
    static createOrShow(extensionUri) {
        const column = vscode.ViewColumn.Beside;
        if (PairVoicePanel.currentPanel) {
            PairVoicePanel.currentPanel._panel.reveal(column);
            return PairVoicePanel.currentPanel;
        }
        const panel = vscode.window.createWebviewPanel('pairvoice', 'PairVoice', column, {
            enableScripts: true,
            localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'media')],
            retainContextWhenHidden: true
        });
        PairVoicePanel.currentPanel = new PairVoicePanel(panel, extensionUri);
        return PairVoicePanel.currentPanel;
    }
    constructor(panel, extensionUri) {
        this._disposables = [];
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._panel.webview.html = this._getHtml();
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
    }
    postMessage(msg) {
        this._panel.webview.postMessage(msg);
    }
    onMessage(handler) {
        this._panel.webview.onDidReceiveMessage(handler, null, this._disposables);
    }
    dispose() {
        PairVoicePanel.currentPanel = undefined;
        this._panel.dispose();
        this._disposables.forEach(d => d.dispose());
    }
    _getHtml() {
        const nonce = getNonce();
        const scriptUri = this._panel.webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'vapi.js'));
        const mediaPath = path.join(this._extensionUri.fsPath, 'media', 'panel.html');
        if (fs.existsSync(mediaPath)) {
            const template = fs.readFileSync(mediaPath, 'utf8');
            return template
                .replace(/\{\{vapiScript\}\}/g, scriptUri.toString())
                .replace(/\{\{cspSource\}\}/g, this._panel.webview.cspSource)
                .replace(/\{\{nonce\}\}/g, nonce);
        }
        return this._fallbackHtml(scriptUri.toString(), this._panel.webview.cspSource, nonce);
    }
    _fallbackHtml(scriptUri, cspSource, nonce) {
        return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}' ${cspSource}; style-src 'nonce-${nonce}' ${cspSource}; connect-src https://api.vapi.ai wss://api.vapi.ai; img-src ${cspSource} https: data:; media-src ${cspSource} blob: data:; worker-src ${cspSource} blob:;">
<title>PairVoice</title>
<style nonce="${nonce}">
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); padding: 16px; }
  .status { font-size: 11px; color: var(--vscode-descriptionForeground); margin-bottom: 16px; }
  .mic-btn { width: 64px; height: 64px; border-radius: 50%; border: 2px solid var(--vscode-button-background); background: var(--vscode-button-background); color: var(--vscode-button-foreground); font-size: 24px; cursor: pointer; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; transition: all 0.2s; }
  .mic-btn:hover { opacity: 0.85; }
  .mic-btn.listening { background: #e05252; border-color: #e05252; animation: pulse 1.2s infinite; }
  @keyframes pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.08)} }
  .transcript { font-size: 13px; color: var(--vscode-foreground); min-height: 40px; margin-bottom: 12px; padding: 8px; background: var(--vscode-input-background); border-radius: 6px; line-height: 1.5; }
  .response { font-size: 13px; color: var(--vscode-descriptionForeground); min-height: 60px; margin-bottom: 16px; line-height: 1.6; }
  .diff-view { font-family: var(--vscode-editor-font-family); font-size: 12px; background: var(--vscode-textCodeBlock-background); padding: 10px; border-radius: 6px; white-space: pre; overflow-x: auto; margin-bottom: 12px; display: none; max-height: 300px; overflow-y: auto; }
  .diff-view .add { color: #4ec94e; }
  .diff-view .del { color: #f05050; }
  .action-btns { display: none; gap: 8px; }
  .btn { padding: 6px 16px; border-radius: 4px; border: 1px solid var(--vscode-button-background); background: var(--vscode-button-background); color: var(--vscode-button-foreground); cursor: pointer; font-size: 12px; }
  .btn-secondary { background: transparent; color: var(--vscode-button-background); }
  .section-title { font-size: 11px; font-weight: 600; letter-spacing: 0.05em; color: var(--vscode-descriptionForeground); text-transform: uppercase; margin-bottom: 8px; }
  .kb-source { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--vscode-widget-border); font-size: 12px; }
  .kb-badge { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
  .shortcut { font-size: 11px; color: var(--vscode-descriptionForeground); text-align: center; margin-top: 8px; }
  .section { margin: 20px 0; }
  .kb-section { margin-top: 24px; }
</style>
</head>
<body>
<div id="app">
  <p class="status" id="status">Ready — press ⌘⇧V to speak</p>

  <button class="mic-btn" id="micBtn" title="Start / Stop listening">🎤</button>
  <p class="shortcut">Ctrl+Shift+V to toggle</p>

	  <div class="section">
	    <div class="section-title">You said</div>
	    <div class="transcript" id="transcript">Waiting for voice input...</div>
	  </div>

  <div>
    <div class="section-title">Agent response</div>
    <div class="response" id="response">Your pair programmer is ready. Ask about code, errors, PRs, or say "fix this bug".</div>
  </div>

  <div class="diff-view" id="diffView"></div>
  <div class="action-btns" id="actionBtns">
    <button class="btn" id="applyBtn">Apply fix</button>
    <button class="btn btn-secondary" id="dismissBtn">Dismiss</button>
  </div>

	  <div class="kb-section">
	    <div class="section-title">Knowledge sources</div>
	    <div id="kbSources">
	      <div class="kb-source"><span>Workspace (not indexed)</span><span class="kb-badge">—</span></div>
	    </div>
	  </div>
	  <script nonce="${nonce}" src="${scriptUri}"></script>
	  <script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  let isListening = false;
  let pendingDiff = null;

  const micBtn     = document.getElementById('micBtn');
  const status     = document.getElementById('status');
  const transcript = document.getElementById('transcript');
  const response   = document.getElementById('response');
  const diffView   = document.getElementById('diffView');
  const actionBtns = document.getElementById('actionBtns');
  const applyBtn   = document.getElementById('applyBtn');
  const dismissBtn = document.getElementById('dismissBtn');

  micBtn.addEventListener('click', toggleListening);

  function toggleListening() {
    isListening = !isListening;
    if (isListening) {
      micBtn.classList.add('listening');
      micBtn.textContent = '⏹';
      status.textContent = 'Listening...';
      vscode.postMessage({ type: 'startVoice' });
    } else {
      micBtn.classList.remove('listening');
      micBtn.textContent = '🎤';
      status.textContent = 'Ready';
      vscode.postMessage({ type: 'stopVoice' });
    }
  }

  applyBtn.addEventListener('click', () => {
    if (pendingDiff) {
      vscode.postMessage({ type: 'applyFix', diff: pendingDiff });
      actionBtns.style.display = 'none';
      diffView.style.display = 'none';
      status.textContent = 'Fix applied';
      pendingDiff = null;
    }
  });

  dismissBtn.addEventListener('click', () => {
    actionBtns.style.display = 'none';
    diffView.style.display = 'none';
    pendingDiff = null;
  });

  // Handle messages from extension
  window.addEventListener('message', event => {
    const msg = event.data;
    switch (msg.type) {
      case 'transcript':
        transcript.textContent = msg.text;
        break;
      case 'response':
        response.textContent = msg.text;
        micBtn.classList.remove('listening');
        micBtn.textContent = '🎤';
        isListening = false;
        status.textContent = 'Ready';
        break;
      case 'showDiff':
        pendingDiff = msg;
        renderDiff(msg.diff);
        actionBtns.style.display = 'flex';
        break;
      case 'indexStatus':
        updateKbSources(msg.sources);
        break;
      case 'error':
        status.textContent = 'Error: ' + msg.text;
        break;
    }
  });

  function renderDiff(diffText) {
    diffView.style.display = 'block';
    diffView.innerHTML = diffText.split('\\n').map(line => {
      if (line.startsWith('+') && !line.startsWith('+++')) return \`<span class="add">\${esc(line)}</span>\`;
      if (line.startsWith('-') && !line.startsWith('---')) return \`<span class="del">\${esc(line)}</span>\`;
      return esc(line);
    }).join('\\n');
  }

  function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function updateKbSources(sources) {
    const el = document.getElementById('kbSources');
    el.innerHTML = sources.map(s =>
      \`<div class="kb-source"><span>\${s.name}</span><span class="kb-badge">\${s.chunks} chunks</span></div>\`
    ).join('');
  }
</script>
</body>
</html>`;
    }
}
exports.PairVoicePanel = PairVoicePanel;
//# sourceMappingURL=webviewPanel.js.map