// The incident runbooks the agents read through their get_runbook tool (GET /defender/runbooks),
// rendered for people. Same files, so what you read here is exactly what the Advisor follows.

import { Fragment, useEffect, useState, type ReactNode } from "react";
import { errorText, getRunbooks } from "../api";
import { Empty } from "../components/Empty";

// ponytail: renders only the Markdown subset the runbooks use (#/## headings, 1./- lists,
// **bold**, `code`, paragraphs). Swap in a Markdown library if the runbooks outgrow it.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong>
    : part.startsWith("`") ? <code key={i} className="case-call">{part.slice(1, -1)}</code>
    : <Fragment key={i}>{part}</Fragment>,
  );
}

function Markdown({ source }: { source: string }) {
  const out: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((t, i) => <li key={i}>{inline(t)}</li>);
    out.push(list.ordered ? <ol key={out.length}>{items}</ol> : <ul key={out.length}>{items}</ul>);
    list = null;
  };
  for (const line of source.split("\n")) {
    const ol = line.match(/^\d+\.\s+(.*)/);
    const ul = line.match(/^[-*]\s+(.*)/);
    if (ol || ul) {
      const ordered = !!ol;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((ol ?? ul)![1]);
      continue;
    }
    flush();
    if (line.startsWith("## ")) out.push(<h3 key={out.length}>{inline(line.slice(3))}</h3>);
    else if (line.startsWith("# ")) out.push(<h2 key={out.length}>{inline(line.slice(2))}</h2>);
    else if (line.trim()) out.push(<p key={out.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="md">{out}</div>;
}

const title = (body: string, id: string) => body.match(/^# (.*)/m)?.[1] ?? id;

export function Runbooks() {
  const [books, setBooks] = useState<{ id: string; body: string }[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    getRunbooks()
      .then((b) => { setBooks(b); setOpen(b[0]?.id ?? null); })
      .catch((e) => setErr(errorText(e)));
  }, []);

  const shown = books?.find((b) => b.id === open);
  return (
    <main className="page runbooks-page">
      <h1>Runbooks</h1>
      <p className="lede">
        The firm's incident playbooks. The agents read these with their <code>get_runbook</code> tool
        and follow each one's containment order; the RB-0x ids are the steps the approval cards cite.
      </p>
      {err ? (
        <div className="notice t-exfil" role="alert">{err}</div>
      ) : !books ? (
        <Empty title="Loading runbooks…" />
      ) : (
        <div className="rb-grid">
          <nav className="rb-list" aria-label="Runbooks">
            {books.map((b) => (
              <button key={b.id} type="button" aria-pressed={b.id === open} onClick={() => setOpen(b.id)}>
                <span>{title(b.body, b.id)}</span>
                <code>{b.id}</code>
              </button>
            ))}
          </nav>
          <article className="panel rb-body">{shown && <Markdown source={shown.body} />}</article>
        </div>
      )}
    </main>
  );
}
