import pikepdf
import pytest


@pytest.mark.parametrize("annotations,expected", [
    (None, False),
    (pikepdf.Array([pikepdf.Dictionary(Subtype=pikepdf.Name.Widget)]), True),
    (pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name.Annot)]), False),
    (pikepdf.Array([None, 42, pikepdf.Dictionary(Subtype=pikepdf.Name.Link)]), False),
    (pikepdf.Dictionary(), False),
    (pikepdf.Array([None, pikepdf.Dictionary(Subtype=pikepdf.Name.Widget)]), True),
])
def test_annotation_shapes(web, tmp_path, annotations, expected):
    main, _ = web
    path = tmp_path / "fields.pdf"
    with pikepdf.new() as pdf:
        page = pdf.add_blank_page()
        if annotations is not None:
            page.Annots = annotations
        pdf.save(path)
    assert main.has_fields(str(path)) is expected


def test_title_uses_upload_directory(web, tmp_path):
    main, _ = web
    folder = tmp_path / ("a" * 64)
    folder.mkdir()
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.docinfo.Title = "Actual title"
        pdf.save(folder / "fallback-name.pdf")
    assert main.get_pdf_title_from_hash(folder.name) == "Actual title"
    assert main.get_pdf_title_from_hash("b" * 64) == ""


def test_highlights_escape_document_html(web):
    main, _ = web
    assert main.highlight_text('<script>x</script>', [(8, 9)]) == '&lt;script&gt;<span class="highlight">x</span>&lt;/script&gt;'
    assert main.highlight_text('<img onerror="alert(1)">', []) == '&lt;img onerror=&quot;alert(1)&quot;&gt;'
