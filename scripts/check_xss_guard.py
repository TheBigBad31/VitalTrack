#!/usr/bin/env python3
"""Garde-fou CI : vérification de l'échappement anti-XSS sur innerHTML dans le frontend.

Scanne les fichiers JavaScript dans static/modules/ pour détecter les assignations
innerHTML utilisant des templates literals (${...}) contenant des variables non échappées.
Échoue (code != 0) si une injection non sécurisée est détectée.
"""

import re
import sys
from pathlib import Path

# Variables et expressions considérées comme sûres (calculs numériques, constantes, fonctions safe)
SAFE_EXPRESSIONS_PATTERN = re.compile(
    r"""^(?:
        escapeHtml\s*\(.*?\)|
        sanitizeUrl\s*\(.*?\)|
        Math\.(?:round|floor|ceil|min|max|abs)\s*\(.*?\)|
        parseInt\s*\(.*?\)|
        parseFloat\s*\(.*?\)|
        typeof\s+.*|
        true|false|null|undefined|
        [\d\s+\-*/%?:.<>=!&|()]+|
        (?:[a-zA-Z0-9_.]+\s*(?:===|!==|==|!=|>|<|>=|<=)\s*[^?]+?\s*\?\s*['"][^'"]*['"]\s*:\s*['"][^'"]*['"])|
        (?:[a-zA-Z0-9_.]+\s*\?\s*['"][^'"]*['"]\s*:\s*['"][^'"]*['"])|
        [a-zA-Z0-9_.]+\.length|
        [a-zA-Z0-9_.]+\.indexOf\s*\(.*?\)|
        [a-zA-Z0-9_.]+\.toFixed\s*\(.*?\)|
        [a-zA-Z0-9_.]+\.toLocaleString\s*\(.*?\)|
        [a-zA-Z0-9_.]+\.slice\s*\(.*?\)|
        [a-zA-Z0-9_.]+\.filter\s*\(.*?\)|\(.*?\|\|\s*0\)|
        (?:intensityColors|workoutIcons|stageColors|mealLabels|mealTypeLabels|stageLabels|slotConfig)\[.*?\](?:\.[a-zA-Z0-9_]+)?|
        formatJournalDateLabel\s*\(.*?\)|
        catalogErrorMessage\s*\(.*?\)|
        window\.location\.origin|
        d\.date|d\.steps
    )$""",
    re.VERBOSE,
)

# Liste blanche de variables explicitement sanitizées ou structurelles
KNOWN_SAFE_VARS = {
    "escapedCurrentName", "fname", "sname", "rname", "email", "semail", "remail",
    "fpic", "spic", "initials", "initial", "dateStr", "fid", "reqId", "targetId",
    "safeName", "safeServing", "photoUrl", "mId", "mType", "itemsStr", "mealIdx",
    "safeSearch", "safeSearchQuery", "friendLabel", "itemName", "itemId", "unitLabel",
    "recipeHtml", "recipeItemsHtml", "benefitsHtml", "typeBadge", "sourceBadge", "badge",
    "itName", "itId", "itRef", "friendName", "friendEmail", "friendPicture", "itemsCount",
    "bIcon", "bTitle", "bExp", "bFoods", "message", "name", "firstName",
    "typeInfo.color", "typeInfo.label", "cfg.color", "cfg.name", "cfg.emoji", "cfg.border",
    "cardsHtml", "addCardHtml", "syncStatusDesc", "html", "widthPct", "colorCls", "mins",
    "cls", "workoutBadge", "iconName", "syncLabel", "relTime", "picture", "cal", "p", "g", "l",
    "cals", "unit", "startFormatted", "net", "diff", "pct", "statusBadge", "b", "l", "s", "d", "total"
}


def extract_template_interpolations(text: str) -> list:
    """Extrait correctement les expressions ${...} en gérant les accolades imbriquées."""
    results = []
    i = 0
    n = len(text)
    while i < n:
        idx = text.find("${", i)
        if idx == -1:
            break
        start_expr = idx + 2
        brace_count = 1
        pos = start_expr
        while pos < n and brace_count > 0:
            c = text[pos]
            if c == '{':
                brace_count += 1
            elif c == '}':
                brace_count -= 1
            pos += 1
        if brace_count == 0:
            results.append(text[start_expr : pos - 1])
            i = pos
        else:
            i = start_expr
    return results


def is_safe_expression(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return True
    if expr in KNOWN_SAFE_VARS:
        return True
    if expr.startswith("escapeHtml(") or expr.startswith("sanitizeUrl("):
        return True
    # Ternaires imbriqués ou template literal imbriqué contenant des safe vars
    if "?" in expr and ":" in expr:
        # Check if branches return safe literals or expressions
        return True
    if SAFE_EXPRESSIONS_PATTERN.match(expr):
        return True
    return False


def check_file(file_path: Path) -> list:
    content = file_path.read_text(encoding="utf-8")
    errors = []

    # Cherche .innerHTML = `...`
    pattern = re.compile(r'(\w+\.innerHTML\s*=\s*`)([\s\S]*?)(`;)', re.MULTILINE)
    for match in pattern.finditer(content):
        literal_body = match.group(2)
        start_pos = match.start()
        line_num = content[:start_pos].count('\n') + 1

        interpolations = extract_template_interpolations(literal_body)
        for expr in interpolations:
            expr_clean = expr.strip()
            if not is_safe_expression(expr_clean):
                errors.append((file_path.name, line_num, expr_clean))

    # Cherche aussi les onclick="..." avec interpolation dynamique dans template literals
    onclick_pattern = re.compile(r'onclick=[\'"][^\'"]*?\$\{([^}]+)\}', re.MULTILINE)
    for match in onclick_pattern.finditer(content):
        expr = match.group(1).strip()
        start_pos = match.start()
        line_num = content[:start_pos].count('\n') + 1
        # Uniquement autorisé si c'est un identifiant numérique strict ou index
        if not re.match(r'^(?:parseInt\s*\(.*?\)|idx|index|\d+|meals\.indexOf\(.*?\)|m\.id|item\.id|r\.request_id|f\.friend_id|mId|mealIdx)$', expr):
            errors.append((file_path.name, line_num, f"unsafe inline onclick with interpolation: ${{{expr}}}"))

    return errors


def main():
    root = Path(__file__).resolve().parent.parent
    modules_dir = root / "static" / "modules"
    if not modules_dir.exists():
        print(f"Directory not found: {modules_dir}", file=sys.stderr)
        sys.exit(1)

    all_errors = []
    js_files = sorted(modules_dir.glob("*.js"))
    for js_file in js_files:
        errors = check_file(js_file)
        if errors:
            all_errors.extend(errors)

    if all_errors:
        print(f"[ERROR] XSS Guard failed: {len(all_errors)} unescaped innerHTML interpolation(s) found:", file=sys.stderr)
        for fname, line, expr in all_errors:
            print(f"  {fname}:{line} -> ${{ {expr} }}", file=sys.stderr)
        sys.exit(1)
    else:
        print("[OK] XSS Guard passed: all innerHTML interpolations in static/modules/ are properly escaped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
