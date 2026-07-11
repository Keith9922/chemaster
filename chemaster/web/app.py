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
        from chemaster.engines import probe_engines

        return {
            "engines": [
                {"name": s.name, "available": s.available, "path": s.path}
                for s in probe_engines()
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

        def on_step(step, turn, max_turns):
            """每完成一步推一条结构化事件给前端。"""
            am = getattr(step, "assistant_message", None)
            text = (am.content if am else "") or ""
            tcs = (am.tool_calls if am else []) or []
            trs = step.tool_responses or []
            # 文本独白（无工具调用），单独存一条
            if text and not tcs:
                task.events.append({
                    "type": "narration", "step": turn, "text": text[:600],
                })
                return
            # 把每个 tool 调用与对应 response 配对
            for tc, tr in zip(tcs, trs):
                ok = not getattr(tr, "is_error", False)
                tr_content = (getattr(tr, "content", "") or "")
                task.events.append({
                    "type": "tool_call", "step": turn,
                    "tool": getattr(tc, "name", "?"),
                    "args": getattr(tc, "arguments", {}) or {},
                    "ok": ok,
                    "result_excerpt": tr_content[:240],
                })

        # 用 web 的 task_id 作为 agent trajectory id，便于事后用 task_id 找轨迹
        ti = TaskInstance(description=task.intent, task_id=f"task-{task.task_id}")
        result = agent.run(ti, on_step=on_step)
        task.status = "done" if result.status == "completed" else "failed"
        finish_payload = result.finish_payload or {}
        # 若 Agent 未显式调 finish，至少提取最后一条 assistant_message 的 content 作为总结
        fallback_summary = ""
        if not finish_payload.get("summary") and result.steps:
            for s in reversed(result.steps):
                am = getattr(s, "assistant_message", None)
                content = (am.content if am else "") or ""
                if content.strip():
                    fallback_summary = content.strip()[:600]
                    break
        task.result = {
            "agent_status": result.status,
            "summary": finish_payload.get("summary") or fallback_summary,
            "key_results": finish_payload.get("key_results", {}),
            "n_steps": len(result.steps),
            "trajectory_path": f"runs/task-{task.task_id}/trajectory.json",
            "no_finish_payload": not bool(finish_payload),
        }
    except Exception as exc:
        logger.exception("Web agent task %s failed", task.task_id)
        task.status = "failed"
        task.result = {"error": f"{type(exc).__name__}: {exc}"}


# ══════════════════════════════════════════════════════════════════════════════
# Default index HTML (served when static/index.html missing)
# ══════════════════════════════════════════════════════════════════════════════


_SKILL_DESC = {
    "conformer": "构象搜索",
    "dlpno-ccsdt": "DLPNO-CCSD(T) 高精度单点",
    "opt-freq": "几何优化 + 频率",
    "pes-scan": "势能面扫描",
    "pka": "酸碱解离常数",
    "soc": "自旋–轨道耦合矩阵元",
    "solvation": "溶剂模型计算",
    "tadf-pipeline": "TADF 发光体表征流水线",
    "tddft": "TDDFT 激发态",
    "ts-search": "过渡态搜索",
}

_ENGINE_DESC = {
    "g16": "Gaussian 16（商业，常用主线软件）",
    "g09": "Gaussian 09（商业）",
    "bdf": "BDF（北大刘文剑组，相对论 / SOC）",
    "momap": "MOMAP（清华帅志刚组，TVCF 速率）",
    "psi4": "psi4（开源量子化学，本机已装）",
    "orca": "ORCA（学术免费）",
    "xtb": "xTB（半经验快速预筛）",
}

_DEFAULT_INDEX_HTML = """\
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ChemMaster · 计算化学省力小帮手</title>
<!-- marked.js: 把 Agent 输出的 markdown 文本渲染成正常排版（CDN 单文件 ~30KB） -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Segoe UI", sans-serif;
         margin: 0; background: #f5f5f7; color: #222; }
  header { background: #1d1d1f; color: #fff; padding: 12px 24px;
           display: flex; align-items: center; justify-content: space-between;
           gap: 12px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 17px; font-weight: 500; }
  header .badge { font-size: 11px; opacity: 0.7; margin-left: 8px;
                  font-weight: 400; }
  header button.help { background: rgba(255,255,255,0.12); color: #fff;
                       border: 1px solid rgba(255,255,255,0.3); border-radius: 6px;
                       padding: 4px 12px; font-size: 13px; cursor: pointer; }
  header button.help:hover { background: rgba(255,255,255,0.22); }
  main { display: grid; grid-template-columns: 2fr 1fr; gap: 16px;
         padding: 16px; max-width: 1300px; margin: 0 auto; }
  .panel { background: #fff; border-radius: 8px; padding: 16px;
           box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  #chat { height: 60vh; overflow-y: auto; border: 1px solid #e5e5ea;
          border-radius: 6px; padding: 12px; background: #fafafa;
          font-family: ui-monospace, SFMono-Regular, monospace; font-size: 13px;
          white-space: pre-wrap; }
  #chat .me  { color: #0066cc; font-weight: 600; margin: 4px 0; }
  #chat .out { color: #333; margin: 4px 0; }
  #chat .ok  { color: #1a7f37; margin: 4px 0; }
  #chat .err { color: #cf222e; background: #fff5f5;
               border-left: 3px solid #cf222e; padding: 6px 10px;
               border-radius: 4px; margin: 6px 0; }
  #chat .rec { background: #fff7d4; border-left: 3px solid #f0b232;
               padding: 6px 10px; margin: 6px 0; border-radius: 4px; }
  #chat .conf { background: #f4f4ff; border-left: 3px solid #5b6bf0;
                padding: 6px 10px; margin: 6px 0; border-radius: 4px; }
  #chat .empty { color: #98989d; padding: 12px; text-align: center; }
  #chat .empty .examples { display: flex; flex-direction: column;
                            gap: 6px; margin-top: 12px; }
  #chat .empty .ex { background: #fff; border: 1px solid #d2d2d7;
                      border-radius: 6px; padding: 8px 12px;
                      cursor: pointer; text-align: left;
                      font-family: -apple-system, "PingFang SC", sans-serif;
                      color: #1d1d1f; transition: all 0.15s; }
  #chat .empty .ex:hover { border-color: #0a84ff; background: #f0f7ff; }
  #chat .thinking { color: #6e6e73; font-style: italic; padding: 4px 0; }
  #chat .thinking .dots::after {
    content: ''; animation: dots 1.4s infinite; }
  @keyframes dots {
    0%,20% { content: '.'; } 40% { content: '..'; }
    60%,100% { content: '...'; }
  }
  #cmd { flex: 1; padding: 8px 12px; font-size: 14px;
         border: 1px solid #d2d2d7; border-radius: 6px;
         font-family: -apple-system, "PingFang SC", sans-serif; }
  #cmd:focus { outline: none; border-color: #0a84ff; }
  .small { font-size: 12px; color: #6e6e73; }
  .legend { font-size: 11px; color: #6e6e73; margin-top: 6px; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
          font-size: 11px; margin: 0 6px 4px 0; cursor: help; }
  .pill.ok { background: #d1f4d1; color: #155e0f; }
  .pill.no { background: #fde2e1; color: #8a1c1c; }
  button.btn { background: #0a84ff; color: #fff; border: 0;
               padding: 6px 14px; border-radius: 6px; cursor: pointer;
               font-size: 13px; font-family: inherit; }
  button.btn:hover { background: #0070e0; }
  button.btn:disabled { background: #b0b0b8; cursor: not-allowed; }
  button.alt { background: #e5e5ea; color: #1d1d1f; }
  button.alt:hover { background: #d4d4d8; }
  button.danger { background: #ff453a; color: #fff; }
  button.danger:hover { background: #e0392f; }
  h3 { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
  .skills-list span { display: inline-block; padding: 1px 6px; margin: 2px 3px 2px 0;
                       background: #f0f0f3; border-radius: 4px;
                       font-size: 11px; cursor: help; }
  .bench-row { margin: 4px 0; }
  .bench-tag { display: inline-block; font-size: 10px; padding: 1px 5px;
                border-radius: 3px; margin-left: 4px; }
  .bench-tag.real { background: #d1f4d1; color: #155e0f; }
  .bench-tag.mock { background: #ffeec2; color: #7a4d00; }
  /* 步骤时间线 */
  .timeline { margin: 6px 0; max-height: 280px; overflow-y: auto;
              border: 1px solid #e5e5ea; border-radius: 6px; padding: 6px; }
  .step-row { display: flex; align-items: flex-start; padding: 4px 6px;
              border-radius: 4px; gap: 8px; font-size: 12px; }
  .step-row:hover { background: #f5f5f7; }
  .step-row .idx { color: #98989d; font-family: ui-monospace, monospace;
                   min-width: 22px; text-align: right; }
  .step-row .icon { font-size: 14px; line-height: 1; }
  .step-row .body { flex: 1; min-width: 0; }
  .step-row .tool { font-family: ui-monospace, monospace;
                    color: #1d1d1f; font-weight: 500; }
  .step-row .args { color: #6e6e73; font-size: 11px;
                    overflow: hidden; text-overflow: ellipsis;
                    white-space: nowrap; }
  .step-row .err  { color: #cf222e; font-size: 11px; }
  .step-row.ok    { background: rgba(209,244,209,0.3); }
  .step-row.fail  { background: rgba(253,226,225,0.3); }
  .step-row.narr  { background: #f9f9fb; }
  /* 工具参数表格（confirm 卡片内） */
  .param-table { margin: 6px 0; width: 100%; border-collapse: collapse;
                 font-family: ui-monospace, SFMono-Regular, monospace;
                 font-size: 11px; }
  .param-table td { padding: 3px 6px; vertical-align: top;
                    border-bottom: 1px solid #ececef; }
  .param-table td:first-child { color: #6e6e73; width: 110px;
                                 white-space: nowrap; font-weight: 500; }
  .param-table td:last-child { color: #1d1d1f; word-break: break-all; }
  .geom-block { background: #f5f5f7; border-radius: 4px;
                padding: 6px 8px; margin: 4px 0;
                white-space: pre; font-family: ui-monospace, monospace;
                font-size: 11px; max-height: 140px; overflow: auto; }
  details.collapsible summary { cursor: pointer; color: #0a84ff;
                                font-size: 11px; padding: 2px 0; }
  details.collapsible[open] summary { font-weight: 500; }
  /* 关键结果表格（任务结束） */
  .key-table { width: 100%; border-collapse: collapse; margin: 6px 0;
               font-size: 12px; background: #fff; border-radius: 6px;
               overflow: hidden; box-shadow: 0 0 0 1px #e5e5ea; }
  .key-table th, .key-table td { padding: 6px 10px; text-align: left;
                                  border-bottom: 1px solid #ececef; }
  .key-table th { background: #f5f5f7; color: #6e6e73; font-weight: 500;
                   font-size: 11px; text-transform: uppercase;
                   letter-spacing: 0.04em; }
  .key-table tr:last-child td { border-bottom: 0; }
  .key-table td.num { font-family: ui-monospace, monospace;
                      color: #1a7f37; font-weight: 500; }
  /* 摘要面板（带 markdown 渲染） */
  .md-summary { background: #fff; border: 1px solid #d1f4d1;
                border-left: 4px solid #1a7f37; border-radius: 6px;
                padding: 12px 14px; margin: 6px 0;
                font-family: -apple-system, "PingFang SC", sans-serif;
                font-size: 13px; line-height: 1.6; white-space: normal; }
  .md-summary h1, .md-summary h2, .md-summary h3 {
                margin: 8px 0 4px; font-size: 14px; }
  .md-summary p { margin: 4px 0; }
  .md-summary code { background: #f0f0f3; padding: 1px 5px;
                     border-radius: 3px; font-size: 12px; }
  .md-summary strong { color: #1a7f37; }
  .md-summary ul, .md-summary ol { margin: 4px 0 4px 20px; padding: 0; }
  .summary-meta { color: #6e6e73; font-size: 11px;
                  margin-top: 8px; padding-top: 6px;
                  border-top: 1px dashed #e5e5ea; }
  /* 帮助浮层 */
  .modal-bg { display: none; position: fixed; inset: 0;
              background: rgba(0,0,0,0.4); z-index: 100;
              align-items: center; justify-content: center; padding: 20px; }
  .modal-bg.show { display: flex; }
  .modal { background: #fff; border-radius: 10px; padding: 24px;
           max-width: 540px; width: 100%; max-height: 85vh; overflow-y: auto; }
  .modal h2 { margin: 0 0 12px; font-size: 18px; }
  .modal h4 { margin: 14px 0 4px; font-size: 13px; color: #1d1d1f; }
  .modal p, .modal li { font-size: 13px; line-height: 1.6; color: #333; }
  .modal code { background: #f0f0f3; padding: 1px 6px; border-radius: 3px;
                font-size: 12px; }
  .modal .close { float: right; background: none; border: 0;
                   font-size: 22px; cursor: pointer; color: #6e6e73;
                   margin: -4px -4px 0 0; }
  /* 移动端响应式 */
  @media (max-width: 768px) {
    main { grid-template-columns: 1fr; padding: 10px; gap: 10px; }
    header { padding: 10px 14px; }
    header h1 { font-size: 15px; }
    header .badge { display: none; }
    #chat { height: 50vh; font-size: 12px; }
    .panel { padding: 12px; }
    .pill { font-size: 10px; padding: 2px 7px; }
  }
  @media (max-width: 420px) {
    header h1 { font-size: 14px; }
  }
</style>
</head>
<body>
<header>
  <h1>ChemMaster <span class="badge">计算化学省力小帮手</span></h1>
  <button class="help" onclick="document.getElementById('helpModal').classList.add('show')">使用说明</button>
</header>
<main>
  <section class="panel">
    <h3>对话</h3>
    <div id="chat"></div>
    <div style="margin-top:10px; display:flex; gap:8px;">
      <input id="cmd" placeholder="用一句中文/英文描述你想算什么，例如：算一下水二聚体在 B3LYP-D3/def2-SVP 下的结合能"/>
      <button class="btn" id="sendBtn" onclick="submitTask()">发送</button>
    </div>
  </section>
  <aside>
    <div class="panel">
      <h3>计算引擎</h3>
      <div id="engines" class="small">检测中…</div>
      <div class="legend">🟢 已安装可用 ／ 🔴 未在本机检测到（鼠标悬停可看说明）</div>
    </div>
    <div class="panel" style="margin-top:12px">
      <h3>技能（Skills）</h3>
      <div id="skills" class="small skills-list">加载中…</div>
      <div class="legend">每个 Skill 是一份方法学 playbook，鼠标悬停可看用途。</div>
    </div>
    <div class="panel" style="margin-top:12px">
      <h3>当前任务</h3>
      <div id="active" class="small">（空闲中）</div>
    </div>
    <div class="panel" style="margin-top:12px">
      <h3>基准数据快照</h3>
      <div id="bench" class="small">加载中…</div>
      <div class="legend">数据按仓库 summary.json 实时聚合。</div>
    </div>
  </aside>
</main>

<div class="modal-bg" id="helpModal" onclick="if(event.target===this) this.classList.remove('show')">
  <div class="modal">
    <button class="close" onclick="document.getElementById('helpModal').classList.remove('show')">×</button>
    <h2>使用说明</h2>
    <p><b>ChemMaster</b> 是一个本地运行、由大语言模型驱动的计算化学 Agent。
    你用一句自然语言描述要算什么，系统自动调度 psi4 / Gaussian 等本机已安装的计算软件完成全流程。</p>

    <h4>📥 第一次使用</h4>
    <ul>
      <li>右侧「计算引擎」会自动列出本机可用的引擎，绿色 = 已装、红色 = 未装。</li>
      <li>右侧「技能」是 Agent 可参考的方法学 playbook 列表，鼠标悬停看用途。</li>
      <li>本机 <code>~/.chemaster/</code> 下放一份 LLM API key（已支持 Anthropic、MiniMax、DeepSeek、Qwen）。</li>
    </ul>

    <h4>🚀 提交任务</h4>
    <ol>
      <li>在底部输入框用中文/英文描述意图。</li>
      <li>点「发送」或回车。</li>
      <li>Agent 会逐步调度工具，在对话区显示推荐卡片或确认卡片，由你接受/修改/取消。</li>
      <li>任务执行中可点「取消任务」中断。</li>
    </ol>

    <h4>💡 推荐先试这几个</h4>
    <ul>
      <li><code>算一下水分子的能量</code></li>
      <li><code>算一下水二聚体在 B3LYP-D3/def2-SVP 下的结合能</code></li>
      <li><code>对苯分子做几何优化和频率计算</code></li>
    </ul>

    <h4>🛡️ 数据/隐私</h4>
    <p>所有计算和大模型对话都在本机进行（API 走你提供的 key）。分子结构不会自动上传到任何云端。
    运行轨迹存放在 <code>./runs/&lt;task_id&gt;/</code>。</p>

    <h4>📚 更多</h4>
    <p>详细文档见仓库的 <code>docs/USER_GUIDE.md</code>，或访问
    <a href="https://github.com/Keith9922/chemaster" target="_blank">GitHub</a>。</p>
  </div>
</div>

<script>
let currentTask = null;
let pollTimer = null;
let stepCount = 0;
const chat = document.getElementById("chat");
const cmd  = document.getElementById("cmd");
const sendBtn = document.getElementById("sendBtn");
const activeEl = document.getElementById("active");

const EXAMPLES = [
  "算一下水分子的能量",
  "算一下水二聚体在 B3LYP-D3/def2-SVP 下的结合能",
  "对苯分子做几何优化和频率计算",
];

function renderEmpty() {
  chat.innerHTML = `
    <div class="empty">
      <div>👋 你好！这里是 ChemMaster 对话区。</div>
      <div style="margin-top:6px">用一句话告诉我要算什么，下面是几个例子，点击直接试：</div>
      <div class="examples"></div>
    </div>`;
  const exDiv = chat.querySelector(".examples");
  EXAMPLES.forEach(t => {
    const b = document.createElement("button");
    b.className = "ex"; b.textContent = "💬 " + t;
    b.onclick = () => { cmd.value = t; submitTask(); };
    exDiv.appendChild(b);
  });
}

function clearEmpty() {
  const e = chat.querySelector(".empty");
  if (e) e.remove();
}

function append(html, cls="out") {
  clearEmpty();
  const div = document.createElement("div");
  div.className = cls;
  div.innerHTML = html;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

let thinkingEl = null;
function showThinking(text) {
  if (thinkingEl) thinkingEl.remove();
  thinkingEl = append(`<span class="thinking">⏳ ${text}<span class="dots"></span></span>`);
}
function clearThinking() {
  if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
}

cmd.addEventListener("keydown", e => {
  if (e.key === "Enter") submitTask();
});

async function submitTask() {
  const text = cmd.value.trim();
  if (!text) return;
  if (currentTask) {
    append(`<span class="err">⚠️ 当前任务还在跑，请等任务完成或先取消。</span>`);
    return;
  }
  cmd.value = "";
  sendBtn.disabled = true; sendBtn.textContent = "处理中…";
  append(`<span class="me">&gt; ${escapeHtml(text)}</span>`);
  showThinking("正在提交任务到 Agent");
  stepCount = 0;
  try {
    const r = await fetch("/api/run", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({intent: text})});
    if (!r.ok) {
      const errText = await r.text();
      clearThinking();
      append(`<span class="err">✗ 提交失败 (HTTP ${r.status})：${escapeHtml(errText.slice(0,200))}</span>`);
      sendBtn.disabled = false; sendBtn.textContent = "发送";
      return;
    }
    const data = await r.json();
    currentTask = data.task_id;
    renderActive();
    showThinking("Agent 正在思考与调度工具，预计需 30 秒到几分钟…");
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollTask, 1500);
  } catch (err) {
    clearThinking();
    append(`<span class="err">✗ 网络异常：${escapeHtml(String(err))}</span>`);
    sendBtn.disabled = false; sendBtn.textContent = "发送";
  }
}

function renderActive() {
  if (!currentTask) {
    activeEl.innerHTML = "（空闲中）";
    return;
  }
  activeEl.innerHTML = `
    <div>任务 <code>${currentTask}</code> <span style="color:#1a7f37">·运行中</span></div>
    <div id="timeline" class="timeline"><div class="small" style="color:#98989d">等待第一个事件…</div></div>
    <button class="btn danger" style="margin-top:8px;font-size:11px;padding:4px 10px"
       onclick="cancelTask()">取消任务</button>`;
}

function summarizeArgs(args) {
  if (!args || typeof args !== "object") return "";
  const keys = Object.keys(args);
  if (keys.length === 0) return "";
  // 优先显示几个关键字段
  const priority = ["method", "basis", "tool", "molecule", "value", "from_unit", "to_unit", "name"];
  const parts = [];
  priority.forEach(k => {
    if (k in args && args[k] != null) parts.push(`${k}=${args[k]}`);
  });
  // 几何块单独标注
  if ("geometry_xyz" in args) {
    const lines = String(args.geometry_xyz).split("\\n");
    parts.push(`geometry: ${lines[0]?.trim() || "?"} 原子`);
  }
  // 其余字段计数
  const shown = new Set([...priority, "geometry_xyz"]);
  const rest = keys.filter(k => !shown.has(k));
  if (rest.length) parts.push(`+${rest.length} 项`);
  return parts.slice(0, 3).join("  ");
}

function renderTimeline(events) {
  const tl = document.getElementById("timeline");
  if (!tl) return;
  if (!events.length) {
    tl.innerHTML = `<div class="small" style="color:#98989d">等待第一个事件…</div>`;
    return;
  }
  const html = events.map((ev, i) => {
    const idx = `<span class="idx">${i + 1}.</span>`;
    if (ev.type === "narration") {
      return `<div class="step-row narr">${idx}
        <span class="icon">💭</span>
        <div class="body"><div class="args">${escapeHtml(ev.text || "")}</div></div></div>`;
    }
    if (ev.type === "tool_call") {
      const cls = ev.ok ? "ok" : "fail";
      const icon = ev.ok ? "✓" : "✗";
      const argsTxt = summarizeArgs(ev.args);
      const errTxt = (!ev.ok && ev.result_excerpt)
        ? `<div class="err">${escapeHtml(ev.result_excerpt.split("\\n")[0])}</div>` : "";
      return `<div class="step-row ${cls}">${idx}
        <span class="icon" style="color:${ev.ok ? '#1a7f37' : '#cf222e'}">${icon}</span>
        <div class="body">
          <div class="tool">${escapeHtml(ev.tool || "?")}</div>
          ${argsTxt ? `<div class="args">${escapeHtml(argsTxt)}</div>` : ""}
          ${errTxt}
        </div></div>`;
    }
    if (ev.type === "confirm") {
      return `<div class="step-row">${idx}
        <span class="icon">🔵</span>
        <div class="body"><div class="tool">${escapeHtml(ev.tool || "?")}</div>
        <div class="args">等待用户确认</div></div></div>`;
    }
    if (ev.type === "recommend") {
      return `<div class="step-row">${idx}
        <span class="icon">🟡</span>
        <div class="body"><div class="tool">化学决策推荐</div>
        <div class="args">${escapeHtml(ev.decision || "")}</div></div></div>`;
    }
    return "";
  }).join("");
  tl.innerHTML = html;
  tl.scrollTop = tl.scrollHeight;
}

function cancelTask() {
  if (!currentTask) return;
  if (!confirm("确定要取消当前任务吗？已经跑出的中间结果不会丢失，但 Agent 将停止后续步骤。")) return;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  append(`<span class="err">⛔ 已取消任务（前端停止轮询；后端进程仍会跑完当前 step）</span>`);
  clearThinking();
  currentTask = null;
  renderActive();
  sendBtn.disabled = false; sendBtn.textContent = "发送";
}

async function pollTask() {
  if (!currentTask) return;
  try {
    const r = await fetch(`/api/task/${currentTask}`);
    const data = await r.json();
    if (data.n_events && data.n_events !== stepCount) {
      stepCount = data.n_events;
      // 拉取最新事件列表渲染时间线
      try {
        const ev = await (await fetch(`/api/task/${currentTask}/events`)).json();
        renderTimeline(ev.events || []);
      } catch (e) {}
    }
    if (data.pending_card) renderCard(data.pending_card);
    if (["done","failed"].includes(data.status)) {
      clearInterval(pollTimer); pollTimer = null;
      clearThinking();
      const r = data.result || {};
      if (r.error) {
        append(`<span class="err">✗ 任务失败：${escapeHtml(r.error)}</span>`);
      } else if (r.summary) {
        // 用 marked.js 把 markdown 渲染成正常排版
        const summaryHtml = (typeof marked !== "undefined")
          ? marked.parse(r.summary)
          : `<p>${escapeHtml(r.summary).replace(/\\n/g, "<br>")}</p>`;
        const headLine = r.no_finish_payload
          ? `✓ 任务结束（${r.n_steps||0} 步） · Agent 未显式调用 finish，下方为最后一段陈述`
          : `✓ 任务完成 · 共 ${r.n_steps||0} 步`;
        const traj = r.trajectory_path
          ? `<div class="summary-meta">🗂 完整轨迹存于 <code>${escapeHtml(r.trajectory_path)}</code></div>` : "";
        clearEmpty();
        const div = document.createElement("div");
        div.className = "md-summary";
        div.innerHTML = `<div style="color:#1a7f37;font-weight:600;font-size:12px;margin-bottom:6px">${headLine}</div>${summaryHtml}${traj}`;
        chat.appendChild(div);
        // 关键结果表格化
        if (r.key_results && Object.keys(r.key_results).length) {
          const tbl = document.createElement("table");
          tbl.className = "key-table";
          tbl.innerHTML = `<thead><tr><th>字段</th><th>数值</th></tr></thead>` +
            `<tbody>` +
            Object.entries(r.key_results).map(([k, v]) => {
              const isNum = (typeof v === "number") || /^-?\\d/.test(String(v));
              return `<tr><td>${escapeHtml(k)}</td>` +
                     `<td class="${isNum ? 'num' : ''}">${escapeHtml(String(v))}</td></tr>`;
            }).join("") +
            `</tbody>`;
          chat.appendChild(tbl);
        }
        chat.scrollTop = chat.scrollHeight;
      } else {
        append(`<span class="ok">任务结束，状态：${data.status}（${r.n_steps||0} 步）</span>`);
        if (r.trajectory_path) {
          append(`<span class="small" style="color:#6e6e73">🗂 完整轨迹：<code>${escapeHtml(r.trajectory_path)}</code></span>`);
        }
      }
      currentTask = null;
      renderActive();
      sendBtn.disabled = false; sendBtn.textContent = "发送";
    }
  } catch (err) {
    // 网络抖动忽略
  }
}

function renderParamsTable(args) {
  if (!args || typeof args !== "object" || Object.keys(args).length === 0)
    return "<div class='small' style='color:#98989d'>(无参数)</div>";
  const rows = [];
  for (const [k, v] of Object.entries(args)) {
    if (k === "geometry_xyz") continue;  // 单独渲染
    const display = (typeof v === "object") ? JSON.stringify(v) : String(v);
    rows.push(`<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(display)}</td></tr>`);
  }
  let html = `<table class="param-table"><tbody>${rows.join("")}</tbody></table>`;
  if ("geometry_xyz" in args) {
    const xyz = String(args.geometry_xyz);
    const lines = xyz.split(/\\\\n|\\n/).filter(Boolean);
    const nAtoms = lines[0]?.trim() || "?";
    html += `<details class="collapsible"><summary>geometry: ${escapeHtml(nAtoms)} 原子（点击展开 XYZ 坐标）</summary>` +
            `<div class="geom-block">${escapeHtml(xyz)}</div></details>`;
  }
  return html;
}

function renderCard(card) {
  const cardId = "card_" + currentTask + "_" + stepCount;
  if (document.getElementById(cardId)) return;
  clearThinking();
  const div = document.createElement("div");
  div.id = cardId;
  if (card.mode === "confirm") {
    div.className = "conf";
    const reason = card.reason ? `<span class="small" style="color:#5b6bf0;margin-left:6px">⏱ ${escapeHtml(card.reason)}</span>` : "";
    div.innerHTML = `<b>🔵 需要确认</b>　工具：<code>${escapeHtml(card.tool || '')}</code>${reason}
       ${renderParamsTable(card.args)}
       <div style="margin-top:8px;display:flex;gap:6px">
         <button class="btn" onclick="respond({approved:true})">✓ 同意执行</button>
         <button class="btn alt" onclick="respond({approved:false})">✗ 拒绝</button>
       </div>`;
  } else if (card.mode === "recommend") {
    div.className = "rec";
    div.innerHTML = `<b>🟡 化学决策推荐</b> ${escapeHtml(card.decision || '')}<br>
       推荐方案：<b>${escapeHtml(card.recommendation || '')}</b><br>
       <span class="small">理由：${escapeHtml(card.reasoning || '')}</span><br>
       备选：${(card.alternatives||[]).map(escapeHtml).join(" / ") || "(无)"}
       <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
         <button class="btn" onclick="respond({status:'accept'})">✓ 接受</button>
         <button class="btn alt" onclick="respondModify()">✎ 修改</button>
         <button class="btn alt" onclick="respond({status:'cancel'})">✗ 取消</button>
       </div>`;
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function respond(payload) {
  if (!currentTask) return;
  await fetch(`/api/task/${currentTask}/respond`, {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(payload)});
  showThinking("已记录你的回复，Agent 继续执行");
}

function respondModify() {
  const v = prompt("请输入修改后的方案：");
  if (v) respond({status:"modify", modified_value: v});
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

const ENGINE_DESC = __ENGINE_DESC_JSON__;
const SKILL_DESC = __SKILL_DESC_JSON__;

async function loadStatus() {
  try {
    const e = await (await fetch("/api/engines")).json();
    const html = e.engines.map(x => {
      const tip = ENGINE_DESC[x.name] || x.name;
      const status = x.available ? "已安装于 " + (x.path || "PATH") : "未在本机检测到";
      return `<span class="pill ${x.available?'ok':'no'}" title="${escapeHtml(tip)}（${escapeHtml(status)}）">${x.name}</span>`;
    }).join("");
    document.getElementById("engines").innerHTML = html;
  } catch (err) {}

  try {
    const s = await (await fetch("/api/skills")).json();
    const html = s.skills.length
      ? s.skills.map(name => {
          const tip = SKILL_DESC[name] || name;
          return `<span title="${escapeHtml(tip)}">${escapeHtml(name)}</span>`;
        }).join("")
      : "<span class='small'>(无)</span>";
    document.getElementById("skills").innerHTML = html;
  } catch (err) {}

  try {
    const b = await (await fetch("/api/benchmarks")).json();
    let lines = [];
    if (b.s22) {
      const n = (b.s22.results || []).length;
      const tag = (b.s22.data_source === "real_psi4")
        ? `<span class="bench-tag real">real psi4</span>`
        : `<span class="bench-tag mock">${escapeHtml(b.s22.data_source||'?')}</span>`;
      lines.push(`<div class="bench-row">S22: MAE ${b.s22.mae_kcal} kcal/mol（${n} 体系）${tag}</div>`);
    }
    if (b.quest) {
      const tag = (b.quest.data_source === "real_psi4")
        ? `<span class="bench-tag real">real psi4</span>`
        : `<span class="bench-tag mock">${escapeHtml(b.quest.data_source||'?')}</span>`;
      lines.push(`<div class="bench-row">QUEST: MAE ${b.quest.mae_eV} eV${tag}</div>`);
    }
    if (b.anthracene) {
      const ds = b.anthracene.data_source || '?';
      const k_r = b.anthracene.result?.results?.k_r_s_inv;
      const tag = (ds === "real_psi4" || ds === "real_pyscf")
        ? `<span class="bench-tag real">${escapeHtml(ds)}</span>`
        : `<span class="bench-tag mock">${escapeHtml(ds)}（示例数据）</span>`;
      lines.push(`<div class="bench-row">蒽 (anthracene): k_r ≈ ${k_r ? k_r.toExponential(2) : "?"} s⁻¹${tag}</div>`);
    }
    document.getElementById("bench").innerHTML = lines.join("") || "<span class='small'>(无数据)</span>";
  } catch (err) {}
}

renderEmpty();
loadStatus();
setInterval(loadStatus, 30000);
</script>
</body>
</html>
"""

# 把 Python 端的描述字典编译进 HTML（避免再加一个 API endpoint）
_DEFAULT_INDEX_HTML = (
    _DEFAULT_INDEX_HTML
    .replace("__ENGINE_DESC_JSON__", json.dumps(_ENGINE_DESC, ensure_ascii=False))
    .replace("__SKILL_DESC_JSON__", json.dumps(_SKILL_DESC, ensure_ascii=False))
)


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
