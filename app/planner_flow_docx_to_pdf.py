"""تحويل ملف مجرى الأحداث (.docx) إلى PDF دون تعديل جدول النظام."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def convert_docx_bytes_to_pdf(data: bytes) -> bytes | None:
    """يحاول Microsoft Word ثم LibreOffice. يعيد بايتات PDF أو None."""
    if not data or data[:2] != b"PK":
        return None
    with tempfile.TemporaryDirectory(prefix="pf-docx-pdf-") as tmp:
        root = Path(tmp)
        docx_path = root / "source.docx"
        pdf_path = root / "source.pdf"
        try:
            docx_path.write_bytes(data)
        except OSError:
            return None
        if _convert_via_word(docx_path, pdf_path) or _convert_via_libreoffice(
            docx_path, root
        ):
            return _read_pdf(pdf_path)
    return None


def _read_pdf(path: Path) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw[:4] == b"%PDF":
        return raw
    return None


def _convert_via_word(docx_path: Path, pdf_path: Path) -> bool:
    if sys.platform != "win32":
        return False
    ps1 = docx_path.parent / "to_pdf.ps1"
    ps1.write_text(
        "\n".join(
            [
                "param([string]$Src, [string]$Dest)",
                "$ErrorActionPreference = 'Stop'",
                "$word = New-Object -ComObject Word.Application",
                "$word.Visible = $false",
                "$word.DisplayAlerts = 0",
                "try {",
                "  $doc = $word.Documents.Open($Src, $false, $true)",
                "  $wdExportFormatPDF = 17",
                "  $doc.ExportAsFixedFormat($Dest, $wdExportFormatPDF, $false)",
                "  $doc.Close($false)",
                "} finally {",
                "  $word.Quit() | Out-Null",
                "  [System.GC]::Collect()",
                "  [System.GC]::WaitForPendingFinalizers()",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1),
                str(docx_path.resolve()),
                str(pdf_path.resolve()),
            ],
            capture_output=True,
            timeout=90,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and pdf_path.is_file()


def _soffice_candidates() -> list[Path]:
    found: list[Path] = []
    for name in ("soffice", "soffice.exe"):
        from shutil import which

        w = which(name)
        if w:
            found.append(Path(w))
    found.extend(
        [
            Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
            Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
        ]
    )
    out: list[Path] = []
    seen: set[str] = set()
    for p in found:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            out.append(p)
    return out


def _convert_via_libreoffice(docx_path: Path, out_dir: Path) -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for exe in _soffice_candidates():
        try:
            proc = subprocess.run(
                [
                    str(exe),
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    "--nologo",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out_dir),
                    str(docx_path.resolve()),
                ],
                capture_output=True,
                timeout=90,
                creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and (out_dir / "source.pdf").is_file():
            return True
    return False
