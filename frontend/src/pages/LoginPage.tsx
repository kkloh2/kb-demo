import { useState, type FormEvent } from "react";
import { login, type LoginResponse } from "../api/auth";
import { OcbcLogo } from "../components/OcbcLogo";
import "../styles/login.css";

interface Props {
  /** Shown above the form, e.g. why the previous session ended. */
  notice?: string | null;
  onSuccess: (session: LoginResponse) => void;
}

export function LoginPage({ notice, onSuccess }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Enter your LAN ID and password.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      onSuccess(await login({ username, password }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setPassword("");
      setSubmitting(false);
    }
  }

  const message = error ?? notice;

  return (
    <main className="login">
      <div className="card">
        <header className="card__header">
          <OcbcLogo />
          <h1 className="card__title">Data Hub</h1>
          <p className="card__subtitle">Sign in with your LAN ID and password.</p>
        </header>

        <form onSubmit={handleSubmit} noValidate>
          {message && (
            <div className={error ? "alert" : "alert alert--info"} role={error ? "alert" : "status"}>
              {message}
            </div>
          )}

          <div className="field">
            <label className="field__label" htmlFor="username">
              LAN ID
            </label>
            <input
              id="username"
              className="input"
              autoComplete="username"
              placeholder="Enter your LAN ID"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="current-password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
