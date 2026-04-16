from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, request

from backend.hr_chatbot.recruitment_scorecard import extract_keywords, generate_behavioral_questions

from app.core.config import settings


logger = logging.getLogger(__name__)


def skim_candidate_profile(*, candidate_name: str, role_title: str, resume_text: str, job_description: str) -> dict[str, Any]:
    api_key = settings.openai_api_key.strip()
    if api_key:
        try:
            payload = _skim_with_openai(
                api_key=api_key,
                candidate_name=candidate_name,
                role_title=role_title,
                resume_text=resume_text,
                job_description=job_description,
            )
            payload["source"] = "openai"
            return payload
        except Exception:
            logger.exception("Recruitment skim layer fell back to heuristics after an OpenAI API failure.")

    fallback = _skim_with_heuristics(
        candidate_name=candidate_name,
        role_title=role_title,
        resume_text=resume_text,
        job_description=job_description,
    )
    fallback["source"] = "heuristic"
    return fallback


def _skim_with_openai(
    *,
    api_key: str,
    candidate_name: str,
    role_title: str,
    resume_text: str,
    job_description: str,
) -> dict[str, Any]:
    payload = {
        "model": settings.openai_recruitment_model,
        "input": [
            {
                "role": "developer",
                "content": (
                    "You are a senior technical recruiter performing a fast skim read of a candidate CV against a job "
                    "description. Return strict JSON only. Extract concise matched skills, likely gaps, risk flags, "
                    "and generate four tailored interview questions that clearly connect to the CV and role."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Candidate name: {candidate_name}\n"
                    f"Target role: {role_title}\n\n"
                    f"Job description:\n{job_description}\n\n"
                    f"CV text:\n{resume_text}"
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "recruitment_skim_profile",
                "schema": {
                    "type": "object",
                    "properties": {
                        "matched_skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 8,
                        },
                        "insights": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 3,
                            "maxItems": 6,
                        },
                        "gaps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 4,
                        },
                        "risk_flags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                        "summary": {"type": "string"},
                        "screening_questions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                    },
                    "required": [
                        "matched_skills",
                        "insights",
                        "gaps",
                        "risk_flags",
                        "summary",
                        "screening_questions",
                    ],
                    "additionalProperties": False,
                },
            }
        },
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=45) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI recruitment skim request failed with status {exc.code}: {body}") from exc

    text_output = _extract_response_text(response_payload)
    parsed = json.loads(text_output)
    screening_questions = [
        str(item).strip() for item in parsed["screening_questions"] if str(item).strip()
    ]
    if len(screening_questions) < 4:
        for fallback_question in generate_behavioral_questions(job_description):
            if fallback_question not in screening_questions:
                screening_questions.append(fallback_question)
            if len(screening_questions) >= 4:
                break
    return {
        "matched_skills": [str(item).strip() for item in parsed["matched_skills"] if str(item).strip()],
        "insights": [str(item).strip() for item in parsed["insights"] if str(item).strip()],
        "gaps": [str(item).strip() for item in parsed["gaps"] if str(item).strip()],
        "risk_flags": [str(item).strip() for item in parsed["risk_flags"] if str(item).strip()],
        "summary": str(parsed["summary"]).strip(),
        "screening_questions": screening_questions[:4],
    }


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]

    output = payload.get("output", [])
    for item in output:
        for content in item.get("content", []):
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value

    raise ValueError("No text output found in OpenAI recruitment skim response.")


def _skim_with_heuristics(
    *,
    candidate_name: str,
    role_title: str,
    resume_text: str,
    job_description: str,
) -> dict[str, Any]:
    jd_keywords = extract_keywords(job_description)
    resume_lower = resume_text.lower()
    matched_skills = [keyword for keyword in jd_keywords if keyword in resume_lower][:8]
    missing_skills = [keyword for keyword in jd_keywords if keyword not in resume_lower][:4]
    question_seed_terms = matched_skills[:2] + missing_skills[:2]

    insights = [
        f"{candidate_name} shows the strongest visible alignment for {', '.join(matched_skills[:3]) or role_title}.",
        (
            f"The CV maps well to the {role_title} brief through concrete mentions of "
            f"{', '.join(matched_skills[:4])}."
            if matched_skills
            else f"The CV gives limited direct evidence for the {role_title} brief and needs deeper probing."
        ),
        (
            f"Interview depth is needed around {', '.join(missing_skills[:2])} and real-world ownership."
            if missing_skills
            else "The interview should validate measurable outcomes, stakeholder communication, and technical depth."
        ),
    ]

    risk_flags = []
    if not matched_skills:
        risk_flags.append("Few explicit keyword matches between CV and job description.")
    if len(resume_text.split()) < 30:
        risk_flags.append("Resume text is short, so important experience details may be missing.")

    tailored_questions = _build_tailored_questions(
        role_title=role_title,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        fallback_questions=generate_behavioral_questions(job_description),
        question_seed_terms=question_seed_terms,
    )

    summary = (
        f"AI skim complete for {candidate_name}. Matched skills: {', '.join(matched_skills[:5]) or 'limited direct matches'}. "
        f"The interview will probe {' and '.join(missing_skills[:2]) if missing_skills else 'depth, outcomes, and communication'}."
    )

    return {
        "matched_skills": matched_skills,
        "insights": insights,
        "gaps": missing_skills,
        "risk_flags": risk_flags,
        "summary": summary,
        "screening_questions": tailored_questions,
    }


def _build_tailored_questions(
    *,
    role_title: str,
    matched_skills: list[str],
    missing_skills: list[str],
    fallback_questions: list[str],
    question_seed_terms: list[str],
) -> list[str]:
    custom_questions: list[str] = []

    if matched_skills:
        custom_questions.append(
            f"Your CV highlights {matched_skills[0]}. Tell me about a project where you used it to deliver a measurable outcome."
        )
    if len(matched_skills) > 1:
        custom_questions.append(
            f"You mention {matched_skills[1]}. Describe a difficult decision or trade-off you handled while using it."
        )
    if missing_skills:
        custom_questions.append(
            f"This role needs {missing_skills[0]}. What related experience would help you ramp up quickly in that area?"
        )
    if len(missing_skills) > 1:
        custom_questions.append(
            f"How would you approach learning and applying {missing_skills[1]} in your first month as a {role_title}?"
        )

    for question in fallback_questions:
        if len(custom_questions) >= 4:
            break
        if question not in custom_questions:
            custom_questions.append(question)

    if len(custom_questions) < 4 and question_seed_terms:
        custom_questions.append(
            f"Which example best shows your readiness for this {role_title} role, especially around {question_seed_terms[0]}?"
        )

    return custom_questions[:4]
