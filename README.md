# LAN Share Pro (Python, No extra app)

一个完整的局域网文件共享服务，适合两台或多台 Mac/PC 在同一网络内互传。

详细文档: [docs/DETAILED_GUIDE.zh-CN.md](docs/DETAILED_GUIDE.zh-CN.md)

## 能力清单

- 密码登录 + Cookie 会话
- SQLite 元数据管理
- 文件上传（流式写入，适合大文件）
- 文件下载（支持 HTTP Range 断点续传）
- 文件列表、搜索、分页、排序
- 文件删除（软删除 + 物理删除）
- SHA-256 完整性校验
- 分享链接（有效期 + 下载次数限制）
- 共享便签实时同步（多设备自动更新）
- 文件列表实时刷新（上传、删除、下载计数）
- 局域网访问地址展示
- 前端页面：拖拽上传、进度、操作按钮、分享弹窗、共享便签

## 目录结构

```text
lan-share-complete/
  server.py
  web/
    index.html
    styles.css
    app.js
  data/
    lan_share.db
    admin_password.txt
  uploads/
```

## 启动方式

```bash
cd /Users/yanlongfei/lan-share-complete
python3 server.py
```

首次启动会自动生成访问密码，并打印在终端：

- `Admin Password: xxxxx`

浏览器访问：

- 本机：`http://127.0.0.1:8765`
- 局域网：`http://你的IP:8765`

## 可配置项（环境变量）

- `LAN_SHARE_HOST` 默认 `0.0.0.0`
- `LAN_SHARE_PORT` 默认 `8765`
- `LAN_SHARE_PASSWORD` 手动指定访问密码（默认自动生成并保存）
- `LAN_SHARE_MAX_MB` 单文件大小上限，默认 `4096`
- `LAN_SHARE_SESSION_HOURS` 登录会话时长，默认 `24`
- `LAN_SHARE_DATA_DIR` 数据目录
- `LAN_SHARE_UPLOAD_DIR` 文件目录

示例：

```bash
LAN_SHARE_PORT=9000 LAN_SHARE_MAX_MB=8192 python3 server.py
```

## API 一览

- `POST /api/login` 登录
- `POST /api/logout` 退出
- `GET /api/me` 当前登录状态
- `GET /api/network` 局域网访问地址
- `GET /api/stats` 统计信息
- `GET /api/events` 实时事件流（SSE）
- `GET /api/note` 获取共享便签
- `POST /api/note` 更新共享便签
- `GET /api/files` 文件列表（query/page/page_size/sort/order）
- `POST /api/upload?filename=...` 上传文件（body 为二进制文件）
- `GET /api/files/:id/download` 下载文件（支持 Range）
- `DELETE /api/files/:id` 删除文件
- `POST /api/files/:id/share` 生成分享链接
- `GET /api/public/:code/download` 通过分享码下载（免登录）
- `GET /s/:code` 分享落地页

## 安全建议

- 只在可信局域网使用
- 使用强密码（可通过 `LAN_SHARE_PASSWORD` 指定）
- 用完后停止服务，避免长期暴露
- 若要跨公网，建议反向代理 + HTTPS + IP 白名单

## 常见问题

1. 其他设备打不开
- 确认在同一 Wi-Fi
- 检查防火墙是否允许 Python 监听端口
- 使用 `http://服务端局域网IP:端口` 访问

2. 上传失败
- 检查是否超过 `LAN_SHARE_MAX_MB`
- 检查磁盘剩余空间

3. 忘记密码
- 删除 `data/admin_password.txt` 后重启服务自动生成新密码
