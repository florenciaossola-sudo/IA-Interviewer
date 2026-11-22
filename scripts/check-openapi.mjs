const baseUrl = process.env.AI_INTERVIEWER_API_URL || "http://127.0.0.1:8081";
const requiredPaths = [
  "/run/start",
  "/run/answer",
  "/review/queue",
  "/runs/{run_id}/review",
  "/runs/{run_id}/assessment.html",
];

const response = await fetch(`${baseUrl}/openapi.json`);
if (!response.ok) {
  throw new Error(`OpenAPI endpoint failed: ${response.status}`);
}
const schema = await response.json();
const missing = requiredPaths.filter((path) => !schema.paths?.[path]);
if (missing.length) {
  throw new Error(`OpenAPI contract is missing: ${missing.join(", ")}`);
}
console.log(`OpenAPI contract valid: ${Object.keys(schema.paths).length} paths`);