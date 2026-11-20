from coach.formatting import split_messages, strip_tags, to_html


def test_keeps_allowed_tags_and_escapes_rest():
    assert to_html("<b>Supino</b> 60kg < 70kg & <script>x</script>") == \
        "<b>Supino</b> 60kg &lt; 70kg &amp; &lt;script&gt;x&lt;/script&gt;"


def test_converts_markdown():
    out = to_html("## Treino A\n- **Agachamento** 3x8\n- Leg press")
    assert out == "<b>Treino A</b>\n• <b>Agachamento</b> 3x8\n• Leg press"


def test_split_on_marker_and_limit():
    parts = split_messages("Visão geral\n---\nDia A\n\n---\nDia B")
    assert parts == ["Visão geral", "Dia A", "Dia B"]
    long = "\n\n".join(["linha " * 50] * 40)
    assert all(len(p) <= 4000 for p in split_messages(long))


def test_strip_tags():
    assert strip_tags("<b>a</b> &amp; b") == "a & b"
