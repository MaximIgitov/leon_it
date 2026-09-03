import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { killPort } from "./global-setup";

const STATE_DIR = path.join(__dirname, ".state");

function kill(pid: number | undefined): void {
  if (!pid) return;
  try {
    if (process.platform === "win32") {
      execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" });
    } else {
      process.kill(-pid, "SIGTERM");
    }
  } catch {
    /* уже завершён */
  }
}

export default async function globalTeardown(): Promise<void> {
  if (process.env.E2E_EXTERNAL) return;
  const file = path.join(STATE_DIR, "pids.json");
  if (!existsSync(file)) return;
  const pids = JSON.parse(readFileSync(file, "utf-8")) as Record<string, number>;
  Object.values(pids).forEach(kill);
  // На Windows дерево процессов npm → node не всегда убивается по PID; добиваем по портам.
  killPort(3000);
  killPort(8000);
}
