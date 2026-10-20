import TaskEditor from './TaskEditor';
import { createClient } from '@/utils/supabase/server';
import { redirect, notFound } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { getPersonaConfig } from '@/lib/companyConfig';

export default async function TaskPage(props: { params?: Promise<{ taskId: string }> | { taskId: string } }) {
  const params = props.params ? await Promise.resolve(props.params) : { taskId: '' };
  const taskId = params.taskId;
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  
  if (!user) {
    redirect('/login');
  }

  // Fetch profile
  const { data: profile } = await supabase.from('profiles').select('*').eq('id', user.id).single();
  const personaConfig = getPersonaConfig(profile?.chosen_persona);

  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
  const res = await fetch(`${apiUrl}/api/tasks/${taskId}`, { headers, cache: 'no-store' });
  
  if (!res.ok) {
    if (res.status === 404) return notFound();
    if (res.status === 403) redirect('/dashboard');
    throw new Error('Failed to load task');
  }

  const task = await res.json();

  // Fetch latest submission for this user and task
  const { data: latestSubmission } = await supabase
    .from('submissions')
    .select('submission_id, submitted_code, correctness_score, quality_score, total_score, feedback, created_at')
    .eq('user_id', user.id)
    .eq('task_id', taskId)
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle();

  return (
    <AppShell
      userEmail={user.email}
      userSkill={profile?.skill_level}
      userPersona={personaConfig.teamName}
    >
      <div className="space-y-6">
        <TaskEditor
          task={task}
          userId={user.id}
          initialSubmission={latestSubmission}
        />
      </div>
    </AppShell>
  );
}
