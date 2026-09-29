"""Image generation and caching tools using gemini-3.1-flash-lite-image in the global region."""

import uuid
from typing import Any
from google import genai
from google.genai import types
from google.cloud import storage, firestore
from google.adk.tools import ToolContext

PROJECT_ID = "qwiklabs-gcp-03-6baaeaff7c42"
BUCKET_NAME = "bi-cost-explainer-o7rv0e"
IMAGE_COLLECTION = "report_images"

BRAND_STYLE = (
    "flat vector illustration, dark navy background, teal and amber accents, "
    "clean corporate data-platform aesthetic, no text, no numbers, no charts, no logos"
)

# Initialize clients with hardcoded project ID
_genai_client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location="global",
)
_storage_client = storage.Client(project=PROJECT_ID)
_firestore_client = firestore.Client(project=PROJECT_ID)

METAPHOR_MAP = {
    "full scans": "a giant vacuum hoovering up an entire warehouse of boxes",
    "usage growth, efficient": "a smooth fast conveyor belt with neat parcels",
    "schedule instead of live": "a crowd of people all pressing the same elevator button",
}


def _get_cached_url(doc_id: str) -> str | None:
    doc = _firestore_client.collection(IMAGE_COLLECTION).document(doc_id).get()
    if doc.exists:
        return doc.to_dict().get("public_url")
    return None


def _set_cached_url(doc_id: str, week_start: str, image_type: str, public_url: str) -> None:
    _firestore_client.collection(IMAGE_COLLECTION).document(doc_id).set({
        "week_start": week_start,
        "image_type": image_type,
        "public_url": public_url,
    })


async def _generate_and_store_image(
    prompt_subject: str,
    doc_id: str,
    week_start: str,
    image_type: str,
    tool_context: ToolContext | None,
) -> str:
    # Check Firestore cache first
    cached = _get_cached_url(doc_id)
    if cached:
        return cached

    full_prompt = f"{BRAND_STYLE}. Subject: {prompt_subject}"
    response = _genai_client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=full_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    if not response.candidates or not response.candidates[0].content.parts:
        raise RuntimeError("No image returned from gemini-3.1-flash-lite-image.")

    part = response.candidates[0].content.parts[0]
    image_bytes = part.inline_data.data
    mime_type = part.inline_data.mime_type or "image/jpeg"
    ext = "jpg" if "jpeg" in mime_type else "png"
    filename = f"{image_type}_{uuid.uuid4().hex[:8]}.{ext}"

    # 1. Save artifact if tool_context available
    if tool_context and hasattr(tool_context, "save_artifact"):
        try:
            await tool_context.save_artifact(
                filename=filename,
                artifact=types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            )
        except Exception as e:
            print(f"Notice: artifact saving skipped: {e}")

    # 2. Upload bytes directly to public GCS bucket (no local file written)
    bucket = _storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

    # 3. Cache in Firestore
    _set_cached_url(doc_id, week_start, image_type, public_url)

    return public_url


async def generate_cover_image(
    topic: str,
    week_start: str = "latest",
    tool_context: ToolContext = None,
) -> str:
    """Generates a branded cover image for a weekly BI cost report with Firestore caching.

    Args:
        topic: The topic or title of the report (e.g. 'Weekly BI Spend Report').
        week_start: The week start date (YYYY-MM-DD) for report caching.
        tool_context: ADK ToolContext injected automatically by the runtime.

    Returns:
        The public HTTPS URL of the cover image.
    """
    doc_id = f"{week_start}_cover"
    return await _generate_and_store_image(
        prompt_subject=f"Cover illustration for {topic}",
        doc_id=doc_id,
        week_start=week_start,
        image_type="cover",
        tool_context=tool_context,
    )


async def generate_driver_image(
    fix_type: str,
    week_start: str = "latest",
    tool_context: ToolContext = None,
) -> str:
    """Generates a visual metaphor image representing a specific BI cost driver fix type.

    Metaphors:
    - 'full scans' -> a giant vacuum hoovering up an entire warehouse of boxes
    - 'usage growth, efficient' -> a smooth fast conveyor belt with neat parcels
    - 'schedule instead of live' -> a crowd of people all pressing the same elevator button

    Args:
        fix_type: The remediation or driver type from suggest_fix.
        week_start: The week start date (YYYY-MM-DD) for report caching.
        tool_context: ADK ToolContext injected automatically by the runtime.

    Returns:
        The public HTTPS URL of the metaphor image.
    """
    fix_lower = fix_type.lower()
    if "full scan" in fix_lower:
        metaphor = METAPHOR_MAP["full scans"]
        image_type = "driver_full_scans"
    elif "usage growth" in fix_lower or "efficient" in fix_lower:
        metaphor = METAPHOR_MAP["usage growth, efficient"]
        image_type = "driver_usage_growth"
    elif "schedule" in fix_lower or "live" in fix_lower:
        metaphor = METAPHOR_MAP["schedule instead of live"]
        image_type = "driver_schedule_instead_of_live"
    else:
        metaphor = f"an abstract depiction of cloud infrastructure operations: {fix_type}"
        image_type = f"driver_{uuid.uuid4().hex[:6]}"

    doc_id = f"{week_start}_{image_type}"
    return await _generate_and_store_image(
        prompt_subject=metaphor,
        doc_id=doc_id,
        week_start=week_start,
        image_type=image_type,
        tool_context=tool_context,
    )
