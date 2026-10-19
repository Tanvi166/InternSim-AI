'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'

function formatAuthError(error: any): string {
  if (!error) return 'An unknown authentication error occurred'
  const msg = error.message || String(error)
  if (msg.toLowerCase().includes('fetch failed') || msg.toLowerCase().includes('failed to fetch')) {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL || 'unconfigured URL'
    return `Unable to connect to Supabase backend at ${supabaseUrl}. Please verify your network connection and check NEXT_PUBLIC_SUPABASE_URL in .env.local.`
  }
  return msg
}

export async function login(formData: FormData) {
  try {
    const supabase = await createClient()

    const data = {
      email: formData.get('email') as string,
      password: formData.get('password') as string,
    }

    const { error } = await supabase.auth.signInWithPassword(data)

    if (error) {
      console.error('[AUTH LOGIN ERROR]:', error.message, error)
      const userMsg = formatAuthError(error)
      redirect(`/login?error=${encodeURIComponent(userMsg)}`)
    }

    // Check if they have a profile
    const { data: userData } = await supabase.auth.getUser()
    if (userData.user) {
      const { data: profile } = await supabase
        .from('profiles')
        .select('id')
        .eq('id', userData.user.id)
        .single()

      if (!profile) {
        redirect('/onboarding')
      }
    }

    revalidatePath('/', 'layout')
    redirect('/dashboard')
  } catch (err: any) {
    if (err?.digest?.startsWith('NEXT_REDIRECT')) {
      throw err
    }
    console.error('[AUTH LOGIN UNHANDLED ERROR]:', err)
    const userMsg = formatAuthError(err)
    redirect(`/login?error=${encodeURIComponent(userMsg)}`)
  }
}

export async function signup(formData: FormData) {
  try {
    const supabase = await createClient()

    const data = {
      email: formData.get('email') as string,
      password: formData.get('password') as string,
    }

    const { error } = await supabase.auth.signUp(data)

    if (error) {
      console.error('[AUTH SIGNUP ERROR]:', error.message, error)
      const userMsg = formatAuthError(error)
      redirect(`/login?error=${encodeURIComponent(userMsg)}`)
    }

    revalidatePath('/', 'layout')
    redirect('/onboarding')
  } catch (err: any) {
    if (err?.digest?.startsWith('NEXT_REDIRECT')) {
      throw err
    }
    console.error('[AUTH SIGNUP UNHANDLED ERROR]:', err)
    const userMsg = formatAuthError(err)
    redirect(`/login?error=${encodeURIComponent(userMsg)}`)
  }
}
