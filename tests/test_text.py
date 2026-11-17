from remote_radar.text import extract_links, find_terms, html_to_text, normalize_key


def test_html_to_text_keeps_paragraphs_and_bullets() -> None:
    html = "<p>Hello&nbsp;<b>world</b></p><ul><li>One</li><li>Two</li></ul><script>x()</script>"
    assert html_to_text(html) == "Hello world\n\n• One\n• Two"


def test_html_to_text_handles_plain_text_and_empty() -> None:
    assert html_to_text("  plain   text ") == "plain text"
    assert html_to_text(None) == ""


def test_extract_links_unescapes_attributes() -> None:
    assert extract_links('<a href="https:&#x2F;&#x2F;example.com&#x2F;jobs">x</a>') == [
        "https://example.com/jobs"
    ]


def test_normalize_key_ignores_case_punctuation_and_brackets() -> None:
    assert normalize_key("Senior QA Engineer (Remote) – EU") == "senior qa engineer eu"


def test_find_terms_matches_whole_tokens_only() -> None:
    text = "We use Next.js, CI/CD and n8n. No Javascripting."
    assert find_terms(text, ["next.js", "ci/cd", "n8n", "javascript", "node"]) == [
        "next.js",
        "ci/cd",
        "n8n",
    ]
