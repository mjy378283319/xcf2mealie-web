"""下厨房 -> Mealie 批量导入 Web UI

一个极简界面：粘贴下厨房链接，点确定，自动抓取 + 估算 + 推送到 Mealie。
"""
import os
import sys
import json
import shutil
import subprocess
import tempfile
from datetime import datetime

from flask import Flask, render_template_string, request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(APP_DIR, "xcf2mealie.py")
DEFAULT_TAG = os.environ.get("DEFAULT_TAG", "下厨房")
PORT = int(os.environ.get("PORT", "9926"))

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>下厨房 → Mealie 批量导入</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{box-sizing:border-box}
  body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;max-width:820px;margin:32px auto;padding:0 16px;color:#222;background:#fafafa;line-height:1.55}
  h1{font-size:22px;margin:0 0 6px}
  .sub{color:#666;font-size:13px;margin-bottom:24px}
  .card{background:#fff;border:1px solid #eaeaea;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
  .row{margin:14px 0}
  label{font-size:13px;color:#444;display:block;margin-bottom:6px;font-weight:500}
  textarea,input[type=text],input[type=password]{width:100%;padding:10px;border:1px solid #d0d0d0;border-radius:6px;font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;background:#fff;color:#222}
  textarea{min-height:200px;resize:vertical}
  .btn{background:#1677ff;color:#fff;border:0;padding:11px 28px;border-radius:6px;font-size:15px;cursor:pointer;font-weight:600;letter-spacing:.5px}
  .btn:hover:not(:disabled){background:#0958d9}
  .btn:disabled{background:#999;cursor:not-allowed}
  .note{background:#fff7e6;border:1px solid #ffd591;padding:12px 14px;border-radius:6px;font-size:13px;color:#874d00;margin-bottom:16px}
  .ok{background:#f6ffed;border:1px solid #b7eb8f;padding:12px 14px;border-radius:6px;font-size:13px;color:#237804;margin-bottom:16px}
  .meta{color:#888;font-size:12px;margin-top:8px}
  small.hint{color:#888;font-weight:400}
  a{color:#1677ff;text-decoration:none}
  a:hover{text-decoration:underline}
</style>
</head>
<body>
<h1>🍜 下厨房 → Mealie 批量导入</h1>
<div class="sub">粘贴下厨房菜谱链接，每行一个，点确定即可批量抓取并导入到你的 Mealie。</div>

{% if has_token %}
<div class="ok">✓ 已从容器环境变量读取到 Mealie Token（无需在下方粘贴，更安全）</div>
{% else %}
<div class="note">⚠️ 容器未设置 <code>MEALIE_TOKEN</code> 环境变量，请在下方粘贴你的 Mealie API Token（仅本次使用，不落盘）。<br>建议改为在 Unraid 容器环境变量里设置 <code>MEALIE_TOKEN</code>。</div>
{% endif %}

<form method="post" action="/import">
  <div class="card">
    <div class="row">
      <label>下厨房链接 <small class="hint">（每行一个，例如 <code>https://www.xiachufang.com/recipe/12345/</code>）</small></label>
      <textarea name="links" placeholder="https://www.xiachufang.com/recipe/104133214/
https://www.xiachufang.com/recipe/106679017/
https://www.xiachufang.com/recipe/106963831/" required></textarea>
    </div>
    <div class="row">
      <label>追加标签 <small class="hint">（每个菜谱都会打上，可留空用默认「下厨房」）</small></label>
      <input type="text" name="tag" value="{{ default_tag }}">
    </div>
    {% if not has_token %}
    <div class="row">
      <label>Mealie API Token <small class="hint">（粘贴自 Mealie「用户设置 → API Tokens → Long Lived Token」）</small></label>
      <input type="password" name="token" placeholder="eyJhbGciOi...">
    </div>
    {% endif %}
    <div class="row">
      <button type="submit" class="btn" id="submitBtn">确定导入</button>
      <span class="meta" style="margin-left:12px">预计耗时 1-3 分钟/菜谱（取决于网速与步骤图数量）</span>
    </div>
  </div>
  <div class="meta">
    目标 Mealie：<code>{{ mealie_url or '未设置 MEALIE_URL 环境变量' }}</code>
  </div>
</form>

<script>
  document.querySelector('form').addEventListener('submit', function(){
    var b = document.getElementById('submitBtn');
    b.disabled = true;
    b.textContent = '导入中，请稍候（约 1-3 分钟）…';
    setTimeout(function(){ b.textContent = '仍在处理…请勿关闭页面'; }, 30000);
  });
</script>
</body>
</html>
"""

RESULT_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>CLEAN</title>
</head>
<body>clean</body>
</html>
"""

app = Flask(__name__)


def run_cmd(cmd, cwd=None, timeout=None):
    """Run a subprocess, return (returncode, stdout, stderr, started_at, ended_at)."""
    started = datetime.now().strftime("%H:%M:%S")
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd or APP_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr, started, datetime.now().strftime("%H:%M:%S")
    except subprocess.TimeoutExpired as e:
        return -1, (e.stdout or ""), (e.stderr or "") + "\n[TIMEOUT]", started, datetime.now().strftime("%H:%M:%S")


def parse_links(text):
    links = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        links.append(line)
    # 去重保序
    seen = set()
    deduped = []
    for u in links:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


@app.route("/", methods=["GET"])
def index():
    return render_template_string(
        INDEX_HTML,
        mealie_url=os.environ.get("MEALIE_URL", ""),
        has_token=bool(os.environ.get("MEALIE_TOKEN")),
        default_tag=DEFAULT_TAG,
        version=datetime.now().strftime("%Y-%m-%d"),
    )


@app.route("/import", methods=["POST"])
def do_import():
    raw = request.form.get("links", "")
    token_override = (request.form.get("token") or "").strip()
    tag = (request.form.get("tag") or DEFAULT_TAG).strip() or DEFAULT_TAG
    mealie_url = (os.environ.get("MEALIE_URL") or "").rstrip("/")
    token = token_override or os.environ.get("MEALIE_TOKEN", "")

    if not mealie_url:
        return render_template_string(RESULT_HTML, error="容器未设置 MEALIE_URL 环境变量，无法导入。", results=[])
    if not token:
        return render_template_string(RESULT_HTML, error="缺少 Mealie API Token：请在容器环境变量 MEALIE_TOKEN 设置，或在表单里粘贴。", results=[])

    links = parse_links(raw)
    if not links:
        return render_template_string(RESULT_HTML, error="请粘贴至少一个下厨房菜谱链接（每行一个）。", results=[])

    results = []
    work = tempfile.mkdtemp(prefix="xcf_")
    try:
        urls_file = os.path.join(work, "urls.txt")
        with open(urls_file, "w", encoding="utf-8") as f:
            f.write("\n".join(links))
        out_dir = os.path.join(work, "data")
        os.makedirs(out_dir, exist_ok=True)

        # Step 1: fetch + estimate
        fetch_cmd = [sys.executable, SCRIPT, "fetch", "--file", urls_file, "--out", out_dir, "--estimate"]
        rc, so, se, t0, t1 = run_cmd(fetch_cmd, timeout=900)
        results.append({
            "step": "fetch + estimate",
            "cmd": " ".join(fetch_cmd),
            "returncode": rc,
            "stdout": so,
            "stderr": se,
            "time": f"{t0} -> {t1}",
        })
        if rc != 0:
            return render_template_string(RESULT_HTML, error="fetch 阶段失败，未进行 push。", results=results, count=len(links))

        # Step 2: push
        push_cmd = [sys.executable, SCRIPT, "push", out_dir, "--mealie", mealie_url, "--token", token, "--tag", tag]
        rc, so, se, t0, t1 = run_cmd(push_cmd, timeout=1800)
        results.append({
            "step": "push to Mealie",
            "cmd": " ".join(push_cmd).replace(token, "***TOKEN***"),
            "returncode": rc,
            "stdout": so,
            "stderr": se,
            "time": f"{t0} -> {t1}",
        })

        ok = results[-1]["returncode"] == 0
        return render_template(
            "result.html",
            error=None if ok else "push 阶段失败，请查看下方输出。",
            results=results,
            count=len(links),
            ok=ok,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    print(f"[xcf2mealie-web] 启动：http://0.0.0.0:{PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)
