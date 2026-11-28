import json
from pathlib import Path


def test_vercel_json_gis_headers():
    vercel_path = Path(__file__).resolve().parent.parent / "vercel.json"
    data = json.loads(vercel_path.read_text(encoding="utf-8"))

    catch_all_blocks = [
        block for block in data.get("headers", []) if block.get("source") == "/(.*)"
    ]
    assert catch_all_blocks, "Expected a '/(.*)' headers block in vercel.json"

    headers = {h["key"]: h["value"] for h in catch_all_blocks[0]["headers"]}

    csp = headers.get("Content-Security-Policy", "")
    style_src_part = next(
        (part.strip() for part in csp.split(";") if part.strip().startswith("style-src")),
        "",
    )
    assert "https://accounts.google.com" in style_src_part, (
        f"Expected https://accounts.google.com in style-src, got: {style_src_part}"
    )

    assert headers.get("Cross-Origin-Opener-Policy") == "same-origin-allow-popups"
