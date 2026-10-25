import { redirect } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { createClient } from '@/utils/supabase/server';
import StudentRepositoryWorkspace from './StudentRepositoryWorkspace';

export default async function StudentRepositoryWorkspacePage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect('/login');

  return (
    <AppShell userEmail={user.email}>
      <StudentRepositoryWorkspace userId={user.id} />
    </AppShell>
  );
}
