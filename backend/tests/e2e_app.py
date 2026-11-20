"""Offline Gemini fixture for the browser walkthrough."""
import os

from app.analyst import api, workflow
from app.main import create_app


async def offline_analysis(facts, run_id, model, key):
    return {
        stage: {"summary": "The sandbox evidence was reviewed.", "confidence": "medium",
                "evidence_refs": [], "next_step": "Review the case before verifying."}
        for stage in workflow.ROLES
    }


def create_test_app():
    os.environ["GOOGLE_API_KEY"] = "offline-e2e-key"
    api.missing_packages = lambda: False
    workflow.analyze = offline_analysis
    return create_app()
