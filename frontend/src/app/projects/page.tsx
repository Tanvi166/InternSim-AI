import { redirect } from 'next/navigation';
import { FolderKanban } from 'lucide-react';
import { AppShell } from '@/components/AppShell';
import { createClient } from '@/utils/supabase/server';
import StartNewProjectButton from '@/app/dashboard/StartNewProjectButton';
import ProjectDirectory, { ProjectSummary } from './ProjectDirectory';

export default async function ProjectsPage({ searchParams }: {
  searchParams: Promise<{ q?: string | string[]; status?: string | string[] }>;
}) {
  const params = await searchParams;
  const query = typeof params.q === 'string' ? params.q.trim() : '';
  const validStatuses = ['all', 'active', 'completed', 'abandoned'] as const;
  const status = validStatuses.find((candidate) => candidate === params.status) || 'all';
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect('/login');

  const { data: profile } = await supabase.from('profiles').select('*').eq('id', user.id).single();
  if (!profile) redirect('/onboarding');

  let allProjects: ProjectSummary[] = [];
  let unavailable = false;
  try {
    const { data: { session } } = await supabase.auth.getSession();
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    const response = await fetch(`${apiUrl}/api/projects`, {
      headers: session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {},
      cache: 'no-store',
    });
    if (!response.ok) unavailable = true;
    else allProjects = await response.json();
  } catch {
    unavailable = true;
  }

  const projects = allProjects.filter((project) => {
    const matchesStatus = status === 'all' || project.status === status;
    const normalizedQuery = query.toLowerCase();
    const matchesQuery = !normalizedQuery || `${project.title} ${project.description} ${project.persona}`.toLowerCase().includes(normalizedQuery);
    return matchesStatus && matchesQuery;
  });
  const activeProject = allProjects.find((project) => project.status === 'active');
  const isCurrentCompleted = Boolean(activeProject && activeProject.completed_tickets_count >= activeProject.target_tickets);

  return (
    <AppShell userEmail={user.email} userSkill={profile.skill_level} userPersona={profile.chosen_persona}>
      <div className="mx-auto max-w-6xl space-y-7">
        <section className="flex flex-col gap-5 border-b border-white/[0.07] pb-7 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-2 flex items-center gap-2 text-xs font-medium text-cyan-300"><FolderKanban className="h-4 w-4" /> Project workspace</p>
            <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-[2.15rem]">My Projects</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Review your active, completed, and abandoned project work.</p>
          </div>
          {!unavailable && <div className="shrink-0">
            <StartNewProjectButton persona={activeProject?.persona || profile.chosen_persona || 'Enterprise SaaS'} isCurrentCompleted={!activeProject || isCurrentCompleted} className="h-10 rounded-xl bg-cyan-300 px-4 text-xs font-semibold text-slate-950 shadow-none hover:bg-cyan-200" />
          </div>}
        </section>

        {unavailable ? (
          <section className="rounded-2xl border border-amber-200/10 bg-amber-200/[0.04] p-6 sm:p-8">
            <h2 className="text-base font-semibold text-white">Projects could not be loaded</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">The project service did not return a response. Check that the backend is available, then try again.</p>
          </section>
        ) : <ProjectDirectory projects={projects} query={query} status={status} totalProjectCount={allProjects.length} />}

        {!unavailable && allProjects.length === 0 && <p className="text-center text-xs text-slate-600">Starting a project creates it in your account and begins a new ticket sequence.</p>}
      </div>
    </AppShell>
  );
}
