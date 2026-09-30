import math
import os
import sys
import traceback

GlobalFailCount = 0
GlobalPassCount = 0
GlobalCheckFailCount = 0
GlobalCase = ""


def Color(Text, Code, Stream):
    if Stream.isatty() and "NO_COLOR" not in os.environ:
        return f"\033[{Code}m{Text}\033[0m"
    return Text


def Fail(Message):
    global GlobalCheckFailCount
    GlobalCheckFailCount += 1
    print(Color(f"    {GlobalCase}: {Message}", 31, sys.stderr), file=sys.stderr, flush=True)


def Expect(Condition, Message):
    if not Condition:
        Fail(Message)


def ExpectEqual(Actual, Expected):
    if Actual != Expected:
        Fail(f"expected {Expected!r}, got {Actual!r}")


def ExpectClose(Actual, Expected, *, RelTol=1e-7, AbsTol=0.0):
    if not math.isclose(Actual, Expected, rel_tol=RelTol, abs_tol=AbsTol):
        Fail(f"expected {Expected!r}, got {Actual!r}; RelTol={RelTol:g}, AbsTol={AbsTol:g}")


def ExpectRaises(ErrorType, Fn, *Args, **Kwargs):
    try:
        Fn(*Args, **Kwargs)
    except ErrorType:
        return
    except Exception as Error:
        Fail(f"{Fn.__name__}: expected {ErrorType.__name__}, got {type(Error).__name__}: {Error}")
        return
    Fail(f"{Fn.__name__}: expected {ErrorType.__name__}")


def Run(Fn):
    global GlobalCase, GlobalPassCount, GlobalFailCount
    GlobalCase = Fn.__name__
    Before = GlobalCheckFailCount
    try:
        Fn()
    except Exception as Error:
        Frame = traceback.extract_tb(Error.__traceback__)[-1]
        Fail(f"{type(Error).__name__}: {Error} ({Frame.filename}:{Frame.lineno})")
    if GlobalCheckFailCount == Before:
        GlobalPassCount += 1
        print(Color(f"PASS {GlobalCase}", 32, sys.stdout), flush=True)
    else:
        GlobalFailCount += 1
        print(Color(f"FAIL {GlobalCase}", 31, sys.stdout), flush=True)


def Summary(*, SuiteErrors=0):
    Passed = Color(f"{GlobalPassCount} passed", 32, sys.stdout)
    Failed = Color(f"{GlobalFailCount} failed", 31 if GlobalFailCount else 32, sys.stdout)
    print(f"\n{GlobalPassCount + GlobalFailCount} tests: {Passed}, {Failed}", flush=True)
    if SuiteErrors:
        print(Color(f"{SuiteErrors} suite errors", 31, sys.stdout), flush=True)
    return min(GlobalFailCount + SuiteErrors, 255)
