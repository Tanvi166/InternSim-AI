import { login, signup } from './actions';
import { AuthForm } from './AuthForm';

export default async function LoginPage(props: {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }> | { [key: string]: string | string[] | undefined };
}) {
  const searchParams = props.searchParams ? await Promise.resolve(props.searchParams) : {};
  const error = typeof searchParams?.error === 'string' ? searchParams.error : undefined;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-4 selection:bg-cyan-500 selection:text-black">
      <div className="w-full max-w-md flex flex-col items-center">
        <AuthForm
          initialError={error}
          loginAction={login}
          signupAction={signup}
        />
      </div>
    </div>
  );
}
