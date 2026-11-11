import type { User } from "../api/auth";
import "../styles/home.css";

interface Props {
  user: User;
}

/** Landing content inside the app shell, until feature pages are added. */
export function HomePage({ user }: Props) {
  return (
    <div className="page">
      <h1 className="page__title">Welcome, {user.display_name}</h1>
      {(user.title || user.department) && (
        <p className="page__lede">{[user.title, user.department].filter(Boolean).join(", ")}</p>
      )}
    </div>
  );
}
