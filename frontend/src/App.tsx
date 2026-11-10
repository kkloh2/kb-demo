import { useEffect, useState } from "react";
import { logout, me, type LoginResponse, type User } from "./api/auth";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";

const TOKEN_KEY = "datahub.token";

function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the session just won't survive a refresh */
  }
}

interface Session {
  token: string;
  user: User;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [restoring, setRestoring] = useState(() => readToken() !== null);
  const [notice, setNotice] = useState<string | null>(null);

  // Restore the session on page refresh.
  useEffect(() => {
    const token = readToken();
    if (!token) return;
    me(token)
      .then((user) => setSession({ token, user }))
      .catch((err: Error) => {
        writeToken(null);
        setNotice(err.message);
      })
      .finally(() => setRestoring(false));
  }, []);

  function handleLogin(res: LoginResponse) {
    writeToken(res.access_token);
    setNotice(null);
    setSession({ token: res.access_token, user: res.user });
  }

  function handleSignOut() {
    if (session) void logout(session.token);
    writeToken(null);
    setSession(null);
  }

  if (restoring) return null;
  if (!session) return <LoginPage notice={notice} onSuccess={handleLogin} />;
  return <HomePage user={session.user} onSignOut={handleSignOut} />;
}
