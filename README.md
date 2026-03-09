# LAN Share Complete

> A browser-first LAN file sharing service for Mac and PC, built with Python standard library only.
>
> One device starts the server, every other device opens a browser. No extra desktop app required.

[详细说明文档（中文）](docs/DETAILED_GUIDE.zh-CN.md)

## Why This Project

This project is designed for a simple but practical scenario:

- You have two or more devices on the same LAN
- You want to transfer files through a browser
- You do not want to install a new application
- You still want a complete product experience instead of a bare file server

Compared with a temporary script or a plain directory listing server, this project adds authentication, metadata management, resumable downloads, share links, and real-time sync for both file list changes and shared notes.

## Core Features

- Password login with cookie session
- Drag-and-drop upload in browser
- Streamed file upload for large files
- HTTP Range download for resume support
- File list with search, pagination, and sorting
- Soft delete plus physical file cleanup
- SHA-256 checksum generation
- Public share links with expiration and max-download limits
- Shared note with real-time sync across devices
- Server-Sent Events for live file list updates
- SQLite metadata storage
- LAN address discovery for easier access from other devices

## Product Model

Only one machine needs to run this project.

- Device A: starts `server.py`
- Device B / C / phone / tablet: opens `http://DeviceA-IP:8765` in a browser
- All logged-in devices can upload, download, delete, and update the shared note in real time

This means the project works more like a lightweight private LAN portal than a peer-to-peer desktop app.

## Quick Start

### 1. Clone the repository

```bash
git clone git@github.com:nihaoyaxiaofei/lan-share-complete.git
cd lan-share-complete
```

### 2. Start the server

```bash
python3 server.py
```

On first launch, the server prints:

- local address, such as `http://127.0.0.1:8765`
- LAN address, such as `http://192.168.x.x:8765`
- admin password, such as `Admin Password: xxxxx`

### 3. Open it from another device

Make sure both devices are on the same LAN, then open:

```text
http://<server-lan-ip>:8765
```

### 4. Log in and transfer files

After login, you can:

- drag files into the page to upload
- download existing files
- create share links
- edit the shared note
- watch file list updates appear automatically on other devices

## Typical Use Cases

### Two MacBooks transfer files

- Mac A runs the server
- Mac B opens the browser page
- Either side can upload files to the shared space
- Both sides see file list and note updates in real time

### Temporary team dropbox on office Wi-Fi

- One machine hosts the service during a meeting
- Everyone joins with a browser
- Files can be exchanged without installing tools

### Shared text board across devices

- Use the shared note for quick cross-device text handoff
- Updates propagate automatically through SSE

## Configuration

The server can be configured with environment variables.

| Variable | Default | Description |
| --- | --- | --- |
| `LAN_SHARE_HOST` | `0.0.0.0` | Listen address |
| `LAN_SHARE_PORT` | `8765` | Server port |
| `LAN_SHARE_PASSWORD` | auto-generated | Admin password |
| `LAN_SHARE_MAX_MB` | `4096` | Max upload size in MB |
| `LAN_SHARE_SESSION_HOURS` | `24` | Session lifetime in hours |
| `LAN_SHARE_DATA_DIR` | `./data` | Metadata directory |
| `LAN_SHARE_UPLOAD_DIR` | `./uploads` | File storage directory |

Example:

```bash
LAN_SHARE_PORT=9000 \
LAN_SHARE_PASSWORD='YourStrongPass' \
LAN_SHARE_MAX_MB=8192 \
python3 server.py
```

## API Overview

- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`
- `GET /api/network`
- `GET /api/stats`
- `GET /api/events`
- `GET /api/note`
- `POST /api/note`
- `GET /api/files`
- `POST /api/upload?filename=...`
- `GET /api/files/:id/download`
- `DELETE /api/files/:id`
- `POST /api/files/:id/share`
- `GET /api/public/:code/download`
- `GET /s/:code`

For API examples and implementation details, see [详细说明文档（中文）](docs/DETAILED_GUIDE.zh-CN.md).

## Project Structure

```text
lan-share-complete/
  server.py
  README.md
  docs/
    DETAILED_GUIDE.zh-CN.md
  web/
    index.html
    styles.css
    app.js
  data/
  uploads/
```

## Security Notes

This project is intended for trusted LAN environments.

- Use a strong password through `LAN_SHARE_PASSWORD`
- Do not expose it directly to the public internet
- If internet access is required, place it behind HTTPS and an access control layer
- Stop the service when it is no longer needed

## Roadmap

- upload resume support for very large files
- QR code generation for faster mobile access
- multi-user roles and permission scopes
- optional HTTPS reverse proxy deployment guide
