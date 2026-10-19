'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { PlusCircle, Loader2, ArrowRight } from 'lucide-react';
import { createClient } from '@/utils/supabase/client';

interface GenerateTaskButtonProps {
  skillLevel: string;
  persona: string;
  difficultyLevel?: number;
  projectId?: string;
  variant?: 'primary' | 'secondary';
  label?: string;
  className?: string;
}

export default function GenerateTaskButton({
  skillLevel,
  persona,
  difficultyLevel = 1,
  projectId,
  variant = 'primary',
  label = 'Pick Up Next Ticket',
  className = ''
}: GenerateTaskButtonProps) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleGenerate = async () => {
    setLoading(true);
    toast.info('Generating ticket specification...', {
      description: 'Creating ticket & hidden unit tests with AI Engine',
    });

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;

      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const res = await fetch(`${apiUrl}/api/tasks/generate`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          skill_level: skillLevel,
          persona: persona,
          difficulty_level: difficultyLevel,
          task_type: Math.random() > 0.5 ? 'bug-fix' : 'feature-dev',
          language: 'python',
          project_id: projectId || undefined,
          include_continuity: true
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to generate ticket');
      }

      const data = await res.json();
      toast.success('Ticket Assigned!', {
        description: `Ticket PLAT-${data.task_id.replace(/[^a-zA-Z0-9]/g, '').slice(-4).toUpperCase()} ready for investigation`,
      });
      router.push(`/tasks/${data.task_id}`);
    } catch (err: unknown) {
      console.error('Task generation error:', err);
      const errMsg = err instanceof Error ? err.message : 'Failed to generate ticket. Ensure backend is running.';
      toast.error('Ticket Generation Failed', { description: errMsg });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      onClick={handleGenerate}
      disabled={loading}
      className={
        variant === 'primary'
          ? `bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs h-10 px-5 gap-2 shadow-lg shadow-cyan-500/20 ${className}`
          : `bg-zinc-900 hover:bg-zinc-800 text-zinc-100 border border-zinc-800 hover:border-zinc-700 text-xs h-9 px-4 gap-2 ${className}`
      }
    >
      {loading ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Generating Ticket...</span>
        </>
      ) : (
        <>
          <PlusCircle className="h-4 w-4" />
          <span>{label}</span>
          <ArrowRight className="h-3.5 w-3.5 opacity-70" />
        </>
      )}
    </Button>
  );
}
