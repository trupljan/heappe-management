"""
Generate QScheduler_COVERAGE.md.

Runs every `QScheduler*` test class under coverage.py, measures the code of each feature listed in
heappe_ui/reports/qscheduler_coverage.toml and renders heappe_ui/templates/reports/qscheduler_coverage.md.

    python manage.py qscheduler_coverage            # write the report (left untouched when nothing changed)
    python manage.py qscheduler_coverage --check    # CI: fail when the report is out of date

Needs coverage.py: pip install -r requirements-dev.txt
"""
import ast
import datetime
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string

DATA_FILE = Path(__file__).resolve().parents[2] / "reports" / "qscheduler_coverage.toml"
TEMPLATE = "reports/qscheduler_coverage.md"
STATE_RE = re.compile(r"<!-- qscheduler-coverage-state (\{.*?\}) -->")
DATE_RE = re.compile(r"^\| Date \| [^|]* \|$", re.M)
STATUSES = ("covered", "partial", "none")
ICONS = {"covered": "✅", "partial": "🟡", "none": "❌"}


def pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 100.0


# ---------------------------------------------------------------------------------------------------------------------
# Source code: line ranges of functions, classes and methods
# ---------------------------------------------------------------------------------------------------------------------

def _body_range(node):
    # From the first body statement: `def` and decorator lines run at import time and would count as covered.
    return node.body[0].lineno, node.end_lineno


def code_index(path):
    """{qualified name: [(first line, last line), ...]} of top-level functions, classes and their methods."""
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    index = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            index[node.name] = [_body_range(node)]
        elif isinstance(node, ast.ClassDef):
            methods = [m for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for m in methods:
                index[f"{node.name}.{m.name}"] = [_body_range(m)]
            index[node.name] = [_body_range(m) for m in methods] or [_body_range(node)]
    return index


class Measured:
    """Executed / missing lines and branches of one file (from the coverage.py JSON report)."""

    def __init__(self, data):
        self.executed = set(data["executed_lines"])
        self.missing = set(data["missing_lines"])
        self.br_executed = [tuple(b) for b in data.get("executed_branches", [])]
        self.br_missing = [tuple(b) for b in data.get("missing_branches", [])]

    def count(self, ranges):
        inside = lambda line: any(a <= line <= b for a, b in ranges)
        covered = {l for l in self.executed if inside(l)}
        missed = {l for l in self.missing if inside(l)}
        br_cov = sum(1 for b in self.br_executed if inside(b[0]))
        br_miss = sum(1 for b in self.br_missing if inside(b[0]))
        return {'lines': len(covered) + len(missed), 'covered': len(covered),
                'branches': br_cov + br_miss, 'covered_branches': br_cov}


def add_counts(a, b):
    return {k: a.get(k, 0) + b[k] for k in b}


# ---------------------------------------------------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Run the QScheduler tests under coverage.py and generate QScheduler_COVERAGE.md."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true",
                            help="Do not write; exit with an error when the report is out of date.")
        parser.add_argument("--output", help="Report file (default: 'output' in the data file).")

    def handle(self, *args, **opts):
        base = Path(settings.BASE_DIR)
        cfg = tomllib.loads(DATA_FILE.read_text())
        output = base / (opts["output"] or cfg["output"])
        files = {key: base / rel for key, rel in cfg["files"].items()}

        indexes = {key: code_index(path) for key, path in files.items()}
        self.validate_refs(cfg, indexes)          # fail fast, before the tests run
        labels = self.discover_tests(base, cfg["tests"])
        test_run, measured = self.run_coverage(base, labels, files)

        sections, mapped = self.measure_features(cfg, indexes, measured)
        totals, file_rows = self.totals(cfg, files, measured)
        context = {
            'cfg': cfg,
            'date': datetime.date.today().isoformat(),
            'tests': test_run,
            'labels': labels,
            'files': file_rows,
            'totals': totals,
            'sections': sections,
            'gaps': self.gaps(cfg, sections),
            'least_covered': self.least_covered(cfg, indexes, measured),
            'unmapped': self.unmapped(cfg, indexes, mapped),
            'fingerprint': self.fingerprint(files),
            'icons': ICONS,
            'thresholds': cfg["thresholds"],
            'data_file': DATA_FILE.relative_to(base).as_posix(),
            'template': f"heappe_ui/templates/{TEMPLATE}",
        }

        old = output.read_text() if output.exists() else ""
        old_state = self.read_state(old)
        current = {k: totals[k] for k in ("line", "branch", "combined")}
        # "Previous" = the last report with different numbers, so regenerating without changes keeps the comparison.
        previous = old_state.get("previous") if old_state.get("totals") == current else old_state.get("totals")
        context['previous'] = previous
        context['state'] = json.dumps({'totals': current, 'previous': previous}, sort_keys=True)

        new = render_to_string(TEMPLATE, context).strip() + "\n"
        same = DATE_RE.sub("", new) == DATE_RE.sub("", old)

        if opts["check"]:
            if not same:
                diff = list(difflib.unified_diff(DATE_RE.sub("", old).splitlines(), DATE_RE.sub("", new).splitlines(),
                                                 "committed", "generated", lineterm="", n=0))
                self.stdout.write("\n".join(diff[:60]) + ("\n..." if len(diff) > 60 else ""))
                raise CommandError(f"{output.name} is out of date. Run `python manage.py qscheduler_coverage` "
                                   f"and commit the result.")
            self.stdout.write(self.style.SUCCESS(f"{output.name} is up to date "
                                                 f"(lines {totals['line']}%, branches {totals['branch']}%)."))
            return
        if same:
            self.stdout.write(self.style.SUCCESS(f"{output.name} is already up to date; not rewritten."))
            return
        output.write_text(new)
        self.stdout.write(self.style.SUCCESS(f"Wrote {output.name}: lines {totals['line']}%, "
                                             f"branches {totals['branch']}%, combined {totals['combined']}%."))
        if context['unmapped']:
            self.stdout.write(self.style.WARNING(
                f"{len(context['unmapped'])} function(s) are not mapped to a feature in {DATA_FILE.name}: "
                + ", ".join(u['ref'] for u in context['unmapped'])))

    # ---- tests and coverage ----

    def discover_tests(self, base, tests_cfg):
        pattern = re.compile(tests_cfg["class_pattern"], re.M)
        names = pattern.findall((base / tests_cfg["path"]).read_text())
        if not names:
            raise CommandError(f"No test classes match {tests_cfg['class_pattern']!r} in {tests_cfg['path']}.")
        return [f"{tests_cfg['module']}.{n}" for n in names]

    def run_coverage(self, base, labels, files):
        try:
            import coverage
        except ImportError:
            raise CommandError("coverage.py is not installed: pip install -r requirements-dev.txt")
        with tempfile.TemporaryDirectory() as tmp:
            data_file, json_file = Path(tmp) / ".coverage", Path(tmp) / "coverage.json"
            include = ",".join(str(p) for p in files.values())
            cmd = [sys.executable, "-m", "coverage", "run", "--branch", f"--data-file={data_file}",
                   f"--include={include}", "manage.py", "test", "--noinput", *labels]
            self.stdout.write(f"Running {len(labels)} QScheduler test classes under coverage...")
            proc = subprocess.run(cmd, cwd=base, capture_output=True, text=True)
            out = proc.stdout + proc.stderr
            ran = re.search(r"^Ran (\d+) tests?", out, re.M)
            if proc.returncode != 0 or not ran:
                tail = "\n".join(l for l in out.splitlines() if "WARNING Retrying" not in l)[-3000:]
                raise CommandError(f"The QScheduler tests failed; the report was not generated.\n{tail}")
            cov = coverage.Coverage(data_file=str(data_file))
            cov.load()
            cov.json_report(outfile=str(json_file), include=[str(p) for p in files.values()])
            report = json.loads(json_file.read_text())
        measured = {}
        by_path = {str((base / name).resolve()): data for name, data in report["files"].items()}
        for key, path in files.items():
            data = by_path.get(str(path.resolve()))
            if data is None:
                raise CommandError(f"{path} was not measured (never imported by the tests?).")
            measured[key] = (Measured(data), data["summary"])
        return {'count': int(ran.group(1)), 'ok': True, 'coverage_version': coverage.__version__,
                'python': ".".join(map(str, sys.version_info[:2]))}, measured

    # ---- features ----

    def measure_features(self, cfg, indexes, measured):
        th = cfg["thresholds"]
        mapped = set()
        sections = []
        for section in cfg["sections"]:
            rows = []
            for f in section["features"]:
                row = {'name': f["name"], 'verified': f.get("verified", "–"), 'not_tested': f.get("not_tested", "–"),
                       'code': f.get("code", []), 'measured': None, 'reason': f.get("status_reason", "")}
                if f.get("code"):
                    counts = {}
                    for ref in f["code"]:
                        key, name = self.parse_ref(ref, indexes)
                        mapped.add((key, name))
                        counts = add_counts(counts, measured[key][0].count(indexes[key][name]))
                    if not counts["lines"]:
                        raise CommandError(f"Feature '{f['name']}': its code has no executable lines.")
                    line = pct(counts["covered"], counts["lines"])
                    row['measured'] = dict(counts, line=line, branch=pct(counts["covered_branches"], counts["branches"]))
                    row['status'] = ("covered" if line >= th["covered"] else
                                     "partial" if line >= th["partial"] else "none")
                else:
                    if f.get("status") not in STATUSES:
                        raise CommandError(f"Feature '{f['name']}' needs either 'code' or a 'status' "
                                           f"({', '.join(STATUSES)}).")
                    row['status'] = f["status"]
                row['icon'] = ICONS[row['status']]
                rows.append(row)
            sections.append({'title': section["title"], 'note': section.get("note", ""), 'features': rows})
        return sections, mapped

    def validate_refs(self, cfg, indexes):
        for section in cfg["sections"]:
            for f in section["features"]:
                for ref in f.get("code", []):
                    self.parse_ref(ref, indexes)
        for ref in cfg.get("unmapped", {}).get("ignore", []):
            self.parse_ref(ref, indexes)

    def parse_ref(self, ref, indexes):
        key, sep, name = ref.partition(":")
        if not sep or key not in indexes:
            raise CommandError(f"Invalid code reference '{ref}': use '<file key>:<name>' with a key from [files].")
        if name not in indexes[key]:
            raise CommandError(f"'{ref}' does not exist (renamed or removed?). Update {DATA_FILE.name}.")
        return key, name

    def gaps(self, cfg, sections):
        rows = [dict(f, section=s['title']) for s in sections for f in s['features'] if f['status'] != "covered"]
        order = {"none": 0, "partial": 1}
        rows.sort(key=lambda f: (order[f['status']], f['measured']['line'] if f['measured'] else 0,
                                 -(f['measured']['lines'] if f['measured'] else 0)))
        return rows[:cfg["thresholds"]["gap_rows"]]

    def least_covered(self, cfg, indexes, measured):
        th = cfg["thresholds"]
        rows = []
        for key, index in indexes.items():
            for name, ranges in index.items():
                if "." not in name and any("." in n and n.startswith(name + ".") for n in index):
                    continue      # classes: list their methods instead
                c = measured[key][0].count(ranges)
                if c["lines"] >= th["least_covered_min_statements"] and c["covered"] < c["lines"]:
                    rows.append({'ref': f"{key}:{name}", 'file': Path(cfg["files"][key]).name, 'name': name,
                                 'lines': c["lines"], 'missed': c["lines"] - c["covered"],
                                 'line': pct(c["covered"], c["lines"])})
        rows.sort(key=lambda r: (-r['missed'], r['ref']))
        return rows[:th["least_covered_rows"]]

    def unmapped(self, cfg, indexes, mapped):
        """Functions and methods not measured by any feature (a class whose methods are all unmapped is listed once)."""
        ignore = set(cfg.get("unmapped", {}).get("ignore", []))
        rows = []
        for key, index in indexes.items():
            classes = {n for n in index if "." not in n and any(m.startswith(n + ".") for m in index)}
            missing = []
            for name in index:
                cls = name.split(".")[0]
                if name in classes or f"{key}:{name}" in ignore or (key, name) in mapped or (key, cls) in mapped:
                    continue
                missing.append(name)
            for cls in classes:
                methods = [n for n in index if n.startswith(cls + ".")]
                if methods and all(m in missing for m in methods):
                    missing = [n for n in missing if n not in methods] + [cls]
            rows += [{'ref': f"{key}:{n}"} for n in sorted(missing)]
        return rows

    # ---- totals and state ----

    def totals(self, cfg, files, measured):
        rows, sums = [], {'lines': 0, 'covered': 0, 'branches': 0, 'covered_branches': 0, 'partial': 0}
        for key in files:
            s = measured[key][1]
            row = {'name': Path(cfg["files"][key]).name, 'description': cfg.get("file_descriptions", {}).get(key, ""),
                   'lines': s["num_statements"], 'covered': s["covered_lines"], 'missed': s["missing_lines"],
                   'branches': s["num_branches"], 'covered_branches': s["covered_branches"],
                   'partial': s["num_partial_branches"]}
            row['line'] = pct(row['covered'], row['lines'])
            row['branch'] = pct(row['covered_branches'], row['branches'])
            row['combined'] = pct(row['covered'] + row['covered_branches'], row['lines'] + row['branches'])
            rows.append(row)
            for k in sums:
                sums[k] += row[k]
        totals = dict(sums, missed=sums['lines'] - sums['covered'], line=pct(sums['covered'], sums['lines']),
                      branch=pct(sums['covered_branches'], sums['branches']),
                      combined=pct(sums['covered'] + sums['covered_branches'], sums['lines'] + sums['branches']))
        return totals, rows

    def fingerprint(self, files):
        h = hashlib.sha256()
        for path in [*files.values(), DATA_FILE]:
            h.update(path.read_bytes())
        return h.hexdigest()[:12]

    def read_state(self, text):
        m = STATE_RE.search(text)
        if not m:
            return {}
        try:
            return json.loads(m.group(1))
        except ValueError:
            return {}
