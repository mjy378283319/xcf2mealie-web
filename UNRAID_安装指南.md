# Unraid 汉化版 详细安装指南

> 适用：Unraid 6.12+，已安装 **Community Applications**（汉化版叫"应用"或"Apps"）
> 镜像：`ghcr.io/YOURNAME/xcf2mealie-web:latest`（先按 README 在 GitHub 触发自动构建，或本地构建后 push 到 Docker Hub）

---

## 方式 1：Add Container（最简单，**推荐**）

适合：不想改 Community Applications 模板库的人。

### 步骤 1：进 Docker 页面
- Unraid Web UI → 顶部菜单 **Docker** → 左侧 **Add Container**

### 步骤 2：填表
按下面这张表填（**只填 Name / Repository / Port mappings / Extra Parameters**，其它留默认）：

| 字段（汉化） | 字段（英文） | 填什么 |
|---|---|---|
| 名称 | Name | `xcf2mealie` |
| 仓库 | Repository | `ghcr.io/YOURNAME/xcf2mealie-web:latest` |
| 网络 | Network | `bridge`（默认） |
| 端口映射 | Port mappings | 主机端口 `9926` → 容器端口 `9926`（TCP） |
| 额外参数 | Extra Parameters | （留空） |
| 自动重启 | Auto restart | `Always`（容器退出自动拉起） |

### 步骤 3：环境变量（关键）
在 **Add Container** 表单最下方 **Add another Path / Port / Variable / Label / Device** → 选 **Variable**，**重复 3 次**添加下面 3 个环境变量：

| Key | Value | 说明 |
|---|---|---|
| `MEALIE_URL` | `https://cd.109622.xyz:9443/` | 你的 Mealie 完整地址，**注意末尾斜杠** |
| `MEALIE_TOKEN` | `eyJhbGciOi...` | Mealie「用户设置 → API Tokens」生成的长期 Token |
| `DEFAULT_TAG` | `下厨房` | （可选）默认追加的溯源标签 |

> ⚠️ **Token 千万别加引号**，Unraid 会原样写入。**也别用 MEALIE_TOKEN= 后面带空格**。

### 步骤 4：应用
点右下角 **Apply**。Unraid 会去 ghcr.io 拉镜像（首次约 50MB），拉完自动启动。

### 步骤 5：打开界面
浏览器访问：
```
http://你的UnraidIP:9926/
```
例如 `http://192.168.1.10:9926/`

看到「🍜 下厨房 → Mealie 批量导入」即成功。

### 步骤 6：导入
1. 粘贴下厨房链接到文本框（每行一个）
2. （可选）改"追加标签"，默认 `下厨房`
3. 点 **确定导入**
4. 等待 1-3 分钟/菜谱，浏览器会显示 fetch + push 两个阶段的日志

---

## 方式 2：命令行（适合喜欢 SSH 的人）

```bash
# 1. SSH 进 Unraid（root@Tower）
ssh root@你的UnraidIP

# 2. 拉镜像（如果你已经推到 ghcr.io）
docker pull ghcr.io/YOURNAME/xcf2mealie-web:latest

# 3. 启动
docker run -d \
  --name xcf2mealie \
  --restart unless-stopped \
  -p 9926:9926 \
  -e MEALIE_URL="https://cd.109622.xyz:9443/" \
  -e MEALIE_TOKEN="eyJhbGciOi..." \
  -e DEFAULT_TAG="下厨房" \
  ghcr.io/YOURNAME/xcf2mealie-web:latest

# 4. 看日志
docker logs -f xcf2mealie

# 5. 浏览器打开 http://UnraidIP:9926/
```

**停止 / 删除容器**：
```bash
docker stop xcf2mealie
docker rm xcf2mealie
```

**更新镜像**：
```bash
docker pull ghcr.io/YOURNAME/xcf2mealie-web:latest
docker stop xcf2mealie && docker rm xcf2mealie
# 再用上面 docker run 重新拉起
```

---

## 方式 3：Community Applications 模板（高级，让别人也能搜到）

如果你想让本工具出现在 CA 商店（自己或公开），需要一个 XML 模板文件。
模板示例（保存为 `https://raw.githubusercontent.com/YOURNAME/xcf2mealie-web/main/xcf2mealie-web.xml`）：

```xml
<?xml version="1.0"?>
<Container version="2">
  <Name>xcf2mealie-web</Name>
  <Repository>ghcr.io/YOURNAME/xcf2mealie-web:latest</Repository>
  <Registry>https://github.com/YOURNAME/xcf2mealie-web/pkgs/container/xcf2mealie-web</Registry>
  <Support>https://github.com/YOURNAME/xcf2mealie-web</Support>
  <Project>https://github.com/YOURNAME/xcf2mealie-web</Project>
  <Category>Tools:Recipe</Category>
  <WebUI>http://[IP]:[PORT:9926]/</WebUI>
  <TemplateURL>https://raw.githubusercontent.com/YOURNAME/xcf2mealie-web/main/xcf2mealie-web.xml</TemplateURL>
  <Icon>https://raw.githubusercontent.com/YOURNAME/xcf2mealie-web/main/icon.png</Icon>
  <Description>下厨房批量导入 Mealie 的极简 Web 工具。粘贴链接、点确定即可。</Description>
  <Networking>
    <Mode>bridge</Mode>
    <Ports>
      <Port>
        <HostPort>9926</HostPort>
        <ContainerPort>9926</ContainerPort>
        <Protocol>tcp</Protocol>
      </Port>
    </Ports>
  </Networking>
  <Data>
    <Volume>
      <HostDir></HostDir>
      <ContainerDir></ContainerDir>
      <Mode></Mode>
    </Volume>
  </Data>
  <Environment>
    <Variable>
      <Name>MEALIE_URL</Name>
      <Mode></Mode>
      <Description>你的 Mealie 完整 URL（含 https:// 和末尾斜杠）</Description>
    </Variable>
    <Variable>
      <Name>MEALIE_TOKEN</Name>
      <Mode></Mode>
      <Description>Mealie Long Lived Token（在 Mealie 用户设置 → API Tokens 生成）</Description>
    </Variable>
    <Variable>
      <Name>DEFAULT_TAG</Name>
      <Mode></Mode>
      <Description>默认追加的标签（推荐：下厨房）</Description>
    </Variable>
  </Environment>
</Container>
```

**挂到 CA 的方法**：
1. Unraid Web UI → **Apps** → 底部 **Template Repositories**
2. 填入：`https://github.com/YOURNAME/xcf2mealie-web`（仓库根目录会自动识别 `*.xml`）
3. 保存后回到 **Apps** 搜索 `xcf2mealie` 即可看到，点击安装

---

## 🔍 故障排查

### 镜像拉不下来
```bash
docker pull ghcr.io/YOURNAME/xcf2mealie-web:latest
```
- 报错 `denied: requested access to the resource is denied` → 镜像还是私有，去 GitHub 仓库 → **Packages** → 点击包 → **Package settings** → 滚到底 **Change package visibility** → Public
- 报错 `manifest unknown` → tag 写错了，去 GitHub Actions 看实际发布的 tag

### 容器起不来
```bash
docker logs xcf2mealie
```
正常输出：
```
[xcf2mealie-web] 启动：http://0.0.0.0:9926
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:9926
```
如果只有最后两行没启动，**说明是 Flask 启动失败**（极少），看具体报错。

### 浏览器 502 / 连接拒绝
- Unraid **Settings → Management Access** 检查 `9926` 端口是否在允许范围
- 防火墙 / 路由器有没有拦
- 容器内 `docker exec -it xcf2mealie curl http://127.0.0.1:9926/` 验证服务本身

### 导入时报 Token 401
- Token 过期了，去 Mealie 重新生成
- Token 里有空格 / 换行，重新复制

### push 时 500 / SQLite 报错
- 这是 Mealie 自身数据库问题，**不是本工具问题**
- Unraid **Docker** → 找到 Mealie 容器 → 重启
- 如果反复出现，检查 Unraid 磁盘健康（SMART）+ 给 Mealie 数据卷加 backup

### 步骤图没显示
- 工具已把图片以 `<img>` 内嵌在步骤 text 字段，Mealie 前端会自动渲染
- 如果看不到，在 Mealie 菜谱编辑页看「步骤」字段里是否含 `<img src="/api/media/recipes/...">`

---

## 🔄 自动更新

如果你想"GitHub 推代码 → Unraid 自动用新镜像"，有两个思路：

1. **Watchtower 容器**（Unraid CA 商店搜 "Watchtower"）：自动检测并重启有新镜像的容器
2. **手动**：每改完代码 `git push` → 几分钟后在 Unraid 跑：
   ```bash
   docker pull ghcr.io/YOURNAME/xcf2mealie-web:latest
   docker stop xcf2mealie && docker rm xcf2mealie
   docker run -d --name xcf2mealie --restart unless-stopped -p 9926:9926 \
     -e MEALIE_URL=... -e MEALIE_TOKEN=... \
     ghcr.io/YOURNAME/xcf2mealie-web:latest
   ```
