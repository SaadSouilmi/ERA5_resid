import ast as Ast
import contextlib as Contextlib
import importlib as Importlib
import io as Io
import re as Re

from py.paths import (
    AnalysisDataDirectory,
    FiguresDirectory,
    NotebookFiguresDirectory,
    ProjectRoot,
)

from .check import Expect, ExpectEqual, Run


def RepositoryPathsDoNotDependOnWorkingDirectory():
    Expect((ProjectRoot / "pyproject.toml").is_file(), "root does not point to the project")
    ExpectEqual(AnalysisDataDirectory, ProjectRoot / "data2")
    ExpectEqual(FiguresDirectory, ProjectRoot / "paper/figures/paper")
    ExpectEqual(NotebookFiguresDirectory, ProjectRoot / "paper/figures/notebooks")


def ScriptsImportWithoutRunningAnalysis():
    Output = Io.StringIO()
    with Contextlib.redirect_stdout(Output):
        for Name in (
            "audit_cleaning",
            "build_clean_dataset",
            "build_paper_figures",
            "export_notebooks",
        ):
            Module = Importlib.import_module(f"py.scripts.{Name}")
            Expect(callable(Module.Main), f"{Name} has no entry point")
    ExpectEqual(Output.getvalue(), "")


def ActiveNotebooksRemainImportable():
    for Name in (
        "cleaning_process",
        "resid_analysis",
        "poststrat_analysis",
        "data_comparison",
        "temp_resid",
    ):
        Module = Importlib.import_module(f"py.notebooks.{Name}")
        Expect(hasattr(Module, "app"), f"{Name} has no Marimo app")


def PythonBindingsUsePascalCase():
    Violations = []
    for File in sorted((ProjectRoot / "src/py").rglob("*.py")):
        Notebook = File.parent.name == "notebooks"
        for Node in Ast.walk(Ast.parse(File.read_text())):
            Names = []
            if isinstance(Node, Ast.Name) and isinstance(Node.ctx, Ast.Store):
                Names = [Node.id]
            elif isinstance(Node, Ast.arg):
                Names = [Node.arg]
            elif isinstance(Node, (Ast.FunctionDef, Ast.AsyncFunctionDef, Ast.ClassDef)):
                Names = [Node.name]
            elif isinstance(Node, (Ast.Import, Ast.ImportFrom)):
                Names = [Item.asname or Item.name.split(".")[0] for Item in Node.names]
            elif isinstance(Node, Ast.ExceptHandler) and Node.name:
                Names = [Node.name]
            for Name in Names:
                if Name == "_" or (Name.startswith("__") and Name.endswith("__")):
                    continue
                if Notebook and Name in {"marimo", "app", "__generated_with"}:
                    continue
                if not Re.fullmatch(r"_?[A-Z][A-Za-z0-9]*", Name):
                    Violations.append(f"{File.relative_to(ProjectRoot)}:{Node.lineno}: {Name}")
    ExpectEqual(Violations, [])


def Main():
    Run(RepositoryPathsDoNotDependOnWorkingDirectory)
    Run(ScriptsImportWithoutRunningAnalysis)
    Run(ActiveNotebooksRemainImportable)
    Run(PythonBindingsUsePascalCase)
