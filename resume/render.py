"""Deterministic, stdlib-only Markdown renderer for a ResumeDraft.

Turns a ResumeDraft (subject + selected scored claims) into a human-readable
Markdown resume. Emits a Summary stat line, an Experience section grouped by
stack, a Skills section, and Contact/Education placeholder sections.

No model, subprocess, or network call is made — stdlib and resume.select only.
"""

from __future__ import annotations

from resume.select import ResumeDraft
from portfolio.render import _escape, claim_group, count_repos_from_refs, stack_languages

_NO_BULLETS_NOTICE = "_no grounded resume bullets_"
_CONTACT_PLACEHOLDER = "_Add your contact details._"
_EDUCATION_PLACEHOLDER = "_Add your education._"


def render_resume(draft: ResumeDraft, *, show_refs: bool = False) -> str:
    """Render a ResumeDraft to a Markdown string.

    Non-empty draft emits: # heading, Summary stat line, ## Experience with
    ## <Stack> group sections (claim bullets in draft.selected order), ## Skills,
    ## Contact placeholder, ## Education placeholder.

    Empty draft emits: # heading, 'no grounded resume bullets' notice, then
    ## Contact and ## Education placeholders only.
    """
    lines: list[str] = []

    lines.append(f"# Resume — {_escape(draft.subject)}")
    lines.append("")

    if not draft.selected:
        lines.append(_NO_BULLETS_NOTICE)
        lines.append("")
        lines.append("## Contact")
        lines.append("")
        lines.append(_CONTACT_PLACEHOLDER)
        lines.append("")
        lines.append("## Education")
        lines.append("")
        lines.append(_EDUCATION_PLACEHOLDER)
        lines.append("")
        return "\n".join(lines)

    # --- Summary stat line ---
    n_selected = len(draft.selected)
    n_repos = count_repos_from_refs(ref for sc in draft.selected for ref in sc.claim.evidence_refs)
    m = len(draft.jd_keywords_matched)
    t = draft.jd_keywords_total
    lines.append(f"{n_selected} contributions · {n_repos} repos · {m}/{t} JD keywords")
    lines.append("")

    # --- Experience section ---
    lines.append("## Experience")
    lines.append("")

    # Group claims: iterate draft.selected in order to preserve within-group order
    groups: dict[str, list] = {}
    for sc in draft.selected:
        group = claim_group(sc.claim, draft.evidence_by_ref)
        groups.setdefault(group, []).append(sc)

    # Sort groups: descending count, ascending name; Other always last
    other_scs = groups.pop("Other", [])
    sorted_groups = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if other_scs:
        sorted_groups.append(("Other", other_scs))

    for group_name, scs in sorted_groups:
        lines.append(f"## {group_name}")
        lines.append("")
        for sc in scs:
            if show_refs:
                refs_str = ", ".join(_escape(ref) for ref in sc.claim.evidence_refs)
                lines.append(f"- {_escape(sc.claim.text)} [{refs_str}]")
            else:
                lines.append(f"- {_escape(sc.claim.text)}")
        lines.append("")

    # --- Skills section ---
    selected_refs = {ref for sc in draft.selected for ref in sc.claim.evidence_refs}
    selected_evidence = (ev for ev in draft.evidence_by_ref.values() if ev.ref in selected_refs)
    langs = stack_languages(selected_evidence)
    lines.append("## Skills")
    lines.append("")
    if langs:
        lines.append(", ".join(sorted(langs)))
    else:
        lines.append("_no stack detected_")
    lines.append("")

    # --- Placeholder sections ---
    lines.append("## Contact")
    lines.append("")
    lines.append(_CONTACT_PLACEHOLDER)
    lines.append("")
    lines.append("## Education")
    lines.append("")
    lines.append(_EDUCATION_PLACEHOLDER)
    lines.append("")

    return "\n".join(lines)
