import { completeOnboarding } from './actions';
import { OnboardingForm } from './OnboardingForm';
import { createClient } from '@/utils/supabase/server';
import { redirect } from 'next/navigation';

export default async function OnboardingPage(props: {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }> | { [key: string]: string | string[] | undefined };
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  
  if (!user) {
    redirect('/login');
  }

  const { data: profile } = await supabase.from('profiles').select('id').eq('id', user.id).single();
  
  if (profile) {
    // Already onboarded
    redirect('/dashboard');
  }

  const searchParams = props.searchParams ? await Promise.resolve(props.searchParams) : {};
  const error = typeof searchParams?.error === 'string' ? searchParams.error : undefined;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-4 md:p-8 selection:bg-cyan-500 selection:text-black">
      <OnboardingForm
        initialError={error}
        completeOnboardingAction={completeOnboarding}
      />
    </div>
  );
}
