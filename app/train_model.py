"""
تدريب نموذج تصنيف أوفلاين من ملفات Excel (.xlsx) — بدون إنترنت بعد تثبيت الحزم.

الاستخدام من جذر المشروع:
  .venv\\Scripts\\python.exe -m app.train_model
  .venv\\Scripts\\python.exe -m app.train_model --data-dir ml_training/raw --model-out ml_training/models/eval_classifier.joblib

ضع ملفات التدريب في المجلد (نفس أسماء الأعمدة في كل الملفات مفضّل).
عمود التصنيف (الهدف y): افتراضياً آخر عمود، أو حدّده بـ --label-name \"اسم العمود\"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _cell_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "نعم" if val else "لا"
    if isinstance(val, float):
        if val == int(val) and abs(val) < 1e15:
            return str(int(val))
    return str(val).strip()


def _to_float(s: str) -> float | None:
    t = (s or "").strip().replace("\u00a0", " ").replace(",", ".").replace("٫", ".")
    if not t or t.lower() in ("na", "n/a", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def load_xlsx_matrix(
    path: Path, *, sheet_index: int = 0, max_rows: int = 5000, max_cols: int = 200
) -> tuple[list[str], list[list[str]], str | None]:
    """يعيد (رؤوس الأعمدة من الصف الأول، صفوف الجسم، رسالة خطأ)."""
    path = Path(path)
    if not path.is_file():
        return [], [], "ملف غير موجود"
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        return [], [], "امتداد غير مدعوم (استخدم .xlsx)"

    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError:
        return [], [], "ثبّت openpyxl: pip install openpyxl"

    err: str | None = None
    headers: list[str] = []
    body: list[list[str]] = []
    try:
        wb = load_workbook(filename=str(path), data_only=True, read_only=True)
        try:
            names = wb.sheetnames
            if not names:
                return [], [], "لا توجد أوراق"
            si = max(0, min(int(sheet_index), len(names) - 1))
            ws = wb[names[si]]
            mr = int(getattr(ws, "max_row", None) or 1)
            mc = int(getattr(ws, "max_column", None) or 1)
            max_r = min(mr, max_rows)
            max_c = min(mc, max_cols)
            raw: list[list[str]] = []
            for row in ws.iter_rows(
                min_row=1,
                max_row=max_r,
                min_col=1,
                max_col=max_c,
                values_only=True,
            ):
                raw.append([_cell_str(c) for c in row])
            if not raw:
                return [], [], "ورقة فارغة"
            ncol = max_c
            for r in raw:
                while len(r) < ncol:
                    r.append("")
            headers = list(raw[0])
            body = raw[1:] if len(raw) > 1 else []
        finally:
            wb.close()
    except Exception as exc:
        err = str(exc)
        return [], [], err
    return headers, body, err


def _column_kind(samples: list[str]) -> str:
    """numeric إذا غالبية القيم أرقاماً، وإلا categorical."""
    vals = [s for s in samples if (s or "").strip()]
    if not vals:
        return "categorical"
    n_ok = sum(1 for s in vals if _to_float(s) is not None)
    return "numeric" if (n_ok / len(vals)) >= 0.75 else "categorical"


def build_xy(
    paths: list[Path],
    *,
    sheet_index: int,
    label_name: str | None,
    label_col_index: int | None,
) -> tuple[np.ndarray, np.ndarray, list[str], list[int], list[str], str]:
    """
    يجمع كل الصفوف من الملفات.
    يعيد: X (object array للخلط بين رقمي ونصي لاحقاً), y, أسماء الميزات, فهارس الأعمدة المستخدمة, التصنيفات, خطأ.
    """
    all_rows: list[list[str]] = []
    headers_ref: list[str] | None = None

    for p in paths:
        h, body, err = load_xlsx_matrix(p, sheet_index=sheet_index)
        if err:
            return np.array([]), np.array([]), [], [], [], err
        if not h or not body:
            continue
        if headers_ref is None:
            headers_ref = h
        elif [x.strip() for x in h] != [x.strip() for x in headers_ref]:
            return (
                np.array([]),
                np.array([]),
                [],
                [],
                [],
                f"رؤوس الأعمدة تختلف عن الملف الأول: {p.name}",
            )
        all_rows.extend(body)

    if headers_ref is None or not all_rows:
        return np.array([]), np.array([]), [], [], [], "لا توجد صفوف بيانات في الملفات"

    ncols = len(headers_ref)
    # عمود التصنيف
    if label_name and label_name.strip():
        key = label_name.strip()
        try:
            y_idx = next(i for i, name in enumerate(headers_ref) if (name or "").strip() == key)
        except StopIteration:
            return np.array([]), np.array([]), [], [], [], f"عمود التصنيف غير موجود: {key}"
    elif label_col_index is not None:
        y_idx = max(0, min(int(label_col_index), ncols - 1))
    else:
        y_idx = ncols - 1

    feat_indices = [j for j in range(ncols) if j != y_idx]
    if not feat_indices:
        return np.array([]), np.array([]), [], [], [], "لا توجد أعمدة ميزات بعد حجب عمود التصنيف"

    # عيّن نوع كل عمود ميزة من عيّنة عشوائية
    col_samples: dict[int, list[str]] = {j: [] for j in feat_indices}
    for row in all_rows[: min(500, len(all_rows))]:
        for j in feat_indices:
            if j < len(row):
                col_samples[j].append(row[j])

    kinds = {j: _column_kind(col_samples[j]) for j in feat_indices}
    feature_names = [headers_ref[j].strip() or f"col_{j}" for j in feat_indices]

    X_list: list[list[Any]] = []
    y_list: list[str] = []
    for row in all_rows:
        while len(row) < ncols:
            row.append("")
        y_raw = (row[y_idx] or "").strip()
        if not y_raw:
            continue
        feats: list[Any] = []
        for j in feat_indices:
            cell = (row[j] if j < len(row) else "") or ""
            if kinds[j] == "numeric":
                v = _to_float(cell)
                feats.append(v if v is not None else np.nan)
            else:
                feats.append(cell.strip() if cell.strip() else "___empty___")
        X_list.append(feats)
        y_list.append(y_raw)

    if len(y_list) < 5:
        return (
            np.array([]),
            np.array([]),
            [],
            [],
            [],
            f"عدد الأمثلة بعد إزالة الصفوف بلا تصنيف قليل جداً: {len(y_list)} (الحد الأدنى المقترح 5)",
        )

    X = np.asarray(X_list, dtype=object)
    y = np.asarray(y_list)
    classes = sorted(set(y_list))
    return X, y, feature_names, feat_indices, classes, ""


def make_pipeline(numeric_cols: list[int], categorical_cols: list[int]) -> Pipeline:
    """numeric_cols / categorical_cols: فهارس داخل مصفوفة الميزات فقط (0..n_feat-1)."""
    transformers: list[tuple[str, Pipeline, list[int]]] = []
    if numeric_cols:
        transformers.append(
            (
                "num",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_cols,
            )
        )
    if categorical_cols:
        transformers.append(
            (
                "cat",
                Pipeline(
                    steps=[
                        (
                            "enc",
                            OrdinalEncoder(
                                handle_unknown="use_encoded_value",
                                unknown_value=-1,
                            ),
                        ),
                    ]
                ),
                categorical_cols,
            )
        )
    pre = ColumnTransformer(transformers=transformers, remainder="drop", sparse_threshold=0)
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    )
    return Pipeline(steps=[("prep", pre), ("clf", clf)])


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    default_data = root / "ml_training" / "raw"
    default_model = root / "ml_training" / "models" / "eval_classifier.joblib"
    default_meta = root / "ml_training" / "models" / "eval_classifier.meta.json"

    p = argparse.ArgumentParser(description="تدريب تصنيف أوفلاين من ملفات Excel")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=default_data,
        help="مجلد يحتوي ملفات .xlsx للتدريب",
    )
    p.add_argument(
        "--model-out",
        type=Path,
        default=default_model,
        help="مسار حفظ النموذج (.joblib)",
    )
    p.add_argument(
        "--meta-out",
        type=Path,
        default=default_meta,
        help="مسار ملف JSON لوصف النموذج والأعمدة",
    )
    p.add_argument("--sheet", type=int, default=0, help="فهرس الورقة (0 = الأولى)")
    p.add_argument(
        "--label-name",
        default="",
        help='اسم عمود التصنيف بالضبط كما في الصف الأول؛ إن تُرك فارغاً يُستخدم آخر عمود',
    )
    p.add_argument(
        "--label-col",
        type=int,
        default=-1,
        help="فهرس عمود التصنيف (0-based). القيمة -1 تعني آخر عمود إذا لم يُمرَّر --label-name",
    )
    p.add_argument("--test-size", type=float, default=0.2, help="نسبة مجموعة الاختبار")
    args = p.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.is_dir():
        print(f"خطأ: المجلد غير موجود: {data_dir}", file=sys.stderr)
        print("أنشئ المجلد وضع ملفات .xlsx بداخله.", file=sys.stderr)
        return 1

    paths = sorted(data_dir.glob("*.xlsx")) + sorted(data_dir.glob("*.xlsm"))
    if not paths:
        print(f"لا توجد ملفات .xlsx في: {data_dir}", file=sys.stderr)
        return 1

    label_name = (args.label_name or "").strip() or None
    label_idx = None if label_name else (int(args.label_col) if int(args.label_col) >= 0 else None)

    X, y, feature_names, feat_indices, classes, err = build_xy(
        paths,
        sheet_index=int(args.sheet),
        label_name=label_name,
        label_col_index=label_idx,
    )
    if err:
        print(err, file=sys.stderr)
        return 1

    # أنواع الأعمدة داخل X
    n_feat = X.shape[1]
    numeric_idx: list[int] = []
    categorical_idx: list[int] = []
    for j in range(n_feat):
        col_vals = X[:, j]
        n_float = sum(1 for v in col_vals if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)))
        n_str = sum(1 for v in col_vals if isinstance(v, str))
        if n_float >= n_str:
            numeric_idx.append(j)
        else:
            categorical_idx.append(j)

    # OrdinalEncoder يتوقع مصفوفة ثنائية الأبعاد n×1 لكل عمود
    class_counts = Counter(y.tolist())
    stratify = (
        y
        if len(class_counts) > 1 and all(c >= 2 for c in class_counts.values())
        else None
    )
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=float(args.test_size),
        random_state=42,
        stratify=stratify,
    )

    pipe = make_pipeline(numeric_idx, categorical_idx)
    pipe.fit(X_train, y_train)
    y_pred = pipe.predict(X_test)
    acc = accuracy_score(y_test, y_pred)

    model_out = Path(args.model_out).resolve()
    model_out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, model_out)

    meta = {
        "data_dir": str(data_dir),
        "files": [str(x.name) for x in paths],
        "sheet_index": int(args.sheet),
        "label_column": label_name or ("last" if label_idx is None else label_idx),
        "feature_names": feature_names,
        "feature_indices_in_sheet": feat_indices,
        "numeric_feature_indices": numeric_idx,
        "categorical_feature_indices": categorical_idx,
        "classes": classes,
        "n_samples": int(len(y)),
        "test_accuracy": round(float(acc), 4),
        "classification_report": classification_report(y_test, y_pred, zero_division=0),
    }
    meta_out = Path(args.meta_out).resolve()
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    meta_out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"تم التدريب على {len(y)} صفاً من {len(paths)} ملفاً.")
    print(f"دقة الاختبار (تقريبية): {acc:.4f}")
    print(f"النموذج: {model_out}")
    print(f"الوصف: {meta_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
