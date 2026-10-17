"""Medical corpus configuration; public reference documents are excluded."""

from kloop.extract.provider import PROMPT

ROOT_FOLDER_ID = "428390666255"
SOURCE_FOLDER_ID = "428391006380"
MEDICAL_PROMPT = (
    PROMPT + " Extract company-specific clinical, safety, quality, commercial/HEOR and regulatory "
    "claims exactly as stated. Keep study populations, endpoints, time periods, uncertainty, "
    "units and reporting timelines. Do not infer medical advice or turn a tentative finding "
    "into an established result."
)
