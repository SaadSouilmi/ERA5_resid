"""Shared typography for standalone notebook exports and their audit."""

import base64 as Base64

from py.paths import ProjectRoot


def ReportCss():
    Fonts = []
    for Face, Weight, Style in [
        ("regular", 400, "normal"),
        ("italic", 400, "italic"),
        ("bold", 700, "normal"),
        ("bolditalic", 700, "italic"),
    ]:
        File = ProjectRoot / "assets/fonts" / f"lmroman10-{Face}.otf"
        Data = Base64.b64encode(File.read_bytes()).decode()
        Fonts.append(
            '@font-face {font-family:"Latin Modern Roman";'
            f"font-weight:{Weight};font-style:{Style};"
            f'src:url(data:font/otf;base64,{Data}) format("opentype");}}'
        )
    return (
        "\n".join(Fonts)
        + """
html {font-size:18px;}
body {color:#000;background:#fefefe;margin:auto;padding:1em;max-width:72em;
font-family:"Latin Modern Roman","Computer Modern Roman","CMU Serif",serif;}
h1,h2,h3 {font-family:inherit;color:#000;}
a {color:#9e358f;text-decoration:none;} a:visited {color:#828282;}
code {font-family:Menlo,Monaco,"Courier New",monospace;color:darkgreen;font-weight:bold;}
pre {white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;border:2px solid #f0ad4e;
border-radius:6px;font-size:smaller;padding:14px;}
pre code {color:#222;font-weight:normal;}
table {border-spacing:0;border:1px solid #ccc;width:100%;font-size:smaller;text-align:left;}
th,td {padding:8px;overflow-wrap:anywhere;} th {background:#ddd;}
tr:nth-child(odd) {background:#eee;} img,svg {max-width:100%;}
:root {--text-font:"Latin Modern Roman",serif;--heading-font:"Latin Modern Roman",serif;}
"""
    )


def StyleHtml(Text):
    return Text.replace("</head>", "<style>" + ReportCss() + "</style></head>", 1)
