# CSEHub frontend

This is a dependency-free static client for CSEHub's public learning library.

## Configuration

It calls the project's Render API at `https://csehub-ezdl.onrender.com/api` by default, including when opened with Live Server. To use a local Django API or another deployed backend, set `window.CSEHUB_API_BASE_URL` before `js/config.js` in `index.html`, for example:

```html
<script>window.CSEHUB_API_BASE_URL = "https://api.example.com/api";</script>
```

The frontend origin must be included in the backend's `CORS_ALLOWED_ORIGINS` setting.

## Local development

From the repository root:

```powershell
python -m http.server 3000 --directory frontend
```

Then open `http://localhost:3000`. Run Django separately at port 8000.
