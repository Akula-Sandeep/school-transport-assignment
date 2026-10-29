"""Command line entry point: python -m transport <command> [options]."""
import argparse
import os
import sys

from . import config as C


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m transport",
                                description="School transport assignment workflow: synthetic data, "
                                            "rules engine, validation and anomaly detection.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate, export, validate and report one dataset")
    g.add_argument("--scale", choices=sorted(C.SCALES), default="starter")
    g.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    g.add_argument("--out", default=None, help="output folder (default output/<scale>)")
    g.add_argument("--formats", default=None,
                   help="comma list from csv,json,sql,json.gz,sql.gz (csv is always written); "
                        "default csv,json,sql (full: csv,json.gz,sql.gz)")

    v = sub.add_parser("validate", help="re-run validation + detection on an existing output folder")
    v.add_argument("--data", required=True)

    r = sub.add_parser("repro", help="regenerate twice with the same seed and compare checksums")
    r.add_argument("--scale", choices=sorted(C.SCALES), default="starter")
    r.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    r.add_argument("--out", default=None, help="folder whose reports/ receives reproducibility.json")

    sub.add_parser("docs", help="regenerate docs/data_dictionary.md and docs/schema.sql")

    a = sub.add_parser("all", help="starter + full datasets, reproducibility check for both")
    a.add_argument("--seed", type=int, default=C.DEFAULT_SEED)

    args = p.parse_args(argv)
    from . import pipeline
    if args.cmd == "generate":
        formats = tuple(f.strip() for f in args.formats.split(",") if f.strip()) if args.formats else None
        _, summary = pipeline.generate(args.scale, args.seed, args.out, formats)
        return 0 if summary["validation"]["passed"] else 1
    if args.cmd == "validate":
        summary = pipeline.run_checks(args.data)
        return 0 if summary["validation"]["passed"] else 1
    if args.cmd == "repro":
        out = args.out or os.path.join("output", args.scale)
        rep = pipeline.reproducibility(args.scale, args.seed, out)
        return 0 if rep["identical_runs"] and rep["files_changed_with_control_seed"] > 0 else 1
    if args.cmd == "docs":
        from .schema import data_dictionary_md, ddl
        os.makedirs("docs", exist_ok=True)
        with open(os.path.join("docs", "data_dictionary.md"), "w", encoding="utf-8") as fh:
            fh.write(data_dictionary_md())
        with open(os.path.join("docs", "schema.sql"), "w", encoding="utf-8") as fh:
            fh.write(ddl())
        print("wrote docs/data_dictionary.md and docs/schema.sql")
        return 0
    if args.cmd == "all":
        ok = True
        for scale in ("starter", "full"):
            out = os.path.join("output", scale)
            _, summary = pipeline.generate(scale, args.seed, out)
            rep = pipeline.reproducibility(scale, args.seed, out)
            ok = ok and summary["validation"]["passed"] and rep["identical_runs"]
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
