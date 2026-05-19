"""ChemMaster local Web frontend — FastAPI backend + minimal SPA.

Endpoints:
- GET  /                         → main HTML page
- GET  /api/tools                → list registered tools (JSON)
- GET  /api/skills               → list available skills
- GET  /api/engines              → engine availability status
- POST /api/run                  → submit a natural-language task; returns task_id
- GET  /api/task/{task_id}       → poll task status
- GET  /api/task/{task_id}/events → SSE stream of agent events for live UI
- POST /api/task/{task_id}/respond → user response to confirm / recommend card
- GET  /api/benchmarks           → benchmark summary aggregator (for §4 figures)

This is the minimum-viable Web frontend. It does not aim for production-grade
UX but does provide the four claims the thesis needs:
1. Three-frontend equivalence (CLI / TUI / Web run the same task)
2. Visual rendering of structures + spectra
3. Lower barrier of entry for chemists who don't use CLI
4. Demo target for the thesis defense

Launch:
    pip install fastapi uvicorn
    python -m chemaster.web
    # or:
    chemaster web
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"


# ══════════════════════════════════════════════════════════════════════════════
# In-memory task store
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class WebTask:
    task_id: str
    intent: str
    status: str = "queued"         # queued / running / waiting_user / done / failed
    events: list[dict] = field(default_factory=list)
    pending_card: dict | None = None
    result: dict | None = None
    user_response_event: threading.Event = field(default_factory=threading.Event)
    user_response: dict | None = None


class WebTaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, WebTask] = {}
        self._lock = threading.Lock()

    def new_task(self, intent: str) -> WebTask:
        tid = str(uuid.uuid4())[:8]
        task = WebTask(task_id=tid, intent=intent)
        with self._lock:
            self._tasks[tid] = task
        return task

    def get(self, tid: str) -> WebTask | None:
        return self._tasks.get(tid)


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI app factory
# ══════════════════════════════════════════════════════════════════════════════


def create_app(agent_factory: Any | None = None):
    """Create the FastAPI application.

    Args:
        agent_factory: callable returning a fresh ChemAgent instance per task,
            or None for display-only mode.
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        raise RuntimeError(
            "FastAPI is not installed. Run: pip install fastapi uvicorn"
        )

    app = FastAPI(title="ChemMaster", version="0.3.0")
    store = WebTaskStore()

    # Static files (the SPA)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ────────────────────────────────────────────────────────
    # Routes
    # ────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_html = STATIC_DIR / "index.html"
        if index_html.exists():
            return HTMLResponse(index_html.read_text(encoding="utf-8"))
        return HTMLResponse(_DEFAULT_INDEX_HTML)

    @app.get("/api/tools")
    async def list_tools():
        if agent_factory is None:
            return {"tools": [], "note": "no agent_factory configured"}
        agent = agent_factory()
        return {
            "tools": [
                {"name": t, "description":
                 (agent.tools.get(t).description or "")[:200]}
                for t in agent.tools.names()
            ],
        }

    @app.get("/api/skills")
    async def list_skills():
        skills_dir = Path(__file__).resolve().parents[1] / "kb" / "skills"
        if not skills_dir.exists():
            return {"skills": []}
        return {"skills": sorted(p.name for p in skills_dir.iterdir() if p.is_dir())}

    @app.get("/api/engines")
    async def engine_status():
        engines = ["g16", "g09", "bdf", "momap", "psi4", "orca", "xtb"]
        return {
            "engines": [
                {"name": e, "available": shutil.which(e) is not None,
                 "path": shutil.which(e)}
                for e in engines
            ],
        }

    @app.post("/api/run")
    async def submit_task(payload: dict):
        intent = payload.get("intent", "").strip()
        if not intent:
            raise HTTPException(status_code=400, detail="intent is required")
        task = store.new_task(intent)
        # Run agent in background thread
        if agent_factory is not None:
            threading.Thread(target=_run_agent_blocking,
                              args=(task, agent_factory), daemon=True).start()
        else:
            task.status = "done"
            task.result = {"note": "no agent configured (display-only)"}
        return {"task_id": task.task_id, "status": task.status}

    @app.get("/api/task/{task_id}")
    async def task_status(task_id: str):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return {
            "task_id": task.task_id,
            "intent": task.intent,
            "status": task.status,
            "n_events": len(task.events),
            "pending_card": task.pending_card,
            "result": task.result,
        }

    @app.get("/api/task/{task_id}/events")
    async def task_events(task_id: str):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return {"events": task.events}

    @app.post("/api/task/{task_id}/respond")
    async def respond(task_id: str, payload: dict):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        task.user_response = payload
        task.user_response_event.set()
        task.pending_card = None
        return {"ok": True}

    @app.get("/api/benchmarks")
    async def benchmarks():
        bench_root = Path(__file__).resolve().parents[2] / "benchmarks"
        out: dict[str, Any] = {}
        for name in ("s22", "quest", "anthracene"):
            summary_file = bench_root / name / "summary.json"
            if summary_file.exists():
                try:
                    out[name] = json.loads(summary_file.read_text())
                except Exception as exc:
                    out[name] = {"error": str(exc)}
        eng_metrics = bench_root / "engineering_metrics"
        if eng_metrics.exists():
            out["engineering"] = {}
            for f in eng_metrics.glob("*.json"):
                try:
                    out["engineering"][f.stem] = json.loads(f.read_text())
                except Exception:
                    pass
        return out

    return app


def _run_agent_blocking(task: WebTask, agent_factory: Any) -> None:
    """Run the agent for one task in this thread, recording events."""
    try:
        from chemaster.agent.types import TaskInstance
        agent = agent_factory()
        task.status = "running"

        def confirm_cb(tool: str, args: dict, reason: str) -> bool:
            task.pending_card = {"mode": "confirm", "tool": tool,
                                  "args": args, "reason": reason}
            task.events.append({"type": "confirm", **task.pending_card})
            task.status = "waiting_user"
            task.user_response_event.clear()
            task.user_response_event.wait()
            task.status = "running"
            return bool(task.user_response and task.user_response.get("approved"))

        def recommend_cb(payload: dict) -> dict:
            task.pending_card = {"mode": "recommend", **payload}
            task.events.append({"type": "recommend", **payload})
            task.status = "waiting_user"
            task.user_response_event.clear()
            task.user_response_event.wait()
            task.status = "running"
            return task.user_response or {"status": "accept"}

        agent.config.confirm_callback = confirm_cb
        agent.config.recommend_callback = recommend_cb

        result = agent.run(TaskInstance(intent=task.intent))
        task.status = "done" if result.status == "completed" else "failed"
        task.result = {
            "agent_status": result.status,
            "summary": getattr(agent, "_finish_payload", {}).get("summary", ""),
            "key_results": getattr(agent, "_finish_payload", {}).get("key_results", {}),
            "n_steps": result.steps_used,
        }
    except Exception as exc:
        logger.exception("Web agent task %s failed", task.task_id)
        task.status = "failed"
        task.result = {"error": f"{type(exc).__name__}: {exc}"}


# ══════════════════════════════════════════════════════════════════════════════
# Default index HTML (served when static/index.html missing)
# ══════════════════════════════════════════════════════════════════════════════


_DEFAULT_INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ChemMaster</title>
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 0;
         background: #f5f5f7; color: #222; }
  header { background: #1d1d1f; color: #fff; padding: 12px 24px; }
  header h1 { margin: 0; font-size: 18px; font-weight: 500; }
  main { display: grid; grid-template-columns: 2fr 1fr; gap: 16px;
         padding: 16px; max-width: 1300px; margin: 0 auto; }
  .panel { background: #fff; border-radius: 8px; padding: 16px;
           box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  #chat { height: 60vh; overflow-y: auto; border: 1px solid #e5e5ea;
          border-radius: 6px; padding: 12px; background: #fafafa;
          font-family: ui-monospace, SFMono-Regular, monospace; font-size: 13px;
          white-space: pre-wrap; }
  #chat .me  { color: #0066cc; font-weight: 600; }
  #chat .out { color: #333; }
  #chat .ok  { color: #1a7f37; }
  #chat .err { color: #cf222e; }
  #chat .rec { background: #fff7d4; border-left: 3px solid #f0b232;
               padding: 6px 10px; margin: 6px 0; border-radius: 4px; }
  #chat .conf { background: #f4f4ff; border-left: 3px solid #5b6bf0;
                padding: 6px 10px; margin: 6px 0; border-radius: 4px; }
  #cmd { width: 100%; padding: 8px 12px; font-size: 14px;
         border: 1px solid #d2d2d7; border-radius: 6px; }
  .small { font-size: 12px; color: #6e6e73; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
          font-size: 11px; margin-right: 6px; }
  .pill.ok { background: #d1f4d1; color: #155e0f; }
  .pill.no { background: #fde2e1; color: #8a1c1c; }
  button.btn { background: #0a84ff; color: #fff; border: 0;
               padding: 6px 14px; border-radius: 6px; cursor: pointer;
               font-size: 13px; }
  button.alt { background: #e5e5ea; color: #1d1d1f; }
  h3 { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
</style>
</head>
<body>
<header><h1>ChemMaster — labor-saving collaborator for computational chemistry</h1></header>
<main>
  <section class="panel">
    <h3>Conversation</h3>
    <div id="chat"></div>
    <div style="margin-top:10px; display:flex; gap:8px;">
      <input id="cmd" placeholder="Describe your computation, e.g. 'optimize water with B3LYP/6-31G(d)'"/>
      <button class="btn" onclick="submitTask()">Send</button>
    </div>
  </section>
  <aside>
    <div class="panel">
      <h3>Engines</h3>
      <div id="engines" class="small">checking...</div>
    </div>
    <div class="panel" style="margin-top:12px">
      <h3>Skills</h3>
      <div id="skills" class="small">loading...</div>
    </div>
    <div class="panel" style="margin-top:12px">
      <h3>Active task</h3>
      <div id="active" class="small">(idle)</div>
    </div>
    <div class="panel" style="margin-top:12px">
      <h3>Benchmark snapshot</h3>
      <div id="bench" class="small">loading...</div>
    </div>
  </aside>
</main>
<script>
let currentTask = null;
let pollTimer = null;
const chat = document.getElementById("chat");
const cmd  = document.getElementById("cmd");

function append(html, cls="out") {
  const div = document.createElement("div");
  div.className = cls;
  div.innerHTML = html;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

cmd.addEventListener("keydown", e => {
  if (e.key === "Enter") submitTask();
});

async function submitTask() {
  const text = cmd.value.trim();
  if (!text) return;
  cmd.value = "";
  append(`<span class="me">&gt; ${text}</span>`);
  const r = await fetch("/api/run", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({intent: text})});
  const data = await r.json();
  currentTask = data.task_id;
  document.getElementById("active").innerText = `task ${data.task_id}: ${text.slice(0,40)}`;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollTask, 1500);
}

async function pollTask() {
  if (!currentTask) return;
  const r = await fetch(`/api/task/${currentTask}`);
  const data = await r.json();
  if (data.pending_card) {
    renderCard(data.pending_card);
  }
  if (["done","failed"].includes(data.status)) {
    clearInterval(pollTimer);
    if (data.result && data.result.summary) {
      append(`<span class="ok">✓ ${data.result.summary}</span>`);
    } else if (data.result && data.result.error) {
      append(`<span class="err">✗ ${data.result.error}</span>`);
    } else {
      append(`<span class="ok">task ${data.status}</span>`);
    }
    document.getElementById("active").innerText = "(idle)";
    currentTask = null;
  }
}

function renderCard(card) {
  if (card.mode === "confirm") {
    if (document.getElementById("card_" + currentTask)) return;
    const div = document.createElement("div");
    div.id = "card_" + currentTask;
    div.className = "conf";
    div.innerHTML = `<b>CONFIRM</b> ${card.tool} — ${card.reason}<br>
       <code>${JSON.stringify(card.args).slice(0,200)}</code><br>
       <button class="btn" onclick="respond({approved:true})">Approve</button>
       <button class="btn alt" onclick="respond({approved:false})">Reject</button>`;
    chat.appendChild(div);
  } else if (card.mode === "recommend") {
    if (document.getElementById("card_" + currentTask)) return;
    const div = document.createElement("div");
    div.id = "card_" + currentTask;
    div.className = "rec";
    div.innerHTML = `<b>RECOMMEND</b> ${card.decision}<br>
       <b>${card.recommendation}</b><br>
       <span class="small">${card.reasoning}</span><br>
       Alternatives: ${(card.alternatives||[]).join(" / ") || "(none)"}<br>
       <button class="btn" onclick="respond({status:'accept'})">Accept</button>
       <button class="btn alt" onclick="respondModify()">Modify</button>
       <button class="btn alt" onclick="respond({status:'cancel'})">Cancel</button>`;
    chat.appendChild(div);
  }
  chat.scrollTop = chat.scrollHeight;
}

async function respond(payload) {
  if (!currentTask) return;
  await fetch(`/api/task/${currentTask}/respond`, {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(payload)});
  const card = document.getElementById("card_" + currentTask);
  if (card) card.remove();
}

function respondModify() {
  const v = prompt("Modified value:");
  if (v) respond({status:"modify", modified_value: v});
}

async function loadStatus() {
  try {
    const e = await (await fetch("/api/engines")).json();
    const html = e.engines.map(x =>
      `<span class="pill ${x.available?'ok':'no'}">${x.name}</span>`).join("");
    document.getElementById("engines").innerHTML = html;
  } catch (err) {}

  try {
    const s = await (await fetch("/api/skills")).json();
    document.getElementById("skills").innerText =
      s.skills.length ? s.skills.join(", ") : "(none)";
  } catch (err) {}

  try {
    const b = await (await fetch("/api/benchmarks")).json();
    let lines = [];
    if (b.s22)        lines.push(`S22: MAE ${b.s22.mae_kcal} kcal/mol`);
    if (b.quest)      lines.push(`QUEST: MAE ${b.quest.mae_eV} eV`);
    if (b.anthracene) lines.push(`anthracene: ${b.anthracene.result?.results?.k_r_s_inv?.toExponential(2) || "?"} s⁻¹`);
    document.getElementById("bench").innerHTML = lines.join("<br>") || "(no data)";
  } catch (err) {}
}

loadStatus();
setInterval(loadStatus, 30000);
</script>
</body>
</html>
"""


def main(host: str = "127.0.0.1", port: int = 8765,
         agent_factory: Any | None = None) -> None:
    """Launch the Web UI."""
    try:
        import uvicorn
    except ImportError:
        raise RuntimeError("uvicorn is not installed. Run: pip install fastapi uvicorn")

    app = create_app(agent_factory=agent_factory)
    print(f"ChemMaster Web UI running at http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")
