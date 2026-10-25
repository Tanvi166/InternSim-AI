import Link from 'next/link';
import { redirect } from 'next/navigation';
import { ArrowLeft, ArrowRight, CircleAlert, FolderKanban } from 'lucide-react';
import { AppShell } from '@/components/AppShell';
import { createClient } from '@/utils/supabase/server';

interface Project {
  project_id: string;
  title: string;
  description: string;
  persona: string;
  language: string;
  status: 'active' | 'completed' | 'abandoned';
  target_tickets: number;
  completed_tickets_count: number;
}

interface Task {
  task_id: string;
  title: string;
  description: string;
  task_type: string;
  difficulty_level: number;
  language: string;
}

async function getJson<T>(url: string, token: string): Promise<{ data?: T; status: number }> {
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    if (!response.ok) return { status: response.status };
    return { data: await response.json(), status: response.status };
  } catch {
    return { status: 0 };
  }
}

export default async function ProjectWorkspacePage({ params }: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect('/login');

  const [{ data: profile }, { data: { session } }] = await Promise.all([
    supabase.from('profiles').select('*').eq('id', user.id).single(),
    supabase.auth.getSession(),
  ]);
  if (!profile) redirect('/onboarding');
  if (!session?.access_token) redirect('/login');

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
  const projectResult = await getJson<Project>(
    `${apiUrl}/api/projects/${encodeURIComponent(projectId)}`,
    session.access_token,
  );
  const project = projectResult.data;

  const tasksResult = project
    ? await getJson<Task[]>(`${apiUrl}/api/tasks?project_id=${encodeURIComponent(project.project_id)}`, session.access_token)
    : { status: projectResult.status, data: undefined };
  const unavailable = !project || !tasksResult.data;
  const progress = project?.target_tickets
    ? Math.min(100, Math.round(project.completed_tickets_count / project.target_tickets * 100))
    : 0;

  return (
    <AppShell userEmail={user.email} userSkill={profile.skill_level} userPersona={profile.chosen_persona}>
      <div className="mx-auto max-w-5xl space-y-7">
        <Link href="/projects" className="inline-flex items-center gap-2 text-xs text-slate-400 hover:text-white"><ArrowLeft className="h-4 w-4" />All projects</Link>
        {unavailable ? (
          <section role="alert" className="rounded-2xl border border-amber-200/10 bg-amber-200/[0.04] p-6 sm:p-8">
            <CircleAlert className="h-5 w-5 text-amber-200" />
            <h1 className="mt-3 text-lg font-semibold text-white">Project workspace unavailable</h1>
            <p className="mt-2 text-sm leading-6 text-slate-400">{projectResult.status === 404 ? 'This project could not be found for your account.' : 'The project or its assignments could not be loaded. Check the backend connection and try again.'}</p>
          </section>
        ) : project ? (
          <>
            <header className="rounded-2xl border border-white/[0.08] bg-[#0e1420] p-6 sm:p-8">
              <p className="mb-3 flex items-center gap-2 text-xs font-medium text-cyan-200"><FolderKanban className="h-4 w-4" />Project workspace · {project.status}</p>
              <h1 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">{project.title}</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">{project.description}</p>
              <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-slate-400">
                <span>{project.persona}</span><span>{project.language}</span><span>{project.completed_tickets_count} of {project.target_tickets} tickets passed</span>
              </div>
              <div className="mt-4 h-1.5 max-w-xl overflow-hidden rounded-full bg-white/[0.07]"><div className="h-full rounded-full bg-cyan-300" style={{ width: `${progress}%` }} /></div>
            </header>
            <section aria-labelledby="project-tasks-title" className="space-y-3">
              <div><h2 id="project-tasks-title" className="text-lg font-semibold text-white">Project tickets</h2><p className="mt-1 text-xs text-slate-500">Assignments below are loaded for this project only.</p></div>
              {(tasksResult.data || []).length ? (tasksResult.data || []).map((task) => (
                <article key={task.task_id} className="flex flex-col gap-4 rounded-xl border border-white/[0.08] bg-[#0e1420] p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-wider text-slate-500">{task.task_type} · Tier {task.difficulty_level} · {task.language}</p>
                    <h3 className="mt-1 text-sm font-medium text-white">{task.title}</h3>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">{task.description}</p>
                  </div>
                  <Link href={`/tasks/${encodeURIComponent(task.task_id)}`} className="inline-flex shrink-0 items-center gap-2 text-xs font-medium text-cyan-200 hover:text-cyan-100">Open ticket <ArrowRight className="h-3.5 w-3.5" /></Link>
                </article>
              )) : <div className="rounded-xl border border-dashed border-white/[0.1] p-6 text-center text-sm text-slate-400">No tickets have been generated for this project yet.</div>}
            </section>
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
