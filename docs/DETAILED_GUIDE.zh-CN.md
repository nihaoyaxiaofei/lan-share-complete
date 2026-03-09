# LAN Share Pro 详细说明文档

版本: `v1.0`  
项目路径: `/Users/yanlongfei/lan-share-complete`  
适用场景: 两台或多台设备在同一局域网内进行文件共享与传输。

## 1. 项目概览

LAN Share Pro 是一个基于 Python 标准库实现的局域网文件共享系统，目标是:

- 不安装额外桌面应用，直接浏览器可用
- 支持上传、下载、删除、分享链接
- 支持较大文件传输（流式处理）
- 提供基础安全能力（密码登录、会话、登录限流、文件路径保护）
- 提供元数据管理（SQLite）

核心能力:

- 登录鉴权（密码 + Cookie 会话）
- 文件上传（`POST /api/upload`）
- 文件列表（搜索、分页、排序）
- 文件下载（支持 `Range` 断点续传）
- 文件删除（软删除标记 + 物理删除文件）
- 分享链接（有效期 + 下载次数限制）
- 共享便签实时同步（多设备自动更新）
- 文件列表实时刷新（基于 SSE 事件流）
- SHA-256 哈希校验

## 2. 目录结构

```text
lan-share-complete/
  server.py                # 后端主程序
  README.md                # 快速说明
  docs/
    DETAILED_GUIDE.zh-CN.md
  web/
    index.html             # 前端页面结构
    styles.css             # 样式
    app.js                 # 前端逻辑
  data/
    lan_share.db           # SQLite 数据库
    admin_password.txt     # 自动生成的管理员密码
  uploads/                 # 文件存储目录
```

## 3. 快速开始（3-5 分钟）

### 3.1 启动服务

```bash
cd /Users/yanlongfei/lan-share-complete
python3 server.py
```

启动后会输出:

- 服务监听地址，如 `http://0.0.0.0:8765`
- 局域网可访问地址，如 `http://192.168.x.x:8765`
- 管理密码 `Admin Password: ...`

### 3.2 首次登录

1. 浏览器访问 `http://127.0.0.1:8765`
2. 输入终端里打印的 `Admin Password`
3. 进入主页面后即可上传、下载、分享

### 3.3 两台 Mac 互传

假设 A 机开服务、B 机访问:

1. A 机执行启动命令。
2. A 机记下局域网地址 `http://A机IP:8765`。
3. B 机在浏览器打开该地址。
4. B 机输入同一密码后即可上传文件到 A 机，或下载 A 机已有文件。

## 4. 配置项（环境变量）

可通过环境变量覆盖默认配置。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LAN_SHARE_HOST` | `0.0.0.0` | 监听地址 |
| `LAN_SHARE_PORT` | `8765` | 服务端口 |
| `LAN_SHARE_PASSWORD` | 空 | 管理密码；设置后优先使用该值 |
| `LAN_SHARE_MAX_MB` | `4096` | 单文件上传上限（MB） |
| `LAN_SHARE_SESSION_HOURS` | `24` | 登录会话时长（小时） |
| `LAN_SHARE_DATA_DIR` | `./data` | 数据目录 |
| `LAN_SHARE_UPLOAD_DIR` | `./uploads` | 文件目录 |

示例:

```bash
LAN_SHARE_PORT=9000 \
LAN_SHARE_PASSWORD='YourStrongPass' \
LAN_SHARE_MAX_MB=8192 \
python3 server.py
```

## 5. 功能详解

### 5.1 登录与会话

- 登录接口: `POST /api/login`
- 成功后服务端下发 `lan_session` Cookie（`HttpOnly`）
- 通过 `GET /api/me` 检查登录状态
- `POST /api/logout` 退出并清除会话

防暴力破解:

- 同一 IP 连续失败达到阈值会临时锁定
- 锁定后返回 `429 Too many attempts`

### 5.2 上传

- 接口: `POST /api/upload?filename=xxx`
- 请求体: 文件二进制流
- 需要 `Content-Length`
- 超限会返回 `413`
- 服务端流式写入 `.part` 临时文件，完成后原子移动
- 上传完成后计算并保存 SHA-256

### 5.3 下载

- 登录下载: `GET /api/files/:id/download`
- 公共分享下载: `GET /api/public/:code/download`
- 支持 `Range`，可断点续传

### 5.4 列表 / 搜索 / 分页 / 排序

- 接口: `GET /api/files`
- 参数:
- `query`: 文件名关键字
- `page`: 页码（最小 1）
- `page_size`: 每页条数（1-100）
- `sort`: `created_at | size | name | downloads`
- `order`: `asc | desc`

### 5.5 删除

- 接口: `DELETE /api/files/:id`
- 逻辑:
- 数据库中标记 `deleted=1`
- 记录 `deleted_at`
- 删除磁盘中的实际文件

### 5.6 共享便签与实时事件

- `GET /api/note` 获取当前共享便签
- `POST /api/note` 更新共享便签
- `GET /api/events` 建立 SSE 长连接
- 服务端在上传、删除、下载计数变化、便签更新时广播事件

### 5.7 分享链接

- 生成接口: `POST /api/files/:id/share`
- 参数:
- `expires_hours`: 过期小时数（1-720）
- `max_downloads`: 最大下载次数（1-100000）
- 返回 `share_url` 和 `code`
- 分享页地址: `GET /s/:code`

## 6. API 详细示例（curl）

以下示例默认服务地址为 `http://127.0.0.1:8765`。

### 6.1 登录

```bash
curl -i -c /tmp/lan_cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"password":"你的密码"}' \
  http://127.0.0.1:8765/api/login
```

### 6.2 上传

```bash
curl -b /tmp/lan_cookie.txt \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @/path/to/file.zip \
  'http://127.0.0.1:8765/api/upload?filename=file.zip'
```

### 6.3 列表

```bash
curl -b /tmp/lan_cookie.txt \
  'http://127.0.0.1:8765/api/files?page=1&page_size=20&sort=created_at&order=desc'
```

### 6.4 下载

```bash
curl -L -b /tmp/lan_cookie.txt \
  -o downloaded.bin \
  'http://127.0.0.1:8765/api/files/<file_id>/download'
```

### 6.5 Range 下载（断点）

```bash
curl -L -b /tmp/lan_cookie.txt \
  -H 'Range: bytes=0-1048575' \
  -o first_1mb.bin \
  'http://127.0.0.1:8765/api/files/<file_id>/download'
```

### 6.6 获取共享便签

```bash
curl -b /tmp/lan_cookie.txt \
  http://127.0.0.1:8765/api/note
```

### 6.7 更新共享便签

```bash
curl -b /tmp/lan_cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"content":"hello from another device"}' \
  http://127.0.0.1:8765/api/note
```

### 6.8 创建分享

```bash
curl -b /tmp/lan_cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"expires_hours":24,"max_downloads":20}' \
  'http://127.0.0.1:8765/api/files/<file_id>/share'
```

### 6.9 通过分享码下载

```bash
curl -L -o from_share.bin \
  'http://127.0.0.1:8765/api/public/<code>/download'
```

### 6.10 删除文件

```bash
curl -X DELETE -b /tmp/lan_cookie.txt \
  'http://127.0.0.1:8765/api/files/<file_id>'
```

## 7. 数据模型（SQLite）

数据库文件: `data/lan_share.db`

### 7.1 files 表

- `id`: 文件 ID（主键）
- `stored_name`: 磁盘存储名（唯一）
- `original_name`: 原始文件名
- `mime_type`: MIME 类型
- `size_bytes`: 文件大小
- `sha256`: 文件 SHA-256
- `created_at`: 上传时间（ISO 格式）
- `uploaded_by`: 上传者 IP
- `downloads`: 下载次数
- `deleted`: 删除标记
- `deleted_at`: 删除时间

### 7.2 notes 表

- `id`: 固定为 1
- `content`: 共享便签内容
- `updated_at`: 最近更新时间
- `updated_by`: 最近更新来源

### 7.3 shares 表

- `code`: 分享码（主键）
- `file_id`: 对应文件 ID
- `created_at`: 创建时间
- `expires_at`: 过期时间
- `max_downloads`: 最大下载次数
- `download_count`: 已下载次数

## 8. 安全说明

已实现的安全措施:

- 会话 Cookie 使用 `HttpOnly`
- 登录密码比对使用安全比较方式（防时序侧信道）
- 登录失败限流与短时锁定
- 文件名清理与长度限制
- 路径拼接安全校验（防目录穿越）
- 上传大小限制

仍建议增强:

- 仅在可信局域网使用
- 设置强密码并定期更新
- macOS 防火墙仅放行必要网络
- 若暴露公网，必须加反向代理 HTTPS、IP 白名单、WAF

## 9. 运维建议

### 9.1 日志

- 当前日志输出到标准输出（终端）
- 建议生产化时重定向到文件并按天轮转

### 9.2 备份

建议至少备份:

- `data/lan_share.db`
- `uploads/`
- `data/admin_password.txt`（如果使用自动密码）

### 9.3 升级

1. 停服务
2. 备份 `data` 与 `uploads`
3. 更新代码
4. 启动并验证 `GET /api/health`

## 10. 常见问题排查

### 10.1 其他设备打不开页面

- 检查两台设备是否同一网段
- 用 `http://服务端局域网IP:端口` 访问
- 检查 macOS 防火墙是否拦截 Python
- 检查端口是否被占用

### 10.2 登录失败

- 确认密码是否与终端输出一致
- 如果短时间连续输错，等待限流窗口后重试
- 忘记密码可删除 `data/admin_password.txt` 后重启

### 10.3 上传失败

- 检查文件是否超过 `LAN_SHARE_MAX_MB`
- 检查磁盘空间
- 检查网络是否中断（中断会返回 `Upload interrupted`）

### 10.4 分享链接失效

- 可能已过 `expires_at`
- 可能达到 `max_downloads`
- 可能原文件已被删除

## 11. 后续扩展建议

如果你要继续做“更完整”的产品级版本，推荐下一步:

1. 分片上传 + 断点续传（上传侧）
2. WebSocket 实时进度与状态广播
3. 角色权限（管理员 / 访客）
4. 审计日志与操作追踪
5. 定时清理策略（按时间或空间阈值）
6. mDNS/Bonjour 自动发现设备

---

如果你希望，我可以继续补一份 `launchd` 开机自启部署文档，并直接给你可用的 `plist` 文件。
