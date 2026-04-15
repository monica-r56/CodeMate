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
exports.initTerminalCapture = initTerminalCapture;
exports.collectContext = collectContext;
exports.navigateToFile = navigateToFile;
exports.applyEdit = applyEdit;
const vscode = __importStar(require("vscode"));
const cp = __importStar(require("child_process"));
const path = __importStar(require("path"));
// Stores last captured terminal output (updated via onDidWriteTerminalData)
let _lastTerminalOutput = '';
function initTerminalCapture(context) {
    const disposable = vscode.window.onDidWriteTerminalData?.((e) => {
        const text = e.data || '';
        _lastTerminalOutput = (_lastTerminalOutput + text).slice(-3000); // keep last 3000 chars
    });
    if (disposable) {
        context.subscriptions.push(disposable);
    }
}
async function collectContext() {
    const editor = vscode.window.activeTextEditor;
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const repoPath = workspaceFolder?.uri.fsPath || '';
    let activeFilePath = '';
    let activeFileContent = '';
    let selectedText = '';
    let cursorLine = 0;
    if (editor) {
        activeFilePath = vscode.workspace.asRelativePath(editor.document.uri);
        activeFileContent = editor.document.getText();
        selectedText = editor.document.getText(editor.selection);
        cursorLine = editor.selection.active.line + 1;
    }
    const { owner, repo } = await getGitRemote(repoPath);
    return {
        activeFilePath,
        activeFileContent: activeFileContent.slice(0, 8000), // cap at 8k chars
        selectedText,
        cursorLine,
        repoOwner: owner,
        repoName: repo,
        repoPath,
        terminalOutput: _lastTerminalOutput
    };
}
function getGitRemote(repoPath) {
    return new Promise((resolve) => {
        if (!repoPath)
            return resolve({ owner: '', repo: '' });
        cp.exec('git remote get-url origin', { cwd: repoPath }, (err, stdout) => {
            if (err || !stdout)
                return resolve({ owner: '', repo: '' });
            const url = stdout.trim();
            // Parse both SSH and HTTPS formats
            // git@github.com:owner/repo.git  OR  https://github.com/owner/repo.git
            const match = url.match(/github\.com[:/]([^/]+)\/([^/.]+)/);
            if (match) {
                resolve({ owner: match[1], repo: match[2] });
            }
            else {
                resolve({ owner: '', repo: '' });
            }
        });
    });
}
async function navigateToFile(filePath, line) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder)
        return;
    const fullPath = vscode.Uri.file(path.join(workspaceFolder.uri.fsPath, filePath));
    try {
        const doc = await vscode.workspace.openTextDocument(fullPath);
        const editor = await vscode.window.showTextDocument(doc);
        if (line > 0) {
            const pos = new vscode.Position(Math.max(0, line - 1), 0);
            editor.selection = new vscode.Selection(pos, pos);
            editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
        }
    }
    catch {
        vscode.window.showErrorMessage(`PairVoice: Could not open file ${filePath}`);
    }
}
async function applyEdit(filePath, newContent) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder)
        return false;
    const fullPath = vscode.Uri.file(path.join(workspaceFolder.uri.fsPath, filePath));
    const edit = new vscode.WorkspaceEdit();
    try {
        const doc = await vscode.workspace.openTextDocument(fullPath);
        const fullRange = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
        edit.replace(fullPath, fullRange, newContent);
        await vscode.workspace.applyEdit(edit);
        // Persist the change to disk immediately so the fix is "real" even if the file isn't open.
        await doc.save();
        return true;
    }
    catch {
        return false;
    }
}
//# sourceMappingURL=contextCollector.js.map