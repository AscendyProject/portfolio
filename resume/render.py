"""Deterministic, stdlib-only Markdown renderer for a ResumeDraft.

Turns a ResumeDraft (subject + selected scored claims) into a human-readable
Markdown resume. Emits a Summary stat line, an Experience section grouped by
stack, a Skills section, and Contact/Education placeholder sections.

No model, subprocess, or network call is made — stdlib and resume.select only.
"""

from __future__ import annotations

from portfolio.i18n import LANGS
from portfolio.render import _escape, claim_group, count_repos_from_refs, stack_languages
from resume.select import ResumeDraft


def render_resume(draft: ResumeDraft, *, show_refs: bool = False, lang: str = "en") -> str:
    """Render a ResumeDraft to a Markdown string.

    Non-empty draft emits: # heading, Summary stat line, ## Experience with
    ## <Stack> group sections (claim bullets in draft.selected order), ## Skills,
    ## Contact placeholder, ## Education placeholder.

    Empty draft emits: # heading, 'no grounded resume bullets' notice, then
    ## Contact and ## Education placeholders only.
    """
    strings = LANGS[lang]
    lines: list[str] = []

    lines.append(f"# {strings['title_resume']} — {_escape(draft.subject)}")
    lines.append("")

    if not draft.selected:
        lines.append(strings["no_grounded_bullets"])
        lines.append("")
        lines.append(f"## {strings['section_contact']}")
        lines.append("")
        lines.append(strings["contact_placeholder"])
        lines.append("")
        lines.append(f"## {strings['section_education']}")
        lines.append("")
        lines.append(strings["education_placeholder"])
        lines.append("")
        return "\n".join(lines)

    # --- Summary stat line ---
    n_selected = len(draft.selected)
    n_repos = count_repos_from_refs(ref for sc in draft.selected for ref in sc.claim.evidence_refs)
    m = len(draft.jd_keywords_matched)
    t = draft.jd_keywords_total
    lines.append(
        f"{n_selected} {strings['stat_contributions']} · {n_repos} {strings['stat_repos']} · {m}/{t} {strings['stat_jd_keywords']}"
    )
    lines.append("")

    # --- Experience section ---
    lines.append(f"## {strings['section_experience']}")
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
        # Translate "Other" sentinel; tech names (Python, Go) are language-neutral.
        display_name = strings["group_other"] if group_name == "Other" else group_name
        lines.append(f"## {display_name}")
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
    detected_langs = stack_languages(selected_evidence)
    lines.append(f"## {strings['section_skills']}")
    lines.append("")
    if detected_langs:
        lines.append(", ".join(sorted(detected_langs)))
    else:
        lines.append(strings["no_stack_detected"])
    lines.append("")

    # --- Placeholder sections ---
    lines.append(f"## {strings['section_contact']}")
    lines.append("")
    lines.append(strings["contact_placeholder"])
    lines.append("")
    lines.append(f"## {strings['section_education']}")
    lines.append("")
    lines.append(strings["education_placeholder"])
    lines.append("")

    return "\n".join(lines)
