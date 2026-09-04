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
- 🔐 **安全**：Token 走容器环境变量，不进镜像
- 🐳 **多架构镜像**：自动构建 `linux/amd64` + `linux/arm64`（Unraid x86_64 直接用）

## 🚀 快速开始（docker run）

```bash
docker run -d \
  --name xcf2mealie \
  --restart unless-stopped \
  -p 9926:9926 \
  -e MEALIE_URL=https://your-mealie.example.com/ \
  -e MEALIE_TOKEN=eyJhbGciOi... \
  ghcr.io/YOURNAME/xcf2mealie:latest
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
| `DEFAULT_TAG` | ❌ | 每个菜谱默认追加的标签，默认 `下厨房` |
| `PORT` | ❌ | Web UI 端口，默认 `9926` |

## 🔧 故障排查

- **界面打不开**：检查端口是否被宿主机占用，`docker logs xcf2mealie` 看启动日志
- **Token 报错 401**：Token 失效或填错，重新到 Mealie 生成一个
- **fetch 失败**：下厨房页面需要登录或被滑块拦截，工具已自动尝试移动端站点，仍失败则那个菜谱跳过
- **push 500**：Mealie 数据库文件问题（用户实测 Unraid SQLite 模式下偶发），重启 Mealie 容器即可
- **看不到镜像（ghcr.io）**：GitHub 仓库 → Packages → 把镜像设为 Public

## 📁 文件结构

```
xcf2mealie_web/
├── app.py                 # Flask 主程序（Web UI 后端）
├── xcf2mealie.py          # 核心导入逻辑（命令行工具）
├── templates/
│   ├── index.html         # 首页：链接输入 + 提交
│   └── result.html        # 导入结果页
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

## 📜 许可

仅供个人使用。下厨房页面版权归原作者所有，导入到 Mealie 仅作为个人收藏。
