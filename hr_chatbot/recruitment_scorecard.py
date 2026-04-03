from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re


class Recommendation(str, Enum):
    STRONG_YES = "strong_yes"
    YES = "yes"
    MAYBE = "maybe"
    NO = "no"


@dataclass
class ScoreEvidence:
    score: int
    evidence: list[str] = field(default_factory=list)


@dataclass
class RecruitmentScorecard:
    candidate_name: str
    role_title: str
    skill_alignment: ScoreEvidence
    behavioral_fit: ScoreEvidence
    communication: ScoreEvidence
    problem_solving: ScoreEvidence
    culture_add: ScoreEvidence
    risk_flags: list[str]
    recommended_follow_up_questions: list[str]
    transcript_summary: str
    overall_suitability_score: int
    recommendation: Recommendation

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["recommendation"] = self.recommendation.value
        return payload


def extract_keywords(job_description: str) -> list[str]:
    phrases = re.findall(r"\b[a-zA-Z][a-zA-Z0-9+\-/]{2,}\b", job_description.lower())
    stop_words = {
        "with",
        "from",
        "that",
        "this",
        "have",
        "will",
        "your",
        "their",
        "about",
        "into",
        "role",
        "team",
        "years",
        "experience",
    }
    ranked: list[str] = []
    for phrase in phrases:
        if phrase not in stop_words and phrase not in ranked:
            ranked.append(phrase)
    return ranked[:12]


def score_keyword_alignment(cv_text: str, job_description: str) -> ScoreEvidence:
    keywords = extract_keywords(job_description)
    cv_lower = cv_text.lower()
    matches = [keyword for keyword in keywords if keyword in cv_lower]
    score = min(5, max(1, round((len(matches) / max(len(keywords), 1)) * 5)))
    evidence = [f"Matched job keyword: {keyword}" for keyword in matches[:5]]
    if not evidence:
        evidence.append("Few explicit job keywords were found in the CV.")
    return ScoreEvidence(score=score, evidence=evidence)


def score_behavioral_answers(answers: list[str]) -> tuple[ScoreEvidence, ScoreEvidence, ScoreEvidence]:
    behavioral_signals = {
        "ownership": {"owned", "led", "responsible", "improved", "delivered"},
        "communication": {"stakeholder", "communicated", "aligned", "presented", "explained"},
        "problem_solving": {"resolved", "analyzed", "debugged", "optimized", "root cause"},
    }
    combined = " ".join(answers).lower()

    behavioral_hits = [term for term in behavioral_signals["ownership"] if term in combined]
    communication_hits = [term for term in behavioral_signals["communication"] if term in combined]
    problem_hits = [term for term in behavioral_signals["problem_solving"] if term in combined]

    behavioral = ScoreEvidence(
        score=min(5, max(1, len(behavioral_hits) + 2)),
        evidence=[f"Behavioral signal: {term}" for term in behavioral_hits[:4]] or ["Limited ownership evidence."],
    )
    communication = ScoreEvidence(
        score=min(5, max(1, len(communication_hits) + 2)),
        evidence=[f"Communication signal: {term}" for term in communication_hits[:4]]
        or ["Limited communication evidence."],
    )
    problem_solving = ScoreEvidence(
        score=min(5, max(1, len(problem_hits) + 2)),
        evidence=[f"Problem-solving signal: {term}" for term in problem_hits[:4]]
        or ["Limited problem-solving evidence."],
    )
    return behavioral, communication, problem_solving


def score_culture_add(answers: list[str]) -> ScoreEvidence:
    combined = " ".join(answers).lower()
    signals = {"mentor", "learned", "collaborated", "customer", "feedback", "inclusive"}
    hits = [signal for signal in signals if signal in combined]
    return ScoreEvidence(
        score=min(5, max(1, len(hits) + 1)),
        evidence=[f"Culture-add signal: {term}" for term in hits[:4]] or ["Culture-add evidence needs follow-up."],
    )


def determine_recommendation(overall_score: int, risk_flags: list[str]) -> Recommendation:
    if "Integrity concern" in risk_flags:
        return Recommendation.NO
    if overall_score >= 85:
        return Recommendation.STRONG_YES
    if overall_score >= 70:
        return Recommendation.YES
    if overall_score >= 55:
        return Recommendation.MAYBE
    return Recommendation.NO


def generate_behavioral_questions(job_description: str) -> list[str]:
    keywords = extract_keywords(job_description)[:3]
    if not keywords:
        return [
            "Tell me about a time you handled conflicting priorities.",
            "Describe a situation where you improved a process.",
            "How do you approach feedback from stakeholders?",
        ]

    return [
        f"Tell me about a time you used {keywords[0]} to deliver a measurable outcome.",
        f"Describe a challenging situation involving {keywords[1]} and how you handled it."
        if len(keywords) > 1
        else "Describe a challenging project and how you handled it.",
        f"Give an example of how you communicated trade-offs while working on {keywords[2]}."
        if len(keywords) > 2
        else "Give an example of how you communicated trade-offs to a stakeholder.",
        "Tell me about a time you had to learn something quickly to succeed in a role.",
    ]


def build_scorecard(
    *,
    candidate_name: str,
    role_title: str,
    cv_text: str,
    job_description: str,
    screening_answers: list[str],
) -> RecruitmentScorecard:
    skill_alignment = score_keyword_alignment(cv_text, job_description)
    behavioral_fit, communication, problem_solving = score_behavioral_answers(screening_answers)
    culture_add = score_culture_add(screening_answers)

    risk_flags: list[str] = []
    combined_answers = " ".join(screening_answers).lower()
    if "i don't know" in combined_answers or "not sure" in combined_answers:
        risk_flags.append("Low confidence in behavioral responses")
    if "blame" in combined_answers:
        risk_flags.append("Possible collaboration risk")

    weighted_total = (
        skill_alignment.score * 0.35
        + behavioral_fit.score * 0.2
        + communication.score * 0.15
        + problem_solving.score * 0.2
        + culture_add.score * 0.1
    )
    overall_score = int(round((weighted_total / 5) * 100))

    return RecruitmentScorecard(
        candidate_name=candidate_name,
        role_title=role_title,
        skill_alignment=skill_alignment,
        behavioral_fit=behavioral_fit,
        communication=communication,
        problem_solving=problem_solving,
        culture_add=culture_add,
        risk_flags=risk_flags,
        recommended_follow_up_questions=generate_behavioral_questions(job_description),
        transcript_summary=" ".join(answer.strip() for answer in screening_answers if answer.strip()),
        overall_suitability_score=overall_score,
        recommendation=determine_recommendation(overall_score, risk_flags),
    )


SCORECARD_SCHEMA = {
    "candidate_name": "str",
    "role_title": "str",
    "skill_alignment": {"score": "int[1-5]", "evidence": "list[str]"},
    "behavioral_fit": {"score": "int[1-5]", "evidence": "list[str]"},
    "communication": {"score": "int[1-5]", "evidence": "list[str]"},
    "problem_solving": {"score": "int[1-5]", "evidence": "list[str]"},
    "culture_add": {"score": "int[1-5]", "evidence": "list[str]"},
    "risk_flags": "list[str]",
    "recommended_follow_up_questions": "list[str]",
    "transcript_summary": "str",
    "overall_suitability_score": "int[0-100]",
    "recommendation": [recommendation.value for recommendation in Recommendation],
}

