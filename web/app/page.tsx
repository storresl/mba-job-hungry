import { BriefcaseBusiness, Clock3, Layers3, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const metrics = [
  {
    label: "New offers in the last 24 hours",
    detail: "Rolling 24-hour window",
    icon: Clock3,
  },
  {
    label: "New offers in the last 7 days",
    detail: "Rolling 168-hour window",
    icon: Layers3,
  },
  {
    label: "Total job offers",
    detail: "All current offers",
    icon: BriefcaseBusiness,
  },
] as const;

export default function Home() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <BriefcaseBusiness aria-hidden="true" className="size-5" />
            </div>
            <div>
              <p className="font-semibold tracking-tight">MBA Jobs</p>
              <p className="text-xs text-muted-foreground">INSEAD community</p>
            </div>
          </div>
          <span className="rounded-full border px-3 py-1 text-xs font-medium text-muted-foreground">
            Early preview
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-14 sm:px-8 sm:py-20">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1.5fr)_minmax(18rem,0.7fr)] lg:items-end">
          <div>
            <p className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Your job search, at a glance
            </p>
            <h1 className="max-w-2xl text-4xl font-semibold tracking-tight sm:text-5xl">
              Find your next opportunity.
            </h1>
            <p className="mt-5 max-w-xl text-base leading-7 text-muted-foreground">
              A private space for INSEAD job offers. The dashboard will bring
              together fresh listings, trends, and tailored matches.
            </p>
          </div>

          <Card className="bg-muted/35">
            <CardHeader>
              <div className="mb-3 flex size-9 items-center justify-center rounded-lg bg-background ring-1 ring-border">
                <ShieldCheck aria-hidden="true" className="size-4" />
              </div>
              <CardTitle>INSEAD access</CardTitle>
              <CardDescription>
                Sign-in will require a verified @insead.edu email address.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button disabled className="w-full" aria-label="Email sign-in coming soon">
                Email sign-in coming soon
              </Button>
              <p className="mt-3 text-center text-xs text-muted-foreground">
                Email code first. Single sign-on later.
              </p>
            </CardContent>
          </Card>
        </div>

        <section aria-labelledby="metrics-heading" className="mt-16 sm:mt-20">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="metrics-heading" className="text-xl font-semibold tracking-tight">
                Job market snapshot
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                These figures will appear after the jobs database is connected.
              </p>
            </div>
            <span className="text-xs text-muted-foreground">No live data yet</span>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {metrics.map((metric) => {
              const Icon = metric.icon;
              return (
                <Card key={metric.label}>
                  <CardHeader>
                    <div className="mb-4 flex size-9 items-center justify-center rounded-lg bg-muted">
                      <Icon aria-hidden="true" className="size-4" />
                    </div>
                    <CardTitle className="text-sm">{metric.label}</CardTitle>
                    <CardDescription>{metric.detail}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <p className="text-4xl font-semibold tabular-nums" aria-label="Not available yet">
                      —
                    </p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
