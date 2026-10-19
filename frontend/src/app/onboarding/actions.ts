'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'

export async function completeOnboarding(formData: FormData) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  
  if (!user) {
    redirect('/login')
  }

  const skill_level = formData.get('skill_level') as string
  const chosen_persona = formData.get('persona') as string

  // Insert into public.profiles
  const { error } = await supabase
    .from('profiles')
    .insert({
      id: user.id,
      skill_level: skill_level,
      chosen_persona: chosen_persona,
      current_difficulty_tier: 1
    })

  if (error) {
    redirect('/onboarding?error=Failed to save profile. Please try again.')
  }

  revalidatePath('/', 'layout')
  redirect('/dashboard')
}
