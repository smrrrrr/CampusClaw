const { test, beforeEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");

function loadTS(relativePath, overrides = {}) {
  const filename = path.resolve(__dirname, relativePath);
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const originalRequire = mod.require.bind(mod);
  mod.require = (id) => overrides[id] ?? originalRequire(id);
  mod._compile(compiled, filename);
  return mod.exports;
}

const store = loadTS("../lib/store.ts");
const { refreshAccessToken, apiRequest, streamChat, api, mcpApi } = loadTS("../lib/api.ts", { "./store": store });
const { useAuthStore } = store;
const restored = {
  access_token: "renewed-token", role: "student", must_change_password: true,
  is_phone_login: true, can_switch_student: true,
  user: { id: 2, name: "小明", class_id: 101, teaching_classes: null },
};

beforeEach(() => {
  useAuthStore.getState().reset();
  global.document = { cookie: "" };
});

test("reload restores all session fields from the refresh cookie", async () => {
  global.fetch = async (url, options) => {
    assert.equal(url, "/api/auth/refresh");
    assert.equal(options.credentials, "include");
    return Response.json(restored);
  };
  assert.equal(await refreshAccessToken(), true);
  const state = useAuthStore.getState();
  assert.equal(state.accessToken, "renewed-token");
  assert.equal(state.userRole, "student");
  assert.equal(state.isPhoneLogin, true);
  assert.equal(state.canSwitchStudent, true);
  assert.equal(state.mustChangePassword, true);
  assert.deepEqual(state.currentStudent, { id: 2, name: "小明", class_id: 101 });
});

test("concurrent recovery requests share one refresh", async () => {
  let calls = 0;
  global.fetch = async () => { calls++; return Response.json(restored); };
  assert.deepEqual(await Promise.all([refreshAccessToken(), refreshAccessToken()]), [true, true]);
  assert.equal(calls, 1);
});

test("401 retries the protected request with the restored token", async () => {
  let requests = 0;
  global.fetch = async (url, options) => {
    if (url === "/api/auth/refresh") return Response.json(restored);
    requests++;
    if (requests === 1) return new Response(null, { status: 401 });
    assert.equal(options.headers.Authorization, "Bearer renewed-token");
    return Response.json({ ok: true });
  };
  assert.deepEqual(await apiRequest("/api/materials"), { ok: true });
  assert.equal(requests, 2);
});

test("expired refresh cookies do not create an authenticated session", async () => {
  global.fetch = async () => new Response(null, { status: 401 });
  assert.equal(await refreshAccessToken(), false);
  assert.equal(useAuthStore.getState().accessToken, null);
});

test("SSE meta and done retain tool status across split UTF-8 chunks", async () => {
  const calls = [{ tool_ref: "unit_convert@campus-tools", status: "ok" }];
  const payload = [
    { type: "meta", tool_calls: calls },
    { type: "delta", content: "换算结果" },
    { type: "done", answer: "1000 m", citations: [], remaining: 19, tool_calls: calls },
  ].map(item => `data: ${JSON.stringify(item)}\n\n`).join("");
  const bytes = new TextEncoder().encode(payload);
  global.fetch = async () => new Response(new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7));
    controller.close();
  } }));
  let metadata, final, delta = "";
  await streamChat(1, "1 km 转成 m", { onMeta: value => { metadata = value; }, onDelta: value => { delta += value; }, onDone: value => { final = value; } });
  assert.deepEqual(metadata, calls);
  assert.deepEqual(final.tool_calls, calls);
  assert.equal(final.answer, "1000 m");
  assert.equal(delta, "换算结果");
});

test("skill file upload preserves multipart content after token refresh", async () => {
  let attempts = 0;
  const file = new File(["[名称]\n审题"], "SKILL.md", { type: "text/markdown" });
  global.fetch = async (url, options) => {
    if (url === "/api/auth/refresh") return Response.json(restored);
    assert.equal(url, "/api/teacher/skills/preview");
    assert.ok(options.body instanceof FormData);
    assert.equal(options.headers["Content-Type"], undefined);
    assert.equal(options.body.get("class_id"), "101");
    assert.equal(options.body.get("file").name, "SKILL.md");
    assert.equal(await options.body.get("file").text(), "[名称]\n审题");
    if (++attempts === 1) return new Response(null, { status: 401 });
    assert.equal(options.headers.Authorization, "Bearer renewed-token");
    return Response.json({ content: "校验后的正文", name: "审题", keywords: [], tools: [] });
  };
  assert.equal((await mcpApi.previewSkill(101, file)).name, "审题");
  assert.equal(attempts, 2);
});

test("new conversations bind the selected subject application", async () => {
  global.fetch = async (url, options) => {
    assert.equal(url, "/api/student/conversations");
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(options.body), { title: "新对话", application_id: 12 });
    return Response.json({ id: 1, application_id: 12, title: "新对话", updated_at: "" });
  };
  assert.equal((await api.createConversation(undefined, 12)).application_id, 12);
});
