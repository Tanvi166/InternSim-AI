import { createClient } from '@/utils/supabase/server';
import { redirect } from 'next/navigation';
import Link from 'next/link';
import { AppShell } from '@/components/AppShell';
import GenerateTaskButton from './GenerateTaskButton';
import StartNewProjectButton from './StartNewProjectButton';
import { StatusBadge } from '@/components/StatusBadge';
import { getPersonaConfig, formatTicketId, getSprintMetrics } from '@/lib/companyConfig';
import { 
  Building2, 
  CheckCircle2, 
  Clock, 
  Terminal, 
  TrendingUp, 
  AlertCircle, 
  ArrowRight, 
  Code2, 
  ShieldCheck, 
  Layers, 
  Sparkles,
  Award,
  Flame
} from 'lucide-react';

export default async function DashboardPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  
  if (!user) {
    redirect('/login');
  }

  // Fetch user profile
  const { data: profile } = await supabase
    .from('profiles')
    .select('*')
    .eq('id', user.id)
    .single();

  if (!profile) {
    redirect('/onboarding');
  }

  // Fetch task history (submissions)
  const { data: submissions } = await supabase
    .from('submissions')
    .select(`
      submission_id,
      task_id,
      correctness_score,
      quality_score,
      total_score,
      created_at,
      tasks (
        task_id,
        title,
        description,
        difficulty_level,
        task_type,
        language
      )
    `)
    .eq('user_id', user.id)
    .order('created_at', { ascending: false });

  const safeSubmissions = submissions || [];

  // Fetch active project from backend API (with auto-provision fallback)
  let activeProject: any = null;
  try {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    const { data: { session } } = await supabase.auth.getSession();
    const token = session?.access_token;
    const projRes = await fetch(`${apiUrl}/api/projects/active`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: 'no-store'
    });
    if (projRes.ok) {
      activeProject = await projRes.json();
    }
  } catch (err) {
    console.warn('Could not fetch active project:', err);
  }

  // Query all tasks belonging to the active project to establish the sequential ticket lifecycle
  let projectTasks: any[] = [];
  if (activeProject?.project_id) {
    const { data: pTasks } = await supabase
      .from('tasks')
      .select('*')
      .eq('project_id', activeProject.project_id)
      .order('created_at', { ascending: true });
    projectTasks = pTasks || [];
  }

  // Set of task IDs that the user has passed (correctness >= 40)
  const passedTaskIds = new Set(
    safeSubmissions
      .filter((s: any) => (s.correctness_score || 0) >= 40)
      .map((s: any) => s.task_id)
  );

  // Determine active ticket:
  // 1. Look within project tasks for the first task that is NOT yet passed (could be unsubmitted OR needing revision)
  let latestTask: any = null;
  let activeTicketStatus: 'new' | 'revising' | 'passed' = 'new';
  let latestTaskSubmission: any = null;

  if (projectTasks.length > 0) {
    const unpassedProjectTask = projectTasks.find((t: any) => !passedTaskIds.has(t.task_id));
    if (unpassedProjectTask) {
      latestTask = unpassedProjectTask;
      // Check if user previously submitted this task (i.e. needing revision)
      latestTaskSubmission = safeSubmissions.find((s: any) => s.task_id === unpassedProjectTask.task_id);
      if (latestTaskSubmission) {
        activeTicketStatus = 'revising';
      }
    }
  } else {
    // Fallback if no project tasks yet: query latest unpassed task
    let fallbackQuery = supabase
      .from('tasks')
      .select('*')
      .order('created_at', { ascending: false });

    if (activeProject?.project_id) {
      fallbackQuery = fallbackQuery.eq('project_id', activeProject.project_id);
    }
    if (passedTaskIds.size > 0) {
      fallbackQuery = fallbackQuery.not('task_id', 'in', `(${Array.from(passedTaskIds).join(',')})`);
    }
    const { data: fallbackTasks } = await fallbackQuery.limit(1);
    if (fallbackTasks && fallbackTasks.length > 0) {
      latestTask = fallbackTasks[0];
      latestTaskSubmission = safeSubmissions.find((s: any) => s.task_id === latestTask.task_id);
      if (latestTaskSubmission) {
        activeTicketStatus = 'revising';
      }
    }
  }

  const personaConfig = getPersonaConfig(profile.chosen_persona);
  const totalSubmissions = submissions?.length || 0;
  const { sprint, day, sprintProgress } = getSprintMetrics(totalSubmissions);

  // Calculate metrics
  const avgScore = totalSubmissions > 0 
    ? Math.round(safeSubmissions.reduce((acc: number, cur: any) => acc + (cur.total_score || 0), 0) / totalSubmissions) 
    : 0;

  const passedSubmissions = safeSubmissions.filter((s: any) => (s.correctness_score || 0) >= 40);
  const testPassRate = totalSubmissions > 0 
    ? Math.round((passedSubmissions.length / totalSubmissions) * 100) 
    : 0;

  const avgQuality = totalSubmissions > 0
    ? Math.round(safeSubmissions.reduce((acc: number, cur: any) => acc + (cur.quality_score || 0), 0) / totalSubmissions)
    : 0;

  const activeTicketId = latestTask ? formatTicketId(latestTask.task_id) : null;
  const isProjectCompleted = activeProject && (activeProject.status === 'completed' || activeProject.completed_tickets_count >= activeProject.target_tickets);

  return (
    <AppShell
      userEmail={user.email}
      userSkill={profile.skill_level}
      userPersona={personaConfig.teamName}
    >
      <div className="space-y-8 pb-12">
        {/* Good Morning / Team Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-xl bg-zinc-900/80 border border-zinc-800/80 backdrop-blur-sm">
          <div>
            <div className="flex items-center gap-2 text-xs font-mono text-cyan-400 mb-1">
              <Building2 className="h-3.5 w-3.5" />
              <span>{personaConfig.teamName}</span>
            </div>
            <h1 className="text-2xl font-bold text-zinc-100 tracking-tight">
              Good morning, {user.email?.split('@')[0] || 'Engineer'}
            </h1>
            <p className="text-xs text-zinc-400 font-mono mt-1">
              Active Sprint: <span className="text-zinc-200 font-semibold">Sprint {sprint} · Day {day}</span> · {latestTask ? (activeTicketStatus === 'revising' ? 'Ticket Revision In Progress' : 'Ticket Assigned') : isProjectCompleted ? 'Project Completed' : 'Ready for Next Ticket'}
            </p>
          </div>

          <div className="flex items-center gap-3">
            {isProjectCompleted ? (
              <StartNewProjectButton
                persona={profile.chosen_persona || 'Enterprise SaaS'}
                isCurrentCompleted={true}
              />
            ) : (
              <GenerateTaskButton
                skillLevel={profile.skill_level || 'Beginner'}
                persona={profile.chosen_persona || 'Enterprise SaaS'}
                difficultyLevel={profile.current_difficulty_tier || 1}
                projectId={activeProject?.project_id}
                label={latestTask ? 'Assign Another Ticket' : 'Pick Up Next Ticket'}
                variant="primary"
              />
            )}
          </div>
        </div>

        {/* Project Overview & Ticket Sequence Lifecycle Track */}
        {activeProject && (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5 space-y-4 font-mono text-xs shadow-lg">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-zinc-800 pb-3">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 text-[10px] font-bold">
                  ACTIVE INTERNSHIP PROJECT
                </span>
                <span className="font-sans font-bold text-zinc-100 text-sm">
                  {activeProject.title}
                </span>
              </div>
              <div className="flex items-center gap-2 text-zinc-400">
                <span>Sprint Milestone:</span>
                <span className="font-bold text-cyan-400">
                  {activeProject.completed_tickets_count} of {activeProject.target_tickets} Tickets Passed
                </span>
              </div>
            </div>

            <p className="text-zinc-400 font-sans text-xs leading-relaxed">
              {activeProject.description}
            </p>

            {/* Sequence of Sprint Tickets (Slots 1 to 4) */}
            <div className="pt-2">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-2 font-semibold">
                Project Ticket Sequence ({activeProject.target_tickets} Tickets Planned)
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {Array.from({ length: activeProject.target_tickets }).map((_, slotIdx) => {
                  const taskForSlot = projectTasks[slotIdx];
                  const isPassed = taskForSlot && passedTaskIds.has(taskForSlot.task_id);
                  const isActive = taskForSlot && latestTask && taskForSlot.task_id === latestTask.task_id;
                  const isLocked = !taskForSlot && slotIdx > (projectTasks.length);

                  return (
                    <div
                      key={slotIdx}
                      className={`p-3 rounded-lg border transition-all ${
                        isPassed
                          ? 'bg-zinc-950/70 border-emerald-900/60'
                          : isActive
                          ? 'bg-cyan-950/20 border-cyan-500/60 shadow-md shadow-cyan-500/5'
                          : taskForSlot
                          ? 'bg-zinc-950/50 border-zinc-800'
                          : 'bg-zinc-950/20 border-zinc-900 border-dashed text-zinc-600'
                      }`}
                    >
                      <div className="flex items-center justify-between text-[10px] mb-1.5">
                        <span className="font-bold">
                          {taskForSlot ? formatTicketId(taskForSlot.task_id) : `Ticket #${slotIdx + 1}`}
                        </span>
                        {isPassed ? (
                          <span className="px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">
                            PASSED
                          </span>
                        ) : isActive ? (
                          <span className="px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 font-bold">
                            {activeTicketStatus === 'revising' ? 'REVISING' : 'ACTIVE'}
                          </span>
                        ) : taskForSlot ? (
                          <span className="px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400">
                            QUEUED
                          </span>
                        ) : (
                          <span className="text-zinc-600">UPCOMING</span>
                        )}
                      </div>

                      <div className="text-xs font-sans font-medium text-zinc-200 line-clamp-1">
                        {taskForSlot ? taskForSlot.title : `Milestone Task ${slotIdx + 1}`}
                      </div>

                      {taskForSlot && (
                        <div className="mt-2 pt-2 border-t border-zinc-800/60 flex items-center justify-between text-[10px]">
                          <span className="text-zinc-500 uppercase">{taskForSlot.task_type}</span>
                          <Link href={`/tasks/${taskForSlot.task_id}`} className="text-cyan-400 hover:underline">
                            {isPassed ? 'Review Code' : 'Open Ticket'} →
                          </Link>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Current Active Ticket Dominant Card or Empty State */}
        {latestTask ? (
          <div className="relative rounded-xl border border-cyan-500/40 bg-zinc-900/90 p-6 shadow-2xl overflow-hidden">
            <div className="absolute top-0 right-0 h-32 w-32 bg-cyan-500/5 rounded-full blur-2xl pointer-events-none" />

            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-zinc-800 font-mono text-xs">
              <div className="flex items-center gap-2.5">
                <span className="px-2.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800/80 font-bold">
                  {activeTicketId}
                </span>
                <StatusBadge 
                  status={activeTicketStatus === 'revising' ? 'warning' : 'in-progress'} 
                  label={activeTicketStatus === 'revising' ? 'Revision Needed (Requires Update)' : 'Current Assigned Ticket'} 
                />
                <span className="text-zinc-500">· Priority: P1 HIGH</span>
              </div>

              <span className="text-zinc-400">
                Language: <span className="text-zinc-200 font-semibold uppercase">{latestTask.language || 'Python'}</span>
              </span>
            </div>

            <div className="mt-5 space-y-3">
              <h2 className="text-xl font-bold text-zinc-100 tracking-tight">
                {latestTask.title}
              </h2>
              <p className="text-xs md:text-sm text-zinc-300 leading-relaxed max-w-4xl line-clamp-3">
                {latestTask.description}
              </p>

              {activeTicketStatus === 'revising' && latestTaskSubmission && (
                <div className="p-3 rounded-lg bg-amber-950/30 border border-amber-800/50 text-amber-200/90 text-xs font-mono flex items-start gap-2 mt-3">
                  <AlertCircle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">Prior Submission Scored {latestTaskSubmission.total_score}/100:</span> Correctness {latestTaskSubmission.correctness_score}/60, Quality {latestTaskSubmission.quality_score}/40. Reopen the workspace to debug, test, and resubmit without losing submission history.
                  </div>
                </div>
              )}
            </div>

            <div className="mt-6 pt-4 border-t border-zinc-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3 text-xs text-zinc-400 font-mono">
                <div className="flex items-center gap-1">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                  <span>Level Tier: {profile.current_difficulty_tier || 1}</span>
                </div>
                <span>·</span>
                <div>
                  Assigned Reviewer: <span className="text-zinc-200">{personaConfig.reviewerName}</span>
                </div>
              </div>

              <Link href={`/tasks/${latestTask.task_id}`}>
                <button className="inline-flex items-center gap-2 px-5 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs transition-colors shadow-lg shadow-cyan-500/20">
                  <span>{activeTicketStatus === 'revising' ? 'Revise Ticket Workspace' : 'Open Ticket Workspace'}</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </Link>
            </div>
          </div>
        ) : (
          <div className="relative rounded-xl border border-zinc-800 bg-zinc-900/60 p-8 shadow-xl overflow-hidden text-center">
            <div className="max-w-md mx-auto space-y-4">
              <div className="inline-flex p-3 rounded-xl bg-zinc-800/80 border border-zinc-700/60 text-cyan-400 mb-1">
                <CheckCircle2 className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-zinc-100 tracking-tight">
                  No Active Tickets In Progress
                </h3>
                <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed font-sans">
                  {totalSubmissions > 0
                    ? 'All assigned tickets in your sprint queue have been completed and reviewed! Pick up your next engineering ticket to continue progression.'
                    : 'You currently have no tickets assigned. Pick up your first ticket to start the sprint.'}
                </p>
              </div>
              <div className="pt-2 flex justify-center">
                {isProjectCompleted ? (
                  <StartNewProjectButton
                    persona={profile.chosen_persona || 'Enterprise SaaS'}
                    isCurrentCompleted={true}
                  />
                ) : (
                  <GenerateTaskButton
                    skillLevel={profile.skill_level || 'Beginner'}
                    persona={profile.chosen_persona || 'Enterprise SaaS'}
                    difficultyLevel={profile.current_difficulty_tier || 1}
                    projectId={activeProject?.project_id}
                    label="Pick Up Next Ticket"
                    variant="primary"
                  />
                )}
              </div>
            </div>
          </div>
        )}

        {/* Sprint Progress Bar & Stat Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Stat 1: Completed Tickets */}
          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800/80">
            <div className="flex items-center justify-between text-zinc-400 font-mono text-xs mb-2">
              <span>Sprint Tickets</span>
              <Terminal className="h-4 w-4 text-cyan-400" />
            </div>
            <div className="text-2xl font-bold text-zinc-100 font-mono">
              {totalSubmissions} <span className="text-xs text-zinc-500 font-normal">tickets</span>
            </div>
            <div className="mt-3 w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
              <div 
                className="bg-cyan-400 h-full rounded-full transition-all duration-500"
                style={{ width: `${sprintProgress}%` }}
              />
            </div>
            <p className="mt-1.5 text-[11px] text-zinc-500 font-mono">
              Sprint {sprint} progress ({sprintProgress}%)
            </p>
          </div>

          {/* Stat 2: Test Pass Rate */}
          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800/80">
            <div className="flex items-center justify-between text-zinc-400 font-mono text-xs mb-2">
              <span>Test Pass Rate</span>
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="text-2xl font-bold text-zinc-100 font-mono">
              {testPassRate}%
            </div>
            <p className="mt-3 text-[11px] text-emerald-400 font-mono flex items-center gap-1">
              <ShieldCheck className="h-3 w-3" />
              <span>{passedSubmissions.length} of {totalSubmissions} passed suite</span>
            </p>
          </div>

          {/* Stat 3: Avg Code Quality */}
          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800/80">
            <div className="flex items-center justify-between text-zinc-400 font-mono text-xs mb-2">
              <span>Avg Code Review</span>
              <Award className="h-4 w-4 text-amber-400" />
            </div>
            <div className="text-2xl font-bold text-zinc-100 font-mono">
              {avgQuality} <span className="text-xs text-zinc-500 font-normal">/ 40</span>
            </div>
            <p className="mt-3 text-[11px] text-amber-400/90 font-mono">
              Senior PR reviewer score average
            </p>
          </div>

          {/* Stat 4: Engineering Level */}
          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800/80">
            <div className="flex items-center justify-between text-zinc-400 font-mono text-xs mb-2">
              <span>Engineering Tier</span>
              <Flame className="h-4 w-4 text-purple-400" />
            </div>
            <div className="text-2xl font-bold text-zinc-100 font-mono">
              Tier {profile.current_difficulty_tier || 1}
            </div>
            <p className="mt-3 text-[11px] text-purple-300 font-mono">
              Role: {profile.skill_level || 'Beginner'}
            </p>
          </div>
        </div>

        {/* Ticket Submission History Table */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold text-zinc-100 tracking-tight">
                Completed Ticket History
              </h3>
              <p className="text-xs text-zinc-400 font-mono mt-0.5">
                Past engineering submissions and code review feedback
              </p>
            </div>
            {totalSubmissions > 0 && (
              <Link href="/progress">
                <button className="text-xs font-mono text-cyan-400 hover:underline flex items-center gap-1">
                  <span>View Progression Analytics</span>
                  <ArrowRight className="h-3 w-3" />
                </button>
              </Link>
            )}
          </div>

          {totalSubmissions > 0 ? (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden shadow-lg">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-zinc-950/80 border-b border-zinc-800 text-zinc-400 uppercase tracking-wider">
                  <tr>
                    <th className="p-4">Ticket ID</th>
                    <th className="p-4">Specification Title</th>
                    <th className="p-4">Type</th>
                    <th className="p-4">Submitted Date</th>
                    <th className="p-4">Status</th>
                    <th className="p-4 text-right">Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60">
                  {safeSubmissions.map((sub: any) => {
                    const ticketId = formatTicketId(sub.task_id);
                    const isPassed = (sub.correctness_score || 0) >= 40;
                    return (
                      <tr key={sub.submission_id} className="hover:bg-zinc-800/40 transition-colors">
                        <td className="p-4 font-bold text-cyan-400">
                          {sub.tasks?.task_id ? (
                            <Link href={`/tasks/${sub.tasks.task_id}`} className="hover:underline">
                              {ticketId}
                            </Link>
                          ) : (
                            ticketId
                          )}
                        </td>
                        <td className="p-4 text-zinc-200 font-sans font-medium">
                          {sub.tasks?.title || 'System Ticket'}
                        </td>
                        <td className="p-4 text-zinc-400">
                          <span className="px-2 py-0.5 rounded bg-zinc-800 text-[10px]">
                            {sub.tasks?.task_type || 'bug-fix'}
                          </span>
                        </td>
                        <td className="p-4 text-zinc-400">
                          {new Date(sub.created_at).toLocaleDateString()}
                        </td>
                        <td className="p-4">
                          <StatusBadge 
                            status={isPassed ? 'passed' : 'failed'} 
                            label={isPassed ? 'Passed' : 'Needs Work'} 
                          />
                        </td>
                        <td className="p-4 text-right font-bold text-zinc-100 text-sm">
                          {sub.total_score} <span className="text-xs text-zinc-500 font-normal">/ 100</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-12 rounded-xl border border-zinc-800/80 bg-zinc-900/30 text-center font-mono space-y-3">
              <AlertCircle className="h-8 w-8 text-zinc-500 mx-auto" />
              <h4 className="text-zinc-200 font-semibold text-sm">No engineering history yet</h4>
              <p className="text-xs text-zinc-400 max-w-md mx-auto">
                You are currently between assignments. Click "Pick Up Next Ticket" above to assign your first ticket.
              </p>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
