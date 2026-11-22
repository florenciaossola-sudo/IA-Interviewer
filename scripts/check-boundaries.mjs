import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, normalize, relative } from "node:path";
import process from "node:process";

const root = process.cwd();
const scanRoots = ["apps", "packages", "services"];
const violations = [];

const importRegex = /(?:import\s+[^"']*?from\s+["']([^"']+)["'])|(?:import\s*["']([^"']+)["'])/g;

function walk(dir) {
  const entries = readdirSync(dir);
  for (const entry of entries) {
    const full = join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      if (entry === "node_modules" || entry === "dist" || entry === ".venv") {
        continue;
      }
      walk(full);
      continue;
    }

    if (!full.endsWith(".ts") && !full.endsWith(".tsx") && !full.endsWith(".js") && !full.endsWith(".mjs")) {
      continue;
    }

    checkFile(full);
  }
}

function segment(pathValue) {
  const norm = normalize(pathValue).replace(/\\/g, "/");
  if (norm.includes("/packages/")) {
    return "packages";
  }
  if (norm.includes("/services/")) {
    return "services";
  }
  if (norm.includes("/apps/")) {
    return "apps";
  }
  return "other";
}

function checkFile(filePath) {
  const source = readFileSync(filePath, "utf8");
  const fromSegment = segment(filePath);

  let match;
  while ((match = importRegex.exec(source)) !== null) {
    const specifier = match[1] ?? match[2];
    if (!specifier || !specifier.startsWith(".")) {
      continue;
    }

    const resolved = normalize(join(filePath, "..", specifier)).replace(/\\/g, "/");
    const toSegment = segment(resolved);

    if (fromSegment === "packages" && (toSegment === "apps" || toSegment === "services")) {
      violations.push({ filePath, specifier, reason: "packages cannot depend on apps/services" });
    }

    if (fromSegment === "services" && toSegment === "apps") {
      violations.push({ filePath, specifier, reason: "services cannot depend on apps" });
    }
  }
}

for (const scanRoot of scanRoots) {
  const fullRoot = join(root, scanRoot);
  try {
    walk(fullRoot);
  } catch {
    // Missing root is allowed for incremental setup.
  }
}

if (violations.length > 0) {
  console.error("Boundary violations found:");
  for (const violation of violations) {
    console.error(`- ${relative(root, violation.filePath)} imports ${violation.specifier} (${violation.reason})`);
  }
  process.exit(1);
}

console.log("Boundary checks passed.");
