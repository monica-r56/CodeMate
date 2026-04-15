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
exports.activate = activate;
exports.deactivate = deactivate;
/**
 * PairVoice VS Code extension runtime—registers commands, syncs context with the backend, and routes panel messages.
 */
const vscode = __importStar(require("vscode"));
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const webviewPanel_1 = require("./webviewPanel");
const contextCollector_1 = require("./contextCollector");
const voiceServer_1 = require("./voiceServer");
const HEALTH_CHECK_INTERVAL = 30000;
const SETUP_COMPLETE_KEY = 'pairvoice.setupComplete';
let _panel;
let _statusBar;
let _isListening = false;
let _voiceServer;
let _lastVapiStartPayload;
/**
 * Kick off PairVoice: register commands, wire the panel, watch saves, and keep the backend status indicator current.
 */
function activate(context) {
    (0, contextCollector_1.initTerminalCapture)(context);
    _voiceServer = new voiceServer_1.VoiceServer(context.extensionUri.fsPath, (event) => {
        // Keep panel updated even if voice runs outside the webview.
        if (event.type === 'transcript') {
            _panel?.postMessage({ type: 'transcript', text: event.text });
        }
        else if (event.type === 'response') {
            _panel?.postMessage({ type: 'response', text: event.text });
        }
        else if (event.type === 'status') {
            _panel?.postMessage({ type: 'status', text: event.text });
        }
        else if (event.type === 'error') {
            _panel?.postMessage({ type: 'error', text: event.text });
        }
        else if (event.type === 'diff') {
            _panel?.postMessage({
                type: 'showDiff',
                filePath: event.filePath,
                newContent: event.newContent,
                diff: event.diff
            });
            if (event.speech) {
                _panel?.postMessage({ type: 'response', text: event.speech });
            }
        }
        else if (event.type === 'navigate') {
            void (0, contextCollector_1.navigateToFile)(event.filePath, event.line || 0);
            if (event.speech) {
                _panel?.postMessage({ type: 'response', text: event.speech });
            }
        }
        else if (event.type === 'output') {
            _panel?.postMessage({ type: 'response', text: event.output });
            if (event.speech) {
                _panel?.postMessage({ type: 'response', text: event.speech });
            }
        }
    });
    context.subscriptions.push({ dispose: () => _voiceServer?.dispose() });
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.openPanel', () => {
        _panel = webviewPanel_1.PairVoicePanel.createOrShow(context.extensionUri);
        _panel.onMessage((msg) => handlePanelMessage(msg, context));
        void refreshIndexStatus(context);
    }));
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.startVoice', async () => {
        if (!_panel) {
            _panel = webviewPanel_1.PairVoicePanel.createOrShow(context.extensionUri);
            _panel.onMessage((msg) => handlePanelMessage(msg, context));
        }
        await startListening(context);
    }));
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.stopVoice', stopListening));
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.indexWorkspace', async () => await indexWorkspace()));
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.attachDocument', async () => await attachDocument()));
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.configureVapi', async () => await requestVapiKeys(context)));
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.storeGithubToken', async () => await promptForGithubToken(context)));
    context.subscriptions.push(vscode.commands.registerCommand('pairvoice.checkBackend', async () => await refreshBackendStatus(context)));
    const saveWatcher = vscode.workspace.onDidSaveTextDocument((doc) => {
        void handleDocumentSave(doc, context);
    });
    context.subscriptions.push(saveWatcher);
    _statusBar = createStatusBarItem();
    context.subscriptions.push(_statusBar);
    void requestVapiKeys(context);
    vscode.commands.executeCommand('pairvoice.openPanel');
    void refreshBackendStatus(context);
    void refreshIndexStatus(context);
    const interval = setInterval(() => void refreshBackendStatus(context), HEALTH_CHECK_INTERVAL);
    context.subscriptions.push({ dispose: () => clearInterval(interval) });
}
/**
 * Collect latest editor context, send it to the backend, and notify the webview to start a Vapi call.
 */
async function startListening(context) {
    const config = vscode.workspace.getConfiguration('pairvoice');
    const vapiKey = config.get('vapiPublicKey', '');
    const assistantId = config.get('vapiAssistantId', '');
    const backendUrl = config.get('backendUrl', 'http://localhost:8000');
    if (!vapiKey || !assistantId) {
        vscode.window.showErrorMessage('PairVoice: Please configure your Vapi public key and assistant ID (PairVoice settings).');
        return;
    }
    try {
        const ctx = await (0, contextCollector_1.collectContext)();
        await postJson(`${backendUrl}/context`, {
            user_id: vscode.env.machineId,
            active_file: ctx.activeFilePath,
            active_file_content: ctx.activeFileContent,
            selected_text: ctx.selectedText,
            terminal_output: ctx.terminalOutput,
            repo_owner: ctx.repoOwner,
            repo_name: ctx.repoName,
            repo_path: ctx.repoPath
        });
        _panel?.postMessage({ type: 'status', text: 'Listening...' });
        _lastVapiStartPayload = {
            type: 'startVapiCall',
            vapiPublicKey: vapiKey,
            assistantId,
            context: {
                activeFile: ctx.activeFilePath,
                selectedText: ctx.selectedText.slice(0, 500),
                repoOwner: ctx.repoOwner,
                repoName: ctx.repoName,
                userId: vscode.env.machineId
            }
        };
        _panel?.postMessage(_lastVapiStartPayload);
        _isListening = true;
    }
    catch (error) {
        vscode.window.showErrorMessage(`PairVoice: Unable to start voice session — ${error.message}`);
    }
}
/**
 * Notify the panel to terminate the active Vapi call.
 */
function stopListening() {
    _isListening = false;
    _voiceServer?.requestStop();
    _panel?.postMessage({ type: 'stopVapiCall' });
}
/**
 * Delegate messages from the webview to VS Code commands or backend actions.
 */
async function handlePanelMessage(msg, context) {
    const config = vscode.workspace.getConfiguration('pairvoice');
    const backendUrl = config.get('backendUrl', 'http://localhost:8000');
    switch (msg.type) {
        case 'startVoice':
            await startListening(context);
            break;
        case 'stopVoice':
            stopListening();
            break;
        case 'navigate':
            await (0, contextCollector_1.navigateToFile)(msg.filePath, msg.line || 0);
            break;
        case 'applyFix':
            if (msg.filePath && msg.newContent) {
                const ok = await (0, contextCollector_1.applyEdit)(msg.filePath, msg.newContent);
                _panel?.postMessage({
                    type: ok ? 'response' : 'error',
                    text: ok ? `Applied fix to ${msg.filePath}` : 'Could not apply the fix.'
                });
            }
            break;
        case 'attachDocument':
            await attachDocument();
            await refreshIndexStatus(context);
            break;
        case 'indexUrl':
            if (msg.url) {
                const folder = vscode.workspace.workspaceFolders?.[0];
                await postJson(`${backendUrl}/index/url`, { url: msg.url, repo_path: folder?.uri.fsPath || '' });
                vscode.window.showInformationMessage(`PairVoice: Indexed ${msg.url}`);
                await refreshIndexStatus(context);
            }
            break;
        case 'indexWorkspace':
            await indexWorkspace();
            await refreshIndexStatus(context);
            break;
        case 'openVoiceInBrowser': {
            if (!_lastVapiStartPayload?.vapiPublicKey || !_lastVapiStartPayload?.assistantId) {
                vscode.window.showErrorMessage('PairVoice: Missing Vapi configuration. Set Vapi public key + assistant ID.');
                break;
            }
            _voiceServer?.setConfig({
                vapiPublicKey: _lastVapiStartPayload.vapiPublicKey,
                assistantId: _lastVapiStartPayload.assistantId,
                context: _lastVapiStartPayload.context || {}
            });
            const url = await _voiceServer.ensureStarted();
            await vscode.env.openExternal(vscode.Uri.parse(url));
            _panel?.postMessage({ type: 'status', text: 'Opened voice session in your browser.' });
            break;
        }
    }
}
// deactivate() is defined at the bottom of this file (keep a single export).
/**
 * Send incremental file updates to the backend on save so only the modified file is re-indexed.
 */
async function handleDocumentSave(doc, context) {
    if (!doc || doc.isUntitled || doc.uri.scheme !== 'file')
        return;
    const workspace = vscode.workspace.workspaceFolders?.[0];
    if (!workspace)
        return;
    const relPath = vscode.workspace.asRelativePath(doc.uri);
    const config = vscode.workspace.getConfiguration('pairvoice');
    const backendUrl = config.get('backendUrl', 'http://localhost:8000');
    const payload = {
        file_path: relPath,
        content: doc.getText(),
        repo_path: workspace.uri.fsPath
    };
    const result = (await postJson(`${backendUrl}/index/file-update`, payload, { showError: false }));
    if (result?.chunks_updated) {
        vscode.window.setStatusBarMessage(`PairVoice: Indexed ${relPath}`, 2000);
    }
}
/**
 * Trigger a full workspace indexing run.
 */
async function indexWorkspace() {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
        vscode.window.showWarningMessage('PairVoice: Open a workspace to index.');
        return;
    }
    const backendUrl = vscode.workspace.getConfiguration('pairvoice').get('backendUrl', 'http://localhost:8000');
    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'PairVoice: Indexing workspace...',
        cancellable: false
    }, async (progress) => {
        progress.report({ increment: 0 });
        const ctx = await (0, contextCollector_1.collectContext)();
        const result = await postJson(`${backendUrl}/index/repo`, {
            repo_path: folder.uri.fsPath,
            owner: ctx.repoOwner,
            repo_name: ctx.repoName
        });
        if (!result) {
            _panel?.postMessage({
                type: 'indexStatus',
                sources: [{ name: `${folder.name} (not indexed)`, chunks: 0 }]
            });
            return;
        }
        vscode.window.showInformationMessage('PairVoice: Workspace indexed successfully.');
        const codeChunks = Number(result?.code_chunks ?? 0);
        const docChunks = Number(result?.doc_chunks ?? 0);
        if (_panel && (codeChunks > 0 || docChunks > 0)) {
            _panel.postMessage({
                type: 'indexStatus',
                sources: [
                    { name: `${folder.name} (code)`, chunks: codeChunks },
                    { name: `${folder.name} (docs)`, chunks: docChunks }
                ]
            });
        }
        await refreshIndexStatusFromFolder(folder, backendUrl);
        progress.report({ increment: 100 });
    });
}
/**
 * Upload documents for indexing.
 */
async function attachDocument() {
    const backendUrl = vscode.workspace.getConfiguration('pairvoice').get('backendUrl', 'http://localhost:8000');
    const folder = vscode.workspace.workspaceFolders?.[0];
    const repoPath = folder?.uri.fsPath || '';
    const uris = await vscode.window.showOpenDialog({
        canSelectMany: true,
        filters: {
            Documents: ['md', 'txt', 'pdf', 'html', 'rst']
        },
        openLabel: 'Attach to PairVoice'
    });
    if (!uris || uris.length === 0) {
        return;
    }
    for (const uri of uris) {
        const filename = path.basename(uri.fsPath);
        try {
            const buffer = fs.readFileSync(uri.fsPath);
            const formData = new FormData();
            formData.append('file', new Blob([buffer]), filename);
            if (repoPath) {
                formData.append('repo_path', repoPath);
            }
            const response = await fetch(`${backendUrl}/index/document`, {
                method: 'POST',
                body: formData
            });
            if (!response.ok) {
                throw new Error(await response.text());
            }
            vscode.window.showInformationMessage(`PairVoice: Indexed "${filename}"`);
        }
        catch (error) {
            vscode.window.showErrorMessage(`PairVoice: Failed to index "${filename}" — ${error.message}`);
        }
    }
}
/**
 * Show backend reachability in the status bar.
 */
function createStatusBarItem() {
    const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    item.text = '$(sync~spin) PairVoice: checking backend...';
    item.command = 'pairvoice.checkBackend';
    item.show();
    return item;
}
/**
 * Poll the backend health and update the status bar (green when healthy, red otherwise).
 */
async function refreshBackendStatus(context) {
    if (!_statusBar)
        return;
    const backendUrl = vscode.workspace.getConfiguration('pairvoice').get('backendUrl', 'http://localhost:8000');
    try {
        const response = await fetch(`${backendUrl}/health`);
        if (response.ok) {
            _statusBar.text = '$(circle-filled) PairVoice: Ready';
            _statusBar.color = new vscode.ThemeColor('notificationsInfoIcon.foreground');
        }
        else {
            throw new Error('unhealthy status');
        }
    }
    catch {
        _statusBar.text = '$(debug-disconnect) PairVoice: Backend offline';
        _statusBar.color = new vscode.ThemeColor('notificationsErrorIcon.foreground');
    }
}
async function refreshIndexStatus(context) {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder)
        return;
    const backendUrl = vscode.workspace.getConfiguration('pairvoice').get('backendUrl', 'http://localhost:8000');
    await refreshIndexStatusFromFolder(folder, backendUrl);
}
async function refreshIndexStatusFromFolder(folder, backendUrl) {
    // Optimistic placeholder so the UI reflects the active workspace immediately.
    _panel?.postMessage({
        type: 'indexStatus',
        sources: [{ name: folder.name, chunks: 0 }]
    });
    try {
        const url = `${backendUrl}/index/status?repo_path=${encodeURIComponent(folder.uri.fsPath)}`;
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(await response.text());
        }
        const data = (await response.json());
        const codeChunks = Number(data.code_chunks ?? 0);
        const docChunks = Number(data.doc_chunks ?? 0);
        _panel?.postMessage({
            type: 'indexStatus',
            sources: [
                { name: `${folder.name} (code)`, chunks: codeChunks },
                { name: `${folder.name} (docs)`, chunks: docChunks }
            ]
        });
    }
    catch {
        _panel?.postMessage({
            type: 'indexStatus',
            sources: [{ name: `${folder.name} (not indexed)`, chunks: 0 }]
        });
    }
}
/**
 * Run a lightweight wizard to collect the Vapi public key + assistant ID on first activation.
 */
async function requestVapiKeys(context) {
    const config = vscode.workspace.getConfiguration('pairvoice');
    const currentKey = config.get('vapiPublicKey', '');
    const currentAssistant = config.get('vapiAssistantId', '');
    const alreadyConfigured = !!currentKey && !!currentAssistant;
    const wizardDone = context.globalState.get(SETUP_COMPLETE_KEY, false);
    if (alreadyConfigured && wizardDone)
        return;
    const updated = {};
    if (!currentKey) {
        const entry = await vscode.window.showInputBox({
            prompt: 'Enter your Vapi public key (kept in settings; it is never committed).',
            ignoreFocusOut: true,
            placeHolder: 'pk_live_...',
            title: 'PairVoice configuration step 1 of 2'
        });
        if (!entry)
            return;
        await config.update('vapiPublicKey', entry.trim(), vscode.ConfigurationTarget.Global);
        updated.key = entry.trim();
    }
    if (!currentAssistant) {
        const entry = await vscode.window.showInputBox({
            prompt: 'Enter the assistant ID from vapi.ai (PairVoice assistant).',
            ignoreFocusOut: true,
            placeHolder: 'assistant_xyz',
            title: 'PairVoice configuration step 2 of 2'
        });
        if (!entry)
            return;
        await config.update('vapiAssistantId', entry.trim(), vscode.ConfigurationTarget.Global);
        updated.assistant = entry.trim();
    }
    if ((updated.key || currentKey) && (updated.assistant || currentAssistant)) {
        context.globalState.update(SETUP_COMPLETE_KEY, true);
        vscode.window.showInformationMessage('PairVoice: Vapi credentials configured.');
    }
}
/**
 * Securely store a GitHub token via SecretStorage.
 */
async function promptForGithubToken(context) {
    const token = await vscode.window.showInputBox({
        prompt: 'Enter your GitHub Personal Access Token (repo scope).',
        ignoreFocusOut: true,
        password: true
    });
    if (!token)
        return;
    try {
        await context.secrets.store('pairvoice.githubToken', token.trim());
        vscode.window.showInformationMessage('PairVoice: GitHub token stored securely.');
    }
    catch (error) {
        vscode.window.showErrorMessage(`PairVoice: Could not store GitHub token — ${error.message}`);
    }
}
/**
 * Send a JSON payload to the backend with optional error suppression.
 */
async function postJson(url, data, options = {}) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`${response.status} ${text}`);
        }
        return await response.json();
    }
    catch (error) {
        if (options.showError ?? true) {
            vscode.window.showErrorMessage(`PairVoice: Backend request failed — ${error.message}`);
        }
        console.error('PairVoice backend request error:', error);
        return null;
    }
}
function deactivate() {
    stopListening();
    _voiceServer?.dispose();
}
//# sourceMappingURL=extension.js.map