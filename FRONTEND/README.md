# IP-SAKTI Sahayak — Frontend

The web UI for **IP-SAKTI Sahayak**: a React single-page application covering the
whole workflow — landing/register/login, Product Passport and versions, knowledge
base, AI chat, expert reviews, dashboard and showcase screens.

> Project overview, full setup and troubleshooting: **[../README.md](../README.md)**
> Backend API reference: **[../BACKEND/README.md](../BACKEND/README.md)**

## Stack

- **React 19** (SPA, `src/App.jsx` holds the router and all pages)
- **Vite 8** dev server + `@vitejs/plugin-react`
- **react-router-dom 7** for routing
- **D3** for the visualisations (risk map, dashboards)
- Plain CSS (`src/index.css`, `src/App.css`) — no UI framework

## Requirements

- Node.js 20.19+ / 22+ (verified on Node 24)
- A running backend (see ../README.md) — the dev server proxies `/api` to it

## Getting started

```bash
npm install        # first time only
npm run dev        # http://localhost:5173
```

Or, equivalently:

```bash
node_modules\.bin\vite --host 0.0.0.0 --port 5173    # Windows
node_modules/.bin/vite --host 0.0.0.0 --port 5173    # macOS/Linux
```

The Vite config (`vite.config.js`) does two things:

1. Serves the app on **port 5173**
2. Proxies **`/api/*` requests to `http://localhost:8000`** (the FastAPI backend),
   so development needs no CORS setup

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Start the dev server with hot reload |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | ESLint |

## Routes

| Route | Page |
|---|---|
| `/` | Landing page |
| `/login`, `/register` | Authentication |
| `/home` | Home |
| `/products`, `/products/new` | Product list / create product |
| `/products/:id/versions` | Version list for a product |
| `/products/:id/versions/:versionId` | Version detail: content, analysis, IP screening, change impact, disclosures, reports |
| `/knowledge` | Knowledge-base document upload/management |
| `/chat` | RAG assistant (citations, PDF attachments, language switch) |
| `/reviews` | Expert review workflow |
| `/dashboard` | Dashboard |
| `/demo` | Showcase screens |

## Notes

- Auth uses an access token in memory plus an **httpOnly refresh cookie**; the app
  restores the session on reload via `POST /api/auth/refresh`.
- Registration/login send **JSON** bodies (form data is rejected with 422).
- `dist/` is generated output — delete it freely and rebuild with `npm run build`.
