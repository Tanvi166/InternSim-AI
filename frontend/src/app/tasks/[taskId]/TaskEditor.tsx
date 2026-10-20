'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Editor from 'react-simple-code-editor';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-markdown';
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
  FlaskConical,
  FolderTree,
  FileText,
  File,
  Code
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

  // Multi-file initialization: Determine available files
  const mainFileName = task.language === 'javascript' ? 'solution.js' : 'solution.py';
  const initialFiles: Record<string, string> = {
    ...(task.files || {}),
    [mainFileName]: initialSubmission?.submitted_code ?? (task.starter_code || '')
  };

  const [files, setFiles] = useState<Record<string, string>>(initialFiles);
  const [activeFileName, setActiveFileName] = useState<string>(mainFileName);
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set());
  const [draftStatus, setDraftStatus] = useState<'idle' | 'restored' | 'saved'>('idle');
  const [loading, setLoading] = useState(false);
  const [pipelineStep, setPipelineStep] = useState<number>(0);
  const [result, setResult] = useState<any>(initialSubmission || null);

  // Storage key for multi-file draft: scoped by user, task
  const multiDraftKey = userId && task?.task_id ? `internsim_multifile_draft_${userId}_${task.task_id}` : null;
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
  }, [files, activeFileName, customStdin, activeConsoleTab]);

  // Load draft from localStorage on mount
  useEffect(() => {
    if (!multiDraftKey) return;
    try {
      const saved = window.localStorage.getItem(multiDraftKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (typeof parsed === 'object' && parsed !== null) {
          setFiles((prev) => ({ ...prev, ...parsed }));
          setDraftStatus('restored');
          return;
        }
      }
    } catch (e) {
      console.warn('Could not restore multi-file draft:', e);
    }
  }, [multiDraftKey]);

  // Save changes to active file
  const handleActiveFileChange = (newContent: string) => {
    setFiles((prev) => ({
      ...prev,
      [activeFileName]: newContent
    }));

    setDirtyFiles((prev) => new Set(prev).add(activeFileName));

    if (!multiDraftKey) return;

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    debounceTimerRef.current = setTimeout(() => {
      try {
        const currentPayload = {
          ...files,
          [activeFileName]: newContent
        };
        window.localStorage.setItem(multiDraftKey, JSON.stringify(currentPayload));
        setDraftStatus('saved');
      } catch (e) {
        console.warn('Could not save draft to localStorage:', e);
      }
    }, 400);
  };

  const currentCode = files[activeFileName] ?? '';

  const handleRunCode = async () => {
    setIsRunningCode(true);
    setConsoleOpen(true);
    setActiveConsoleTab('terminal');

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const mainContent = files[mainFileName] ?? currentCode;

      const res = await fetch(`${apiUrl}/api/evaluations/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          language: task.language || 'python',
          code: mainContent,
          stdin: customStdin,
          files: files
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
      const mainContent = files[mainFileName] ?? currentCode;

      const res = await fetch(`${apiUrl}/api/evaluations/test-samples`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: task.task_id,
          code: mainContent,
          language: task.language || 'python',
          files: files
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Sample tests request failed');
      }

      const data = await res.json();
      setSampleTestResults(data);

      if (data.raw_error) {
        toast.error('Sample Tests Failed to Run', { description: 'Syntax or runtime error occurred.' });
      } else if (data.passed_samples === data.total_samples) {
        toast.success('Sample Tests Passed!', {
          description: `All ${data.total_samples} sample test cases returned expected outputs.`
        });
      } else {
        toast.warning('Some Sample Tests Failed', {
          description: `${data.passed_samples}/${data.total_samples} sample tests passed. Check test console.`
        });
      }
    } catch (err: unknown) {
      console.error('Run sample tests error:', err);
      const errMsg = err instanceof Error ? err.message : 'Sample test runner failed';
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

  const handleSubmit = async () => {
    setLoading(true);
    setPipelineStep(1);

    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();

    if (!user) {
      toast.error('Authentication Required', { description: 'Please log in to submit your solution.' });
      setLoading(false);
      setPipelineStep(0);
      return;
    }

    setTimeout(() => setPipelineStep(2), 600);
    setTimeout(() => setPipelineStep(3), 1200);
    setTimeout(() => setPipelineStep(4), 1800);

    try {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const mainContent = files[mainFileName] ?? currentCode;

      const res = await fetch(`${apiUrl}/api/evaluations/submit`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          task_id: task.task_id,
          user_id: user.id,
          submitted_code: mainContent,
          language: task.language,
          files: files
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Submission processing failed');
      }

      const data = await res.json();
      setResult(data);

      if (multiDraftKey) {
        try {
          window.localStorage.removeItem(multiDraftKey);
          setDraftStatus('idle');
          setDirtyFiles(new Set());
        } catch (e) {
          console.warn('Could not clear draft:', e);
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

  const personaConfig = getPersonaConfig(task.persona);
  const ticketId = formatTicketId(task.task_id);
  const descriptionLines = (task.description || '').split('\n').filter((l: string) => l.trim().length > 0);

  const getFileIcon = (fname: string) => {
    if (fname.endsWith('.py')) return <Code className="h-3.5 w-3.5 text-cyan-400" />;
    if (fname.endsWith('.js') || fname.endsWith('.ts')) return <Code className="h-3.5 w-3.5 text-amber-400" />;
    if (fname.endsWith('.json')) return <FileText className="h-3.5 w-3.5 text-emerald-400" />;
    if (fname.endsWith('.md')) return <FileText className="h-3.5 w-3.5 text-purple-400" />;
    return <File className="h-3.5 w-3.5 text-zinc-400" />;
  };

  const fileList = Object.keys(files);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      {/* LEFT PANEL: Ticket Specification & Context (4 cols) */}
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

      {/* CENTER PANEL: Multi-File Code Editor (5 cols) */}
      <div className="lg:col-span-5 space-y-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/90 shadow-2xl overflow-hidden flex flex-col">
          {/* File Explorer & Tab Bar */}
          <div className="bg-zinc-950 border-b border-zinc-800">
            {/* Top Workspace Header */}
            <div className="px-4 py-2 flex items-center justify-between border-b border-zinc-800/60 text-xs font-mono text-zinc-400">
              <div className="flex items-center gap-2">
                <FolderTree className="h-3.5 w-3.5 text-cyan-400" />
                <span className="text-zinc-200 font-semibold">Workspace Files ({fileList.length})</span>
              </div>
              <div className="flex items-center gap-2">
                {draftStatus === 'restored' && (
                  <span className="flex items-center gap-1 text-[10px] text-amber-400/90 font-medium">
                    <Save className="h-3 w-3 text-amber-400" />
                    <span>Draft restored</span>
                  </span>
                )}
                {draftStatus === 'saved' && (
                  <span className="flex items-center gap-1 text-[10px] text-cyan-400/90 font-medium">
                    <Save className="h-3 w-3 text-cyan-400" />
                    <span>Saved locally</span>
                  </span>
                )}
                <span className="text-[10px] text-zinc-500 uppercase">UTF-8 · Interactive Sandbox</span>
              </div>
            </div>

            {/* File Tabs */}
            <div className="flex items-center overflow-x-auto px-2 pt-1 gap-1">
              {fileList.map((fname) => {
                const isActive = activeFileName === fname;
                const isDirty = dirtyFiles.has(fname);
                return (
                  <button
                    key={fname}
                    type="button"
                    onClick={() => setActiveFileName(fname)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-t-md text-xs font-mono transition-colors border-t-2 border-x ${
                      isActive
                        ? 'bg-zinc-900 border-t-cyan-400 border-x-zinc-800 text-zinc-100 font-medium'
                        : 'bg-zinc-950 border-t-transparent border-x-transparent text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/50'
                    }`}
                  >
                    {getFileIcon(fname)}
                    <span>{fname}</span>
                    {isDirty && (
                      <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" title="Unsaved edits" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Prism Code Editor container */}
          <div className="p-3 bg-zinc-950 min-h-[420px] font-mono text-xs">
            <Editor
              value={currentCode}
              onValueChange={handleActiveFileChange}
              highlight={(codeStr) => {
                const isPy = activeFileName.endsWith('.py');
                const isJs = activeFileName.endsWith('.js') || activeFileName.endsWith('.ts');
                const isJson = activeFileName.endsWith('.json');
                const grammar = isPy
                  ? Prism.languages.python
                  : isJs
                  ? Prism.languages.javascript
                  : isJson
                  ? Prism.languages.json
                  : Prism.languages.python;
                return Prism.highlight(codeStr, grammar || Prism.languages.javascript, activeFileName);
              }}
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
                    <span>Evaluating PR...</span>
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
                          : 'bg-amber-950 text-amber-400 border border-amber-800'
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
                    <span>Standard Output</span>
                    {terminalResult && (
                      <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                        terminalResult.exit_code === 0 && !terminalResult.error
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : 'bg-rose-950 text-rose-400 border border-rose-800'
                      }`}>
                        Exit: {terminalResult.exit_code ?? 0}
                      </span>
                    )}
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  {activeConsoleTab === 'terminal' && (
                    <button
                      type="button"
                      onClick={() => setShowStdinInput(!showStdinInput)}
                      className="text-[10px] text-zinc-400 hover:text-zinc-200 px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800"
                    >
                      {showStdinInput ? 'Hide Stdin' : 'Custom Stdin'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setConsoleOpen(false)}
                    className="text-zinc-500 hover:text-zinc-300 p-1"
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* Console Body */}
              <div className="p-4 max-h-72 overflow-y-auto space-y-3">
                {activeConsoleTab === 'sampleTests' ? (
                  <div className="space-y-3">
                    {isRunningTests && (
                      <div className="flex items-center justify-center gap-2 py-8 text-zinc-400">
                        <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
                        <span>Running sample test harness against visible test suite...</span>
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
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {showStdinInput && (
                      <div className="p-2.5 rounded bg-zinc-900 border border-zinc-800 space-y-1">
                        <label className="text-[10px] text-zinc-400 font-bold uppercase block">
                          Standard Input (stdin):
                        </label>
                        <textarea
                          value={customStdin}
                          onChange={(e) => setCustomStdin(e.target.value)}
                          placeholder="Provide custom input lines passed to sys.stdin..."
                          rows={2}
                          className="w-full p-2 rounded bg-zinc-950 border border-zinc-800 text-zinc-200 font-mono text-xs focus:outline-none focus:border-cyan-500"
                        />
                      </div>
                    )}

                    {isRunningCode && (
                      <div className="flex items-center justify-center gap-2 py-8 text-zinc-400">
                        <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
                        <span>Running code buffer in Piston sandbox...</span>
                      </div>
                    )}

                    {!isRunningCode && terminalResult && (
                      <div className="space-y-2">
                        {terminalResult.stdout && (
                          <div className="p-3 rounded bg-zinc-900/90 border border-zinc-800">
                            <span className="text-[10px] text-emerald-400 font-bold uppercase block mb-1">Standard Output:</span>
                            <pre className="text-zinc-200 whitespace-pre-wrap font-mono text-xs overflow-x-auto">
                              {terminalResult.stdout}
                            </pre>
                          </div>
                        )}

                        {terminalResult.stderr && (
                          <div className="p-3 rounded bg-rose-950/30 border border-rose-800/60">
                            <span className="text-[10px] text-rose-400 font-bold uppercase block mb-1">Standard Error:</span>
                            <pre className="text-rose-300 whitespace-pre-wrap font-mono text-xs overflow-x-auto">
                              {terminalResult.stderr}
                            </pre>
                          </div>
                        )}

                        {!terminalResult.stdout && !terminalResult.stderr && (
                          <div className="p-3 rounded bg-zinc-900/60 border border-zinc-800 text-zinc-400 text-center py-4">
                            Execution finished with exit code {terminalResult.exit_code}. No output was printed to stdout or stderr.
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
        {loading && (
          <div className="rounded-xl border border-cyan-500/40 bg-zinc-900/90 p-5 shadow-2xl space-y-4 font-mono text-xs animate-pulse">
            <div className="flex items-center gap-2 text-cyan-400 font-bold">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>CI/CD Evaluation Pipeline</span>
            </div>

            <div className="space-y-2">
              <div className={`p-2 rounded border ${pipelineStep >= 1 ? 'bg-cyan-950/50 border-cyan-800 text-cyan-300' : 'bg-zinc-950 border-zinc-800 text-zinc-500'}`}>
                1. Building Multi-File Sandbox...
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

        {result && (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/90 p-5 shadow-2xl space-y-5">
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

              <div className="mt-3 w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
                <div 
                  className={`h-full rounded-full transition-all duration-700 ${
                    result.total_score >= 80 ? 'bg-emerald-400' : result.total_score >= 60 ? 'bg-amber-400' : 'bg-rose-400'
                  }`}
                  style={{ width: `${result.total_score}%` }}
                />
              </div>
            </div>

            <div className="space-y-3 font-mono text-xs">
              <div>
                <div className="flex justify-between mb-1">
                  <span className="text-zinc-400">Correctness Suite:</span>
                  <span className="text-emerald-400 font-semibold">{result.correctness_score} / 60</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                  <div 
                    className="bg-emerald-400 h-full rounded-full" 
                    style={{ width: `${(result.correctness_score / 60) * 100}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between mb-1">
                  <span className="text-zinc-400">Code Quality & Design:</span>
                  <span className="text-amber-400 font-semibold">{result.quality_score} / 40</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                  <div 
                    className="bg-amber-400 h-full rounded-full" 
                    style={{ width: `${(result.quality_score / 40) * 100}%` }}
                  />
                </div>
              </div>
            </div>

            {result.feedback && (
              <div className="pt-4 border-t border-zinc-800 space-y-3">
                <h4 className="text-xs font-mono font-bold text-zinc-200 flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-cyan-400" />
                  <span>Senior Reviewer Comments</span>
                </h4>
                <p className="text-xs text-zinc-300 leading-relaxed font-sans bg-zinc-950/80 p-3 rounded-lg border border-zinc-800">
                  {result.feedback.comments || 'No specific feedback provided.'}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
