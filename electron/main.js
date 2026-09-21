/* Electron shell. The Python API runs as a child process and dies with the app.
 *
 * The window is frameless-ish on purpose: the tab strip in the page is the
 * title bar (it sets -webkit-app-region: drag), so the app reads as a browser
 * rather than a web page inside a window.
 */

const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const PORT = process.env.QUIPU_PORT || 8848;
const ROOT = path.join(__dirname, "..");
const URL = `http://127.0.0.1:${PORT}/`;

let backend = null;
let win = null;

function pythonPath() {
  const venv =
    process.platform === "win32"
      ? path.join(ROOT, ".venv", "Scripts", "python.exe")
      : path.join(ROOT, ".venv", "bin", "python");
  return require("fs").existsSync(venv) ? venv : "python";
}

function startBackend() {
  backend = spawn(
    pythonPath(),
    ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", String(PORT)],
    { cwd: ROOT, env: process.env }
  );
  backend.stdout.on("data", (d) => process.stdout.write(`[api] ${d}`));
  backend.stderr.on("data", (d) => process.stderr.write(`[api] ${d}`));
  backend.on("exit", (code) => console.log(`[api] exited ${code}`));
}

/** Poll until the API answers, so we never load a blank window. */
function waitForBackend(attempt = 0) {
  return new Promise((resolve, reject) => {
    const probe = () => {
      http
        .get(`${URL}api/health`, (res) => {
          res.resume();
          resolve();
        })
        .on("error", () => {
          if (attempt++ > 60) return reject(new Error("backend did not start"));
          setTimeout(probe, 500);
        });
    };
    probe();
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1680,
    height: 1000,
    minWidth: 1100,
    backgroundColor: "#0b0d10",
    titleBarStyle: "hiddenInset",
    titleBarOverlay: { color: "#15181d", symbolColor: "#8b94a3", height: 38 },
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });

  win.loadURL(URL);

  // Article links belong in the real browser, not inside the app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

app.whenReady().then(async () => {
  startBackend();
  try {
    await waitForBackend();
  } catch (err) {
    console.error(err.message);
  }
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backend) backend.kill();
});
