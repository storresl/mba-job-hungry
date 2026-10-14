import Link from "next/link";
import { notFound } from "next/navigation";
import { io } from "next/cache";
import { Suspense } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BriefcaseBusiness,
  CalendarDays,
  Clock3,
  MapPin,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { loadJobDashboard } from "@/lib/jobs";

const PAGE_SIZE = 6;

function requestedPage(value: string | string[] | undefined, totalPages: number): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed > 0 ? Math.min(parsed, totalPages) : 1;
}

function pageUrl(page: number): string {
  return page === 1 ? "/" : `/?page=${page}`;
}

async function Dashboard({ searchParams }: { searchParams: PageProps<"/">["searchParams"] }) {
  await io();
  const [query, dashboard] = await Promise.all([searchParams, loadJobDashboard()]);
  const totalPages = Math.max(1, Math.ceil(dashboard.jobs.length / PAGE_SIZE));
  const page = requestedPage(query.page, totalPages);
  const start = (page - 1) * PAGE_SIZE;
  const visibleJobs = dashboard.jobs.slice(start, start + PAGE_SIZE);

  const metrics = [
    {
      label: "Total jobs",
      detail: "Offers in the archive",
      value: dashboard.total,
      icon: BriefcaseBusiness,
    },
    {
      label: "Last 168 hours",
      detail: "Published in the last 7 days",
      value: dashboard.last168Hours,
      icon: CalendarDays,
    },
    {
      label: "Last 24 hours",
      detail: "Published in the last day",
      value: dashboard.last24Hours,
      icon: Clock3,
    },
  ];

  return (
    <>
      <section aria-labelledby="snapshot-heading">
        <h2 id="snapshot-heading" className="text-2xl font-semibold tracking-tight text-white">
          Job market snapshot
        </h2>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {metrics.map((metric) => {
            const Icon = metric.icon;
            return (
              <Card key={metric.label} className="border border-[#21412c] bg-[#101b14] ring-0">
                <CardHeader className="gap-4">
                  <div className="flex size-10 items-center justify-center rounded-lg bg-[#1b3a27] text-[#9dd0a8]">
                    <Icon aria-hidden="true" className="size-5" />
                  </div>
                  <CardTitle className="text-base font-medium text-white">
                    {metric.label}
                  </CardTitle>
                  <CardDescription>{metric.detail}</CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-4xl font-semibold tracking-tight tabular-nums text-white">
                    {metric.value.toLocaleString("en-US")}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="offers-heading" className="mt-14">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <h2 id="offers-heading" className="text-2xl font-semibold tracking-tight text-white">
            Latest offers
          </h2>
          {dashboard.total > 0 && (
            <p className="text-sm text-muted-foreground">
              Showing {start + 1}–{start + visibleJobs.length} of {dashboard.total}
            </p>
          )}
        </div>

        {visibleJobs.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2">
            {visibleJobs.map((job) => (
              <Card
                key={job.id}
                className="border border-[#203b29] bg-[#0e1711] ring-0 transition-colors hover:border-[#3b7050]"
              >
                <CardHeader className="gap-2">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#9dd0a8]">
                    {job.company}
                  </p>
                  <CardTitle className="text-lg font-semibold leading-snug text-white">
                    {job.role}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col">
                  <p className="min-h-20 text-sm leading-6 text-[#b7c7bb]">
                    {job.description}
                  </p>
                  <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2 border-t border-[#24402d] pt-4 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-2">
                      <MapPin aria-hidden="true" className="size-4 text-[#77b489]" />
                      {job.location}
                    </span>
                    <span className="inline-flex items-center gap-2">
                      <CalendarDays aria-hidden="true" className="size-4 text-[#77b489]" />
                      {job.postedLabel}
                    </span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-[#24402d] bg-[#0e1711] px-6 py-10 text-sm text-muted-foreground">
            No saved job offers yet. Run the scraper to populate the dashboard.
          </div>
        )}

        {dashboard.total > 0 && (
          <nav aria-label="Job offers pages" className="mt-8 flex items-center justify-between">
            {page > 1 ? (
              <Link
                href={pageUrl(page - 1)}
                aria-label="Show previous six offers"
                className="inline-flex items-center gap-2 rounded-lg border border-[#2d5b3b] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#173523] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#83c494]"
              >
                <ArrowLeft aria-hidden="true" className="size-4" />
                Previous six
              </Link>
            ) : (
              <span className="text-sm text-[#637669]">Start of offers</span>
            )}
            <span className="text-xs text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            {page < totalPages ? (
              <Link
                href={pageUrl(page + 1)}
                aria-label="Show next six offers"
                className="inline-flex items-center gap-2 rounded-lg border border-[#2d5b3b] bg-[#163522] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#205032] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#83c494]"
              >
                Next six
                <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
            ) : (
              <span className="text-sm text-[#637669]">End of offers</span>
            )}
          </nav>
        )}
      </section>
    </>
  );
}

export default function Home({ searchParams }: PageProps<"/">) {
  // The archive contains private portal data. Keep the preview local until email auth exists.
  if (process.env.NODE_ENV !== "development") notFound();

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-6 py-10 sm:px-8 sm:py-14">
      <header className="mb-12 border-b border-[#23402c] pb-8">
        <h1 className="border-l-4 border-[#2f7647] pl-5 text-3xl font-bold tracking-tight text-white sm:text-4xl">
          MBA Job Hungry
        </h1>
      </header>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading jobs…</p>}>
        <Dashboard searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
