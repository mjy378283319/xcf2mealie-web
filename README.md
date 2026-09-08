# xcf2mealie-web

> **下厨房（xiachufang.com）→ Mealie 批量导入工具，带极简 Web UI**
> 粘贴链接、点确定，自动抓取 + 营养估算 + 推送到你的 Mealie。

![界面示意](https://placeholder) <!-- 可在 README 加截图 -->

## ✨ 特性

- 🖱️ **极简 UI**：一个粘贴框 + 一个按钮，零学习成本
- 📦 **批量导入**：一次粘贴多个链接，每行一个
- 🖼️ **步骤图保留**：自动下载并上传到 Mealie 作为菜谱资源
- 🥗 **营养估算**：按《中国食物成分表》估算 11 项营养指标
- ⏱️ **时间估算**：prep / cook / total 自动计算
- 🏷️ **tags / 分类 / 封面**：源页结构化信息全保留
- ♻️ **自动去重**：Mealie 里已存在的菜谱自动跳过，不会重复添加（可强制覆盖）
- 🔐 **双重安全**：Token 走容器环境变量不进镜像；页面可加账号密码，**兼容 Bitwarden 自动填充**
- 🐳 **多架构镜像**：自动构建 `linux/amd64` + `linux/arm64`（Unraid x86_64 直接用）

## 🚀 快速开始（docker run）

```bash
docker run -d \
  --name xcf2mealie-web \
  --restart unless-stopped \
  -p 9926:9926 \
  -e MEALIE_URL=https://your-mealie.example.com/ \
  -e MEALIE_TOKEN=eyJhbGciOi... \
  -e WEB_USER=admin \
  -e WEB_PASSWORD=换成你的密码 \
  ghcr.io/mjy378283319/xcf2mealie-web:latest
```

浏览器打开 `http://your-host:9926`，粘贴下厨房链接，点"确定导入"即可。

## 🏗️ 自己构建镜像

### 方式 A：本地构建
```bash
docker build -t xcf2mealie:local .
docker run -d --name xcf2mealie -p 9926:9926 \
  -e MEALIE_URL=... -e MEALIE_TOKEN=... \
  xcf2mealie:local
```

### 方式 B：推到 GitHub 自动构建到 ghcr.io

1. 在 GitHub 创建空仓库 `xcf2mealie-web`（public，私有也行但 ghcr.io 私有有配额限制）
2. 把本目录所有文件推上去：
   ```bash
   cd xcf2mealie_web
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin git@github.com:YOURNAME/xcf2mealie-web.git
   git push -u origin main
   ```
3. 推上去后自动触发 GitHub Actions，几分钟后镜像发布到 `ghcr.io/YOURNAME/xcf2mealie-web:latest`
4. 在「Package settings」里把镜像设为 **Public**（默认私有），Unraid 才能直接 pull

> ⚠️ 仓库名若不是 `xcf2mealie-web`，镜像名会跟着变。`docker-compose.yml` 里的 `image:` 也要对应改。

## 🏠 Unraid 部署

详见 [`UNRAID_安装指南.md`](./UNRAID_安装指南.md)。

## 🧩 界面截图位置

启动后浏览器访问 `http://<host>:9926/`。

## ⚙️ 配置

| 环境变量 | 必填 | 说明 |
|---|---|---|
| `MEALIE_URL` | ✅ | Mealie 实例完整 URL，如 `https://cd.example.com:9443/` |
| `MEALIE_TOKEN` | ✅ | Mealie「用户设置 → API Tokens → Long Lived Token」 |
| `WEB_USER` | ❌ | 页面登录用户名。**与 `WEB_PASSWORD` 同时设置才启用登录**，不设则任何人可访问 |
| `WEB_PASSWORD` | ❌ | 页面登录密码（也可写作 `WEB_PASS`） |
| `DEFAULT_TAG` | ❌ | 每个菜谱默认追加的标签，默认 `下厨房` |
| `PORT` | ❌ | Web UI 端口，默认 `9926` |

## 🔑 登录保护 + Bitwarden 自动填充

设置 `WEB_USER` + `WEB_PASSWORD` 重启容器后，访问页面会弹出浏览器原生登录框。
这种标准 **HTTP Basic Auth** 弹框能被密码管理器完美识别：

在 Bitwarden 里新建一条登录项：

| 字段 | 填什么 |
|---|---|
| 名称 | `xcf2mealie-web` |
| 用户名 | 你设的 `WEB_USER` |
| 密码 | 你设的 `WEB_PASSWORD` |
| URI | `http://192.168.x.x:9926`（你的实际访问地址，端口要带上） |

保存后再打开页面，Bitwarden 就会提示自动填充。手机端 Bitwarden 同样可用。

> 未设置这两个变量时页面免登录，首页顶部会显示黄色提醒条。

## ♻️ 去重逻辑

导入前会先拉取 Mealie 里已有菜谱建立索引，按下面顺序比对：

1. **源链接**（`orgURL`）——最准，同一个下厨房链接只导入一次
2. **菜名**——完全同名则跳过

命中的菜谱会显示「已存在于 Mealie，跳过」并跳过后续步骤，不再重复添加。
页面上的「跳过 Mealie 中已存在的菜谱」复选框默认勾选；**取消勾选则强制重新导入**（会产生重复条目，仅在确实要覆盖时用）。

对应命令行参数：

| 参数 | 作用 |
|---|---|
| （默认） | 自动跳过已存在菜谱 |
| `--force` | 强制重新导入，忽略已存在 |
| `--no-skip-existing` | 关闭去重（等价 `--force`） |

## 🔧 故障排查

- **界面打不开**：检查端口是否被宿主机占用，`docker logs xcf2mealie` 看启动日志
- **Token 报错 401**：Token 失效或填错，重新到 Mealie 生成一个
- **fetch 失败**：下厨房页面需要登录或被滑块拦截，工具已自动尝试移动端站点，仍失败则那个菜谱跳过
- **push 500**：Mealie 数据库文件问题（用户实测 Unraid SQLite 模式下偶发），重启 Mealie 容器即可
- **看不到镜像（ghcr.io）**：GitHub 仓库 → Packages → 把镜像设为 Public

## 📁 文件结构

```
xcf2mealie_web/
├── app.py                 # Flask 主程序（UI 内联 + Basic Auth + 去重开关）
├── xcf2mealie.py          # 核心导入逻辑（命令行工具）
├── healthcheck.py         # 容器健康检查（开启登录时 401 也判健康）
├── requirements.txt       # Python 依赖（仅 flask）
├── Dockerfile             # 镜像构建
├── docker-compose.yml     # compose 部署（可选）
├── .dockerignore
├── .github/workflows/
│   └── build.yml          # GitHub Actions 自动构建到 ghcr.io
├── urls.txt.example       # 链接列表文件示例
├── README.md
├── UNRAID_安装指南.md     # 详细汉化 Unraid 安装步骤
└── .gitignore
```

> 页面 HTML 直接内联在 `app.py` 里（不依赖 `templates/` 目录），单文件即可跑。

## 📜 许可

仅供个人使用。下厨房页面版权归原作者所有，导入到 Mealie 仅作为个人收藏。
