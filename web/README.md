# MBA Jobs web

Next.js App Router shell using TypeScript, Tailwind CSS, and shadcn/ui.

## Run locally

Requires Node.js 20.18.1 or newer.

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Current scope

The home page is a UI preview. Its three KPI cards intentionally have no values.
The next milestones are verified `@insead.edu` email OTP, a Supabase jobs table,
and an idempotent import from the scraper's JSON output. Institutional SSO can
replace or supplement email OTP later. Do not deploy this shell as a protected
job board until authentication and server-side authorization are in place.

The KPI windows are rolling durations from the query time: 24 hours, 168 hours,
and all current jobs. A job's first-seen timestamp will be set on initial import
and retained on later upserts.

## Checks

```bash
npm run lint
npx tsc --noEmit
npm run build
```
