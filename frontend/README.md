# RAG Assistant — frontend

Angular 22 application for the Insurance Claims RAG API in the parent folder.

```bash
npm install
npm start          # http://localhost:4200, talks to the API on http://127.0.0.1:8000
npm test           # vitest unit tests
npm run build      # production build -> dist/rag-assistant/browser (served by FastAPI at /)
```

Structure:

```
src/app/
  core/       models, API services, interceptors, guards, preferences store
  shared/     reusable components (empty/error/loading states, chunk card, dialogs), pipes, markdown
  layout/     sidebar shell and health indicator
  features/   chat · documents · evaluation · analytics · settings · developer
```

The API base URL comes from `src/environments/` (empty in production = same origin).
