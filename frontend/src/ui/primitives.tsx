// Shared UI primitives. Every screen is composed from these so the app reads as
// one product: Button, Card, Badge, Panel, PageHeader, fields, meter, stat,
// states. (Table lives in Table.tsx because it carries virtualization.)
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { AlertTriangle, ChevronRight, Info, Inbox, OctagonAlert, Search, X } from "lucide-react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ Button */
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";
interface ButtonOwnProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  iconRight?: ReactNode;
}
export type ButtonProps = ButtonOwnProps & ButtonHTMLAttributes<HTMLButtonElement>;

function btnClass({ variant = "secondary", size = "md" }: ButtonOwnProps, iconOnly: boolean, extra?: string) {
  return cx("ui-btn", `ui-btn--${variant}`, `ui-btn--${size}`, iconOnly && "ui-btn--icon", extra);
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, icon, iconRight, className, children, type = "button", ...rest }, ref,
) {
  return (
    <button ref={ref} type={type} className={btnClass({ variant, size }, !children, className)} {...rest}>
      {icon}{children}{iconRight}
    </button>
  );
});

export function ButtonLink({ variant, size, icon, iconRight, className, children, ...rest }: ButtonOwnProps & LinkProps) {
  return (
    <Link className={btnClass({ variant, size }, !children, className)} {...rest}>
      {icon}{children}{iconRight}
    </Link>
  );
}

/* -------------------------------------------------------------------- Card */
export function Card({ title, description, actions, footer, flush, plainHeader, interactive, className, children, as: Tag = "section", ...aria }: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  flush?: boolean;
  plainHeader?: boolean;
  interactive?: boolean;
  className?: string;
  children?: ReactNode;
  as?: "section" | "div" | "article";
  "aria-label"?: string;
}) {
  return (
    <Tag className={cx("ui-card", interactive && "ui-card--interactive", className)} {...aria}>
      {(title || actions) && (
        <header className={cx("ui-card__header", plainHeader && "ui-card__header--plain")}>
          <div className="ui-card__titles">
            {title && <h2 className="ui-card__title">{title}</h2>}
            {description && <p className="ui-card__description">{description}</p>}
          </div>
          {actions && <div className="ui-card__actions">{actions}</div>}
        </header>
      )}
      {children !== undefined && <div className={cx("ui-card__body", flush && "ui-card__body--flush")}>{children}</div>}
      {footer && <footer className="ui-card__footer">{footer}</footer>}
    </Tag>
  );
}

/* ------------------------------------------------------------------- Badge */
export type Tone = "neutral" | "verified" | "open" | "warning" | "error" | "accent" | "outline";

export function Badge({ tone = "neutral", dot, icon, title, children }: {
  tone?: Tone; dot?: boolean; icon?: ReactNode; title?: string; children: ReactNode;
}) {
  return (
    <span className={`ui-badge ui-badge--${tone}`} title={title}>
      {dot && <span className="ui-badge__dot" aria-hidden />}
      {icon}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------- Panel */
export function Panel({ title, subtitle, actions, onClose, children, className, "aria-label": ariaLabel }: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  onClose?: () => void;
  children: ReactNode;
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <aside className={cx("ui-panel", className)} aria-label={ariaLabel}>
      <header className="ui-panel__header">
        <div className="ui-panel__titles">
          <h2 className="ui-panel__title">{title}</h2>
          {subtitle && <p className="ui-panel__subtitle">{subtitle}</p>}
        </div>
        {actions}
        {onClose && <Button variant="ghost" size="sm" icon={<X />} onClick={onClose} aria-label="Close panel" />}
      </header>
      <div className="ui-panel__body">{children}</div>
    </aside>
  );
}

export function PanelSection({ title, actions, flush, scroll, children }: {
  title?: ReactNode; actions?: ReactNode; flush?: boolean;
  /** Fill the remaining panel height and scroll independently. */
  scroll?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={cx("ui-panel__section", flush && "ui-panel__section--flush", scroll && "ui-panel__section--scroll")}>
      {(title || actions) && (
        <div className="ui-panel__section-head">
          {title && <h3 className="overline">{title}</h3>}
          <span className="spacer" />
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

/* -------------------------------------------------------------- PageHeader */
export function PageHeader({ crumbs, title, meta, actions }: {
  crumbs?: { label: ReactNode; to?: string }[];
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="ui-pagehead">
      <div className="ui-pagehead__main">
        {crumbs && crumbs.length > 0 && (
          <nav className="ui-pagehead__crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => (
              <span key={i} className="row" style={{ gap: 4 }}>
                {i > 0 && <ChevronRight aria-hidden />}
                {c.to ? <Link to={c.to}>{c.label}</Link> : <span aria-current="page">{c.label}</span>}
              </span>
            ))}
          </nav>
        )}
        <h1>{title}</h1>
        {meta && <div className="ui-pagehead__meta">{meta}</div>}
      </div>
      {actions && <div className="ui-pagehead__actions">{actions}</div>}
    </header>
  );
}

/* ------------------------------------------------------------------ Fields */
export function SearchInput({ value, onChange, placeholder, label, autoFocus }: {
  value: string; onChange: (v: string) => void; placeholder?: string; label: string; autoFocus?: boolean;
}) {
  return (
    <div className="ui-search">
      <Search aria-hidden />
      <input type="search" value={value} placeholder={placeholder} aria-label={label} autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape" && value) { e.stopPropagation(); onChange(""); } }} />
      {value && <Button variant="ghost" size="sm" icon={<X />} aria-label="Clear search" onClick={() => onChange("")} />}
    </div>
  );
}

export function Select({ label, value, onChange, options, hideLabel }: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[]; hideLabel?: boolean;
}) {
  const id = `sel-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <span className="ui-field">
      <label htmlFor={id} className={hideLabel ? "sr-only" : "ui-field__label"}>{label}</label>
      <select id={id} className="ui-select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </span>
  );
}

/** Single-select (radio) or multi-select (toggle) pill group. */
export function FilterGroup({ label, items, selected, onToggle, multi }: {
  label: string;
  items: { id: string; label: ReactNode; count?: number }[];
  selected: string[];
  onToggle: (id: string) => void;
  multi?: boolean;
}) {
  return (
    <div className="ui-filter" role={multi ? "group" : "radiogroup"} aria-label={label}>
      {items.map((it) => {
        const on = selected.includes(it.id);
        return (
          <button key={it.id} type="button" className="ui-filter__item"
            role={multi ? undefined : "radio"}
            aria-pressed={multi ? on : undefined} aria-checked={multi ? undefined : on}
            onClick={() => onToggle(it.id)}>
            {it.label}
            {it.count !== undefined && <span className="ui-filter__count">{it.count.toLocaleString()}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="ui-kbd">{children}</kbd>;
}

/* ------------------------------------------------------------------- Meter */
export function ConfidenceMeter({ value, low = 0.8 }: { value: number; low?: number }) {
  const tone = value < low ? "error" : value < 0.9 ? "warning" : "verified";
  const pct = `${Math.round(value * 100)}%`;
  return (
    <span className={`ui-meter ui-meter--${tone}`} title={`Pipeline confidence ${pct}`}>
      <span className="ui-meter__track" aria-hidden><span className="ui-meter__fill" style={{ width: pct }} /></span>
      <span className="ui-meter__value">{pct}</span>
    </span>
  );
}

/* -------------------------------------------------------------------- Stat */
export function Stat({ label, value, hint }: { label: ReactNode; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="ui-stat">
      <div className="ui-stat__label">{label}</div>
      <div className="ui-stat__value">{value}</div>
      {hint && <div className="ui-stat__hint">{hint}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ States */
export function EmptyState({ title, description, icon, action }: {
  title: ReactNode; description?: ReactNode; icon?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="ui-empty" role="status">
      <div className="ui-empty__icon" aria-hidden>{icon ?? <Inbox />}</div>
      <div className="ui-empty__title">{title}</div>
      {description && <div className="ui-empty__desc">{description}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Couldn't load this" }: {
  error: unknown; onRetry?: () => void; title?: string;
}) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="ui-empty ui-empty--error" role="alert">
      <div className="ui-empty__icon" aria-hidden><OctagonAlert /></div>
      <div className="ui-empty__title">{title}</div>
      <div className="ui-empty__desc">{msg}</div>
      {onRetry && <Button size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function Skeleton({ width = "100%", height = 12, style }: { width?: number | string; height?: number; style?: React.CSSProperties }) {
  return <span className="ui-skeleton" style={{ width, height, ...style }} aria-hidden />;
}

export function PageSkeleton({ label = "Loading" }: { label?: string }) {
  return (
    <div className="page" role="status" aria-label={label}>
      <Skeleton width={120} height={12} />
      <Skeleton width={360} height={24} style={{ marginTop: 8 }} />
      <div className="stack-3" style={{ marginTop: 32 }}>
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} height={32} />)}
      </div>
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function Callout({ tone = "neutral", icon, children }: {
  tone?: "neutral" | "open" | "warning" | "error"; icon?: ReactNode; children: ReactNode;
}) {
  const glyph = icon ?? (tone === "warning" || tone === "error" ? <AlertTriangle aria-hidden /> : <Info aria-hidden />);
  return <div className={`ui-callout ui-callout--${tone}`} role={tone === "error" ? "alert" : undefined}>{glyph}<div>{children}</div></div>;
}
