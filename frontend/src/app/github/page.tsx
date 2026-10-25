import Link from 'next/link';
import { ArrowRight, GitBranch } from 'lucide-react';
import { redirect } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import GitHubConnectionPanel from '@/app/dashboard/GitHubConnectionPanel';
import { createClient } from '@/utils/supabase/server';

export default async function GitHubPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect('/login');

  const { data: profile } = await supabase.from('profiles').select('skill_level, chosen_persona').eq('id', user.id).single();
  if (!profile) redirect('/onboarding');

  return (
    <AppShell userEmail={user.email} userSkill={profile.skill_level} userPersona={profile.chosen_persona}>
      <div className="mx-auto max-w-6xl space-y-7">
        <header className="flex flex-col gap-4 border-b border-white/[0.07] pb-7 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-2 flex items-center gap-2 text-xs font-medium text-cyan-300"><GitBranch className="h-4 w-4" /> Account integration</p>
            <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-[2.15rem]">GitHub</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Connect your account, browse repositories you can access, and create a separate starter copy for the coding workspace.</p>
          </div>
          <Link href="/github/workspace" className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-xl border border-white/[0.09] bg-white/[0.04] px-4 text-xs font-medium text-slate-200 transition hover:bg-white/[0.08]">
            Open coding workspace <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </header>

        <GitHubConnectionPanel />

        <p className="text-xs leading-5 text-slate-500">Repository listing and branch creation use your connected GitHub account. The coding workspace runs against your own mapped starter fork; browsing an authorized repository does not copy or modify it.</p>
      </div>
    </AppShell>
  );
}
