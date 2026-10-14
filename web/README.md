# MBA Job Hungry web

Next.js App Router dashboard using TypeScript, Tailwind CSS, and shadcn/ui.

## Run locally

Requires Node.js 20.18.1 or newer.

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Dashboard data

The dashboard reads `../data/jobs.json` on every request. Run the scraper first to
create the archive. The three KPIs are total unique archived offers, offers
published in the rolling last 168 hours, and offers published in the rolling
last 24 hours. Jobs are sorted by the portal's `PostedDate` and paged six at a time.
`PostedDate` has no timezone in the source JSON, so the dashboard treats it as UTC.

Only the title, company, location, publication date, and a short plain-text
description are selected from the archive for rendering. The archive also holds
private portal data, so this route is limited to local development. The next
access milestone is verified `@insead.edu` email OTP with server-side authorization;
institutional SSO can follow later.

## Checks

```bash
npm run lint
npx tsc --noEmit
npm run build
```
