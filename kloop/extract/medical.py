"""Medical corpus configuration; public reference documents are excluded."""

from kloop.extract.provider import PROMPT

ROOT_FOLDER_ID = "428390666255"
SOURCE_FOLDER_ID = "428391006380"
MAX_EXTRACTED_ITEMS = 8
MEDICAL_PROMPT = (
    PROMPT + " Extract company-specific clinical, safety, quality, commercial/HEOR and regulatory "
    "claims exactly as stated. Keep study populations, endpoints, time periods, uncertainty, "
    "units and reporting timelines. Do not infer medical advice or turn a tentative finding "
    "into an established result. "
    "Return AT MOST 8 items for this entire document, even if more attributes are present. "
    "Prefer specific checkable company facts: identifiers, numbers, dates, owners, limits, "
    "and SOP decision rules. Include one complete decision rule or procedure per SOP when "
    "present, within the same 8-item total. Ignore less specific background information. "
    "For this initial extraction every item_id MUST be an empty string; source document IDs, "
    "case IDs and study IDs are subject values, never item_id values. Existing identities: []"
)
MEDICAL_FIELD_DESCRIPTION = (
    "At most 8 facts or complete procedures total per document. Prefer specific checkable "
    "identifiers, numbers, dates, owners, limits and one decision rule per SOP. "
    "Every item_id is empty for initial extraction."
)
