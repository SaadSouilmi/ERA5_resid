import argparse
import importlib
import sys

from . import check as Check

GlobalSuites = ("pdp", "publication", "layout")


def Main():
    Parser = argparse.ArgumentParser(description="Run ERA5 analysis tests")
    Parser.add_argument(
        "Name", metavar="name", nargs="?", default="all", choices=("all", *GlobalSuites)
    )
    Name = Parser.parse_args().Name
    Suites = GlobalSuites if Name == "all" else (Name,)
    SuiteErrors = 0
    for Name in Suites:
        print(f"\n{Name}:", flush=True)
        try:
            Suite = importlib.import_module(f"py.tests.test_{Name}")
            Suite.Main()
        except Exception as Error:
            SuiteErrors += 1
            Message = f"FAIL {Name}: {type(Error).__name__}: {Error}"
            print(Check.Color(Message, 31, sys.stderr), file=sys.stderr, flush=True)
    return Check.Summary(SuiteErrors=SuiteErrors)


if __name__ == "__main__":
    sys.exit(Main())
