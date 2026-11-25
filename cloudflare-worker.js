function endpoint(env) {
  if (!/^[A-Za-z0-9_-]+$/.test(env.GITHUB_OWNER || "") ||
      !/^[A-Za-z0-9_.-]+$/.test(env.GITHUB_REPO || "")) {
    throw new Error("Set valid GITHUB_OWNER and GITHUB_REPO variables");
  }
  if (!env.GITHUB_TOKEN) throw new Error("Missing GITHUB_TOKEN secret");
  return "https://api.github.com/repos/" + env.GITHUB_OWNER + "/" +
    env.GITHUB_REPO + "/actions/workflows/automatic-checks.yml";
}
function headers(env) {
  return {
    Authorization: "Bearer " + env.GITHUB_TOKEN,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "Cinema-Scheduler"
  };
}
export default {
  async fetch(request, env) {
    if (request.method !== "GET") return new Response("Method not allowed", {status: 405});
    try {
      const response = await fetch(endpoint(env), {
        headers: headers(env), redirect: "manual",
        signal: AbortSignal.timeout(20000)
      });
      return Response.json({
        ok: response.ok, githubStatus: response.status,
        message: response.ok
          ? "GitHub connection OK. Verify scheduled dispatch separately."
          : "Check repository, workflow and token permissions."
      }, {headers: {"Cache-Control": "no-store"}});
    } catch {
      return Response.json({ok: false, error: "GitHub connection failed; check configuration and Worker logs."},
        {status: 502, headers: {"Cache-Control": "no-store"}});
    }
  },
  async scheduled(event, env, ctx) {
    const response = await fetch(endpoint(env) + "/dispatches", {
      method: "POST",
      headers: {...headers(env), "Content-Type": "application/json"},
      body: JSON.stringify({ref: "main"}),
      redirect: "manual", signal: AbortSignal.timeout(20000)
    });
    console.log("GitHub dispatch status:", response.status);
    if (!response.ok) throw new Error("GitHub dispatch failed: HTTP " + response.status);
  }
};
