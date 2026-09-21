"""تحويل مصنف Excel إلى PDF عبر Microsoft Excel ثم LibreOffice."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def convert_xlsx_bytes_to_pdf(data: bytes) -> bytes | None:
    """يحاول Microsoft Excel ثم LibreOffice. يعيد بايتات PDF أو None."""
    if not data or data[:2] != b"PK":
        return None
    with tempfile.TemporaryDirectory(prefix="eval-xlsx-pdf-") as tmp:
        root = Path(tmp)
        xlsx_path = root / "source.xlsx"
        pdf_path = root / "source.pdf"
        try:
            xlsx_path.write_bytes(data)
        except OSError:
            return None
        if _convert_via_excel(xlsx_path, pdf_path) or _convert_via_libreoffice(
            xlsx_path, root
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


def _convert_via_excel(xlsx_path: Path, pdf_path: Path) -> bool:
    if sys.platform != "win32":
        return False
    ps1 = xlsx_path.parent / "xlsx_to_pdf.ps1"
    ps1.write_text(
        "\n".join(
            [
                "param([string]$Src, [string]$Dest)",
                "$ErrorActionPreference = 'Stop'",
                "function Invoke-ExcelRetry([scriptblock]$Action) {",
                "  for ($i = 0; $i -lt 25; $i++) {",
                "    try { return & $Action }",
                "    catch {",
                "      $hr = [int]$_.Exception.HResult",
                "      if ($hr -eq [int]0x800AC472 -or $hr -eq [int]0x80010001) {",
                "        Start-Sleep -Milliseconds 200",
                "        continue",
                "      }",
                "      throw",
                "    }",
                "  }",
                "  & $Action",
                "}",
                "$excel = $null",
                "$wb = $null",
                "try {",
                "  $excel = New-Object -ComObject Excel.Application",
                "  $excel.Visible = $false",
                "  $excel.DisplayAlerts = $false",
                "  Start-Sleep -Milliseconds 300",
                "  $wb = Invoke-ExcelRetry { $excel.Workbooks.Open($Src, 0, $true) }",
                "  $ws = Invoke-ExcelRetry { $wb.Worksheets.Item(1) }",
                "  try {",
                "    $ws.PageSetup.Zoom = $false",
                "    $ws.PageSetup.FitToPagesWide = 1",
                "    $ws.PageSetup.FitToPagesTall = 1",
                "    $ws.PageSetup.PaperSize = 9",
                "    $ws.PageSetup.Orientation = 1",
                "  } catch {}",
                "  $xlTypePDF = 0",
                "  Invoke-ExcelRetry { $wb.ExportAsFixedFormat($xlTypePDF, $Dest) }",
                "} finally {",
                "  if ($wb -ne $null) {",
                "    try { Invoke-ExcelRetry { $wb.Close($false) } } catch {}",
                "  }",
                "  if ($excel -ne $null) {",
                "    try { $excel.Quit() } catch {}",
                "  }",
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
                str(xlsx_path.resolve()),
                str(pdf_path.resolve()),
            ],
            capture_output=True,
            timeout=120,
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


def _convert_via_libreoffice(xlsx_path: Path, out_dir: Path) -> bool:
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
                    str(xlsx_path.resolve()),
                ],
                capture_output=True,
                timeout=120,
                creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and (out_dir / "source.pdf").is_file():
            return True
    return False
