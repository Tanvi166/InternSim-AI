import Link from 'next/link';
import { ArrowRight, Check, CircleDashed, FolderKanban, Search } from 'lucide-react';

export interface ProjectSummary {
  project_id: string;
  title: string;
  description: string;
  persona: string;
  language: string;
  status: 'active' | 'completed' | 'abandoned';
  target_tickets: number;
  completed_tickets_count: number;
  created_at: string;
}

const statusLabel: Record<ProjectSummary['status'], string> = {
  active: 'Active',
  completed: 'Completed',
  abandoned: 'Abandoned',
};

export default function ProjectDirectory({
  projects,
  query,
  status,
  totalProjectCount,
}: {
  projects: ProjectSummary[];
  query: string;
  status: 'all' | ProjectSummary['status'];
  totalProjectCount: number;
}) {
  return (
    <section className="space-y-4" aria-label="Project list">
      <form method="get" action="/projects" className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative block flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <span className="sr-only">Search projects</span>
          <input name="q" defaultValue={query} placeholder="Search projects" className="h-10 w-full rounded-xl border border-white/[0.08] bg-[#0e1420] pl-9 pr-3 text-sm text-slate-100 outline-none transition focus:border-cyan-200/30 focus:ring-2 focus:ring-cyan-200/10 placeholder:text-slate-600" />
        </label>
        <label className="sr-only" htmlFor="project-status-filter">Filter projects by status</label>
        <select id="project-status-filter" name="status" defaultValue={status} className="h-10 rounded-xl border border-white/[0.08] bg-[#0e1420] px-3 text-xs text-slate-200 outline-none focus:border-cyan-200/30">
          <option value="all">All statuses</option>
          <option value="active">Active</option>
          <option value="completed">Completed</option>
          <option value="abandoned">Abandoned</option>
        </select>
        <button type="submit" className="h-10 rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 text-xs font-medium text-slate-200 transition hover:bg-white/[0.08]">Apply filters</button>
      </form>

      {projects.length ? <div className="grid gap-3 md:grid-cols-2">
        {projects.map((project) => {
          const target = Math.max(project.target_tickets, 0);
          const complete = Math.min(project.completed_tickets_count, target);
          const progress = target ? Math.round((complete / target) * 100) : 0;
          return <article key={project.project_id} className="rounded-2xl border border-white/[0.08] bg-[#0e1420] p-5 transition-colors hover:border-white/[0.13]">
            <div className="flex items-start justify-between gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-200/[0.08] text-cyan-200"><FolderKanban className="h-4 w-4" /></span>
              <span className={`rounded-full border px-2.5 py-1 text-[10px] font-medium ${project.status === 'active' ? 'border-emerald-200/10 bg-emerald-200/[0.05] text-emerald-200' : project.status === 'completed' ? 'border-cyan-200/10 bg-cyan-200/[0.05] text-cyan-100' : 'border-white/[0.08] bg-white/[0.03] text-slate-400'}`}>{statusLabel[project.status]}</span>
            </div>
            <h2 className="mt-4 text-base font-semibold leading-snug text-white">{project.title}</h2>
            <p className="mt-2 line-clamp-2 min-h-10 text-xs leading-5 text-slate-400">{project.description}</p>
            <p className="mt-4 text-[10px] font-medium uppercase tracking-[0.13em] text-slate-500">{project.persona} <span className="px-1 text-slate-700">·</span> {project.language}</p>
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between text-[11px]"><span className="text-slate-400">Tickets passed</span><span className="font-mono text-slate-300">{complete}/{target}</span></div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.07]"><div className="h-full rounded-full bg-cyan-300" style={{ width: `${progress}%` }} /></div>
            </div>
            <Link href={`/projects/${encodeURIComponent(project.project_id)}`} className="mt-5 inline-flex items-center gap-2 text-xs font-medium text-cyan-200 hover:text-cyan-100">
              {project.status === 'active' ? 'Continue project' : 'View project'} <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            {project.status === 'completed' && <p className="mt-2 inline-flex items-center gap-2 text-xs text-emerald-200"><Check className="h-3.5 w-3.5" />All planned tickets passed</p>}
            {project.status === 'abandoned' && <p className="mt-2 inline-flex items-center gap-2 text-xs text-slate-500"><CircleDashed className="h-3.5 w-3.5" />Project abandoned</p>}
          </article>;
        })}
      </div> : <div className="rounded-2xl border border-dashed border-white/[0.1] bg-white/[0.015] px-6 py-12 text-center">
        <h2 className="text-sm font-semibold text-slate-200">{totalProjectCount ? 'No projects match these filters' : 'No projects yet'}</h2>
        <p className="mt-2 text-xs text-slate-500">{totalProjectCount ? 'Try a different search or status.' : 'Create a project to start your first ticket sequence.'}</p>
      </div>}
    </section>
  );
}
