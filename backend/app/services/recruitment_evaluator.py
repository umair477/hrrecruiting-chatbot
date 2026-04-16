from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, request

from backend.hr_chatbot.recruitment_scorecard import extract_keywords

from app.core.config import settings


logger = logging.getLogger(__name__)


def evaluate_interview_answer(*, question: str, answer: str, job_description: str) -> dict[str, Any]:
    api_key = settings.openai_api_key.strip()
    if api_key:
        try:
            evaluation = _evaluate_with_openai(
                api_key=api_key,
                question=question,
                answer=answer,
                job_description=job_description,
            )
            evaluation["source"] = "openai"
            return evaluation
        except Exception:
            logger.exception("Recruitment evaluator fell back to heuristic scoring after an OpenAI API failure.")

    heuristic = _evaluate_with_heuristics(question=question, answer=answer, job_description=job_description)
    heuristic["source"] = "heuristic"
    return heuristic


def _evaluate_with_openai(*, api_key: str, question: str, answer: str, job_description: str) -> dict[str, Any]:
    payload = {
        "model": settings.openai_evaluator_model,
        "input": [
            {
                "role": "developer",
                "content": (
                    "You grade candidate interview answers. Return strict JSON with keys "
                    "'score' (integer 1-10) and 'justification' (short string). Grade based on "
                    "technical relevance to the role, whether the answer addresses the question, "
                    "and communication clarity."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Job description:\n{job_description}\n\n"
                    f"Interview question:\n{question}\n\n"
                    f"Candidate answer:\n{answer}"
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "candidate_answer_grade",
                "schema": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "integer", "minimum": 1, "maximum": 10},
                        "justification": {"type": "string"},
                    },
                    "required": ["score", "justification"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        },
    }
    http_request = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI evaluator request failed with status {exc.code}: {body}") from exc

    text_output = _extract_response_text(response_payload)
    parsed = json.loads(text_output)
    return {
        "score": int(parsed["score"]),
        "justification": str(parsed["justification"]).strip(),
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

    raise ValueError("No text output found in OpenAI evaluator response.")


def _evaluate_with_heuristics(*, question: str, answer: str, job_description: str) -> dict[str, Any]:
    answer_lower = answer.lower()
    job_keywords = extract_keywords(job_description)
    question_keywords = extract_keywords(question)

    keyword_hits = [keyword for keyword in job_keywords[:8] if keyword in answer_lower]
    question_hits = [keyword for keyword in question_keywords[:5] if keyword in answer_lower]
    action_hits = [
        signal
        for signal in {"built", "led", "improved", "delivered", "optimized", "resolved", "designed", "implemented"}
        if signal in answer_lower
    ]

    score = 3
    if len(answer.split()) >= 20:
        score += 2
    elif len(answer.split()) >= 8:
        score += 1

    score += min(3, len(keyword_hits))
    score += min(2, len(question_hits))
    score += 1 if action_hits else 0
    score = max(1, min(score, 10))

    strengths: list[str] = []
    if keyword_hits:
        strengths.append(f"Referenced role keywords like {', '.join(keyword_hits[:3])}.")
    if question_hits:
        strengths.append("Directly addressed the interview question.")
    if action_hits:
        strengths.append("Used action-oriented examples.")
    if not strengths:
        strengths.append("Answer needs more role-specific detail and clearer outcomes.")

    return {
        "score": score,
        "justification": " ".join(strengths),
    }
