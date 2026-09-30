import contextlib
import importlib
import io

from py.paths import DATA2, ROOT

from .check import Expect, ExpectEqual, Run


def RepositoryPathsDoNotDependOnWorkingDirectory():
    Expect((ROOT / "pyproject.toml").is_file(), "root does not point to the project")
    ExpectEqual(DATA2, ROOT / "data2")


def ScriptsImportWithoutRunningAnalysis():
    Output = io.StringIO()
    with contextlib.redirect_stdout(Output):
        for Name in ("build_paper_figures", "build_poststrat_report"):
            Module = importlib.import_module(f"py.scripts.{Name}")
            Expect(callable(Module.main), f"{Name} has no entry point")
    ExpectEqual(Output.getvalue(), "")


def ActiveNotebooksRemainImportable():
    for Name in ("resid_analysis", "poststrat_analysis", "data_comparison", "temp_resid"):
        Module = importlib.import_module(f"py.notebooks.{Name}")
        Expect(hasattr(Module, "app"), f"{Name} has no Marimo app")


def Main():
    Run(RepositoryPathsDoNotDependOnWorkingDirectory)
    Run(ScriptsImportWithoutRunningAnalysis)
    Run(ActiveNotebooksRemainImportable)
