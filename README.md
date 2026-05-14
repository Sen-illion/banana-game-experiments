# Human Eval Lite Deploy

This directory is a lightweight deployment package for Render.

## What it includes
- Web app code (`server.py`, `index.html`, `app.js`, `styles.css`)
- Runtime data (`data/theme_catalog.json`, `data/invite_tokens.json`, `data/invite_links.csv`)
- Tooling scripts in `tools/`

## What it excludes
- Large image assets. Images are served from CDN:
  - `https://sen-illion.com/dn-eval-assets/...`

## Render settings
- Start command:
  - `gunicorn server:app --bind 0.0.0.0:$PORT`
- Environment variables (required for durable submission storage):
  - `OSS_ENDPOINT=oss-cn-shenzhen.aliyuncs.com`
  - `OSS_BUCKET=sen-illion`
  - `OSS_ACCESS_KEY_ID=<your_ram_ak>`
  - `OSS_ACCESS_KEY_SECRET=<your_ram_sk>`
  - `OSS_RESULTS_PREFIX=dn-eval-submissions`
  - `OSS_PUBLIC_BASE_URL=https://sen-illion.com`
  - `HUMAN_EVAL_ADMIN_KEY=<admin_export_key>`

## Download submissions to local
Use:

```powershell
ossutil ls oss://sen-illion/dn-eval-submissions
ossutil cp -r oss://sen-illion/dn-eval-submissions D:\human-eval-submissions
```
