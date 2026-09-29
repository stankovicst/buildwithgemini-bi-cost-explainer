# Copyright 2026 Google LLC
"""Custom services registration for ADK web and runner."""

import os
from urllib.parse import urlparse
from google.adk.cli.service_registry import get_service_registry
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService

# Ensure app-level services are loaded
import app.app_utils.services


def agentengine_memory_factory(uri: str, **kwargs):
    """Factory for agentengine:// URIs routing to the deployed Agent Engine in us-east1."""
    parsed = urlparse(uri)
    engine_id = (parsed.netloc + parsed.path).split("/")[-1] or "6689197845947351040"
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-6baaeaff7c42")
    location = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", "us-east1")
    return VertexAiMemoryBankService(
        project=project,
        location=location,
        agent_engine_id=engine_id,
    )


get_service_registry().register_memory_service("agentengine", agentengine_memory_factory)
