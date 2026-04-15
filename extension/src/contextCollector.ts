import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

export interface EditorContext {
  activeFilePath: string;
  activeFileContent: string;
  selectedText: string;
  cursorLine: number;
  repoOwner: string;
  repoName: string;
  repoPath: string;
  terminalOutput: string;
}

// Stores last captured terminal output (updated via onDidWriteTerminalData)
let _lastTerminalOutput = '';

export function initTerminalCapture(context: vscode.ExtensionContext) {
  const disposable = (vscode.window as any).onDidWriteTerminalData?.((e: any) => {
    const text: string = e.data || '';
    _lastTerminalOutput = (_lastTerminalOutput + text).slice(-3000); // keep last 3000 chars
  });
  if (disposable) {
    context.subscriptions.push(disposable);
  }
}

export async function collectContext(): Promise<EditorContext> {
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

function getGitRemote(repoPath: string): Promise<{ owner: string; repo: string }> {
  return new Promise((resolve) => {
    if (!repoPath) return resolve({ owner: '', repo: '' });
    cp.exec('git remote get-url origin', { cwd: repoPath }, (err, stdout) => {
      if (err || !stdout) return resolve({ owner: '', repo: '' });
      const url = stdout.trim();
      // Parse both SSH and HTTPS formats
      // git@github.com:owner/repo.git  OR  https://github.com/owner/repo.git
      const match = url.match(/github\.com[:/]([^/]+)\/([^/.]+)/);
      if (match) {
        resolve({ owner: match[1], repo: match[2] });
      } else {
        resolve({ owner: '', repo: '' });
      }
    });
  });
}

export async function navigateToFile(filePath: string, line: number) {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) return;

  const fullPath = vscode.Uri.file(path.join(workspaceFolder.uri.fsPath, filePath));
  try {
    const doc = await vscode.workspace.openTextDocument(fullPath);
    const editor = await vscode.window.showTextDocument(doc);
    if (line > 0) {
      const pos = new vscode.Position(Math.max(0, line - 1), 0);
      editor.selection = new vscode.Selection(pos, pos);
      editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
    }
  } catch {
    vscode.window.showErrorMessage(`PairVoice: Could not open file ${filePath}`);
  }
}

export async function applyEdit(filePath: string, newContent: string) {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) return false;

  const fullPath = vscode.Uri.file(path.join(workspaceFolder.uri.fsPath, filePath));
  const edit = new vscode.WorkspaceEdit();
  try {
    const doc = await vscode.workspace.openTextDocument(fullPath);
    const fullRange = new vscode.Range(
      doc.positionAt(0),
      doc.positionAt(doc.getText().length)
    );
    edit.replace(fullPath, fullRange, newContent);
    await vscode.workspace.applyEdit(edit);
    // Persist the change to disk immediately so the fix is "real" even if the file isn't open.
    await doc.save();
    return true;
  } catch {
    return false;
  }
}
