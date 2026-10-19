const FOCUSABLE =
  'input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

/**
 * Moves focus to the field or card an error is about: the element itself when
 * it is a control, else its first control, else the element (made focusable).
 */
export function focusTarget(id: string) {
  const element = document.getElementById(id);
  if (element === null) {
    return;
  }
  const control = element.matches(FOCUSABLE)
    ? element
    : (element.querySelector<HTMLElement>(FOCUSABLE) ?? element);
  if (control === element && !element.matches(FOCUSABLE)) {
    element.setAttribute("tabindex", "-1");
  }
  control.focus();
  control.scrollIntoView?.({ block: "center" });
}
