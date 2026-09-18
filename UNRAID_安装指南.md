# Unraid 汉化版 详细安装指南

> 适用：Unraid 6.12+，已安装 **Community Applications**（汉化版叫「应用」或「Apps」）
> 镜像：`ghcr.io/mjy378283319/xcf2mealie-web:latest`（已 Public，可直接拉）

---

## 方式 1：Add Container（最简单，推荐）

### 步骤 1：进 Docker 页面
Unraid Web UI → 顶部菜单 **Docker** → 页面底部 **添加容器**（Add Container）

### 步骤 2：基础字段

| 字段（汉化） | 填什么 |
|---|---|
| 名称 | `xcf2mealie-web` |
| 存储库 / Repository | `ghcr.io/mjy378283319/xcf2mealie-web:latest` |
| 网络类型 | `bridge`（默认） |
| 端口映射 | 主机端口 `9926` → 容器端口 `9926`，类型 `TCP` |
| 额外参数 | （留空） |

### 步骤 3：环境变量（关键）

点 **添加另一个路径、端口、变量、标签或设备** → 选 **变量**，逐个添加：

| Key | Value | 必填 | 说明 |
|---|---|---|---|
| `MEALIE_URL` | `https://cd.109622.xyz:9443/` | ✅ | 你的 Mealie 完整地址，**末尾要带斜杠** |
| `MEALIE_TOKEN` | `eyJhbGciOi...` | ✅ | Mealie「用户设置 → API Tokens」的长期 Token |
| `WEB_USER` | 自定义，如 `admin` | 建议 | 登录用户名 |
| `WEB_PASSWORD` | 自定义强密码 | 建议 | 登录密码 |
| `DEFAULT_TAG` | `下厨房` | ❌ | 默认追加的溯源标签 |
| `SECRET_KEY` | 任意长随机串 | ❌ | 会话签名密钥。不设则**容器每次重启都要重新登录** |

> ⚠️ Value 里**不要加引号**、**不要有前后空格**，Unraid 会原样写入。
> `WEB_USER` 和 `WEB_PASSWORD` **必须成对设置**才会启用登录；不设则免登录访问。

### 步骤 4：应用
点右下角 **应用**（Apply）。首次拉取约 50MB，拉完自动启动。

### 步骤 5：打开界面
```
http://你的UnraidIP:9926/
```
例如 `http://192.168.1.10:9926/`

- **设了登录**：进入 `/login` **独立登录页**，填账号密码后进应用；右上角随时可「退出登录」
- **没设登录**：直接进页面，顶部会有黄色「未启用登录」提醒

### 步骤 6：导入
1. 粘贴下厨房链接到文本框（每行一个）
2. （可选）改「追加标签」，默认 `下厨房`
3. **「跳过 Mealie 中已存在的菜谱」默认勾选** —— 已导入过的会自动跳过
4. 点 **确定导入**
5. 等待 1-3 分钟/菜谱，结果页会显示抓取 / 推送两阶段的完整日志

---

## 🔑 登录页 + Bitwarden 自动填充

设了 `WEB_USER` / `WEB_PASSWORD` 后，访问任何页面都会**先跳到独立登录页 `/login`**，登录后再进应用。

> **特意没用浏览器原生登录弹框**：那种 HTTP Basic Auth 弹框 Bitwarden 经常识别不到、不提示填充。
> 这里是标准 HTML 表单（带 `autocomplete="username"` 与 `autocomplete="current-password"`），密码管理器能稳定识别。

在 Bitwarden 新建一条登录项：

| 字段 | 填什么 |
|---|---|
| 名称 | `xcf2mealie-web` |
| 用户名 | 你设的 `WEB_USER` |
| 密码 | 你设的 `WEB_PASSWORD` |
| URI | `http://192.168.1.10:9926`（换成你的实际地址，**端口要带上**） |

保存后再打开登录页，Bitwarden 就会提示自动填充（手机端同样可用）。

会话保持 **30 天**，不用每次都填。
如果用 Watchtower 之类工具自动更新镜像，建议再给容器加一个固定的 `SECRET_KEY`（任意长随机串），
这样容器重启后不会被迫重新登录。

> 修改 `WEB_USER` / `WEB_PASSWORD` 后需重启容器才生效：Docker → 点容器 → **重启**。

---

## ♻️ 去重说明

每次推送前会拉取 Mealie 里已有菜谱建立索引，按顺序比对：

1. **源链接**（`orgURL`）——同一个下厨房链接只导入一次
2. **菜名**——完全同名则跳过

命中的菜谱在结果页显示「已存在于 Mealie，跳过」，不重复添加。
想强制覆盖：取消勾选页面上的「跳过 Mealie 中已存在的菜谱」。

命令行等价参数：`--force` / `--no-skip-existing`。

---

## 方式 2：命令行（SSH）

```bash
# 1. SSH 进 Unraid
ssh root@你的UnraidIP

# 2. 拉镜像
docker pull ghcr.io/mjy378283319/xcf2mealie-web:latest

# 3. 启动
docker run -d \
  --name xcf2mealie-web \
  --restart unless-stopped \
  -p 9926:9926 \
  -e MEALIE_URL="https://cd.109622.xyz:9443/" \
  -e MEALIE_TOKEN="eyJhbGciOi..." \
  -e WEB_USER="admin" \
  -e WEB_PASSWORD="换成强密码" \
  -e SECRET_KEY="一串任意长随机字符" \
  -e DEFAULT_TAG="下厨房" \
  ghcr.io/mjy378283319/xcf2mealie-web:latest

# 4. 看日志
docker logs -f xcf2mealie-web
```

**停止 / 删除 / 更新**：
```bash
docker stop xcf2mealie-web && docker rm xcf2mealie-web

# 更新到最新镜像
docker pull ghcr.io/mjy378283319/xcf2mealie-web:latest
docker stop xcf2mealie-web && docker rm xcf2mealie-web
# 再用上面 docker run 重新拉起
```

---

## 方式 3：docker-compose（可选）

把 `docker-compose.yml` 放到 Unraid 的 `/mnt/user/appdata/xcf2mealie-web/` 下，改好环境变量后：

```bash
cd /mnt/user/appdata/xcf2mealie-web
docker compose up -d
```

---

## 🔍 故障排查

### 容器日志怎么看
Unraid：**Docker** → 点容器名 → **日志**；或命令行 `docker logs -f xcf2mealie-web`

正常启动会看到：
```
[xcf2mealie-web] 启动：http://0.0.0.0:9926
[xcf2mealie-web] 登录保护已启用（用户：admin，登录页 /login）
```

如果看到「未设置 WEB_USER/WEB_PASSWORD，当前任何人可访问」说明登录没生效。

### 镜像拉不下来
- `denied: requested access to the resource is denied` → 包还是私有。去 GitHub 仓库 → **Packages** → 点击包 → **Package settings** → 滚到 **Danger Zone** → **Change package visibility** → **Public**
- `manifest unknown` → tag 写错，去 GitHub Actions 看实际发布的 tag

### 浏览器 502 / 连接被拒
- Unraid **设置 → 管理访问** 检查 9926 端口是否被允许
- 检查路由器 / 防火墙
- 容器内自测：`docker exec -it xcf2mealie-web python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9926/',timeout=3).status)"`

### 容器显示 unhealthy（红色 X）
开启登录保护后，未登录访问首页会被**重定向**到 `/login`（HTTP 302），这是正常现象而非故障。
本镜像的健康检查脚本已把重定向后的正常响应判为健康。若仍标红，先看日志：

```bash
docker logs --tail 50 xcf2mealie-web
```

### 导入报 Token 401
- Token 过期或复制时带了空格 / 换行，去 Mealie 重新生成再粘

### push 时 500 / SQLite 报错
- 这是 Mealie 自身数据库问题，**不是本工具问题**
- Unraid **Docker** → 找到 Mealie 容器 → 重启
- 反复出现则检查 Unraid 磁盘健康（SMART）并备份 Mealie 数据卷

### 步骤图没显示
- 图片以 `<img>` 内嵌在步骤 text 字段，Mealie 前端会自动渲染
- 在 Mealie 菜谱编辑页看「步骤」里是否含 `<img src="/api/media/recipes/...">`

---

## 🔄 自动更新

1. **Watchtower 容器**（Unraid CA 商店搜「Watchtower」）：自动检测并重启有新镜像的容器
2. **手动**：代码更新后几分钟，在 Unraid 跑上面的「更新到最新镜像」三条命令
