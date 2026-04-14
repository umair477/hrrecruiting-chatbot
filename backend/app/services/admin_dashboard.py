from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, request

from backend.app.core.config import settings
from backend.app.models import EmploymentType


logger = logging.getLogger(__name__)


def split_full_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def recommendation_label_for_score(score: int) -> str:
    if score >= 90:
        return "Highly Recommended"
    if score >= 70:
        return "Recommended"
    if score >= 50:
        return "Needs Review"
    return "Not Recommended"


def generate_job_post(title: str) -> dict[str, Any]:
    api_key = settings.openai_api_key.strip()
    if api_key:
        try:
            payload = _generate_job_post_with_openai(api_key=api_key, title=title)
            payload["source"] = "openai"
            return payload
        except Exception:
            logger.exception("Job generation fell back to heuristics after an OpenAI API failure.")

    payload = _generate_job_post_heuristically(title)
    payload["source"] = "heuristic"
    return payload


def _generate_job_post_with_openai(*, api_key: str, title: str) -> dict[str, Any]:
    payload = {
        "model": settings.openai_recruitment_model,
        "input": [
            {
                "role": "developer",
                "content": (
                    "You are an HR operations assistant generating a polished job post from only a job title. "
                    "Return strict JSON only. Keep the output realistic, concise, and internally consistent."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Generate a complete job post for this title: {title}\n\n"
                    "Return fields for description, required_skills, experience_years, employment_type, "
                    "salary_range, responsibilities, and nice_to_have_qualifications."
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "generated_job_post",
                "schema": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "required_skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 5,
                            "maxItems": 10,
                        },
                        "experience_years": {"type": "integer", "minimum": 0, "maximum": 25},
                        "employment_type": {
                            "type": "string",
                            "enum": [EmploymentType.FULL_TIME.value, EmploymentType.PART_TIME.value, EmploymentType.CONTRACT.value],
                        },
                        "salary_range": {"type": "string"},
                        "responsibilities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 4,
                            "maxItems": 8,
                        },
                        "nice_to_have_qualifications": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 6,
                        },
                    },
                    "required": [
                        "description",
                        "required_skills",
                        "experience_years",
                        "employment_type",
                        "salary_range",
                        "responsibilities",
                        "nice_to_have_qualifications",
                    ],
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
        with request.urlopen(http_request, timeout=45) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI job generation request failed with status {exc.code}: {body}") from exc

    text_output = _extract_response_text(response_payload)
    parsed = json.loads(text_output)
    return {
        "description": str(parsed["description"]).strip(),
        "required_skills": _clean_string_list(parsed["required_skills"]),
        "experience_years": int(parsed["experience_years"]),
        "employment_type": str(parsed["employment_type"]).strip(),
        "salary_range": str(parsed["salary_range"]).strip(),
        "responsibilities": _clean_string_list(parsed["responsibilities"]),
        "nice_to_have_qualifications": _clean_string_list(parsed["nice_to_have_qualifications"]),
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

    raise ValueError("No text output found in OpenAI job generation response.")


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _generate_job_post_heuristically(title: str) -> dict[str, Any]:
    title_lower = title.lower()
    experience_years = _infer_experience_years(title_lower)
    profile = _role_profile_for_title(title_lower)

    description = (
        f"We are hiring a {title} to help scale a fast-moving HR technology environment. "
        f"This role focuses on {profile['focus']}, strong cross-functional delivery, and measurable business outcomes."
    )

    return {
        "description": description,
        "required_skills": profile["required_skills"],
        "experience_years": experience_years,
        "employment_type": EmploymentType.FULL_TIME.value,
        "salary_range": _infer_salary_range(title_lower),
        "responsibilities": [
            f"Own end-to-end delivery for {profile['focus']}.",
            f"Partner with product, operations, and leadership on {profile['partnership_area']}.",
            f"Define and improve standards for {profile['quality_area']}.",
            "Translate business needs into well-scoped execution plans and measurable outcomes.",
            "Mentor teammates and communicate delivery risks, trade-offs, and progress clearly.",
        ],
        "nice_to_have_qualifications": profile["nice_to_have"],
    }


def _infer_experience_years(title_lower: str) -> int:
    if any(keyword in title_lower for keyword in ("principal", "staff", "lead", "head")):
        return 8
    if "senior" in title_lower:
        return 5
    if any(keyword in title_lower for keyword in ("manager", "architect")):
        return 6
    if any(keyword in title_lower for keyword in ("junior", "associate")):
        return 1
    return 3


def _infer_salary_range(title_lower: str) -> str:
    if any(keyword in title_lower for keyword in ("principal", "staff", "head", "director")):
        return "$150,000 - $190,000"
    if any(keyword in title_lower for keyword in ("senior", "manager", "architect", "lead")):
        return "$120,000 - $155,000"
    if any(keyword in title_lower for keyword in ("analyst", "designer", "developer", "engineer")):
        return "$85,000 - $120,000"
    return "$70,000 - $105,000"


def _role_profile_for_title(title_lower: str) -> dict[str, Any]:
    if any(keyword in title_lower for keyword in ("python", "backend", "api")):
        return {
            "focus": "backend services, APIs, and automation workflows",
            "partnership_area": "platform reliability and product delivery",
            "quality_area": "performance, observability, and maintainable architecture",
            "required_skills": [
                "Python",
                "FastAPI",
                "REST API design",
                "SQL and data modeling",
                "Background jobs and workflow orchestration",
                "Testing and debugging",
                "Cloud deployment fundamentals",
            ],
            "nice_to_have": [
                "Experience with HR, recruiting, or internal tooling products",
                "Familiarity with AI-assisted workflow design",
                "Exposure to Docker and CI/CD pipelines",
            ],
        }
    if any(keyword in title_lower for keyword in ("frontend", "react", "ui", "design systems")):
        return {
            "focus": "modern frontend experiences and reusable interface systems",
            "partnership_area": "design systems, accessibility, and product iteration",
            "quality_area": "performance, usability, and maintainable components",
            "required_skills": [
                "React",
                "TypeScript",
                "Component architecture",
                "Responsive design",
                "Accessibility best practices",
                "State management",
                "Frontend testing",
            ],
            "nice_to_have": [
                "Design system ownership experience",
                "Motion and interaction design sensibility",
                "Experience integrating with analytics or AI-powered products",
            ],
        }
    if any(keyword in title_lower for keyword in ("data", "analyst", "analytics", "bi")):
        return {
            "focus": "analytics delivery, reporting, and decision support",
            "partnership_area": "stakeholder reporting and operational planning",
            "quality_area": "data quality, insight communication, and dashboard reliability",
            "required_skills": [
                "SQL",
                "Data analysis",
                "Dashboarding",
                "Python or R",
                "Business communication",
                "Data visualization",
                "Problem-solving",
            ],
            "nice_to_have": [
                "Experience with recruiting or HR analytics",
                "Knowledge of experimentation or forecasting",
                "Comfort working with product and operations leaders",
            ],
        }
    if any(keyword in title_lower for keyword in ("designer", "ux", "product design")):
        return {
            "focus": "user-centered product design and experimentation",
            "partnership_area": "research, prototyping, and product delivery",
            "quality_area": "interaction quality, accessibility, and design consistency",
            "required_skills": [
                "Product design",
                "Figma",
                "User research",
                "Wireframing and prototyping",
                "Design systems",
                "Stakeholder communication",
                "Usability testing",
            ],
            "nice_to_have": [
                "Experience designing B2B SaaS workflows",
                "Strong metrics-informed design practice",
                "Comfort collaborating closely with frontend engineers",
            ],
        }
    return {
        "focus": "cross-functional execution and operational excellence",
        "partnership_area": "business priorities and team coordination",
        "quality_area": "process quality, delivery consistency, and stakeholder trust",
        "required_skills": [
            "Stakeholder communication",
            "Project delivery",
            "Problem-solving",
            "Documentation",
            "Cross-functional collaboration",
            "Analytical thinking",
        ],
        "nice_to_have": [
            "Experience in HR technology or recruiting workflows",
            "Comfort with process improvement initiatives",
            "Exposure to data-informed decision making",
        ],
    }
