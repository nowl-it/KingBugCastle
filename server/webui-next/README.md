# KGC Web UI

The admin dashboard and player portal share this static Next.js export. Use pnpm
for all frontend commands:

```bash
pnpm install
pnpm run dev
pnpm run lint
pnpm run build
```

Create or refresh `pnpm-lock.yaml` only on a networked development host, so it
captures the registry-resolved dependency graph. The repository retains its
legacy `package-lock.json` until that deliberate migration is performed.
