#!/usr/bin/env bun

import { readdirSync, existsSync } from "fs";
import { join } from "path";

const dir = import.meta.dir || process.cwd();

function findCsvFiles() {
  try {
    return readdirSync(dir).filter(f => f.toLowerCase().endsWith(".csv"));
  } catch {
    return [];
  }
}

function checkEnvKey() {
  const envPath = join(dir, ".env");
  if (existsSync(envPath)) {
    const content = Bun.file(envPath).text();
    const match = content.match(/GEMINI_KEY\s*=\s*(.+)/m);
    if (match) return match[1].trim();
  }
  return null;
}

async function prompt(msg: string): Promise<string> {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(msg, (ans) => { rl.close(); resolve(ans); });
  });
}

async function main() {
  console.clear();
  console.log(`
╔══════════════════════════════════════════════════════════╗
║        📊 NSE Option Chain Signal Engine 💹            ║
║              Gemini AI-Powered Analysis                  ║
╚══════════════════════════════════════════════════════════╝
`);

  const csvFiles = findCsvFiles();
  let selectedFile = "";

  if (csvFiles.length === 0) {
    console.log("❌ No CSV files found.");
    selectedFile = await prompt("Enter full path to option chain CSV: ");
    if (!selectedFile || !existsSync(selectedFile)) {
      console.log("❌ File not found. Exiting.");
      process.exit(1);
    }
  } else {
    console.log("\n📁 Available CSV files:\n");
    csvFiles.forEach((f, i) => console.log(`  ${i + 1}. ${f}`));
    console.log();
    
    const idx = await prompt("Choose file number: ");
    const num = parseInt(idx);
    if (num > 0 && num <= csvFiles.length) {
      selectedFile = csvFiles[num - 1];
    } else {
      console.log("❌ Invalid selection. Exiting.");
      process.exit(1);
    }
  }

  let apiKey = checkEnvKey();
  
  if (!apiKey) {
    console.log("\n🔑 Enter your Gemini API key:");
    apiKey = await prompt("Gemini API Key: ");
    if (!apiKey) {
      console.log("❌ API key required. Exiting.");
      process.exit(1);
    }
  } else {
    console.log("✅ Found API key in .env");
    const reuse = await prompt("Use saved key? (y/n): ");
    if (reuse.toLowerCase() !== "y") {
      apiKey = await prompt("Enter new Gemini API Key: ");
    }
  }

  console.log("\n⚙️  Optional (press Enter to skip):");
  
  const expiry = await prompt(`Expiry [28-Apr-2026]: `) || "28-Apr-2026";
  const symbol = await prompt(`Symbol [NIFTY]: `) || "NIFTY";
  
  console.clear();
  console.log(`
╔══════════════════════════════════════════════════════════╗
║                   📋 Setup Summary                  ║
╚══════════════════════════════════════════════════════════╝
  📁 File:   ${selectedFile}
  🔑 API Key: ${apiKey.substring(0, 8)}...${apiKey.slice(-4)}
  📅 Expiry: ${expiry}
  🏷️  Symbol: ${symbol}
`);
  
  const confirm = await prompt("Proceed? (y/n): ");
  if (confirm.toLowerCase() !== "y") {
    console.log("👋 Cancelled.");
    process.exit(0);
  }

  console.clear();
  console.log("🤖 Running analysis...\n");

  const scriptPath = join(dir, "nse_signal.py");
  if (!existsSync(scriptPath)) {
    console.log("❌ nse_signal.py not found.");
    process.exit(1);
  }

  const proc = Bun.spawn([
    "python",
    scriptPath,
    "--file", selectedFile,
    "--key", apiKey,
    "--expiry", expiry,
    "--symbol", symbol
  ]);

  proc.stdout.pipe(process.stdout);
  proc.stderr.pipe(process.stderr);

  const exitCode = await proc.exited;
  
  console.log("\n" + "=".repeat(60));
  if (exitCode === 0) {
    console.log("✅ Analysis complete!");
  } else {
    console.log(`❌ Error (exit code ${exitCode})`);
  }
  console.log("=".repeat(60));
  
  const choice = await prompt("\n1. Run again  2. Exit: ");
  if (choice === "1") {
    main();
  } else {
    console.log("👋 Goodbye!");
  }
}

main();