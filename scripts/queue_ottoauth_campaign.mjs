#!/usr/bin/env node

import fs from "fs";
import path from "path";
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArgs(argv) {
  const args = {
    campaign: "mixed_search",
    deviceId: "browser-agent-1",
    count: 6,
    autoauthRoot: process.env.OTTOAUTH_ROOT || "/Users/mark/Desktop/projects/oneclickstack/autoauth",
    manifestDir: path.join(ROOT, "outputs", "ottoauth_campaign_manifests"),
  };
  for (let index = 2; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--campaign" && next) {
      args.campaign = next;
      index += 1;
    } else if (arg === "--device-id" && next) {
      args.deviceId = next;
      index += 1;
    } else if (arg === "--count" && next) {
      args.count = Number(next);
      index += 1;
    } else if (arg === "--autoauth-root" && next) {
      args.autoauthRoot = next;
      index += 1;
    } else if (arg === "--manifest-dir" && next) {
      args.manifestDir = next;
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

function makeId(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

const CAMPAIGNS = {
  amazon_search: [
    "Go to https://www.amazon.com/, search for Logitech MX Master 3S, open the first plausible product result without purchasing anything, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price or unknown>\"}",
    "Go to https://www.amazon.com/, search for Apple AirPods Pro 2, open the first plausible product result without purchasing anything, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price or unknown>\"}",
    "Go to https://www.amazon.com/, search for Kindle Paperwhite, open the first plausible product result without purchasing anything, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price or unknown>\"}",
    "Go to https://www.amazon.com/, search for Samsung T7 SSD 1TB, open the first plausible product result without purchasing anything, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price or unknown>\"}",
    "Go to https://www.amazon.com/, search for Anker USB-C charger 65W, open the first plausible product result without purchasing anything, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price or unknown>\"}",
    "Go to https://www.amazon.com/, search for Nintendo Switch Pro Controller, open the first plausible product result without purchasing anything, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price or unknown>\"}",
  ],
  newegg_search: [
    "Go to https://www.newegg.com/, search for Logitech MX Master 3S, open the first relevant product result, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price>\"}",
    "Go to https://www.newegg.com/, search for Samsung 990 Pro 2TB, open the first relevant product result, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price>\"}",
    "Go to https://www.newegg.com/, search for RTX 4070 Super, open the first relevant product result, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price>\"}",
    "Go to https://www.newegg.com/, search for AMD Ryzen 7 7800X3D, open the first relevant product result, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price>\"}",
    "Go to https://www.newegg.com/, search for ASUS 27 inch 1440p monitor, open the first relevant product result, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price>\"}",
    "Go to https://www.newegg.com/, search for Keychron K2 keyboard, open the first relevant product result, and report exactly this JSON: {\"status\":\"success\",\"product_title\":\"<title>\",\"price_text\":\"<displayed price>\"}",
  ],
  wikipedia_search: [
    "Go to https://www.wikipedia.org/, search for Ada Lovelace, open the article page, and report exactly this JSON: {\"status\":\"success\",\"title\":\"<article title>\"}",
    "Go to https://www.wikipedia.org/, search for Alan Turing, open the article page, and report exactly this JSON: {\"status\":\"success\",\"title\":\"<article title>\"}",
    "Go to https://www.wikipedia.org/, search for Grace Hopper, open the article page, and report exactly this JSON: {\"status\":\"success\",\"title\":\"<article title>\"}",
    "Go to https://www.wikipedia.org/, search for Claude Shannon, open the article page, and report exactly this JSON: {\"status\":\"success\",\"title\":\"<article title>\"}",
    "Go to https://www.wikipedia.org/, search for Donald Knuth, open the article page, and report exactly this JSON: {\"status\":\"success\",\"title\":\"<article title>\"}",
    "Go to https://www.wikipedia.org/, search for Barbara Liskov, open the article page, and report exactly this JSON: {\"status\":\"success\",\"title\":\"<article title>\"}",
  ],
};

CAMPAIGNS.mixed_search = [
  ...CAMPAIGNS.amazon_search.slice(0, 2),
  ...CAMPAIGNS.newegg_search.slice(0, 2),
  ...CAMPAIGNS.wikipedia_search.slice(0, 2),
];

async function main() {
  const args = parseArgs(process.argv);
  const prompts = CAMPAIGNS[args.campaign];
  if (!prompts) {
    throw new Error(`Unknown campaign: ${args.campaign}`);
  }

  const envPath = path.join(args.autoauthRoot, ".env.local");
  const env = loadEnvFile(envPath);
  const { createClient } = require(path.join(args.autoauthRoot, "node_modules", "@libsql", "client"));
  const client = createClient({
    url: env.TURSO_DB_URL,
    authToken: env.TURSO_DB_AUTH_TOKEN,
  });

  const selectedPrompts = prompts.slice(0, Math.max(0, Math.min(args.count, prompts.length)));
  const now = new Date().toISOString();
  const queued = [];

  for (const prompt of selectedPrompts) {
    const taskId = makeId("mock");
    await client.execute({
      sql: `INSERT INTO computeruse_tasks
        (id, device_id, type, url, status, source, agent_username, task_prompt, run_id, result_json, error, created_at, delivered_at, completed_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      args: [
        taskId,
        args.deviceId,
        "start_local_agent_goal",
        "",
        "queued",
        "toolcalltokenization_campaign",
        "tracecollector",
        prompt,
        null,
        null,
        null,
        now,
        null,
        null,
        now,
      ],
    });
    queued.push({
      id: taskId,
      device_id: args.deviceId,
      campaign: args.campaign,
      task_prompt: prompt,
      created_at: now,
    });
  }

  fs.mkdirSync(args.manifestDir, { recursive: true });
  const manifestPath = path.join(
    args.manifestDir,
    `${new Date().toISOString().replace(/[:.]/g, "-")}_${args.campaign}.json`,
  );
  fs.writeFileSync(
    manifestPath,
    JSON.stringify(
      {
        campaign: args.campaign,
        device_id: args.deviceId,
        created_at: now,
        tasks: queued,
      },
      null,
      2,
    ) + "\n",
  );

  console.log(JSON.stringify({ queued: queued.length, manifest: manifestPath, task_ids: queued.map((task) => task.id) }, null, 2));
}

main().catch((error) => {
  console.error(error.message || String(error));
  process.exit(1);
});
