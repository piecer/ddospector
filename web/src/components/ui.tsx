import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cloneElement, isValidElement, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
export type Tone = "neutral" | "success" | "warning" | "danger" | "info";
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-heading page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}
export function Panel({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"panel " + className}>
      {(title || actions) && (
        <div className="panel-heading panel-header">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p className="panel-description">{description}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </div>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}
export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return <span className={"badge badge-" + tone}>{children}</span>;
}
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && (
        <div className="empty-icon empty-state-icon" aria-hidden="true">
          {icon}
        </div>
      )}
      <h3>{title}</h3>
      <p>{description}</p>
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
export function Button({
  variant = "secondary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button
      type={type}
      className={"button button-" + variant + " " + className}
      {...props}
    />
  );
}
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  const id = useId();
  const control = isValidElement<{
    "aria-labelledby"?: string;
    "aria-describedby"?: string;
  }>(children)
    ? cloneElement(children, {
        "aria-labelledby": children.props["aria-labelledby"] ?? id + "-label",
        "aria-describedby":
          [children.props["aria-describedby"], hint ? id + "-hint" : null]
            .filter(Boolean)
            .join(" ") || undefined,
      })
    : children;
  return (
    <label className="field">
      <span id={id + "-label"} className="field-label">
        {label}
      </span>
      {control}
      {hint && (
        <small id={id + "-hint"} className="field-hint">
          {hint}
        </small>
      )}
    </label>
  );
}
export function Notice({
  tone = "info",
  children,
}: {
  tone?: Exclude<Tone, "neutral">;
  children: ReactNode;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "note"}
      className={"notice notice-" + tone}
    >
      {children}
    </div>
  );
}
export function DataTable({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div
      className="table-scroll table-wrap"
      role="region"
      aria-label={label}
      tabIndex={0}
    >
      {children}
    </div>
  );
}
export function Dialog({
  open,
  title,
  onClose,
  children,
  recoveryOnly = false,
  restoreFocusTo,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Bounded inspection/recovery only: children allow reads/dismissal, never mutations. */
  recoveryOnly?: boolean;
  restoreFocusTo?: { current: HTMLElement | null };
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const focusSession = useRef<{
    invoker: Element | null;
    recovery: boolean;
  } | null>(null);
  const titleId = useId();
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open) {
      // Capture once, before showModal; a recovery portal remount is not a new session.
      focusSession.current ??= {
        invoker: document.activeElement,
        recovery: false,
      };
      if (recoveryOnly) focusSession.current.recovery = true;
      if (!node.open) node.showModal();
    } else {
      if (node.open) node.close();
      const session = focusSession.current;
      // Dismissal consumes restoration, even when stale state disables the invoker.
      // A later readback must not steal focus from newer work.
      focusSession.current = null;
      const invoker = restoreFocusTo?.current ?? session?.invoker;
      if (
        session?.recovery &&
        invoker instanceof HTMLElement &&
        invoker.isConnected &&
        !invoker.matches(":disabled") &&
        !invoker.closest("[inert]")
      ) {
        invoker.focus({ preventScroll: true });
      }
    }
  }, [open, recoveryOnly, restoreFocusTo]);
  const dialog = (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="dialog-heading dialog-header">
        <h2 id={titleId}>{title}</h2>
        <Button
          variant="ghost"
          onClick={onClose}
          aria-label={
            document.documentElement.lang === "ko"
              ? "대화상자 닫기"
              : "Close dialog"
          }
        >
          <X size={18} aria-hidden="true" />
        </Button>
      </div>
      <div className="dialog-body">{open ? children : null}</div>
    </dialog>
  );
  // Ordinary drafts retain the page's fail-closed fieldset. Only bounded,
  // read-only inspection/recovery escapes it; changing this boundary remounts the dialog.
  return recoveryOnly ? createPortal(dialog, document.body) : dialog;
}
