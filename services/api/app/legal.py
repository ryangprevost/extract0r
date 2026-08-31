"""Legal copy, defined once and served to every surface.

Keeping the wording in code (not in a CMS or duplicated in the front end) means the
API, the web app, and every exported .x0r file always carry the same notice, and a
change to it is a reviewable diff.

This is not legal advice; have a lawyer review before you accept public uploads.
"""

from __future__ import annotations

TERMS_VERSION = "2026-08-31"

COPYRIGHT_NOTICE = (
    "Extract0r processes audio you provide. Recorded music, and the compositions "
    "underneath it, are usually protected by copyright. Separating a recording into "
    "stems, transcribing it, and re-mixing it all create derivative works. Do not "
    "upload material you do not own or have permission to use, and do not distribute "
    "what Extract0r produces from someone else's recording without a licence."
)

UPLOAD_GATE_TEXT = (
    "By uploading, you confirm that you own this recording, have a licence for it, or "
    "that your use is otherwise permitted by law, and that you will use the output for "
    "personal study, practice, or other lawful purposes."
)

FAIR_USE_NOTE = (
    "In the United States, transcribing a recording for private study or practice is "
    "often argued to be fair use, but fair use is a defence decided case by case, not "
    "a permission slip. Other countries treat private copying differently. Extract0r "
    "cannot tell you whether your specific use is lawful."
)

NO_DRM_CIRCUMVENTION = (
    "Extract0r will not process audio obtained by circumventing digital rights "
    "management, ripping from a streaming service in breach of its terms, or any "
    "other method that violates the rights holder's terms of use."
)

RETENTION_NOTICE = (
    "Uploaded audio and every file derived from it are deleted automatically after the "
    "retention window shown on this page. You can delete a track immediately at any "
    "time from the studio screen."
)

DMCA_NOTICE = (
    "If you believe material processed through Extract0r infringes your copyright, "
    "send a notice identifying the work, the material at issue, your contact details, "
    "a statement of good-faith belief, and a statement made under penalty of perjury "
    "that you are authorised to act for the rights holder."
)

ALL_NOTICES = {
    "copyright": COPYRIGHT_NOTICE,
    "upload_gate": UPLOAD_GATE_TEXT,
    "fair_use": FAIR_USE_NOTE,
    "no_drm_circumvention": NO_DRM_CIRCUMVENTION,
    "retention": RETENTION_NOTICE,
    "dmca": DMCA_NOTICE,
}
