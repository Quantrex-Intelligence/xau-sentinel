"""Read-only Analysis Engine V2 view. A thin wrapper over api/analysis_v2.py.

GET only. This route never writes to the journal, risk state, alerts, or any
broker, and it is not used by the A+ evaluator, monitoring, or the LLM.
"""
from fastapi import APIRouter

from api import analysis_v2
from api.schemas_analysis_v2 import AnalysisV2Out

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/v2", response_model=AnalysisV2Out)
def get_analysis_v2():
    return analysis_v2.build_payload()
