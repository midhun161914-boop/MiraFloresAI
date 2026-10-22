import { useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown, ShieldOff } from "lucide-react";
import type { Actor } from "../api/client";
import { useSession } from "../session";
import { Badge } from "../ui";
import { Avatar, ROLE_LABEL } from "./evidence";

// "Acting as" — switches identity for everything the server returns.
// Listbox pattern: Enter/Space/↓ opens, ↑/↓ moves, Enter selects, Esc closes.
export function RoleSwitcher() {
  const { actor, actors, setActor } = useSession();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, actors.findIndex((a) => a.id === actor?.id)));
    list.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (!list.current?.parentElement?.contains(e.target as Node) && !button.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, actors, actor]);

  const choose = (a: Actor) => {
    if (a.id !== actor?.id) setActor(a.id);
    setOpen(false);
    button.current?.focus();
  };

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, actors.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(actors.length - 1); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (actors[active]) choose(actors[active]); }
    else if (e.key === "Escape" || e.key === "Tab") { setOpen(false); button.current?.focus(); }
  };

  if (!actor) return <div className="role-switcher role-switcher--loading" aria-hidden />;
  const staff = actors.filter((a) => a.kind === "staff");
  const clients = actors.filter((a) => a.kind === "client");

  const renderOption = (a: Actor) => {
    const i = actors.indexOf(a);
    return (
      <li key={a.id} id={`actor-${a.id}`} role="option" aria-selected={a.id === actor.id}
        className={`ui-option${i === active ? " ui-option--active" : ""}`}
        onMouseEnter={() => setActive(i)} onClick={() => choose(a)}>
        <Avatar name={a.name} role={a.role} />
        <div className="ui-option__main">
          <div className="row">
            <span className="truncate">{a.name}</span>
            {a.credential && <span className="text-tertiary text-xs">{a.credential}</span>}
          </div>
          <div className="ui-option__sub">
            {ROLE_LABEL[a.role] ?? a.role}
            {a.assignments.length > 0 && ` · assigned ${a.assignments.join(", ")}`}
            {!a.sensitive_data_clearance && " · no sensitive-data clearance"}
          </div>
        </div>
        {a.id === actor.id && <Check className="option-check" aria-hidden />}
      </li>
    );
  };

  return (
    <div className="role-switcher">
      {!actor.sensitive_data_clearance && (
        <Badge tone="warning" icon={<ShieldOff aria-hidden />} title="This user lacks sensitive-data clearance: SSNs, IP PINs and account numbers are masked by the server.">
          Identifiers masked
        </Badge>
      )}
      <button ref={button} type="button" className="role-switcher__button"
        aria-haspopup="listbox" aria-expanded={open} aria-label={`Acting as ${actor.name}, ${ROLE_LABEL[actor.role] ?? actor.role}. Switch user`}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); } }}>
        <Avatar name={actor.name} role={actor.role} />
        <span className="role-switcher__text">
          <span className="role-switcher__name">{actor.name}</span>
          <span className="role-switcher__role">{ROLE_LABEL[actor.role] ?? actor.role}</span>
        </span>
        <ChevronsUpDown className="role-switcher__chev" aria-hidden />
      </button>
      {open && (
        <div className="ui-popover role-switcher__menu">
          <ul ref={list} role="listbox" tabIndex={-1} aria-label="Act as"
            aria-activedescendant={actors[active] ? `actor-${actors[active].id}` : undefined}
            onKeyDown={onListKey}>
            <li role="presentation" className="ui-menu-label overline">Firm</li>
            {staff.map(renderOption)}
            <li role="presentation" className="ui-menu-sep" />
            <li role="presentation" className="ui-menu-label overline">Client portal</li>
            {clients.map(renderOption)}
          </ul>
        </div>
      )}
    </div>
  );
}
