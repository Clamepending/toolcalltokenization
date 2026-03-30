#!/usr/bin/env node

import fs from "fs";
import path from "path";
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArgs(argv) {
  const args = {
    deviceId: "browser-agent-1",
    tracesRoot: path.join(ROOT, "data", "ottoauth"),
    autoauthRoot: process.env.OTTOAUTH_ROOT || "/Users/mark/Desktop/projects/oneclickstack/autoauth",
    output: path.join(ROOT, "outputs", "ottoauth_collection_audit.json"),
  };
  for (let index = 2; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--device-id" && next) {
      args.deviceId = next;
      index += 1;
    } else if (arg === "--traces-root" && next) {
      args.tracesRoot = next;
      index += 1;
    } else if (arg === "--autoauth-root" && next) {
      args.autoauthRoot = next;
      index += 1;
    } else if (arg === "--output" && next) {
      args.output = next;
      index += 1;
    }
  }
  return args;
}

function loadEnvFile(filePath) {
  const values = {};
  const content = fs.readFileSync(filePath, "utf8");
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    let value = rest.join("=").trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

function findLocalTaskIds(root) {
  const taskIds = new Set();
  if (!fs.existsSync(root)) return taskIds;
  const stack = [root];
  while (stack.length > 0) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(entryPath);
        continue;
      }
      if (entry.isFile() && entry.name === "task.json") {
        try {
          const payload = JSON.parse(fs.readFileSync(entryPath, "utf8"));
          const taskId = payload?.task?.id;
          if (typeof taskId === "string" && taskId.trim()) {
            taskIds.add(taskId.trim());
          }
        } catch {
          // Ignore malformed local files during audit.
        }
      }
    }
  }
  return taskIds;
}

async function main() {
  const args = parseArgs(process.argv);
  const env = loadEnvFile(path.join(args.autoauthRoot, ".env.local"));
  const { createClient } = require(path.join(args.autoauthRoot, "node_modules", "@libsql", "client"));
  const client = createClient({
    url: env.TURSO_DB_URL,
    authToken: env.TURSO_DB_AUTH_TOKEN,
  });

  const serverRows = await client.execute({
    sql: `SELECT id, status, type, task_prompt, created_at, updated_at
          FROM computeruse_tasks
          WHERE device_id = ?
          ORDER BY created_at DESC`,
    args: [args.deviceId],
  });

  const localTaskIds = findLocalTaskIds(args.tracesRoot);
  const completedRows = serverRows.rows.filter(
    (row) => row.status === "completed" && row.type === "start_local_agent_goal",
  );
  const failedRows = serverRows.rows.filter(
    (row) => row.status === "failed" && row.type === "start_local_agent_goal",
  );
  const missingCompleted = completedRows.filter((row) => !localTaskIds.has(String(row.id)));
  const missingFailed = failedRows.filter((row) => !localTaskIds.has(String(row.id)));

  const payload = {
    device_id: args.deviceId,
    traces_root: args.tracesRoot,
    local_recorded_task_count: localTaskIds.size,
    server_completed_task_count: completedRows.length,
    server_failed_task_count: failedRows.length,
    missing_completed_recordings: missingCompleted.map((row) => ({
      id: row.id,
      created_at: row.created_at,
      updated_at: row.updated_at,
      task_prompt: row.task_prompt,
    })),
    missing_failed_recordings: missingFailed.map((row) => ({
      id: row.id,
      created_at: row.created_at,
      updated_at: row.updated_at,
      task_prompt: row.task_prompt,
    })),
  };

  fs.mkdirSync(path.dirname(args.output), { recursive: true });
  fs.writeFileSync(args.output, JSON.stringify(payload, null, 2) + "\n");
  console.log(JSON.stringify(payload, null, 2));
}

main().catch((error) => {
  console.error(error.message || String(error));
  process.exit(1);
});
