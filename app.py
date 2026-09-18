"""下厨房 -> Mealie 批量导入 Web UI

一个极简界面：粘贴下厨房链接，点确定，自动抓取 + 估算 + 推送到 Mealie。

环境变量：
  MEALIE_URL      Mealie 地址（必填）
  MEALIE_TOKEN    Mealie API Token（可选，不在容器配也能在表单里临时粘）
  DEFAULT_TAG     默认追加标签，默认「下厨房」
  PORT            监听端口，默认 9926
  WEB_USER        登录用户名（与 WEB_PASSWORD 同时设置才启用登录页）
  WEB_PASSWORD    登录密码（登录页形式，非浏览器原生弹框，便于 Bitwarden 自动填充）
  SECRET_KEY      会话签名密钥（可选；不设则每次重启要重新登录）
"""
import os
import sys
import time
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta

from flask import Flask, render_template_string, redirect, request, session, url_for

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(APP_DIR, "xcf2mealie.py")
DEFAULT_TAG = os.environ.get("DEFAULT_TAG", "下厨房")
PORT = int(os.environ.get("PORT", "9926"))

# 登录凭据：两个都非空才启用登录页；WEB_PASS 作为 WEB_PASSWORD 的别名
WEB_USER = (os.environ.get("WEB_USER") or "").strip()
WEB_PASS = (os.environ.get("WEB_PASSWORD") or os.environ.get("WEB_PASS") or "")
AUTH_ENABLED = bool(WEB_USER and WEB_PASS)

# 会话签名密钥：未显式设置则随机生成（代价是容器重启后需要重新登录）
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

# --------------------------------------------------------------------------- #
# 页面模板（内联，避免依赖 templates 目录）
# --------------------------------------------------------------------------- #

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
  .chk{border:1px solid #e8e8e8;background:#fcfcfc;border-radius:6px;padding:11px 13px;font-size:13px;color:#333;display:block;margin:6px 0}
  .chk input{margin-right:8px;vertical-align:middle}
  .chk small{color:#888;display:block;margin:4px 0 0 22px;font-weight:400}
  .btn{background:#1677ff;color:#fff;border:0;padding:11px 28px;border-radius:6px;font-size:15px;cursor:pointer;font-weight:600;letter-spacing:.5px}
  .btn:hover:not(:disabled){background:#0958d9}
  .btn:disabled{background:#999;cursor:not-allowed}
  .note{background:#fff7e6;border:1px solid #ffd591;padding:12px 14px;border-radius:6px;font-size:13px;color:#874d00;margin-bottom:16px}
  .ok{background:#f6ffed;border:1px solid #b7eb8f;padding:12px 14px;border-radius:6px;font-size:13px;color:#237804;margin-bottom:16px}
  .topbar{display:flex;justify-content:space-between;align-items:center;background:#f6ffed;border:1px solid #b7eb8f;color:#237804;border-radius:6px;padding:9px 14px;font-size:13px;margin-bottom:16px}
  .topbar b{color:#237804}
  .topbar .logout{color:#1677ff;font-size:13px;font-weight:500}
  .meta{color:#888;font-size:12px;margin-top:8px}
  small.hint{color:#888;font-weight:400}
  code{background:#f2f2f2;padding:1px 5px;border-radius:3px;font-size:12px}
</style>
</head>
<body>
<h1>下厨房 → Mealie 批量导入</h1>
<div class="sub">粘贴下厨房菜谱链接，每行一个，点确定即可批量抓取并导入到你的 Mealie。</div>

{% if auth_enabled %}
<div class="topbar">
  <span class="who">已登录：<b>{{ current_user }}</b></span>
  <a class="logout" href="/logout">退出登录</a>
</div>
{% else %}
<div class="note">当前<b>未启用登录</b>：任何人都能访问本页面。建议在容器里设置 <code>WEB_USER</code> 与 <code>WEB_PASSWORD</code> 两个环境变量后再重启容器。</div>
{% endif %}

{% if has_token %}
<div class="ok">已从容器环境变量读取到 Mealie Token（无需在下方粘贴，更安全）</div>
{% else %}
<div class="note">容器未设置 <code>MEALIE_TOKEN</code> 环境变量，请在下方粘贴你的 Mealie API Token（仅本次使用，不落盘）。<br>建议改为在容器环境变量里设置 <code>MEALIE_TOKEN</code>。</div>
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
      <label class="chk">
        <input type="checkbox" name="skip_existing" value="1" checked>
        跳过 Mealie 中已存在的菜谱
        <small>按「源链接 + 菜名」比对，已导入的会直接跳过，不会重复添加。取消勾选则强制重新导入（会产生重复条目）。</small>
      </label>
    </div>
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
<title>导入结果 · 下厨房 → Mealie</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{box-sizing:border-box}
  body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;max-width:900px;margin:32px auto;padding:0 16px;color:#222;background:#fafafa;line-height:1.55}
  h1{font-size:22px;margin:0 0 18px}
  .banner{padding:14px 16px;border-radius:8px;font-size:14px;font-weight:600;margin-bottom:18px}
  .banner.ok{background:#f6ffed;border:1px solid #b7eb8f;color:#237804}
  .banner.bad{background:#fff2f0;border:1px solid #ffccc7;color:#a8071a}
  .stage{background:#fff;border:1px solid #eaeaea;border-radius:8px;padding:16px;margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
  .stage h2{font-size:15px;margin:0 0 4px}
  .stage .cmd{color:#888;font-size:12px;margin-bottom:10px;word-break:break-all}
  .badge{display:inline-block;font-size:12px;padding:2px 9px;border-radius:20px;vertical-align:middle;margin-left:8px;font-weight:600}
  .badge.pass{background:#f6ffed;color:#389e0d;border:1px solid #b7eb8f}
  .badge.fail{background:#fff2f0;color:#cf1322;border:1px solid #ffccc7}
  pre{background:#1f1f1f;color:#e8e8e8;padding:14px;border-radius:6px;overflow-x:auto;font:12.5px/1.6 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all;margin:0}
  pre.err{background:#3a1414;color:#ffd7d5}
  .actions{margin-top:20px}
  .btn{display:inline-block;background:#1677ff;color:#fff;text-decoration:none;padding:10px 22px;border-radius:6px;font-size:14px;font-weight:600}
  .btn:hover{background:#0958d9}
</style>
</head>
<body>
<h1>导入结果</h1>

{% if ok %}
<div class="banner ok">导入完成 · 共提交 {{ count }} 个链接</div>
{% else %}
<div class="banner bad">导入未完成 · 共提交 {{ count }} 个链接{% if error %}：{{ error }}{% endif %}</div>
{% endif %}

{% for r in results %}
<div class="stage">
  <h2>{{ r.step }}<span class="badge {{ 'pass' if r.returncode == 0 else 'fail' }}">{{ '成功' if r.returncode == 0 else '失败 rc=' ~ r.returncode }}</span></h2>
  <div class="cmd">{{ r.cmd }}<br>耗时 {{ r.time }}</div>
  {% if r.stdout %}<pre>{{ r.stdout }}</pre>{% endif %}
  {% if r.stderr %}<pre class="err">{{ r.stderr }}</pre>{% endif %}
</div>
{% endfor %}

<div class="actions">
  <a class="btn" href="/">返回继续导入</a>
</div>
</body>
</html>
"""

# --------------------------------------------------------------------------- #
# 独立登录页 + Flask Session 鉴权
#
#   刻意不用 HTTP Basic Auth：浏览器原生的那种登录弹框，Bitwarden 经常识别不到、
#   不会提示填充。改用标准 HTML 表单（autocomplete="username" / "current-password"），
#   密码管理器才能正常抓取字段并自动填充。
# --------------------------------------------------------------------------- #

LOGIN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>登录 · 下厨房 → Mealie</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{box-sizing:border-box}
  body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;background:#fafafa;color:#222;margin:0;padding:48px 16px;line-height:1.55}
  .login-card{background:#fff;border:1px solid #eaeaea;border-radius:10px;max-width:380px;margin:0 auto;padding:28px 26px;box-shadow:0 2px 8px rgba(0,0,0,.05)}
  h1{font-size:19px;margin:0 0 4px}
  .sub{color:#777;font-size:13px;margin-bottom:20px}
  label{display:block;font-size:13px;color:#444;margin:0 0 6px;font-weight:500}
  .row{margin-bottom:16px}
  input[type=text],input[type=password]{width:100%;padding:11px 12px;border:1px solid #d0d0d0;border-radius:6px;font-size:14px;background:#fff;color:#222}
  input[type=text]:focus,input[type=password]:focus{outline:none;border-color:#1677ff;box-shadow:0 0 0 3px rgba(22,119,255,.12)}
  .btn{background:#1677ff;color:#fff;border:0;padding:11px 0;width:100%;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;letter-spacing:.5px}
  .btn:hover{background:#0958d9}
  .banner.bad{background:#fff2f0;border:1px solid #ffccc7;color:#a8071a;padding:10px 13px;border-radius:6px;font-size:13px;margin-bottom:16px}
  .tip{margin-top:18px;padding-top:14px;border-top:1px solid #f0f0f0;color:#999;font-size:12px;text-align:center}
</style>
</head>
<body>
<div class="login-card">
  <h1>下厨房 → Mealie</h1>
  <div class="sub">请输入账号后继续使用</div>

  {% if error %}<div class="banner bad">{{ error }}</div>{% endif %}

  <form method="post" action="/login">
    <input type="hidden" name="next" value="{{ next }}">
    <div class="row">
      <label for="username">用户名</label>
      <input type="text" id="username" name="username" autocomplete="username"
             autocapitalize="off" spellcheck="false" required autofocus>
    </div>
    <div class="row">
      <label for="password">密码</label>
      <input type="password" id="password" name="password" autocomplete="current-password" required>
    </div>
    <button type="submit" class="btn">登 录</button>
  </form>

  <div class="tip">支持 Bitwarden / 浏览器密码管理器自动填充</div>
</div>
</body>
</html>
"""

def _authorized(u: str, p: str) -> bool:
    if not AUTH_ENABLED:
        return True
    return (secrets.compare_digest(u or "", WEB_USER)
            and secrets.compare_digest(p or "", WEB_PASS))


@app.before_request
def _require_auth():
    if not AUTH_ENABLED:
        return None
    if request.endpoint in ("login", "logout", "static"):
        return None
    if session.get("authed"):
        return None
    target = request.full_path if request.query_string else request.path
    return redirect(url_for("login", next=target))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not AUTH_ENABLED:
        return redirect(url_for("index"))
    if session.get("authed"):
        return redirect(url_for("index"))

    nxt = request.args.get("next") or request.form.get("next") or url_for("index")
    error = None

    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        if _authorized(u, p):
            session.permanent = True
            session["authed"] = True
            session["user"] = u
            return redirect(nxt)
        time.sleep(1.2)          # 简单限速，别让人暴力试密码
        error = "用户名或密码错误"

    return render_template_string(LOGIN_HTML, error=error, next=nxt)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #

@app.route("/", methods=["GET"])
def index():
    return render_template_string(
        INDEX_HTML,
        mealie_url=os.environ.get("MEALIE_URL", ""),
        has_token=bool(os.environ.get("MEALIE_TOKEN")),
        default_tag=DEFAULT_TAG,
        auth_enabled=AUTH_ENABLED,
        current_user=session.get("user") or WEB_USER or "-",
    )


@app.route("/import", methods=["POST"])
def do_import():
    raw = request.form.get("links", "")
    token_override = (request.form.get("token") or "").strip()
    tag = (request.form.get("tag") or DEFAULT_TAG).strip() or DEFAULT_TAG
    skip_existing = request.form.get("skip_existing") == "1"
    mealie_url = (os.environ.get("MEALIE_URL") or "").rstrip("/")
    token = token_override or os.environ.get("MEALIE_TOKEN", "")

    links = parse_links(raw)

    if not mealie_url:
        return render_template_string(
            RESULT_HTML, ok=False, count=len(links), results=[],
            error="容器未设置 MEALIE_URL 环境变量，无法导入。")
    if not token:
        return render_template_string(
            RESULT_HTML, ok=False, count=len(links), results=[],
            error="缺少 Mealie API Token：请在容器环境变量 MEALIE_TOKEN 设置，或在表单里粘贴。")
    if not links:
        return render_template_string(
            RESULT_HTML, ok=False, count=0, results=[],
            error="请粘贴至少一个下厨房菜谱链接（每行一个）。")

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
            "step": "抓取 + 估算",
            "cmd": " ".join(fetch_cmd),
            "returncode": rc,
            "stdout": so,
            "stderr": se,
            "time": f"{t0} -> {t1}",
        })
        if rc != 0:
            return render_template_string(
                RESULT_HTML, ok=False, count=len(links), results=results,
                error="抓取阶段失败，已中止，未写入 Mealie。")

        # Step 2: push to Mealie
        push_cmd = [sys.executable, SCRIPT, "push", out_dir,
                    "--mealie", mealie_url, "--token", token, "--tag", tag]
        if not skip_existing:
            push_cmd.append("--force")
        rc, so, se, t0, t1 = run_cmd(push_cmd, timeout=1800)
        results.append({
            "step": "推送到 Mealie" + ("（强制重导）" if not skip_existing else "（跳过已存在）"),
            "cmd": " ".join(push_cmd).replace(token, "***TOKEN***"),
            "returncode": rc,
            "stdout": so,
            "stderr": se,
            "time": f"{t0} -> {t1}",
        })

        ok = results[-1]["returncode"] == 0
        return render_template_string(
            RESULT_HTML,
            ok=ok,
            count=len(links),
            results=results,
            error=None if ok else "推送阶段失败，请查看下方输出。",
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    print(f"[xcf2mealie-web] 启动：http://0.0.0.0:{PORT}", flush=True)
    if AUTH_ENABLED:
        print(f"[xcf2mealie-web] 登录保护已启用（用户：{WEB_USER}，登录页 /login）", flush=True)
    else:
        print("[xcf2mealie-web] 警告：未设置 WEB_USER/WEB_PASSWORD，当前任何人可访问！", flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)
