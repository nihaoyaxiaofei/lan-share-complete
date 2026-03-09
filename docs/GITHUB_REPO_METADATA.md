# GitHub Repo Metadata

This file contains ready-to-use repository metadata for `nihaoyaxiaofei/lan-share-complete`.

## Recommended Settings

- Description: `Browser-first LAN file sharing service with password login, stream upload, resumable downloads, share links, and real-time note sync — built with Python stdlib only.`
- Homepage: `https://github.com/nihaoyaxiaofei/lan-share-complete/blob/main/docs/DETAILED_GUIDE.zh-CN.md`
- Topics:
  - `python`
  - `lan`
  - `file-sharing`
  - `browser-app`
  - `http-server`
  - `sqlite`
  - `sse`
  - `resumable-download`
  - `local-network`
  - `zero-dependency`

## Apply With GitHub CLI

```bash
gh auth login

gh repo edit nihaoyaxiaofei/lan-share-complete \
  --description "Browser-first LAN file sharing service with password login, stream upload, resumable downloads, share links, and real-time note sync — built with Python stdlib only." \
  --homepage "https://github.com/nihaoyaxiaofei/lan-share-complete/blob/main/docs/DETAILED_GUIDE.zh-CN.md" \
  --add-topic python \
  --add-topic lan \
  --add-topic file-sharing \
  --add-topic browser-app \
  --add-topic http-server \
  --add-topic sqlite \
  --add-topic sse \
  --add-topic resumable-download \
  --add-topic local-network \
  --add-topic zero-dependency
```

## Notes

- If you later publish a demo site or docs site, replace the homepage with that URL.
- The current homepage suggestion points to the Chinese detailed guide because this project is intended to run locally inside a private LAN, not as a public hosted demo.
