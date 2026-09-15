import re


def is_html_template(content):
    """Keep the existing basic bold/italic text format on the text renderer."""
    return bool(re.search(
        r'<!doctype\s+html\b|<(?:html|head|body|style|div|section|main|header|footer|'
        r'p|h[1-6]|table|ul|ol|img|span)\b',
        content or '', re.IGNORECASE,
    ))
