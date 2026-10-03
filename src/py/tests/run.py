import argparse as Argparse
import importlib as Importlib
import sys as Sys

from . import check as Check

GlobalSuites = ("pdp", "publication", "layout", "cleaning")


def Main():
    Parser = Argparse.ArgumentParser(description="Run ERA5 analysis tests")
    Parser.add_argument(
        "Name", metavar="name", nargs="?", default="all", choices=("all", *GlobalSuites)
    )
    Name = Parser.parse_args().Name
    Suites = GlobalSuites if Name == "all" else (Name,)
    SuiteErrors = 0
    for Name in Suites:
        print(f"\n{Name}:", flush=True)
        try:
            Suite = Importlib.import_module(f"py.tests.test_{Name}")
            Suite.Main()
        except Exception as Error:
            SuiteErrors += 1
            Message = f"FAIL {Name}: {type(Error).__name__}: {Error}"
            print(Check.Color(Message, 31, Sys.stderr), file=Sys.stderr, flush=True)
    return Check.Summary(SuiteErrors=SuiteErrors)


if __name__ == "__main__":
    Sys.exit(Main())
