import { useState } from "react";

export function SearchBar({ placeholder, onSearch, busy }: {
  placeholder: string; onSearch: (q: string) => void; busy?: boolean;
}) {
  const [q, setQ] = useState("");
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) onSearch(q.trim());
      }}
    >
      <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} />
      <button className="btn" type="submit" disabled={busy || !q.trim()}>search</button>
    </form>
  );
}
