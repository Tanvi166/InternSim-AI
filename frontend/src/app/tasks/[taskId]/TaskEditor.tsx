'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Editor from 'react-simple-code-editor';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/themes/prism.css';
import { toast } from 'sonner';
import { createClient } from '@/utils/supabase/client';
import { getPersonaConfig, formatTicketId } from '@/lib/companyConfig';
import { StatusBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import { 
  Terminal, 
  FileCode2, 
  Send, 
  CheckCircle2, 
  XCircle, 
  Clock, 
  AlertCircle, 
  GitPullRequest, 
  Loader2, 
  ShieldCheck, 
  Building2,
  Sparkles,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Cpu,
  Save,
  Play,
  FlaskConical
} from 'lucide-react';

interface InitialSubmissionData {
  submission_id?: string;
  submitted_code?: string;
  correctness_score?: number;
  quality_score?: number;
  total_score?: number;
  feedback?: any;
  created_at?: string;
}

interface TaskEditorProps {
  task: any;
  userId?: string;
  initialSubmission?: InitialSubmissionData | null;
}

export default function TaskEditor({ task, userId, initialSubmission }: TaskEditorProps) {
  const router = useRouter();

  // Draft storage key scoped to user and task
  const draftStorageKey = userId && task?.task_id ? `internsim_draft_${userId}_${task.task_id}` : null;

  // Determine initial code: latest submission submitted_code or starter_code
  const fallbackCode = initialSubmission?.submitted_code ?? (task.starter_code || '');

  const [code, setCode] = useState(fallbackCode);
  const [draftStatus, setDraftStatus] = useState<'idle' | 'restored' | 'saved'>('idle');
  const [loading, setLoading] = useState(false);
  const [pipelineStep, setPipelineStep] = useState<number>(0);
  const [result, setResult] = useState<any>(initialSubmission || null);

  // Ref to hold pending debounce timer across keystrokes
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);

  const [isRunningCode, setIsRunningCode] = useState(false);
  const [isRunningTests, setIsRunningTests] = useState(false);
  const [customStdin, setCustomStdin] = useState('');
  const [showStdinInput, setShowStdinInput] = useState(false);
  const [activeConsoleTab, setActiveConsoleTab] = useState<'terminal' | 'sampleTests'>('sampleTests');
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [terminalResult, setTerminalResult] = useState<{
    stdout?: string;
    stderr?: string;
    exit_code?: number;
    timed_out?: boolean;
    error?: string;
  } | null>(null);
  const [sampleTestResults, setSampleTestResults] = useState<{
    total_samples: number;
    passed_samples: number;
    results: Array<{
      index: number;
      input: any;
      expected_output: any;
      actual_output: any;
      passed: boolean;
      stderr?: string;
      error?: string;
    }>;
    raw_error?: string;
  } | null>(null);

  // Keyboard shortcut: Ctrl+Enter executes Run Sample Tests (or Run Code if terminal tab is active)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (activeConsoleTab === 'terminal') {
          handleRunCode();
        } else {
          handleRunSampleTests();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [code, customStdin, activeConsoleTab]);

  const handleRunCode = async () => {
    setIsRunningCode(true);
    setConsoleOpen(true);
    setActiveConsoleTab('terminal');

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const res = await fetch(`${apiUrl}/api/evaluations/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          language: task.language || 'python',
          code: code,
          stdin: customStdin
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Execution request failed');
      }

      const data = await res.json();
      setTerminalResult(data);
      if (data.exit_code === 0 && !data.error && !data.stderr) {
        toast.success('Execution Finished', { description: 'Process returned exit code 0.' });
      } else if (data.timed_out) {
        toast.error('Execution Timed Out', { description: 'Process exceeded time limit.' });
      } else {
        toast.warning('Execution Finished with Warnings/Errors', { description: `Exit code: ${data.exit_code}` });
      }
    } catch (err: unknown) {
      console.error('Run code error:', err);
      const errMsg = err instanceof Error ? err.message : 'Execution failed';
      setTerminalResult({
        error: errMsg,
        exit_code: 1
      });
      toast.error('Run Code Failed', { description: errMsg });
    } finally {
      setIsRunningCode(false);
    }
  };

  const handleRunSampleTests = async () => {
    setIsRunningTests(true);
    setConsoleOpen(true);
    setActiveConsoleTab('sampleTests');

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const res = await fetch(`${apiUrl}/api/evaluations/test-samples`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: task.task_id,
          code: code,
          language: task.language || 'python'
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Sample test execution failed');
      }

      const data = await res.json();
      setSampleTestResults(data);

      if (data.total_samples === 0) {
        toast.info('No sample tests available for this ticket.');
      } else if (data.passed_samples === data.total_samples) {
        toast.success(`All ${data.total_samples} Sample Tests Passed!`, {
          description: 'Ready to submit your code for senior review.'
        });
      } else {
        toast.warning(`${data.passed_samples}/${data.total_samples} Sample Tests Passed`, {
          description: 'Inspect output diffs and runtime logs below.'
        });
      }
    } catch (err: unknown) {
      console.error('Run sample tests error:', err);
      const errMsg = err instanceof Error ? err.message : 'Failed to execute sample tests';
      setSampleTestResults({
        total_samples: 0,
        passed_samples: 0,
        results: [],
        raw_error: errMsg
      });
      toast.error('Sample Tests Failed', { description: errMsg });
    } finally {
      setIsRunningTests(false);
    }
  };

  // Load unsaved draft on mount or when task/user changes
  useEffect(() => {
    // Clear any pending debounce from a previous task
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }

    if (!draftStorageKey) {
      setCode(fallbackCode);
      setDraftStatus('idle');
      return;
    }

    try {
      const savedDraft = window.localStorage.getItem(draftStorageKey);
      if (savedDraft !== null && savedDraft !== undefined && savedDraft !== fallbackCode) {
        setCode(savedDraft);
        setDraftStatus('restored');
      } else {
        setCode(fallbackCode);
        setDraftStatus('idle');
      }
    } catch (e) {
      console.warn('localStorage is unavailable for draft loading:', e);
      setCode(fallbackCode);
      setDraftStatus('idle');
    }
  }, [draftStorageKey, fallbackCode]);

  // Handler for user edits triggered exclusively from the code editor input
  const handleCodeChange = (newCode: string) => {
    setCode(newCode);

    if (!draftStorageKey) return;

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    debounceTimerRef.current = setTimeout(() => {
      try {
        window.localStorage.setItem(draftStorageKey, newCode);
        setDraftStatus('saved');
      } catch (e) {
        console.warn('localStorage is unavailable for draft saving:', e);
      }
    }, 400);
  };

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const ticketId = formatTicketId(task.task_id);
  const personaConfig = getPersonaConfig(task.persona);

  const handleSubmit = async () => {
    setLoading(true);
    setResult(null);
    setPipelineStep(1);

    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      toast.error('Authentication Required', { description: 'You must be logged in to create a submission.' });
      setLoading(false);
      setPipelineStep(0);
      return;
    }

    // Step 2: Running tests
    setTimeout(() => setPipelineStep(2), 600);
    // Step 3: Hidden tests
    setTimeout(() => setPipelineStep(3), 1200);
    // Step 4: AI Review
    setTimeout(() => setPipelineStep(4), 1800);

    try {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const res = await fetch(`${apiUrl}/api/evaluations/submit`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          task_id: task.task_id,
          user_id: user.id,
          submitted_code: code,
          language: task.language
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Submission processing failed');
      }

      const data = await res.json();
      setResult(data);

      // Clear the local draft now that submission has been persisted
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
      if (draftStorageKey) {
        try {
          window.localStorage.removeItem(draftStorageKey);
          setDraftStatus('idle');
        } catch (e) {
          console.warn('Could not clear draft from localStorage:', e);
        }
      }

      router.refresh();
      toast.success('Submission Evaluated!', {
        description: `Total Score: ${data.total_score}/100. PR Code Review Complete.`,
      });
    } catch (err: unknown) {
      console.error('Submission error:', err);
      const errMsg = err instanceof Error ? err.message : 'Failed to process submission. Check server connection.';
      toast.error('Submission Error', { description: errMsg });
    } finally {
      setLoading(false);
      setPipelineStep(0);
    }
  };

  // Derive acceptance criteria from description lines
  const descriptionLines = (task.description || '').split('\n').filter((l: string) => l.trim().length > 0);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      {/* LEFT PANEL: Ticket Specification (4 cols) */}
      <div className="lg:col-span-4 space-y-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/80 p-5 shadow-xl space-y-4">
          <div className="flex items-center justify-between font-mono text-xs pb-3 border-b border-zinc-800">
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 font-bold">
                {ticketId}
              </span>
              <span className="text-amber-400 font-semibold">P1 HIGH</span>
            </div>
            <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 uppercase text-[10px]">
              {task.task_type || 'bug-fix'}
            </span>
          </div>

          <div>
            <h2 className="text-lg font-bold text-zinc-100 tracking-tight">
              {task.title}
            </h2>
            <div className="flex items-center gap-2 mt-2 text-xs font-mono text-zinc-400">
              <Building2 className="h-3.5 w-3.5 text-cyan-400" />
              <span>{personaConfig.teamName}</span>
            </div>
          </div>

          <div className="space-y-2">
            <h4 className="text-xs font-mono uppercase text-zinc-400 font-semibold tracking-wider">
              Ticket Description
            </h4>
            <div className="p-3.5 rounded-lg bg-zinc-950/80 border border-zinc-800/80 text-xs text-zinc-300 leading-relaxed space-y-2 font-sans">
              {descriptionLines.map((line: string, i: number) => (
                <p key={i}>{line}</p>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <h4 className="text-xs font-mono uppercase text-zinc-400 font-semibold tracking-wider">
              Acceptance Criteria
            </h4>
            <ul className="space-y-1.5 font-mono text-[11px] text-zinc-300">
              <li className="flex items-start gap-2">
                <ChevronRight className="h-3.5 w-3.5 text-cyan-400 shrink-0 mt-0.5" />
                <span>Must pass 100% of visible and hidden unit test cases</span>
              </li>
              <li className="flex items-start gap-2">
                <ChevronRight className="h-3.5 w-3.5 text-cyan-400 shrink-0 mt-0.5" />
                <span>Adhere to {task.language?.toUpperCase() || 'PYTHON'} clean code & PEP8 guidelines</span>
              </li>
              <li className="flex items-start gap-2">
                <ChevronRight className="h-3.5 w-3.5 text-cyan-400 shrink-0 mt-0.5" />
                <span>Handle edge cases and avoid unnecessary global mutations</span>
              </li>
            </ul>
          </div>

          <div className="pt-3 border-t border-zinc-800/80 flex items-center justify-between text-xs font-mono text-zinc-400">
            <span>Engineering Tier: Lvl {task.difficulty_level || 1}</span>
            <span>Language: {task.language?.toUpperCase()}</span>
          </div>
        </div>
      </div>

      {/* CENTER PANEL: Code Editor (5 cols) */}
      <div className="lg:col-span-5 space-y-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/90 shadow-2xl overflow-hidden flex flex-col">
          {/* File Tab Bar */}
          <div className="h-10 bg-zinc-950 border-b border-zinc-800 px-4 flex items-center justify-between text-xs font-mono">
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-3 py-1 rounded-t-md bg-zinc-900 border-t-2 border-t-cyan-400 border-x border-zinc-800 text-zinc-100 font-medium">
                <FileCode2 className="h-3.5 w-3.5 text-cyan-400" />
                <span>{task.language === 'javascript' ? 'solution.js' : 'solution.py'}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {draftStatus === 'restored' && (
                <span className="flex items-center gap-1 text-[10px] text-amber-400/90 font-medium">
                  <Save className="h-3 w-3 text-amber-400" />
                  <span>Draft restored locally</span>
                </span>
              )}
              {draftStatus === 'saved' && (
                <span className="flex items-center gap-1 text-[10px] text-cyan-400/90 font-medium">
                  <Save className="h-3 w-3 text-cyan-400" />
                  <span>Draft saved locally</span>
                </span>
              )}
              <span className="text-[10px] text-zinc-500 uppercase">UTF-8 · Interactive Buffer</span>
            </div>
          </div>

          {/* Prism Code Editor container */}
          <div className="p-3 bg-zinc-950 min-h-[420px] font-mono text-xs">
            <Editor
              value={code}
              onValueChange={handleCodeChange}
              highlight={codeStr => Prism.highlight(
                codeStr, 
                Prism.languages[task.language === 'python' ? 'python' : 'javascript'] || Prism.languages.javascript, 
                task.language || 'python'
              )}
              padding={12}
              style={{
                fontFamily: '"Geist Mono", "Fira Code", monospace',
                fontSize: 13,
                minHeight: '400px',
                color: '#e4e4e7',
                backgroundColor: 'transparent'
              }}
            />
          </div>

          {/* Action Bar */}
          <div className="p-3 bg-zinc-950/90 border-t border-zinc-800 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleRunCode}
                disabled={isRunningCode || isRunningTests || loading}
                className="h-8 px-3 text-xs font-mono font-medium border-zinc-700 bg-zinc-900 hover:bg-zinc-800 text-zinc-200 gap-1.5 shadow-sm"
              >
                {isRunningCode ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />
                ) : (
                  <Play className="h-3.5 w-3.5 text-cyan-400 fill-cyan-400/20" />
                )}
                <span>Run Code</span>
              </Button>

              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleRunSampleTests}
                disabled={isRunningCode || isRunningTests || loading}
                className="h-8 px-3 text-xs font-mono font-medium border-cyan-800/60 bg-cyan-950/30 hover:bg-cyan-900/40 text-cyan-300 gap-1.5 shadow-sm"
              >
                {isRunningTests ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />
                ) : (
                  <FlaskConical className="h-3.5 w-3.5 text-cyan-400" />
                )}
                <span>Run Sample Tests</span>
              </Button>

              <button
                type="button"
                onClick={() => setConsoleOpen(!consoleOpen)}
                className={`text-[11px] font-mono px-2 py-1 rounded flex items-center gap-1 transition-colors ${
                  consoleOpen ? 'bg-zinc-800 text-zinc-200' : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                <Terminal className="h-3 w-3" />
                <span>Console</span>
                {consoleOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
              </button>
            </div>

            <div className="flex items-center gap-3">
              <span className="hidden sm:inline text-[11px] font-mono text-zinc-500">
                Ctrl+Enter
              </span>
              <Button
                onClick={handleSubmit}
                disabled={loading || isRunningCode || isRunningTests}
                className="bg-cyan-500 hover:bg-cyan-400 text-black font-bold text-xs h-8 px-4 gap-2 shadow-lg shadow-cyan-500/20"
              >
                {loading ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Evaluating...</span>
                  </>
                ) : (
                  <>
                    <Send className="h-3.5 w-3.5" />
                    <span>Submit PR</span>
                  </>
                )}
              </Button>
            </div>
          </div>

          {/* Collapsible Interactive Console Drawer */}
          {consoleOpen && (
            <div className="border-t border-zinc-800 bg-zinc-950 flex flex-col font-mono text-xs">
              {/* Console Tabs */}
              <div className="flex items-center justify-between border-b border-zinc-800/80 px-3 py-1.5 bg-zinc-900/60">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setActiveConsoleTab('sampleTests')}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs transition-colors ${
                      activeConsoleTab === 'sampleTests'
                        ? 'bg-zinc-800 text-cyan-300 font-semibold'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <FlaskConical className="h-3 w-3" />
                    <span>Sample Tests</span>
                    {sampleTestResults && (
                      <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                        sampleTestResults.passed_samples === sampleTestResults.total_samples
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : 'bg-rose-950 text-rose-400 border border-rose-800'
                      }`}>
                        {sampleTestResults.passed_samples}/{sampleTestResults.total_samples}
                      </span>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveConsoleTab('terminal')}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs transition-colors ${
                      activeConsoleTab === 'terminal'
                        ? 'bg-zinc-800 text-cyan-300 font-semibold'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <Terminal className="h-3 w-3" />
                    <span>Terminal Output</span>
                    {terminalResult && (
                      <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                        terminalResult.exit_code === 0 && !terminalResult.error && !terminalResult.stderr
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : 'bg-amber-950 text-amber-400 border border-amber-800'
                      }`}>
                        {terminalResult.exit_code === 0 ? 'exit 0' : `exit ${terminalResult.exit_code ?? 1}`}
                      </span>
                    )}
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  {activeConsoleTab === 'terminal' && (
                    <button
                      type="button"
                      onClick={() => setShowStdinInput(!showStdinInput)}
                      className="text-[10px] text-zinc-400 hover:text-zinc-200 underline"
                    >
                      {showStdinInput ? 'Hide Stdin' : 'Add Custom Stdin'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setConsoleOpen(false)}
                    className="text-zinc-500 hover:text-zinc-300 text-xs px-1"
                  >
                    ✕
                  </button>
                </div>
              </div>

              {/* Console Content Area */}
              <div className="p-3 max-h-[300px] overflow-y-auto space-y-3">
                {/* SAMPLE TESTS TAB */}
                {activeConsoleTab === 'sampleTests' && (
                  <div className="space-y-3">
                    {isRunningTests && (
                      <div className="flex items-center gap-2 text-cyan-400 py-4 justify-center">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span>Running sample test suite in sandbox...</span>
                      </div>
                    )}

                    {!isRunningTests && !sampleTestResults && (
                      <div className="text-zinc-500 text-center py-6">
                        Click <span className="text-cyan-400 font-semibold">"Run Sample Tests"</span> to evaluate visible test cases without submitting.
                      </div>
                    )}

                    {!isRunningTests && sampleTestResults?.raw_error && (
                      <div className="p-3 rounded bg-rose-950/40 border border-rose-800/80 text-rose-300">
                        <div className="flex items-center gap-1.5 font-bold mb-1">
                          <AlertCircle className="h-4 w-4 text-rose-400" />
                          <span>Execution Error</span>
                        </div>
                        <pre className="text-[11px] whitespace-pre-wrap font-mono overflow-x-auto">
                          {sampleTestResults.raw_error}
                        </pre>
                      </div>
                    )}

                    {!isRunningTests && sampleTestResults?.results && sampleTestResults.results.length > 0 && (
                      <div className="space-y-2">
                        {sampleTestResults.results.map((test) => (
                          <div
                            key={test.index}
                            className={`p-3 rounded-lg border transition-colors ${
                              test.passed
                                ? 'bg-zinc-900/60 border-emerald-900/40'
                                : 'bg-rose-950/20 border-rose-800/50'
                            }`}
                          >
                            <div className="flex items-center justify-between mb-2">
                              <span className="font-semibold text-zinc-200 flex items-center gap-1.5">
                                {test.passed ? (
                                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                                ) : (
                                  <XCircle className="h-3.5 w-3.5 text-rose-400" />
                                )}
                                <span>Sample Test #{test.index}</span>
                              </span>
                              <span
                                className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider ${
                                  test.passed
                                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                    : 'bg-rose-950 text-rose-400 border border-rose-800'
                                }`}
                              >
                                {test.passed ? 'PASSED' : 'FAILED'}
                              </span>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[11px]">
                              <div className="p-2 rounded bg-zinc-950 border border-zinc-800/80">
                                <span className="text-zinc-500 block text-[10px] uppercase font-semibold">Input:</span>
                                <pre className="text-zinc-300 whitespace-pre-wrap font-mono overflow-x-auto mt-0.5 max-h-24">
                                  {typeof test.input === 'object' ? JSON.stringify(test.input, null, 2) : String(test.input ?? '')}
                                </pre>
                              </div>

                              <div className="p-2 rounded bg-zinc-950 border border-zinc-800/80">
                                <span className="text-zinc-500 block text-[10px] uppercase font-semibold">Expected Output:</span>
                                <pre className="text-emerald-400 whitespace-pre-wrap font-mono overflow-x-auto mt-0.5 max-h-24">
                                  {typeof test.expected_output === 'object' ? JSON.stringify(test.expected_output, null, 2) : String(test.expected_output ?? '')}
                                </pre>
                              </div>

                              <div className="p-2 rounded bg-zinc-950 border border-zinc-800/80">
                                <span className="text-zinc-500 block text-[10px] uppercase font-semibold">Actual Output:</span>
                                <pre className={`${test.passed ? 'text-emerald-400' : 'text-rose-400'} whitespace-pre-wrap font-mono overflow-x-auto mt-0.5 max-h-24`}>
                                  {test.actual_output !== undefined && test.actual_output !== null && test.actual_output !== ''
                                    ? (typeof test.actual_output === 'object' ? JSON.stringify(test.actual_output, null, 2) : String(test.actual_output))
                                    : (test.error ? '(runtime error)' : (test.actual_output === '' ? '"" (empty string)' : 'None'))}
                                </pre>
                              </div>
                            </div>

                            {(test.error || test.stderr) && (
                              <div className="mt-2 p-2 rounded bg-zinc-950 border border-rose-900/60 text-rose-300 text-[10px]">
                                <span className="font-semibold block uppercase text-rose-400">Traceback / Errors:</span>
                                <pre className="whitespace-pre-wrap mt-0.5 overflow-x-auto max-h-32">
                                  {test.error || test.stderr}
                                </pre>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* TERMINAL OUTPUT TAB */}
                {activeConsoleTab === 'terminal' && (
                  <div className="space-y-3">
                    {showStdinInput && (
                      <div className="space-y-1 p-2 rounded bg-zinc-900 border border-zinc-800">
                        <span className="text-[10px] text-zinc-400 font-semibold uppercase">Custom Standard Input (stdin):</span>
                        <textarea
                          value={customStdin}
                          onChange={(e) => setCustomStdin(e.target.value)}
                          placeholder="Provide input line by line..."
                          rows={2}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded p-1.5 text-xs text-zinc-200 font-mono focus:outline-none focus:border-cyan-500"
                        />
                      </div>
                    )}

                    {isRunningCode && (
                      <div className="flex items-center gap-2 text-cyan-400 py-4 justify-center">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span>Executing code in sandbox...</span>
                      </div>
                    )}

                    {!isRunningCode && !terminalResult && (
                      <div className="text-zinc-500 text-center py-6">
                        Click <span className="text-cyan-400 font-semibold">"Run Code"</span> to run exploratory execution without submitting.
                      </div>
                    )}

                    {!isRunningCode && terminalResult && (
                      <div className="space-y-2">
                        {terminalResult.timed_out && (
                          <div className="p-2 rounded bg-amber-950/40 border border-amber-800/80 text-amber-300 text-xs flex items-center gap-2">
                            <Clock className="h-4 w-4 text-amber-400" />
                            <span>Process execution timed out.</span>
                          </div>
                        )}

                        {terminalResult.error && (
                          <div className="p-2 rounded bg-rose-950/40 border border-rose-800/80 text-rose-300 text-xs">
                            <span className="font-bold">Error:</span> {terminalResult.error}
                          </div>
                        )}

                        {terminalResult.stdout && (
                          <div className="p-2.5 rounded bg-zinc-950 border border-zinc-800/80">
                            <span className="text-[10px] text-zinc-500 block uppercase font-semibold mb-1">Standard Output (stdout):</span>
                            <pre className="text-zinc-200 whitespace-pre-wrap font-mono text-[11px] overflow-x-auto max-h-48">
                              {terminalResult.stdout}
                            </pre>
                          </div>
                        )}

                        {terminalResult.stderr && (
                          <div className="p-2.5 rounded bg-rose-950/20 border border-rose-900/60">
                            <span className="text-[10px] text-rose-400 block uppercase font-semibold mb-1">Standard Error / Exceptions (stderr):</span>
                            <pre className="text-rose-300 whitespace-pre-wrap font-mono text-[11px] overflow-x-auto max-h-48">
                              {terminalResult.stderr}
                            </pre>
                          </div>
                        )}

                        {!terminalResult.stdout && !terminalResult.stderr && !terminalResult.error && (
                          <div className="p-3 rounded bg-zinc-950/80 border border-zinc-800 text-zinc-400 text-xs space-y-1">
                            <div className="flex items-center gap-1.5 text-emerald-400 font-semibold">
                              <CheckCircle2 className="h-4 w-4" />
                              <span>Execution Succeeded (Exit code 0)</span>
                            </div>
                            <p className="text-[11px] text-zinc-500">
                              Your code compiled and executed without errors. If you only defined functions or classes, add print statements or run <strong>Run Sample Tests</strong> to invoke them with test inputs.
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* RIGHT PANEL: Live Pipeline & Review Panel (3 cols) */}
      <div className="lg:col-span-3 space-y-4">
        {/* Animated Pipeline Status during submission */}
        {loading && (
          <div className="rounded-xl border border-cyan-500/40 bg-zinc-900/90 p-5 shadow-2xl space-y-4 font-mono text-xs animate-pulse">
            <div className="flex items-center gap-2 text-cyan-400 font-bold">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>CI/CD Evaluation Pipeline</span>
            </div>

            <div className="space-y-2">
              <div className={`p-2 rounded border ${pipelineStep >= 1 ? 'bg-cyan-950/50 border-cyan-800 text-cyan-300' : 'bg-zinc-950 border-zinc-800 text-zinc-500'}`}>
                1. Building AST Sandbox...
              </div>
              <div className={`p-2 rounded border ${pipelineStep >= 2 ? 'bg-cyan-950/50 border-cyan-800 text-cyan-300' : 'bg-zinc-950 border-zinc-800 text-zinc-500'}`}>
                2. Executing Piston Suite...
              </div>
              <div className={`p-2 rounded border ${pipelineStep >= 3 ? 'bg-cyan-950/50 border-cyan-800 text-cyan-300' : 'bg-zinc-950 border-zinc-800 text-zinc-500'}`}>
                3. Verifying Hidden Tests...
              </div>
              <div className={`p-2 rounded border ${pipelineStep >= 4 ? 'bg-cyan-950/50 border-cyan-800 text-cyan-300' : 'bg-zinc-950 border-zinc-800 text-zinc-500'}`}>
                4. Senior PR Review...
              </div>
            </div>
          </div>
        )}

        {/* Results Panel */}
        {result && (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/90 p-5 shadow-2xl space-y-5">
            {/* Total Score Ring Display */}
            <div className="text-center p-4 rounded-lg bg-zinc-950 border border-zinc-800">
              <span className="text-[11px] font-mono uppercase text-zinc-400 tracking-wider">
                Total Submission Score
              </span>
              <div className="text-3xl font-extrabold font-mono mt-1 text-zinc-100">
                <span className={result.total_score >= 80 ? 'text-emerald-400' : result.total_score >= 60 ? 'text-amber-400' : 'text-rose-400'}>
                  {result.total_score}
                </span>
                <span className="text-xs text-zinc-500 font-normal"> / 100</span>
              </div>

              {/* Progress Bar */}
              <div className="mt-3 w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
                <div 
                  className={`h-full rounded-full transition-all duration-700 ${
                    result.total_score >= 80 ? 'bg-emerald-400' : result.total_score >= 60 ? 'bg-amber-400' : 'bg-rose-400'
                  }`}
                  style={{ width: `${result.total_score}%` }}
                />
              </div>
            </div>

            {/* Sub-Score Breakdown Bars */}
            <div className="space-y-3 font-mono text-xs">
              <div>
                <div className="flex justify-between text-zinc-300 mb-1">
                  <span>Correctness Suite</span>
                  <span className="font-bold">{result.correctness_score} / 60</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                  <div 
                    className="bg-cyan-400 h-full rounded-full"
                    style={{ width: `${(result.correctness_score / 60) * 100}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-zinc-300 mb-1">
                  <span>Code Quality Rating</span>
                  <span className="font-bold">{result.quality_score} / 40</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                  <div 
                    className="bg-purple-400 h-full rounded-full"
                    style={{ width: `${(result.quality_score / 40) * 100}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Senior Engineer Code Review Card */}
            <div className="p-4 rounded-lg bg-zinc-950 border border-zinc-800 space-y-3">
              <div className="flex items-center gap-3 pb-3 border-b border-zinc-800/80">
                <img
                  src={personaConfig.avatarUrl}
                  alt={personaConfig.reviewerName}
                  className="h-9 w-9 rounded-full object-cover border border-zinc-700"
                />
                <div>
                  <h4 className="text-xs font-bold text-zinc-100">{personaConfig.reviewerName}</h4>
                  <p className="text-[10px] text-zinc-400 font-mono">{personaConfig.reviewerRole}</p>
                </div>
              </div>

              <div className="space-y-2">
                <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold">
                  Pull Request Review Feedback
                </span>
                <p className="text-xs text-zinc-300 leading-relaxed font-sans whitespace-pre-wrap">
                  {result.feedback?.comments}
                </p>
              </div>

              {/* Quality Metric Sub-Badges */}
              {result.feedback && (
                <div className="pt-2 grid grid-cols-2 gap-2 font-mono text-[10px]">
                  <div className="p-1.5 rounded bg-zinc-900 border border-zinc-800 flex justify-between">
                    <span className="text-zinc-400">Readability</span>
                    <span className="text-zinc-100 font-bold">{result.feedback.readability}/5</span>
                  </div>
                  <div className="p-1.5 rounded bg-zinc-900 border border-zinc-800 flex justify-between">
                    <span className="text-zinc-400">Structure</span>
                    <span className="text-zinc-100 font-bold">{result.feedback.structure}/5</span>
                  </div>
                  <div className="p-1.5 rounded bg-zinc-900 border border-zinc-800 flex justify-between">
                    <span className="text-zinc-400">Edge Cases</span>
                    <span className="text-zinc-100 font-bold">{result.feedback.edge_cases}/5</span>
                  </div>
                  <div className="p-1.5 rounded bg-zinc-900 border border-zinc-800 flex justify-between">
                    <span className="text-zinc-400">Naming</span>
                    <span className="text-zinc-100 font-bold">{result.feedback.naming}/5</span>
                  </div>
                </div>
              )}

              <div className="pt-3 border-t border-zinc-800/80">
                <Link href="/dashboard" className="w-full block">
                  <Button className="w-full bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs h-9 gap-1.5 shadow-md shadow-cyan-500/10">
                    <span>Return to Sprint Dashboard</span>
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* Initial Idle Panel */}
        {!loading && !result && (
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5 font-mono text-xs space-y-4">
            <div className="flex items-center gap-2 text-zinc-400 font-semibold pb-2 border-b border-zinc-800">
              <GitPullRequest className="h-4 w-4 text-cyan-400" />
              <span>Workspace Status</span>
            </div>

            <div className="space-y-3 text-[11px]">
              <div className="flex justify-between items-center text-zinc-300">
                <span>Environment Status</span>
                <StatusBadge status="passed" label="Ready" />
              </div>
              <div className="flex justify-between items-center text-zinc-300">
                <span>Test Suite</span>
                <StatusBadge status="neutral" label="Not Executed" />
              </div>
              <div className="flex justify-between items-center text-zinc-300">
                <span>Code Review</span>
                <StatusBadge status="neutral" label="Pending" />
              </div>
            </div>

            <p className="text-[11px] text-zinc-500 leading-relaxed pt-2 border-t border-zinc-800">
              Click "Create Submission" to execute test suite and trigger senior engineer PR review.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
