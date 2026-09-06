import { execSync, spawn, type ChildProcess } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

/*
 * Поднимает бэкенд и фронтенд для сквозных тестов, если E2E_EXTERNAL не задан.
 * Бэкенд: uvicorn на SQLite во временном каталоге, MODEL_PROVIDER=fake, письма
 * в консоль. Фронтенд: Vite (в CI — предварительно собранный Nitro server).
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

/** Освободить порт от процесса прошлого прогона (иначе тесты бьют в мёртвый сервер). */
export function killPort(port: number): void {
  try {
    if (process.platform === "win32") {
      const out = execSync(`netstat -ano | findstr LISTENING | findstr :${port}`, { encoding: "utf-8" });
      const pids = new Set(out.split(/\r?\n/).map((l) => l.trim().split(/\s+/).pop()).filter((p) => p && p !== "0"));
      pids.forEach((pid) => execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" }));
    } else {
      execSync(`fuser -k ${port}/tcp`, { stdio: "ignore" });
    }
  } catch {
    /* порт свободен */
  }
}

export default async function globalSetup(): Promise<void> {
  if (process.env.E2E_EXTERNAL) return;
  killPort(3000);
  killPort(8000);
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
  const frontendEnv = { VITE_BACKEND_API_URL: API_URL, VITE_APP_URL: BASE_URL };
  let frontend: ChildProcess;
  if (process.env.E2E_FRONTEND_START) {
    frontend = start("node", [".output/server/index.mjs"], frontendDir, { ...frontendEnv, PORT: "3000", HOST: "127.0.0.1" });
  } else {
    frontend = start("npm", ["run", "dev", "--", "--port", "3000"], frontendDir, frontendEnv);
  }

  writeFileSync(
    path.join(STATE_DIR, "pids.json"),
    JSON.stringify({ api: api.pid, worker: worker.pid, frontend: frontend.pid }),
  );
  await waitFor(`${API_URL}/health`, 90_000);
  await waitFor(BASE_URL, 180_000);
}
