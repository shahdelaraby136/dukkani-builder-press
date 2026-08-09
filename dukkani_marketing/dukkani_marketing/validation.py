ALLOWED_CHANNELS = {"internal", "facebook", "instagram", "whatsapp"}
ALLOWED_STATUSES = {"Draft", "Pending Approval", "Approved", "Rejected"}
MAX_TITLE_LENGTH = 160
MAX_BODY_LENGTH = 20_000


def validate_draft_input(title, body, channel):
    title = (title or "").strip()
    body = (body or "").strip()
    channel = (channel or "internal").strip().lower()
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise ValueError("title is required and must be at most 160 characters")
    if not body or len(body) > MAX_BODY_LENGTH:
        raise ValueError("body is required and must be at most 20,000 characters")
    if channel not in ALLOWED_CHANNELS:
        raise ValueError("unsupported channel")
    return {"title": title, "body": body, "channel": channel}


def next_status(current_status, action):
    transitions = {
        ("Draft", "submit"): "Pending Approval",
        ("Pending Approval", "approve"): "Approved",
        ("Pending Approval", "reject"): "Rejected",
        ("Rejected", "resubmit"): "Pending Approval",
    }
    try:
        return transitions[(current_status, action)]
    except KeyError as error:
        raise ValueError("invalid content status transition") from error
