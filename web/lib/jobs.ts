import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const archivePath = resolve(process.cwd(), "..", "data", "jobs.json");
const dateFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

type StoredJob = {
  id: string;
  list_data?: {
    TitleDisplay?: string;
    JobTitle?: string;
    CompanyName?: string;
    LocationDisplay?: string;
    PostedDate?: string;
    IsEmployerNameHidden?: boolean;
  };
  detail_data?: {
    description?: string | null;
    job_posting?: { Description?: string | null } | null;
  } | null;
};

export type JobSummary = {
  id: string;
  role: string;
  company: string;
  location: string;
  description: string;
  postedAt: number | null;
  postedLabel: string;
};

export type JobDashboard = {
  total: number;
  last168Hours: number;
  last24Hours: number;
  jobs: JobSummary[];
};

function publicationTime(value: string | undefined): number | null {
  if (!value) return null;

  // The portal returns PostedDate without a timezone. Interpret it as UTC consistently.
  const withZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  const timestamp = Date.parse(withZone);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function plainText(html: string): string {
  const entities: Record<string, string> = {
    amp: "&",
    apos: "'",
    bull: "•",
    gt: ">",
    hellip: "…",
    lt: "<",
    mdash: "—",
    nbsp: " ",
    ndash: "–",
    quot: '"',
    rsquo: "'",
    lsquo: "'",
    ldquo: '"',
    rdquo: '"',
  };

  return html
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&(#(?:x[0-9a-f]+|\d+)|[a-z]+);/gi, (match, entity: string) => {
      if (entity.startsWith("#")) {
        const hex = entity[1]?.toLowerCase() === "x";
        const codePoint = Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10);
        return codePoint > 0 && codePoint <= 0x10ffff
          ? String.fromCodePoint(codePoint)
          : " ";
      }
      return entities[entity.toLowerCase()] ?? match;
    })
    .replace(/\s+/g, " ")
    .trim();
}

function briefDescription(job: StoredJob): string {
  const html = job.detail_data?.description || job.detail_data?.job_posting?.Description;
  if (typeof html !== "string") return "Description not available for this offer.";

  const description = plainText(html);
  if (!description) return "Description not available for this offer.";
  if (description.length <= 220) return description;
  return `${description.slice(0, 217).replace(/\s+\S*$/, "")}…`;
}

function summarize(job: StoredJob): JobSummary {
  const listing = job.list_data ?? {};
  const postedAt = publicationTime(listing.PostedDate);

  return {
    id: String(job.id),
    role: listing.TitleDisplay || listing.JobTitle || "Untitled role",
    company: listing.IsEmployerNameHidden
      ? "Confidential company"
      : listing.CompanyName || "Company not listed",
    location: listing.LocationDisplay || "Location not listed",
    description: briefDescription(job),
    postedAt,
    postedLabel: postedAt === null ? "Date unavailable" : dateFormatter.format(postedAt),
  };
}

export async function loadJobDashboard(): Promise<JobDashboard> {
  const now = Date.now();
  let contents: string;
  try {
    contents = await readFile(archivePath, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { total: 0, last168Hours: 0, last24Hours: 0, jobs: [] };
    }
    throw error;
  }

  const archive: unknown = JSON.parse(contents);
  if (
    !archive ||
    typeof archive !== "object" ||
    !("jobs" in archive) ||
    !Array.isArray(archive.jobs)
  ) {
    throw new Error("data/jobs.json does not contain a jobs array");
  }

  const unique = new Map<string, JobSummary>();
  for (const entry of archive.jobs as StoredJob[]) {
    if (entry && entry.id != null) unique.set(String(entry.id), summarize(entry));
  }

  const jobs = [...unique.values()].sort(
    (a, b) => (b.postedAt ?? -Infinity) - (a.postedAt ?? -Infinity) || b.id.localeCompare(a.id),
  );
  const last24Hours = jobs.filter(
    (job) => job.postedAt !== null && job.postedAt <= now && job.postedAt > now - 24 * 60 * 60 * 1000,
  ).length;
  const last168Hours = jobs.filter(
    (job) => job.postedAt !== null && job.postedAt <= now && job.postedAt > now - 168 * 60 * 60 * 1000,
  ).length;

  return { total: jobs.length, last168Hours, last24Hours, jobs };
}
