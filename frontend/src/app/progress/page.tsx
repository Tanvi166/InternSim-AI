import { createClient } from '@/utils/supabase/server';
import { redirect } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { getPersonaConfig, getSprintMetrics, formatTicketId } from '@/lib/companyConfig';
import ProgressCharts from './ProgressCharts';
import Link from 'next/link';
import { 
  TrendingUp, 
  Award, 
  CheckCircle2, 
  ShieldCheck, 
  Terminal, 
  Layers,
  Sparkles,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  HelpCircle,
  Briefcase,
  AlertCircle
} from 'lucide-react';

export default async function ProgressPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  
  if (!user) {
    redirect('/login');
  }

  // Fetch profile
  const { data: profile } = await supabase.from('profiles').select('*').eq('id', user.id).single();
  
  if (!profile) {
    redirect('/onboarding');
  }

  // Fetch all submissions for user
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
        task_type
      )
    `)
    .eq('user_id', user.id)
    .order('created_at', { ascending: true });

  const safeSubmissions = submissions || [];
  const totalSubmissions = safeSubmissions.length;
  const personaConfig = getPersonaConfig(profile.chosen_persona);
  const { sprint, sprintProgress } = getSprintMetrics(totalSubmissions);

  // Fetch active project
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
    console.warn('Could not fetch active project on progress page:', err);
  }

  // --- ADAPTIVE DIFFICULTY ENGINE CLIENT COMPUTATION ---
  // Extract distinct eligible submissions (passed: correctness_score >= 40, deduplicating multiple attempts)
  // Sort descending to get latest distinct tickets
  const sortedDesc = [...safeSubmissions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  const seenTaskIds = new Set<string>();
  const distinctEligible: any[] = [];
  for (const sub of sortedDesc) {
    const taskId = sub.task_id;
    if (taskId && !seenTaskIds.has(taskId)) {
      if ((sub.correctness_score || 0) >= 40) {
        seenTaskIds.add(taskId);
        distinctEligible.push(sub);
      }
    }
  }

  const currentTier = profile.current_difficulty_tier || 1;
  const ROLLING_WINDOW = 3;
  const PROMOTION_THRESHOLD = 75.0;
  const DEMOTION_THRESHOLD = 50.0;
  const MAX_TIER = 5;
  const MIN_TIER = 1;

  const eligibleWindow = distinctEligible.slice(0, ROLLING_WINDOW);
  const hasSufficientData = eligibleWindow.length >= ROLLING_WINDOW;
  
  let rollingAvg: number | null = null;
  let tierStatus: 'promoted' | 'demoted' | 'unchanged' | 'insufficient' = 'insufficient';
  let tierStatusMessage = '';

  if (hasSufficientData) {
    const sum = eligibleWindow.reduce((acc, cur) => acc + (cur.total_score || 0), 0);
    rollingAvg = Math.round((sum / ROLLING_WINDOW) * 10) / 10;

    if (rollingAvg >= PROMOTION_THRESHOLD) {
      if (currentTier >= MAX_TIER) {
        tierStatus = 'unchanged';
        tierStatusMessage = `Performance is exceptional (${rollingAvg}/100), already at maximum Tier ${MAX_TIER}.`;
      } else {
        tierStatus = 'promoted';
        tierStatusMessage = `Eligible for Tier ${currentTier + 1}: Rolling average of last 3 tickets is ${rollingAvg}/100 (>= 75.0).`;
      }
    } else if (rollingAvg < DEMOTION_THRESHOLD) {
      if (currentTier <= MIN_TIER) {
        tierStatus = 'unchanged';
        tierStatusMessage = `Rolling average is ${rollingAvg}/100, currently at base Tier ${MIN_TIER}.`;
      } else {
        tierStatus = 'demoted';
        tierStatusMessage = `Tier reduced to ${currentTier - 1}: Rolling average dropped to ${rollingAvg}/100 (< 50.0).`;
      }
    } else {
      tierStatus = 'unchanged';
      tierStatusMessage = `Tier ${currentTier} maintained: Rolling average is ${rollingAvg}/100 (stable in 50.0 - 74.9 range).`;
    }
  } else {
    tierStatus = 'insufficient';
    tierStatusMessage = `Requires ${ROLLING_WINDOW} distinct passed tickets to evaluate progression (currently ${distinctEligible.length} of ${ROLLING_WINDOW}).`;
  }

  // General metrics
  const avgScore = totalSubmissions > 0 
    ? Math.round(safeSubmissions.reduce((acc: number, cur: any) => acc + (cur.total_score || 0), 0) / totalSubmissions) 
    : 0;

  const avgCorrectness = totalSubmissions > 0 
    ? Math.round(safeSubmissions.reduce((acc: number, cur: any) => acc + (cur.correctness_score || 0), 0) / totalSubmissions) 
    : 0;

  const avgQuality = totalSubmissions > 0 
    ? Math.round(safeSubmissions.reduce((acc: number, cur: any) => acc + (cur.quality_score || 0), 0) / totalSubmissions) 
    : 0;

  return (
    <AppShell
      userEmail={user.email}
      userSkill={profile.skill_level}
      userPersona={personaConfig.teamName}
    >
      <div className="space-y-8 pb-12">
        {/* Header */}
        <div className="p-6 rounded-xl bg-zinc-900/80 border border-zinc-800/80 backdrop-blur-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-mono text-cyan-400 mb-1">
              <TrendingUp className="h-3.5 w-3.5" />
              <span>Engineering Progression Analytics</span>
            </div>
            <h1 className="text-2xl font-bold text-zinc-100 tracking-tight">
              Adaptive Difficulty & Skill Progression
            </h1>
            <p className="text-xs text-zinc-400 font-mono mt-1">
              Dynamic difficulty adapting to your rolling code review and test performance.
            </p>
          </div>

          <div className="flex items-center gap-2 font-mono text-xs">
            <span className="px-3 py-1 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 font-semibold">
              Sprint {sprint} Active
            </span>
          </div>
        </div>

        {/* Adaptive Difficulty Status Card */}
        <div className="p-6 rounded-xl bg-zinc-900/60 border border-zinc-800 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-zinc-800/80 pb-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-lg bg-purple-950/60 border border-purple-800/80 text-purple-400">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <span className="text-[10px] uppercase font-mono tracking-wider text-purple-400 font-bold block">
                  Adaptive Engine Status
                </span>
                <h3 className="text-base font-bold text-zinc-100">
                  Engineering Difficulty Tier {currentTier} of {MAX_TIER}
                </h3>
              </div>
            </div>

            <div className="flex items-center gap-2 font-mono text-xs">
              {tierStatus === 'promoted' && (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800 font-semibold">
                  <ArrowUpRight className="h-3.5 w-3.5" />
                  Tier Promoted
                </span>
              )}
              {tierStatus === 'demoted' && (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-rose-950 text-rose-400 border border-rose-800 font-semibold">
                  <ArrowDownRight className="h-3.5 w-3.5" />
                  Tier Adjusted
                </span>
              )}
              {tierStatus === 'unchanged' && (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-cyan-950 text-cyan-400 border border-cyan-800 font-semibold">
                  <Minus className="h-3.5 w-3.5" />
                  Tier Stable
                </span>
              )}
              {tierStatus === 'insufficient' && (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700 font-semibold">
                  <HelpCircle className="h-3.5 w-3.5" />
                  Gathering Data ({distinctEligible.length}/{ROLLING_WINDOW})
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
            <div className="p-4 rounded-lg bg-zinc-950/60 border border-zinc-800">
              <span className="text-zinc-500 block mb-1">Rolling 3-Ticket Average</span>
              <div className="text-2xl font-bold text-zinc-100">
                {rollingAvg !== null ? (
                  <>
                    <span className={rollingAvg >= 75 ? 'text-emerald-400' : rollingAvg < 50 ? 'text-rose-400' : 'text-cyan-400'}>
                      {rollingAvg}
                    </span>
                    <span className="text-xs text-zinc-500 font-normal"> / 100</span>
                  </>
                ) : (
                  <span className="text-zinc-500 text-base">Pending ({distinctEligible.length}/3)</span>
                )}
              </div>
              <span className="text-[11px] text-zinc-500 mt-1 block">
                Target: &ge; 75.0 for promotion, &lt; 50.0 for adjustment
              </span>
            </div>

            <div className="p-4 rounded-lg bg-zinc-950/60 border border-zinc-800">
              <span className="text-zinc-500 block mb-1">Eligible Completed Tickets</span>
              <div className="text-2xl font-bold text-purple-400">
                {distinctEligible.length} <span className="text-xs text-zinc-500 font-normal">distinct passed</span>
              </div>
              <span className="text-[11px] text-zinc-500 mt-1 block">
                Failed attempts & duplicate retries are deduplicated
              </span>
            </div>

            <div className="p-4 rounded-lg bg-zinc-950/60 border border-zinc-800">
              <span className="text-zinc-500 block mb-1">Active Project Milestones</span>
              <div className="text-2xl font-bold text-cyan-400">
                {activeProject ? (
                  <>
                    {activeProject.completed_tickets_count} <span className="text-xs text-zinc-500 font-normal">/ {activeProject.target_tickets} tickets</span>
                  </>
                ) : (
                  <span className="text-zinc-500 text-base">No active project</span>
                )}
              </div>
              <span className="text-[11px] text-zinc-500 mt-1 block">
                {activeProject?.title || 'Auto-provisions on ticket pickup'}
              </span>
            </div>
          </div>

          <div className="p-3.5 rounded-lg bg-zinc-950/70 border border-zinc-800/80 text-xs font-mono flex items-start gap-2.5">
            <AlertCircle className="h-4 w-4 text-cyan-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="text-zinc-200">
                <span className="font-semibold text-cyan-400">Adaptive Policy:</span> {tierStatusMessage}
              </p>
              <p className="text-zinc-400 text-[11px] leading-relaxed">
                Difficulty promotes at rolling score &ge; 75/100 across 3 distinct passed tickets. A stability buffer between 50 and 75 prevents oscillation. Newly generated tickets are automatically calibrated to your active tier.
              </p>
            </div>
          </div>
        </div>

        {/* Recent Eligible Tickets Table */}
        <div className="p-6 rounded-xl bg-zinc-900/60 border border-zinc-800 space-y-4 font-mono">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-zinc-100 tracking-tight">
                Recent Evaluated Sprint Tickets (Rolling Window)
              </h3>
              <p className="text-xs text-zinc-400 mt-0.5">
                Latest distinct tickets factored into your adaptive difficulty tier
              </p>
            </div>
            <span className="text-xs text-zinc-500">
              Window: Last {Math.min(distinctEligible.length, ROLLING_WINDOW)} of {distinctEligible.length} completed
            </span>
          </div>

          {distinctEligible.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-500">
                    <th className="pb-2 font-medium">Ticket ID</th>
                    <th className="pb-2 font-medium">Title</th>
                    <th className="pb-2 font-medium">Correctness (60)</th>
                    <th className="pb-2 font-medium">Code Quality (40)</th>
                    <th className="pb-2 font-medium">Total Score</th>
                    <th className="pb-2 font-medium text-right">Window Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60">
                  {distinctEligible.slice(0, 5).map((sub, idx) => {
                    const isInWindow = idx < ROLLING_WINDOW;
                    return (
                      <tr key={sub.submission_id} className={isInWindow ? 'text-zinc-200' : 'text-zinc-500'}>
                        <td className="py-2.5 font-bold text-cyan-400">
                          {formatTicketId(sub.task_id)}
                        </td>
                        <td className="py-2.5 max-w-xs truncate font-sans">
                          {sub.tasks?.title || 'Sprint Ticket'}
                        </td>
                        <td className="py-2.5 text-emerald-400 font-semibold">
                          {sub.correctness_score}/60
                        </td>
                        <td className="py-2.5 text-amber-400 font-semibold">
                          {sub.quality_score}/40
                        </td>
                        <td className="py-2.5 font-bold">
                          <span className={sub.total_score >= 75 ? 'text-emerald-400' : sub.total_score < 50 ? 'text-rose-400' : 'text-zinc-200'}>
                            {sub.total_score}
                          </span>
                          <span className="text-zinc-600 font-normal"> / 100</span>
                        </td>
                        <td className="py-2.5 text-right">
                          {isInWindow ? (
                            <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 text-[10px] font-semibold">
                              ACTIVE IN ROLLING AVG
                            </span>
                          ) : (
                            <span className="text-zinc-600 text-[10px]">
                              Historical
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-zinc-500">
              No passed tickets yet. Complete sprint tickets with correctness score &ge; 40 to enter the adaptive window.
            </div>
          )}
        </div>

        {/* Top Summary Stat Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800">
            <span className="text-xs text-zinc-400 font-mono">Overall Avg Score</span>
            <div className="text-3xl font-bold font-mono text-cyan-400 mt-1">
              {avgScore} <span className="text-xs text-zinc-500 font-normal">/ 100</span>
            </div>
          </div>

          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800">
            <span className="text-xs text-zinc-400 font-mono">Correctness Avg</span>
            <div className="text-3xl font-bold font-mono text-emerald-400 mt-1">
              {avgCorrectness} <span className="text-xs text-zinc-500 font-normal">/ 60</span>
            </div>
          </div>

          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800">
            <span className="text-xs text-zinc-400 font-mono">Code Quality Avg</span>
            <div className="text-3xl font-bold font-mono text-amber-400 mt-1">
              {avgQuality} <span className="text-xs text-zinc-500 font-normal">/ 40</span>
            </div>
          </div>

          <div className="p-5 rounded-xl bg-zinc-900/60 border border-zinc-800">
            <span className="text-xs text-zinc-400 font-mono">Engineering Tier</span>
            <div className="text-3xl font-bold font-mono text-purple-400 mt-1">
              Tier {currentTier}
            </div>
          </div>
        </div>

        {/* Charts & Analytics Section */}
        {totalSubmissions > 0 ? (
          <div className="space-y-8">
            <ProgressCharts submissions={safeSubmissions} />
          </div>
        ) : (
          <div className="p-12 rounded-xl border border-zinc-800 bg-zinc-900/30 text-center font-mono space-y-3">
            <BarChart3 className="h-8 w-8 text-zinc-500 mx-auto" />
            <h4 className="text-zinc-200 font-semibold text-sm">No progression data available yet</h4>
            <p className="text-xs text-zinc-400 max-w-md mx-auto">
              Complete your first sprint ticket in the workspace to start tracking skill progression analytics.
            </p>
          </div>
        )}
      </div>
    </AppShell>
  );
}
