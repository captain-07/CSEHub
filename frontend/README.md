# CSEHub frontend

This is a dependency-free static client for CSEHub's public learning library.

## Configuration

Set public deployment configuration before each page's module script. The API URL may be either the backend origin or its `/api` URL; pagination URLs returned by DRF are handled directly.

```html
<script>
  window.CSEHUB_API_BASE_URL = "https://api.example.com";
  window.CSEHUB_SUPABASE_URL = "https://your-project.supabase.co";
  window.CSEHUB_SUPABASE_ANON_KEY = "your-publishable-anon-key";
</script>
```

The frontend origin must be included in the backend's `CORS_ALLOWED_ORIGINS` setting.

## Local development

From the repository root:

```powershell
python -m http.server 3000 --directory frontend
```

Then open `http://localhost:3000`. Run Django separately at port 8000.
