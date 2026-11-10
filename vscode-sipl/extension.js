const vscode = require("vscode");

class SiplDebugAdapterDescriptorFactory {
  createDebugAdapterDescriptor(session) {
    const python = vscode.workspace
      .getConfiguration("sipl")
      .get("pythonPath", "python3");
    const folder = session.workspaceFolder;
    const options = folder ? { cwd: folder.uri.fsPath } : undefined;
    return new vscode.DebugAdapterExecutable(
      python,
      ["-m", "sipl.debug_adapter"],
      options
    );
  }
}

function activate(context) {
  const factory = new SiplDebugAdapterDescriptorFactory();
  context.subscriptions.push(
    vscode.debug.registerDebugAdapterDescriptorFactory("sipl", factory)
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
