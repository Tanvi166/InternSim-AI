import { createClient } from '@/utils/supabase/server';
import { redirect } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { getPersonaConfig, getSprintMetrics } from '@/lib/companyConfig';
import ProgressCharts from './ProgressCharts';
import { 
  TrendingUp, 
  Award, 
  CheckCircle2, 
  ShieldCheck, 
  Terminal, 
  Layers,
  Sparkles,
  BarChart3
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

  // Fetch submissions
  const { data: submissions } = await supabase
    .from('submissions')
    .select(`
      submission_id,
      correctness_score,
      quality_score,
      total_score,
      created_at,
      tasks (
        title,
        task_type
      )
    `)
    .eq('user_id', user.id)
    .order('created_at', { ascending: true });

  const personaConfig = getPersonaConfig(profile.chosen_persona);
  const totalSubmissions = submissions?.length || 0;
  const { sprint, sprintProgress } = getSprintMetrics(totalSubmissions);

  // Derived metrics
  const safeSubmissions = submissions || [];
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
              Engineering Skill Progression
            </h1>
            <p className="text-xs text-zinc-400 font-mono mt-1">
              Real-time analytics computed across {totalSubmissions} completed sprint tickets.
            </p>
          </div>

          <div className="flex items-center gap-2 font-mono text-xs">
            <span className="px-3 py-1 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 font-semibold">
              Sprint {sprint} Active
            </span>
          </div>
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
              Tier {profile.current_difficulty_tier || 1}
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
