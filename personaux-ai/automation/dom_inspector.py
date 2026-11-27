"""Extracts a compact, evidence-grade snapshot of the visible DOM."""
from __future__ import annotations

from dataclasses import dataclass, field

from playwright.sync_api import Page

EXTRACT_JS = r"""
() => {
  const MAX = 70;
  document.querySelectorAll('[data-pux-id]').forEach(e => e.removeAttribute('data-pux-id'));
  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], ' +
    '[role=checkbox], [role=radio], [role=tab], [role=menuitem], [role=combobox], [role=switch], [onclick], ' +
    '[tabindex]:not([tabindex="-1"]), [contenteditable=true]';
  const vw = window.innerWidth, vh = window.innerHeight;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = el => clean(el.innerText || el.textContent);
  const visibleRect = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return null;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) return null;
    return r;
  };
  const accName = el => {
    const al = el.getAttribute('aria-label'); if (al && al.trim()) return clean(al);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(i => document.getElementById(i)).filter(Boolean).map(textOf).join(' '); if (clean(t)) return clean(t); }
    if (el.id) { try { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l && textOf(l)) return textOf(l); } catch (e) {} }
    const pl = el.closest('label'); if (pl && textOf(pl)) return textOf(pl).slice(0, 80);
    const tag = el.tagName.toLowerCase();
    if (!['input', 'select', 'textarea'].includes(tag)) { const t = textOf(el); if (t) return t.slice(0, 80); }
    const img = el.querySelector && el.querySelector('img[alt]'); if (img && img.alt.trim()) return clean(img.alt);
    for (const a of ['title', 'alt']) { const v = el.getAttribute(a); if (v && v.trim()) return clean(v).slice(0, 80); }
    if (tag === 'input' && ['submit', 'button', 'reset'].includes((el.type || '').toLowerCase()) && el.value) return clean(el.value);
    return '';
  };
  const roleOf = el => {
    const r = el.getAttribute('role'); if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === 'a') return 'link';
    if (t === 'button' || t === 'summary') return 'button';
    if (t === 'select') return 'combobox';
    if (t === 'textarea') return 'textbox';
    if (t === 'input') {
      const ty = (el.type || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(ty)) return 'button';
      if (ty === 'checkbox') return 'checkbox';
      if (ty === 'radio') return 'radio';
      return 'textbox';
    }
    return t;
  };
  const items = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(SEL)) {
    if (seen.has(el)) continue; seen.add(el);
    const r = visibleRect(el); if (!r) continue;
    const inView = r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
    items.push({ el, r, inView });
  }
  items.sort((a, b) => (a.inView === b.inView ? 0 : a.inView ? -1 : 1));
  let smallTargets = 0; const smallTargetSamples = [];
  let unnamed = 0;
  for (const it of items) {
    const role = roleOf(it.el);
    const inlineLink = it.el.tagName === 'A' && it.el.closest('p, li, td');
    if (!inlineLink && Math.min(it.r.width, it.r.height) < 24) {
      smallTargets++;
      if (smallTargetSamples.length < 4) smallTargetSamples.push((accName(it.el) || role) + ' (' + Math.round(it.r.width) + 'x' + Math.round(it.r.height) + 'px)');
    }
    if (!accName(it.el) && !['textbox'].includes(role)) unnamed++;
  }
  const elements = items.slice(0, MAX).map((it, i) => {
    const el = it.el; el.setAttribute('data-pux-id', String(i + 1));
    const s = getComputedStyle(el);
    return {
      id: i + 1,
      tag: el.tagName.toLowerCase(),
      role: roleOf(el),
      name: accName(el),
      type: (el.getAttribute('type') || '').toLowerCase(),
      placeholder: el.getAttribute('placeholder') || '',
      field_name: el.getAttribute('name') || el.id || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      href: (el.getAttribute('href') || '').slice(0, 120),
      required: !!(el.required || el.getAttribute('aria-required') === 'true'),
      disabled: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      checked: !!el.checked,
      has_value: !!(el.value && ['input', 'textarea', 'select'].includes(el.tagName.toLowerCase())),
      options: el.tagName === 'SELECT' ? Array.from(el.options).slice(0, 12).map(o => clean(o.text)) : [],
      in_viewport: it.inView,
      width: Math.round(it.r.width), height: Math.round(it.r.height),
      font_size: parseFloat(s.fontSize) || 0,
    };
  });
  let smallText = 0; const smallTextSamples = [];
  for (const el of document.querySelectorAll('p, span, a, li, label, td, small, button, div')) {
    const direct = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    if (direct.length < 3) continue;
    const r = visibleRect(el); if (!r) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs && fs < 12) { smallText++; if (smallTextSamples.length < 3) smallTextSamples.push(direct.slice(0, 50) + ' (' + fs + 'px)'); }
    if (smallText > 200) break;
  }
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
    .filter(h => visibleRect(h)).slice(0, 15)
    .map(h => ({ level: parseInt(h.tagName[1]), text: textOf(h).slice(0, 100) }));
  const alerts = Array.from(document.querySelectorAll('[role=alert], [aria-live=assertive], [aria-invalid=true], .error, .errors, .alert, .invalid-feedback, .field-error'))
    .filter(e => visibleRect(e)).map(e => textOf(e) || ('invalid field: ' + accName(e))).filter(Boolean).slice(0, 6).map(t => t.slice(0, 160));
  const inputs = items.filter(it => ['INPUT', 'SELECT', 'TEXTAREA'].includes(it.el.tagName) && !['submit', 'button', 'reset', 'image'].includes((it.el.type || '').toLowerCase()));
  const body = document.body ? clean(document.body.innerText) : '';
  return {
    url: location.href,
    title: document.title || '',
    lang: document.documentElement.getAttribute('lang') || '',
    elements,
    total_interactive: items.length,
    headings,
    alerts,
    forms: document.forms.length,
    visible_inputs: inputs.length,
    required_inputs: inputs.filter(it => it.el.required || it.el.getAttribute('aria-required') === 'true').length,
    small_targets: smallTargets,
    small_target_samples: smallTargetSamples,
    small_text: smallText,
    small_text_samples: smallTextSamples,
    unnamed_controls: unnamed,
    images_missing_alt: Array.from(document.images).filter(i => !i.hasAttribute('alt') && visibleRect(i)).length,
    text_excerpt: body.slice(0, 2500),
    word_count: body ? body.split(' ').length : 0,
    scroll_height: document.documentElement.scrollHeight,
    viewport_height: vh,
    scroll_y: Math.round(window.scrollY),
  };
}
"""


@dataclass
class DomSnapshot:
    url: str
    title: str
    lang: str
    elements: list[dict]
    total_interactive: int
    headings: list[dict]
    alerts: list[str]
    forms: int
    visible_inputs: int
    required_inputs: int
    small_targets: int
    small_target_samples: list[str]
    small_text: int
    small_text_samples: list[str]
    unnamed_controls: int
    images_missing_alt: int
    text_excerpt: str
    word_count: int
    scroll_height: int
    viewport_height: int
    scroll_y: int
    extra: dict = field(default_factory=dict)

    def element(self, element_id: int | None) -> dict | None:
        if element_id is None:
            return None
        return next((e for e in self.elements if e["id"] == element_id), None)

    def summary(self) -> dict:
        return {
            "title": self.title,
            "lang": self.lang,
            "total_interactive": self.total_interactive,
            "headings": self.headings[:6],
            "alerts": self.alerts,
            "forms": self.forms,
            "visible_inputs": self.visible_inputs,
            "required_inputs": self.required_inputs,
            "small_targets": self.small_targets,
            "small_target_samples": self.small_target_samples,
            "small_text": self.small_text,
            "small_text_samples": self.small_text_samples,
            "unnamed_controls": self.unnamed_controls,
            "images_missing_alt": self.images_missing_alt,
            "word_count": self.word_count,
        }

    def describe_elements(self, limit: int = 60) -> str:
        lines = []
        for e in self.elements[:limit]:
            parts = [f"[{e['id']}] {e['role']}"]
            if e["type"] and e["role"] == "textbox":
                parts.append(f"type={e['type']}")
            parts.append(f"\"{e['name'] or '(no accessible name)'}\"")
            if e["placeholder"]:
                parts.append(f"placeholder=\"{e['placeholder'][:40]}\"")
            if e["field_name"] and e["role"] in ("textbox", "combobox", "checkbox", "radio"):
                parts.append(f"field={e['field_name'][:30]}")
            if e["href"] and e["role"] == "link":
                parts.append(f"href={e['href'][:60]}")
            if e["options"]:
                parts.append("options=" + "|".join(e["options"][:8]))
            flags = []
            if e["required"]:
                flags.append("required")
            if e["disabled"]:
                flags.append("disabled")
            if e["has_value"]:
                flags.append("filled")
            if e["checked"]:
                flags.append("checked")
            if not e["in_viewport"]:
                flags.append("below-fold")
            flags.append(f"{e['width']}x{e['height']}px")
            parts.append("(" + ", ".join(flags) + ")")
            lines.append(" ".join(parts))
        return "\n".join(lines) or "(no interactive elements visible)"


def inspect_page(page: Page) -> DomSnapshot:
    data = page.evaluate(EXTRACT_JS)
    return DomSnapshot(**data)
