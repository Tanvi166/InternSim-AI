'use client';

import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Terminal, Lock, Mail, ArrowRight, ShieldCheck, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface AuthFormProps {
  initialError?: string;
  loginAction: (formData: FormData) => Promise<void>;
  signupAction: (formData: FormData) => Promise<void>;
}

export function AuthForm({ initialError, loginAction, signupAction }: AuthFormProps) {
  const [activeTab, setActiveTab] = useState<'login' | 'signup'>('login');
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    if (initialError) {
      toast.error('Authentication Error', {
        description: initialError,
        duration: 5000,
      });
    }
  }, [initialError]);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    setLoading(true);
  };

  return (
    <div className="w-full max-w-md bg-zinc-900/90 border border-zinc-800 rounded-xl shadow-2xl overflow-hidden backdrop-blur-md">
      {/* Header */}
      <div className="p-6 border-b border-zinc-800/80 bg-zinc-950/60 text-center">
        <div className="mx-auto h-10 w-10 rounded-xl bg-zinc-900 border border-zinc-700/80 flex items-center justify-center text-cyan-400 mb-3 shadow-inner">
          <Terminal className="h-5 w-5" />
        </div>
        <h2 className="text-xl font-bold text-zinc-100 tracking-tight">
          Nexora Platform Engineering
        </h2>
        <p className="text-xs text-zinc-400 font-mono mt-1">
          Access your virtual engineering workspace
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-zinc-800 bg-zinc-950/30 font-mono text-xs">
        <button
          type="button"
          onClick={() => setActiveTab('login')}
          className={`flex-1 py-3 text-center font-medium transition-colors border-b-2 ${
            activeTab === 'login'
              ? 'border-cyan-400 text-cyan-400 bg-zinc-900/40'
              : 'border-transparent text-zinc-400 hover:text-zinc-200'
          }`}
        >
          Sign In
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('signup')}
          className={`flex-1 py-3 text-center font-medium transition-colors border-b-2 ${
            activeTab === 'signup'
              ? 'border-cyan-400 text-cyan-400 bg-zinc-900/40'
              : 'border-transparent text-zinc-400 hover:text-zinc-200'
          }`}
        >
          Create Account
        </button>
      </div>

      {/* Form */}
      <form
        action={activeTab === 'login' ? loginAction : signupAction}
        onSubmit={handleSubmit}
        className="p-6 space-y-4"
      >
        {initialError && (
          <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-rose-300 text-xs font-mono">
            {initialError}
          </div>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="email" className="text-xs text-zinc-300 font-mono">
            Work Email
          </Label>
          <div className="relative">
            <Mail className="absolute left-3 top-2.5 h-4 w-4 text-zinc-500" />
            <Input
              id="email"
              name="email"
              type="email"
              placeholder="engineer@nexora.internal"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="pl-9 bg-zinc-950 border-zinc-800 focus:border-cyan-500/80 text-zinc-100 text-xs font-mono placeholder:text-zinc-600 h-9"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password" className="text-xs text-zinc-300 font-mono">
            Password
          </Label>
          <div className="relative">
            <Lock className="absolute left-3 top-2.5 h-4 w-4 text-zinc-500" />
            <Input
              id="password"
              name="password"
              type="password"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="pl-9 bg-zinc-950 border-zinc-800 focus:border-cyan-500/80 text-zinc-100 text-xs font-mono placeholder:text-zinc-600 h-9"
            />
          </div>
        </div>

        <Button
          type="submit"
          disabled={loading}
          className="w-full bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs h-9 mt-2 gap-2 shadow-lg shadow-cyan-500/15"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Authenticating...</span>
            </>
          ) : activeTab === 'login' ? (
            <>
              <span>Sign In to Workspace</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </>
          ) : (
            <>
              <span>Join Nexora Platform</span>
              <ShieldCheck className="h-3.5 w-3.5" />
            </>
          )}
        </Button>
      </form>

      <div className="px-6 py-3 bg-zinc-950/60 border-t border-zinc-800/60 text-center">
        <p className="text-[11px] text-zinc-400 font-mono">
          Protected by Nexora Enterprise Auth & SSO Policy
        </p>
      </div>
    </div>
  );
}
