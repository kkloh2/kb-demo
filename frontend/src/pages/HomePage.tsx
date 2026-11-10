import type { User } from "../api/auth";
import { OcbcLogo } from "../components/OcbcLogo";
import "../styles/home.css";

interface Props {
  user: User;
  onSignOut: () => void;
}

/** Placeholder landing page after sign-in, until the app's real pages are rebuilt. */
export function HomePage({ user, onSignOut }: Props) {
  return (
    <div className="home">
      <header className="topbar">
        <div className="topbar__brand">
          <OcbcLogo />
          <span className="topbar__product">Data Hub</span>
        </div>
        <div className="topbar__account">
          <span className="topbar__user">
            {user.display_name} <span className="topbar__lan">({user.username})</span>
          </span>
          <button type="button" className="btn-secondary" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <main className="home__body">
        <h1 className="home__title">Welcome, {user.display_name}</h1>
        {(user.title || user.department) && (
          <p className="home__lede">{[user.title, user.department].filter(Boolean).join(", ")}</p>
        )}
      </main>
    </div>
  );
}
