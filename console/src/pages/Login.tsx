import { useState, type FormEvent } from "react";
import { API_URL, errorText, login } from "../api";
import { useSession } from "../context";

export function Login() {
  const { status, setUser, retry } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const s = await login(email.trim(), password);
      setPassword("");
      setUser(s.user);
    } catch (e2) {
      setErr(errorText(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="login-card form" onSubmit={submit}>
        <img className="login-art" src="/mascots/crew.png" alt="" />
        <div>
          <h1>Sign in to the operator console</h1>
          <p className="lede">
            <strong>NMC · SOC</strong> — monitoring the GPU cluster for <strong>Halloran &amp; Vance LLP</strong> (client).
            This console runs off the attacked box, so a fully compromised cluster cannot reach it.
          </p>
        </div>
        {status === "offline" && (
          <div className="notice t-exfil" role="alert">
            Not connected to the command center
            <p>
              Tried <code>{API_URL}</code>. Start the backend, then{" "}
              <button type="button" className="btn btn-ghost" style={{ minHeight: 0, padding: 0, textDecoration: "underline" }} onClick={retry}>
                try again
              </button>
              .
            </p>
          </div>
        )}
        {status === "checking" && <div className="notice t-muted">Checking your session…</div>}
        <label>
          Email
          <input className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {err && <div className="notice t-exfil" role="alert">Sign-in failed<p>{err}</p></div>}
        <button className="btn btn-primary btn-lg" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
