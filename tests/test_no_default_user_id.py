import re
from pathlib import Path

def test_no_default_user_id():
    """Garde-fou BALI-47 : aucun `user_id` par defaut (isolation multi-utilisateur)."""
    pattern = re.compile(r"user_id\s*(:\s*\w+)?\s*=\s*1\b")
    offenders = [
        f"{p}:{i}"
        for p in Path("src").rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if line.lstrip().startswith("def ") and pattern.search(line) or (pattern.search(line) and "user_id: int" in line and "=" in line.split("user_id")[1][:12] and "(" not in line)
    ]
    assert not offenders, offenders

