"""i18n table for the portfolio harness.

LANGS: mapping from language code to an entry dict containing:
  - "name": the natural-language name to inject into LLM prompt instructions
  - All UI string keys used by the five renderers

SUPPORTED_LANGS: a live view of LANGS.keys() (not a frozen snapshot).
  A monkeypatch.setitem(LANGS, "xx", ...) is immediately reflected.

language_name(code): returns the natural-language name for the given code.
detect_language(text): deterministic Unicode-range heuristic → supported code.
  Counts Hangul letters vs Latin letters; dominant wins; ties → 'en'.
  Defaults to 'en' on empty / whitespace-only / no-letter input.
"""

from __future__ import annotations

import unicodedata

LANGS: dict[str, dict] = {
    "en": {
        "name": "English",
        # portfolio/render.py
        "title_portfolio": "Portfolio",
        "no_grounded_claims": "_no grounded claims_",
        "fallback_headline": "Portfolio for {subject} — {n_prs} merged PRs across {n_repos} repos.",
        "stat_merged_prs": "merged PRs",
        "stat_repos": "repos",
        "stack_summary_none": "no stack detected",
        "section_highlights": "Highlights",
        "group_other": "Other",
        "confidence": "Confidence",
        "evidence_section": "Evidence",
        # resume/render.py
        "title_resume": "Resume",
        "no_grounded_bullets": "_no grounded resume bullets_",
        "stat_contributions": "contributions",
        "stat_jd_keywords": "JD keywords",
        "section_experience": "Experience",
        "section_skills": "Skills",
        "no_stack_detected": "_no stack detected_",
        "section_contact": "Contact",
        "section_education": "Education",
        "contact_placeholder": "_Add your contact details._",
        "education_placeholder": "_Add your education._",
        # fit/render.py
        "title_fit": "Fit Assessment",
        "score_label": "Score",
        "band_label": "band",
        "jd_coverage_label": "JD Coverage",
        "section_covered": "Covered Requirements",
        "section_gaps": "Gaps",
        "none_notice": "_none_",
        "section_grounded_reasoning": "Grounded Reasoning",
        "no_grounded_reasoning": "_no grounded reasoning provided_",
        "section_grade_rubric": "Grade Rubric",
        "fit_rubric": (
            "| Grade | Coverage% | Score Band |\n"
            "|-------|-----------|------------|\n"
            "| S     | ≥90%      | 96–100     |\n"
            "| A     | ≥75%      | 85–95      |\n"
            "| B     | ≥55%      | 70–84      |\n"
            "| C     | ≥35%      | 55–69      |\n"
            "| D     | <35%      | 0–54       |"
        ),
        # rating/render.py
        "title_rating": "Capability Rating",
        "grade_label": "Grade",
        "score_label_rating": "Score",
        "rating_disclaimer": (
            "> This score is a rubric-based assessment of this developer's own "
            "grounded evidence — not a comparison to other engineers or a position "
            "in any population."
        ),
        "section_dimensions": "Dimensions",
        # per-dimension display names (keyed by rating.profile dimension key);
        # en values reproduce the legacy dim_name.replace("_", " ").title() output.
        "dimension_names": {
            "volume": "Volume",
            "breadth": "Breadth",
            "stack_diversity": "Stack Diversity",
            "scale": "Change Scale",
        },
        # band enum labels (keyed by rating.profile band value); en values are identity.
        "band_labels": {
            "High": "High",
            "Steady": "Steady",
            "Low": "Low",
            "Wide": "Wide",
            "Moderate": "Moderate",
            "Narrow": "Narrow",
            "Polyglot": "Polyglot",
            "Versatile": "Versatile",
            "Focused": "Focused",
            "Large": "Large",
            "Medium": "Medium",
            "Small": "Small",
        },
        "dim_value_label": "Value",
        "dim_band_label": "Band",
        "dim_points_label": "Points",
        "evidence_refs_label": "Evidence refs",
        "section_assessment": "Assessment",
        "section_improve": "How to Improve",
        "improve_maxed": "maxed",
        "section_rubric": "Rubric",
        "rating_rubric": (
            "| Grade | Score band |\n"
            "|-------|------------|\n"
            "| S     | 96–100     |\n"
            "| A     | 85–95      |\n"
            "| B     | 70–84      |\n"
            "| C     | 55–69      |\n"
            "| D     | 0–54       |"
        ),
        # reference_check/render.py
        "title_letter": "Recommendation Letter",
        "insufficient_evidence": "_insufficient grounded evidence — letter not generated_",
        "letter_greeting": "Dear Hiring Manager,",
        "letter_closing": "Sincerely,",
        # inline refs label used by highlight bullets and reasoning bullets (show_refs=True)
        "refs_inline_label": "refs",
    },
    "ko": {
        "name": "Korean",
        # portfolio/render.py
        "title_portfolio": "포트폴리오",
        "no_grounded_claims": "_근거 있는 클레임 없음_",
        "fallback_headline": "{subject}의 포트폴리오 — {n_repos}개 저장소, {n_prs}개 병합된 PR",
        "stat_merged_prs": "병합된 PR",
        "stat_repos": "저장소",
        "stack_summary_none": "기술 스택 미감지",
        "section_highlights": "주요 성과",
        "group_other": "기타",
        "confidence": "신뢰도",
        "evidence_section": "근거",
        # resume/render.py
        "title_resume": "이력서",
        "no_grounded_bullets": "_근거 있는 이력서 항목 없음_",
        "stat_contributions": "기여",
        "stat_jd_keywords": "JD 키워드",
        "section_experience": "경력",
        "section_skills": "기술",
        "no_stack_detected": "_기술 스택 없음_",
        "section_contact": "연락처",
        "section_education": "학력",
        "contact_placeholder": "_연락처를 추가하세요._",
        "education_placeholder": "_학력을 추가하세요._",
        # fit/render.py
        "title_fit": "적합도 평가",
        "score_label": "점수",
        "band_label": "범위",
        "jd_coverage_label": "JD 커버리지",
        "section_covered": "충족된 요구사항",
        "section_gaps": "미충족 요구사항",
        "none_notice": "_없음_",
        "section_grounded_reasoning": "근거 기반 평가",
        "no_grounded_reasoning": "_근거 있는 평가 없음_",
        "section_grade_rubric": "등급 기준표",
        "fit_rubric": (
            "| 등급 | 커버리지% | 점수 범위  |\n"
            "|------|-----------|------------|\n"
            "| S    | ≥90%      | 96–100     |\n"
            "| A    | ≥75%      | 85–95      |\n"
            "| B    | ≥55%      | 70–84      |\n"
            "| C    | ≥35%      | 55–69      |\n"
            "| D    | <35%      | 0–54       |"
        ),
        # rating/render.py
        "title_rating": "역량 평가",
        "grade_label": "등급",
        "score_label_rating": "점수",
        "rating_disclaimer": (
            "> 이 점수는 개발자 본인의 근거 기반 평가이며, 다른 엔지니어와의 비교나 집단 내 순위를 나타내지 않습니다."
        ),
        "section_dimensions": "평가 항목",
        # 평가 항목 표시 이름 (rating.profile 차원 키 기준)
        "dimension_names": {
            "volume": "활동량",
            "breadth": "범위",
            "stack_diversity": "기술 다양성",
            "scale": "변경 규모",
        },
        # 밴드 레이블 (rating.profile 밴드 값 기준)
        "band_labels": {
            "High": "높음",
            "Steady": "꾸준함",
            "Low": "낮음",
            "Wide": "넓음",
            "Moderate": "보통",
            "Narrow": "좁음",
            "Polyglot": "다언어",
            "Versatile": "다재다능",
            "Focused": "집중",
            "Large": "큼",
            "Medium": "중간",
            "Small": "작음",
        },
        "dim_value_label": "값",
        "dim_band_label": "범위",
        "dim_points_label": "점수",
        "evidence_refs_label": "근거 참조",
        "section_assessment": "종합 평가",
        "section_improve": "점수 올리기",
        "improve_maxed": "최고 단계",
        "section_rubric": "평가 기준",
        "rating_rubric": (
            "| 등급 | 점수 범위  |\n"
            "|------|------------|\n"
            "| S    | 96–100     |\n"
            "| A    | 85–95      |\n"
            "| B    | 70–84      |\n"
            "| C    | 55–69      |\n"
            "| D    | 0–54       |"
        ),
        # reference_check/render.py
        "title_letter": "추천서",
        "insufficient_evidence": "_근거 있는 증거 부족 — 추천서를 생성할 수 없습니다_",
        "letter_greeting": "채용 담당자님께,",
        "letter_closing": "감사합니다,",
        # inline refs label used by highlight bullets and reasoning bullets (show_refs=True)
        "refs_inline_label": "참조",
    },
}

# SUPPORTED_LANGS: a LIVE view of LANGS.keys(), NOT a frozen snapshot.
# monkeypatch.setitem(LANGS, "xx", ...) is immediately reflected here.
SUPPORTED_LANGS = LANGS.keys()


def language_name(code: str) -> str:
    """Return the natural-language name for the given language code.

    Sourced from the same LANGS table entry (single source of truth).
    """
    return LANGS[code]["name"]


def detect_language(text: str) -> str:
    """Detect the dominant script language in text.

    Returns a code present in LANGS (currently 'en' or 'ko').
    Defaults to 'en' on empty / whitespace-only / no-letter input and on ambiguous ties.

    Algorithm: count letter characters by Unicode category:
    - Hangul syllables (AC00–D7FF), jamo (1100–11FF), extended jamo (A960–A97F) → ko_count
    - Basic Latin + Latin Extended A/B (up to U+024F) → en_count
    - Other scripts (Kana, CJK, etc.) → ignored (neither counter incremented)
    - Dominant count wins; ties → 'en'
    """
    ko_count = 0
    en_count = 0
    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if cat[0] != "L":
            continue
        # Hangul syllables (AC00-D7FF), jamo (1100-11FF), extended jamo (A960-A97F)
        if (0xAC00 <= cp <= 0xD7FF) or (0x1100 <= cp <= 0x11FF) or (0xA960 <= cp <= 0xA97F):
            ko_count += 1
        elif cat in ("Ll", "Lu", "Lt", "Lm") and cp <= 0x024F:
            # Basic Latin + Latin Extended A/B
            en_count += 1
    if ko_count > en_count:
        return "ko"
    return "en"
