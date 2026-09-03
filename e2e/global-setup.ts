import { spawn, type ChildProcess } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

/*
 * Поднимает бэкенд и фронтенд для сквозных тестов, если E2E_EXTERNAL не задан.
 * Бэкенд: uvicorn на SQLite во временном каталоге, MODEL_PROVIDER=fake, письма
 * в консоль. Фронтенд: `next dev` (в CI — предварительно собранный `next start`).
 * PID-ы пишутся в файл, чтобы teardown их остановил.
 */
const ROOT = path.resolve(__dirname, "..");
const STATE_DIR = path.join(__dirname, ".state");
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000/api";
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

async function waitFor(url: string, timeoutMs: number): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      /* ещё не поднялся */
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`${url} не ответил за ${timeoutMs} мс`);
}

function start(command: string, args: string[], cwd: string, env: NodeJS.ProcessEnv): ChildProcess {
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ...env },
    stdio: ["ignore", "inherit", "inherit"],
    shell: process.platform === "win32",
    detached: process.platform !== "win32",
  });
  return child;
}

export default async function globalSetup(): Promise<void> {
  if (process.env.E2E_EXTERNAL) return;
  rmSync(STATE_DIR, { recursive: true, force: true });
  mkdirSync(STATE_DIR, { recursive: true });
  const dataDir = path.join(STATE_DIR, "data");
  mkdirSync(dataDir, { recursive: true });

  const uv = process.env.UV_BIN ?? (process.platform === "win32" ? "python -m uv" : "uv");
  const [uvCmd, ...uvPrefix] = uv.split(" ");
  const backendEnv = {
    ENVIRONMENT: "test",
    DATABASE_URL: `sqlite+aiosqlite:///${path.join(dataDir, "e2e.db").replace(/\\/g, "/")}`,
    MEDIA_ROOT: path.join(dataDir, "media"),
    MODEL_PROVIDER: "fake",
    JWT_SECRET: "e2e-secret-e2e-secret-e2e-secret-1234",
    PUBLIC_URL: BASE_URL,
    CORS_ORIGINS: JSON.stringify([BASE_URL]),
    EMAIL_MODE: "console",
    LOG_LEVEL: "WARNING",
  };
  const backendDir = path.join(ROOT, "backend");
  const migrate = start(uvCmd, [...uvPrefix, "run", "alembic", "upgrade", "head"], backendDir, backendEnv);
  await new Promise<void>((resolve, reject) => {
    migrate.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`alembic exit ${code}`))));
  });
  const api = start(
    uvCmd,
    [...uvPrefix, "run", "uvicorn", "leonit.main:app", "--host", "127.0.0.1", "--port", "8000"],
    backendDir,
    backendEnv,
  );
  const worker = start(uvCmd, [...uvPrefix, "run", "python", "-m", "leonit.jobs.worker"], backendDir, backendEnv);

  const frontendDir = path.join(ROOT, "frontend");
  const frontendEnv = { NEXT_PUBLIC_BACKEND_API_URL: API_URL, NEXT_PUBLIC_APP_URL: BASE_URL, NEXT_TELEMETRY_DISABLED: "1" };
  const frontend = process.env.E2E_FRONTEND_START
    ? start("npm", ["run", "start", "--", "-p", "3000"], frontendDir, frontendEnv)
    : start("npm", ["run", "dev", "--", "-p", "3000"], frontendDir, frontendEnv);

  writeFileSync(
    path.join(STATE_DIR, "pids.json"),
    JSON.stringify({ api: api.pid, worker: worker.pid, frontend: frontend.pid }),
  );
  await waitFor(`${API_URL}/health`, 90_000);
  await waitFor(BASE_URL, 180_000);
}
