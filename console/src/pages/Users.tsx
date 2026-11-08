import { useCallback, useEffect, useState, type FormEvent } from "react";
import { addUser, errorText, listUsers, setUserRole } from "../api";
import { Empty } from "../components/Empty";
import { useSession } from "../context";
import { dateTime } from "../format";
import { ROLE, ROLE_ORDER } from "../labels";
import type { Role, User } from "../types";

export function Users() {
  const { user } = useSession();
  const [users, setUsers] = useState<User[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("responder");
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    setLoadErr(null);
    listUsers().then(setUsers).catch((e) => setLoadErr(errorText(e)));
  }, []);
  useEffect(load, [load]);

  if (user?.role !== "admin") {
    return (
      <main className="page">
        <div className="notice t-invest">Only admins can manage users<p>Ask an admin to add people or change roles.</p></div>
      </main>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const u = await addUser({ name: name.trim(), email: email.trim(), role });
      setUsers((prev) => (prev ? [...prev.filter((x) => x.id !== u.id), u] : [u]));
      setResult({ ok: true, text: `Added ${u.name} as ${ROLE[u.role].label.toLowerCase()}.` });
      setName("");
      setEmail("");
    } catch (e2) {
      setResult({ ok: false, text: `User not added: ${errorText(e2)}` });
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (u: User, next: Role) => {
    if (next === u.role) return;
    setChanging(u.id);
    setResult(null);
    try {
      const updated = await setUserRole(u.id, next);
      setUsers((prev) => (prev ? prev.map((x) => (x.id === updated.id ? updated : x)) : prev));
      setResult({ ok: true, text: `${updated.name} is now ${ROLE[updated.role].label.toLowerCase()}.` });
    } catch (e) {
      setResult({ ok: false, text: `Role not changed: ${errorText(e)}` });
    } finally {
      setChanging(null);
    }
  };

  return (
    <main className="page stack">
      <div>
        <h1>Users &amp; roles</h1>
        <p className="lede">
          Add the people who respond to incidents. Roles decide who can approve the agent's
          proposed actions, who can post updates, and who is read-only.
        </p>
      </div>

      <div className="roles">
        {ROLE_ORDER.map((r) => (
          <div key={r}>
            <strong>{ROLE[r].label}</strong>
            {ROLE[r].can}
          </div>
        ))}
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Add a user</h2></div>
        <form className="panel-body form" onSubmit={submit}>
          <div className="row">
            <label>
              Name
              <input className="input" required value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
            </label>
            <label>
              Email
              <input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
            </label>
            <label>
              Role
              <select className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLE_ORDER.map((r) => (
                  <option key={r} value={r}>{ROLE[r].label}</option>
                ))}
              </select>
            </label>
            <button className="btn btn-primary" disabled={busy}>{busy ? "Adding…" : "Add user"}</button>
          </div>
          {result && (
            <div className={`notice ${result.ok ? "t-clean" : "t-exfil"}`} role="status">{result.text}</div>
          )}
        </form>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>People with access</h2>
          {users && <span className="aside">{users.length}</span>}
        </div>
        {loadErr ? (
          <Empty title="Couldn't load users">
            <span>{loadErr}</span>
            <button className="btn" onClick={load}>Try again</button>
          </Empty>
        ) : !users ? (
          <Empty title="Loading users…" />
        ) : users.length === 0 ? (
          <Empty title="No users yet">Add the first responder above.</Empty>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="users">
              <thead>
                <tr><th>Name</th><th>Email</th><th>Role</th><th>Change role</th><th>Added</th></tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.name}{u.id === user?.id && <span className="aside"> (you)</span>}</td>
                    <td>{u.email}</td>
                    <td>{ROLE[u.role].label}</td>
                    <td>
                      <select
                        className="input input-compact"
                        value={u.role}
                        disabled={u.id === user?.id || changing === u.id}
                        onChange={(e) => changeRole(u, e.target.value as Role)}
                        aria-label={`Role for ${u.name}`}
                      >
                        {ROLE_ORDER.map((r) => (
                          <option key={r} value={r}>{ROLE[r].label}</option>
                        ))}
                      </select>
                    </td>
                    <td>{dateTime(u.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
