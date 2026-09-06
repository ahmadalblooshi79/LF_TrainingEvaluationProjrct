"""كشف المسميات والدلالات الرئيسية للوحدات — تحميل وحل المسميات البديلة."""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.domain import UnitDesignation, UnitDesignationAlias

_DATA_XLSX = Path(__file__).resolve().parent / "data" / "unit_designations.xlsx"
_REPO_XLSX = Path(__file__).resolve().parents[1] / "كشف المسميات والدلالات الرئيسية للوحدات.xlsx"

# كاش في الذاكرة: norm(alias|canonical) → unit_id
_ALIAS_NORM_TO_UNIT: dict[str, str] = {}
_UNIT_BY_ID: dict[str, UnitDesignation] = {}
_LOADED = False


def normalize_designation_text(s: str) -> str:
    """توحيد نص للمقارنة (همزات، مسافات، شرطة)."""
    t = (s or "").strip()
    t = (
        t.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ة", "ه")
        .replace("ى", "ي")
    )
    t = t.replace("الـ", "ال").replace("الـ ", "ال")
    t = re.sub(r"(\d+)من", r"\1 من", t)
    t = re.sub(r"(كتيبة)\s+(\d+)\b", r"\1/\2", t)
    t = re.sub(r"(ك)\s+(\d+)\b", r"\1/\2", t)
    # توحيد «م/د» و«م د» و«مـ د» الشائعة في أسماء المجلدات
    t = re.sub(r"م\s*/\s*د", "م/د", t)
    t = re.sub(r"م\s*ـ\s*د", "م/د", t)
    t = re.sub(r"م\s+د\b", "م/د", t)
    t = re.sub(r"\s*/\s*", "/", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _xlsx_candidates() -> list[Path]:
    """يفضّل ملف الجذر المحدَّث ثم النسخة في app/data."""
    out: list[Path] = []
    for p in (_REPO_XLSX, _DATA_XLSX):
        if p.is_file() and p not in out:
            out.append(p)
    return out


def _xlsx_master_count(path: Path) -> int:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, data_only=True, read_only=True)
        try:
            ws = wb["Units_Master"] if "Units_Master" in wb.sheetnames else wb[wb.sheetnames[0]]
            n = 0
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and row[0] and row[1]:
                    n += 1
            return n
        finally:
            wb.close()
    except Exception:
        return 0


def seed_unit_designations_from_xlsx(db: Session, *, force: bool = False) -> dict[str, int]:
    """تحميل/تحديث الدلالات والمسميات من ملف Excel إلى قاعدة البيانات."""
    paths = _xlsx_candidates()
    if not paths:
        reload_unit_designation_cache(db)
        return {"masters": 0, "aliases": 0, "skipped": 1}

    existing = db.query(UnitDesignation).count()
    path = paths[0]
    xlsx_count = _xlsx_master_count(path)
    # أعد المزامنة تلقائياً عند إضافة وحدات جديدة في الكشف
    if existing and not force and xlsx_count > 0 and xlsx_count != existing:
        force = True
    if existing and not force:
        reload_unit_designation_cache(db)
        return {"masters": existing, "aliases": db.query(UnitDesignationAlias).count(), "cached": 1}

    from openpyxl import load_workbook

    path = paths[0]
    wb = load_workbook(path, data_only=True)
    try:
        ws_m = wb["Units_Master"] if "Units_Master" in wb.sheetnames else wb[wb.sheetnames[0]]
        ws_a = wb["Units_Alias"] if "Units_Alias" in wb.sheetnames else None

        masters = 0
        for i, row in enumerate(ws_m.iter_rows(min_row=2, values_only=True), start=1):
            if not row or not row[0]:
                continue
            uid = str(row[0]).strip()
            label = str(row[1] or "").strip()
            utype = str(row[2] or "").strip()
            desc = str(row[3] or "").strip() if len(row) > 3 else ""
            status = str(row[4] or "").strip() if len(row) > 4 else "فعال"
            if not uid or not label:
                continue
            rec = db.get(UnitDesignation, uid)
            if rec is None:
                rec = UnitDesignation(unit_id=uid)
                db.add(rec)
            rec.canonical_label = label
            rec.unit_type = utype
            rec.description = desc
            rec.is_active = status in ("فعال", "active", "1", "true", "True", "")
            rec.sort_order = i
            masters += 1

        aliases = 0
        seen_norms: set[str] = set()
        if ws_a is not None:
            for row in ws_a.iter_rows(min_row=2, values_only=True):
                if not row or not row[0]:
                    continue
                aid = str(row[0]).strip()
                uid = str(row[1] or "").strip()
                alias = str(row[2] or "").strip()
                notes = str(row[3] or "").strip() if len(row) > 3 else ""
                if not aid or not uid or not alias:
                    continue
                if db.get(UnitDesignation, uid) is None:
                    continue
                norm = normalize_designation_text(alias)
                if not norm:
                    continue
                if norm in seen_norms:
                    continue
                existing_alias = (
                    db.query(UnitDesignationAlias)
                    .filter(UnitDesignationAlias.alias_label_norm == norm)
                    .first()
                )
                if existing_alias is not None:
                    existing_alias.unit_id = uid
                    existing_alias.alias_label = alias
                    if notes:
                        existing_alias.notes = notes
                    seen_norms.add(norm)
                    aliases += 1
                    continue
                rec = db.get(UnitDesignationAlias, aid)
                if rec is None:
                    rec = UnitDesignationAlias(alias_id=aid)
                    db.add(rec)
                rec.unit_id = uid
                rec.alias_label = alias
                rec.alias_label_norm = norm
                rec.notes = notes
                seen_norms.add(norm)
                aliases += 1

        # أضف الدلالة الرئيسية نفسها كمسمى للبحث المباشر
        for m in db.query(UnitDesignation).all():
            label = (m.canonical_label or "").strip()
            if not label:
                continue
            norm = normalize_designation_text(label)
            if not norm or norm in seen_norms:
                continue
            exists = (
                db.query(UnitDesignationAlias)
                .filter(UnitDesignationAlias.alias_label_norm == norm)
                .first()
            )
            if exists is None:
                syn_id = f"S_{m.unit_id}"
                if db.get(UnitDesignationAlias, syn_id) is None:
                    db.add(
                        UnitDesignationAlias(
                            alias_id=syn_id,
                            unit_id=m.unit_id,
                            alias_label=label,
                            alias_label_norm=norm,
                            notes="دلالة رئيسية",
                        )
                    )
                    aliases += 1
                    seen_norms.add(norm)
            else:
                seen_norms.add(norm)

        # توليد مسميات «محكم السرية/N من …» للسرايا في الكشف إن لم تُدرج في الورقة
        company_re = re.compile(r"^(.+?)\s*-\s*السرية/(\d+)\s*$")
        for m in db.query(UnitDesignation).all():
            label = (m.canonical_label or "").strip()
            cm = company_re.match(label)
            if not cm:
                continue
            parent, n = cm.group(1).strip(), cm.group(2)
            candidates = [f"محكم السرية/{n} من {parent}"]
            if parent.startswith("قيادة "):
                candidates.append(f"محكم السرية/{n} من {parent[len('قيادة '):]}")
            for i, cand in enumerate(candidates):
                norm = normalize_designation_text(cand)
                if not norm or norm in seen_norms:
                    continue
                exists = (
                    db.query(UnitDesignationAlias)
                    .filter(UnitDesignationAlias.alias_label_norm == norm)
                    .first()
                )
                if exists is not None:
                    seen_norms.add(norm)
                    continue
                syn_id = f"SC{i}_{m.unit_id}"
                if db.get(UnitDesignationAlias, syn_id) is not None:
                    continue
                db.add(
                    UnitDesignationAlias(
                        alias_id=syn_id,
                        unit_id=m.unit_id,
                        alias_label=cand,
                        alias_label_norm=norm,
                        notes="مولَّد من الدلالة الرئيسية",
                    )
                )
                aliases += 1
                seen_norms.add(norm)

        db.commit()
    finally:
        wb.close()

    sync_designations_from_organization(db)
    reload_unit_designation_cache(db)
    return {"masters": masters, "aliases": aliases, "source": str(path)}


def reload_unit_designation_cache(db: Session | None = None) -> None:
    """إعادة بناء كاش الذاكرة من قاعدة البيانات."""
    global _LOADED
    _ALIAS_NORM_TO_UNIT.clear()
    _UNIT_BY_ID.clear()

    close = False
    if db is None:
        from app.database import SessionLocal

        db = SessionLocal()
        close = True
    try:
        for m in db.query(UnitDesignation).filter(UnitDesignation.is_active.is_(True)).all():
            _UNIT_BY_ID[m.unit_id] = m
            n = normalize_designation_text(m.canonical_label or "")
            if n:
                _ALIAS_NORM_TO_UNIT[n] = m.unit_id
        for a in db.query(UnitDesignationAlias).all():
            if a.unit_id not in _UNIT_BY_ID:
                continue
            n = (a.alias_label_norm or "").strip() or normalize_designation_text(
                a.alias_label or ""
            )
            if n:
                _ALIAS_NORM_TO_UNIT[n] = a.unit_id
        _LOADED = True
    finally:
        if close:
            db.close()


def ensure_unit_designations_loaded(db: Session | None = None) -> None:
    if _LOADED and _UNIT_BY_ID:
        return
    close = False
    if db is None:
        from app.database import SessionLocal

        db = SessionLocal()
        close = True
    try:
        if db.query(UnitDesignation).count() == 0:
            seed_unit_designations_from_xlsx(db, force=True)
        else:
            reload_unit_designation_cache(db)
    finally:
        if close:
            db.close()


def resolve_unit_id_for_assignee(assignee_label: str) -> str:
    """يعيد Unit_ID (مثل U001) من مسمى بديل أو دلالة رئيسية."""
    ensure_unit_designations_loaded()
    raw = re.sub(r"^[\s•·\-–]+", "", (assignee_label or "").strip()).strip()
    if not raw:
        return ""
    stripped_num = re.sub(r"^[\d\s.\-–]+", "", raw).strip()
    candidates = [
        raw,
        stripped_num,
        re.sub(r"(\d+)من", r"\1 من", raw),
        re.sub(r"\s+", " ", raw),
        re.sub(r"\s+", " ", stripped_num),
    ]
    seen: set[str] = set()
    for cand in candidates:
        cand = (cand or "").strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        n = normalize_designation_text(cand)
        uid = _ALIAS_NORM_TO_UNIT.get(n)
        if uid:
            return uid
    # أطول دلالة/مسمى محتواة في النص (مثل «كتيبة المدفعية» ↔ «قيادة كتيبة المدفعية»)
    norm_raw = normalize_designation_text(stripped_num or raw)
    if not norm_raw:
        return ""
    best_uid = ""
    best_score = 0
    for alias_norm, uid in _ALIAS_NORM_TO_UNIT.items():
        if not alias_norm or not uid:
            continue
        if alias_norm in norm_raw:
            score = len(alias_norm) + 1000
        elif len(norm_raw) >= 8 and norm_raw in alias_norm:
            score = len(norm_raw)
        else:
            continue
        if score > best_score:
            best_score = score
            best_uid = uid
    return best_uid


def canonical_label_for_unit_id(unit_id: str) -> str:
    ensure_unit_designations_loaded()
    rec = _UNIT_BY_ID.get((unit_id or "").strip())
    return (rec.canonical_label if rec else "") or ""


def canonical_label_for_assignee(assignee_label: str) -> str:
    """الدلالة الرئيسية للوحدة من أي مسمى بديل في عمود المكلف."""
    uid = resolve_unit_id_for_assignee(assignee_label)
    return canonical_label_for_unit_id(uid) if uid else ""


_BN_SLASH_RE = re.compile(r"(?<!السرية)/(\d+)")
_BN_SPACE_RE = re.compile(r"(?:كتيبة|الكتيبة|قتال)\s+(\d+)\b")
_CO_NUM_RE = re.compile(r"السرية/(\d+)")
_COMPANY_CANON_RE = re.compile(r"^(.+?)\s*-\s*السرية/(\d+)\s*$")
# كتالوج القالب القديم — يُحذف من المسميات ويُستبعد من المزامنة
DROPPED_TEMPLATE_BATTALIONS = frozenset({"11", "12", "13", "14"})


def infer_unit_type(label: str) -> str:
    t = (label or "").strip()
    if "هيئة ركن" in t:
        return "هيئة ركن"
    if t.startswith("قيادة ") and "السرية/" not in t:
        return "قيادة"
    if "فصيل" in t:
        return "فصيل"
    if t.startswith("قسم ") or "قسم الأمن" in t:
        return "قسم"
    if "سرية" in t or "السرية" in t:
        return "سرية"
    if "كتيبة" in t:
        return "كتيبة"
    return ""


def _battalion_numbers(text: str) -> set[str]:
    t = text or ""
    return set(_BN_SLASH_RE.findall(t)) | set(_BN_SPACE_RE.findall(t))


def is_dropped_template_battalion_label(label: str) -> bool:
    """وحدات 11–14 فقط — لا يشمل 31/32/33/34."""
    nums = _battalion_numbers(label)
    dropped = nums & DROPPED_TEMPLATE_BATTALIONS
    kept = nums - DROPPED_TEMPLATE_BATTALIONS
    return bool(dropped) and not kept


def _company_numbers(text: str) -> set[str]:
    return set(_CO_NUM_RE.findall(text or ""))


def alias_matches_canonical(alias: str, canonical: str) -> bool:
    """المسمى البديل يخص الدلالة إن لم يحمل رقم كتيبة/سرية مخالفاً."""
    a_bn, c_bn = _battalion_numbers(alias), _battalion_numbers(canonical)
    a_co, c_co = _company_numbers(alias), _company_numbers(canonical)
    if c_bn and a_bn and a_bn != c_bn:
        return False
    if a_bn and not c_bn:
        return False
    if c_co and a_co and a_co != c_co:
        return False
    return True


def generated_aliases_for_canonical(canonical: str) -> list[str]:
    """مسميات بديلة مشتقة من الدلالة الرئيسية (عمود المكلف)."""
    label = (canonical or "").strip()
    if not label:
        return []
    out: list[str] = [label, f"محكم {label}"]
    if label.startswith("قيادة "):
        rest = label[len("قيادة ") :].strip()
        if rest:
            out.append(f"محكم {rest}")
    cm = _COMPANY_CANON_RE.match(label)
    if cm:
        parent, n = cm.group(1).strip(), cm.group(2)
        out.append(f"محكم السرية/{n} من {parent}")
        if parent.startswith("قيادة "):
            out.append(f"محكم السرية/{n} من {parent[len('قيادة '):].strip()}")
        return _unique_keep(out)

    short_map = {
        "سرية الاستطلاع": ("محكم سرية الاستطلاع", "محكم الاستطلاع", "محكم استطلاع"),
        "سرية الـ م/د": ("محكم سرية الـ م/د", "محكم سرية م/د", "محكم الـ م/د", "محكم م/د"),
        "سرية الهاون": ("محكم سرية الهاون", "محكم الهاون", "محكم هاون"),
        "سرية الهندسة": ("محكم سرية الهندسة", "محكم الهندسة", "محكم هندسة", "محكم هندسة الميدان"),
        "سرية الإشارة": ("محكم سرية الإشارة", "محكم الإشارة", "محكم إشارة"),
        "القيادة والسيطرة": ("محكم القيادة والسيطرة", "محكم قيادة وسيطرة"),
        "سرية الدفاع الجوي": ("محكم سرية الدفاع الجوي", "محكم الدفاع الجوي", "محكم دفاع جوي"),
        "سرية الدفاع الكيميائي": (
            "محكم سرية الدفاع الكيميائي",
            "محكم الدفاع الكيميائي",
            "محكم دفاع كيميائي",
        ),
        "كتيبة الإسناد الإداري": (
            "محكم كتيبة الإسناد الإداري",
            "محكم الإسناد الإداري",
        ),
        "السرية الطبية": ("محكم السرية الطبية", "محكم الطبية", "محكم طبية"),
        "سرية الصيانة": ("محكم سرية الصيانة", "محكم الصيانة", "محكم صيانة"),
        "سرية التزويد والنقل": ("محكم سرية التزويد والنقل", "محكم التزويد والنقل"),
        "فصيل الشرطة العسكرية": ("محكم فصيل الشرطة العسكرية", "محكم الشرطة العسكرية"),
        "سرية الحرب الإلكترونية": (
            "محكم سرية الحرب الإلكترونية",
            "محكم الحرب الإلكترونية",
        ),
        "قسم الأمن": ("محكم قسم الأمن", "محكم الأمن"),
        "قيادة مجموعة اللواء": (
            "محكم قيادة مجموعة اللواء",
            "محكم مجموعة اللواء",
            "محكم قيادة اللواء",
            "محكم اللواء",
        ),
        "هيئة ركن مجموعة اللواء": (
            "محكم هيئة ركن مجموعة اللواء",
            "محكم هيئة ركن اللواء",
        ),
        "قيادة كتيبة المدفعية": (
            "محكم قيادة كتيبة المدفعية",
            "محكم كتيبة المدفعية",
            "محكم المدفعية",
        ),
    }
    extras = short_map.get(label)
    if extras:
        out.extend(extras)

    is_c2_branch = label.startswith("القيادة والسيطرة") and "-" in label
    is_bn_cmd = (
        label.startswith("قيادة ")
        and "كتيبة" in label
        and "السرية/" not in label
        and not is_c2_branch
    )
    bns = _battalion_numbers(label)
    if is_bn_cmd and len(bns) == 1:
        n = next(iter(bns))
        out.extend(
            [
                f"محكم قيادة الكتيبة/{n}",
                f"محكم قيادة كتيبة/{n}",
                f"محكم الكتيبة/{n}",
                f"محكم كتيبة/{n}",
                f"محكم كتيبة {n}",
                f"محكم الكتيبة {n}",
                f"محكم ك/{n}",
                f"محكم مجموعة القتال/{n}",
                f"محكم مجموعة قتال/{n}",
                f"محكم م ق/{n}",
            ]
        )
    return _unique_keep(out)


def _unique_keep(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        t = (raw or "").strip()
        n = normalize_designation_text(t)
        if not t or not n or n in seen:
            continue
        seen.add(n)
        out.append(t)
    return out


def _organization_labels_ordered(db: Session) -> list[str]:
    from app.ibank_section_ctx import ibank_section_bypass
    from app.models.domain import InformationBankUnitLevel

    def _collect(rows) -> tuple[list[str], set[str]]:
        labels: list[str] = []
        seen: set[str] = set()
        for r in rows:
            label = (r.label or "").strip()
            n = normalize_designation_text(label)
            if not label or not n or n in seen:
                continue
            seen.add(n)
            labels.append(label)
        return labels, seen

    current, seen = _collect(
        [
            r
            for r in db.query(InformationBankUnitLevel)
            .order_by(InformationBankUnitLevel.sort_order, InformationBankUnitLevel.key)
            .all()
            if not is_dropped_template_battalion_label(r.label or "")
        ]
    )
    extras: list[str] = []
    with ibank_section_bypass():
        all_rows = (
            db.query(InformationBankUnitLevel)
            .order_by(
                InformationBankUnitLevel.ibank_section,
                InformationBankUnitLevel.sort_order,
                InformationBankUnitLevel.key,
            )
            .all()
        )
    for r in all_rows:
        label = (r.label or "").strip()
        n = normalize_designation_text(label)
        if not label or not n or n in seen:
            continue
        if is_dropped_template_battalion_label(label):
            continue
        seen.add(n)
        extras.append(label)
    return current + extras


def _find_designation_by_label(
    rows: list[UnitDesignation], label: str
) -> UnitDesignation | None:
    want = normalize_designation_text(label)
    if not want:
        return None
    for m in rows:
        if normalize_designation_text(m.canonical_label or "") == want:
            return m
    return None


def _upsert_alias(
    db: Session,
    *,
    unit_id: str,
    label: str,
    notes: str,
    seen_norms: set[str],
) -> bool:
    label = (label or "").strip()[:300]
    norm = normalize_designation_text(label)
    if not label or not norm or norm in seen_norms:
        return False
    existing = (
        db.query(UnitDesignationAlias)
        .filter(UnitDesignationAlias.alias_label_norm == norm)
        .first()
    )
    if existing is not None:
        changed = existing.unit_id != unit_id or (existing.alias_label or "") != label
        existing.unit_id = unit_id
        existing.alias_label = label
        if notes and not (existing.notes or "").strip():
            existing.notes = notes
        seen_norms.add(norm)
        return changed
    db.add(
        UnitDesignationAlias(
            alias_id=next_alias_id(db),
            unit_id=unit_id,
            alias_label=label,
            alias_label_norm=norm,
            notes=notes,
        )
    )
    db.flush()
    seen_norms.add(norm)
    return True


def _purge_dropped_template_designations(db: Session) -> int:
    """حذف دلالات 11–14 ومسمياتها البديلة مع الإبقاء على بقية الوحدات."""
    removed = 0
    rows = db.query(UnitDesignation).all()
    drop_ids = [
        m.unit_id
        for m in rows
        if is_dropped_template_battalion_label(m.canonical_label or "")
    ]
    if not drop_ids:
        return 0
    drop_set = set(drop_ids)
    db.query(UnitDesignationAlias).filter(
        UnitDesignationAlias.unit_id.in_(drop_ids)
    ).delete(synchronize_session=False)
    for m in rows:
        if m.unit_id in drop_set:
            db.delete(m)
            removed += 1
    if removed:
        db.flush()
    return removed


def sync_designations_from_organization(db: Session) -> dict[str, int]:
    """يحدّث كشف الدلالات من صفحة التنظيم ويضبط المسميات البديلة لكل دلالة."""
    purged = _purge_dropped_template_designations(db)
    org_labels = [
        lbl
        for lbl in _organization_labels_ordered(db)
        if not is_dropped_template_battalion_label(lbl)
    ]
    rows = db.query(UnitDesignation).all()
    changed = purged
    created = 0
    for idx, label in enumerate(org_labels, start=1):
        if is_dropped_template_battalion_label(label):
            continue
        rec = _find_designation_by_label(rows, label)
        if rec is None:
            rec = UnitDesignation(
                unit_id=next_unit_id(db),
                canonical_label=label,
                unit_type=infer_unit_type(label),
                is_active=True,
                sort_order=idx,
            )
            db.add(rec)
            db.flush()
            rows.append(rec)
            created += 1
            changed += 1
        else:
            if (rec.canonical_label or "").strip() != label:
                rec.canonical_label = label
                changed += 1
            if not (rec.unit_type or "").strip():
                rec.unit_type = infer_unit_type(label)
                changed += 1
            if int(rec.sort_order or 0) != idx:
                rec.sort_order = idx
                changed += 1
            rec.is_active = True

    extra_start = len(org_labels) + 1
    extras = [
        m
        for m in rows
        if normalize_designation_text(m.canonical_label or "")
        not in {normalize_designation_text(x) for x in org_labels}
    ]
    extras.sort(key=lambda m: (int(m.sort_order or 0), m.unit_id))
    for i, rec in enumerate(extras):
        want = extra_start + i
        if int(rec.sort_order or 0) != want:
            rec.sort_order = want
            changed += 1

    by_canon = {
        normalize_designation_text(m.canonical_label or ""): m
        for m in rows
        if normalize_designation_text(m.canonical_label or "")
    }

    for a in list(db.query(UnitDesignationAlias).all()):
        owner = next((m for m in rows if m.unit_id == a.unit_id), None)
        label = (a.alias_label or "").strip()
        if owner and alias_matches_canonical(label, owner.canonical_label or ""):
            continue
        dest = None
        n = normalize_designation_text(label)
        if n in by_canon:
            dest = by_canon[n]
        else:
            cands = [
                m
                for m in rows
                if alias_matches_canonical(label, m.canonical_label or "")
                and _battalion_numbers(label)
                and _battalion_numbers(label) == _battalion_numbers(m.canonical_label or "")
            ]
            if len(cands) == 1:
                dest = cands[0]
        if dest is not None and dest.unit_id != a.unit_id:
            a.unit_id = dest.unit_id
            changed += 1
        elif owner is not None and not alias_matches_canonical(label, owner.canonical_label or ""):
            db.delete(a)
            changed += 1

    db.flush()
    for rec in rows:
        canon = (rec.canonical_label or "").strip()
        if not canon:
            continue
        seen_norms: set[str] = set()
        for a in (
            db.query(UnitDesignationAlias)
            .filter(UnitDesignationAlias.unit_id == rec.unit_id)
            .all()
        ):
            n = (a.alias_label_norm or "").strip() or normalize_designation_text(
                a.alias_label or ""
            )
            if n:
                seen_norms.add(n)
        for cand in generated_aliases_for_canonical(canon):
            if _upsert_alias(
                db,
                unit_id=rec.unit_id,
                label=cand,
                notes="مولَّد من الدلالة الرئيسية",
                seen_norms=seen_norms,
            ):
                changed += 1

    if changed:
        db.flush()
        reload_unit_designation_cache(db)
    return {"changed": changed, "created": created, "labels": len(org_labels)}


def list_designations_for_ibank(db: Session) -> list[dict]:
    """قائمة الدلالات والمسميات لواجهة بنك المعلومات (مصدر عام بلا تمرين)."""
    ensure_unit_designations_loaded(db)
    stats = sync_designations_from_organization(db)
    if stats.get("changed"):
        db.commit()
        reload_unit_designation_cache(db)
    rows = (
        db.query(UnitDesignation)
        .order_by(UnitDesignation.sort_order, UnitDesignation.unit_id)
        .all()
    )
    aliases_by_unit: dict[str, list[dict[str, str]]] = {}
    for a in db.query(UnitDesignationAlias).order_by(UnitDesignationAlias.alias_id).all():
        uid = (a.unit_id or "").strip()
        if not uid:
            continue
        aliases_by_unit.setdefault(uid, []).append(
            {
                "alias_id": a.alias_id,
                "alias_label": (a.alias_label or "").strip(),
                "notes": (a.notes or "").strip(),
            }
        )
    out: list[dict] = []
    for i, m in enumerate(rows, start=1):
        uid = (m.unit_id or "").strip()
        out.append(
            {
                "unit_id": uid,
                "num": i,
                "canonical_label": (m.canonical_label or "").strip(),
                "unit_type": (m.unit_type or "").strip(),
                "is_active": bool(m.is_active),
                "aliases": aliases_by_unit.get(uid, []),
            }
        )
    return out


def _next_prefixed_id(db: Session, *, model, field: str, prefix: str) -> str:
    nums: list[int] = []
    rx = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.I)
    for (raw,) in db.query(getattr(model, field)).all():
        m = rx.match((raw or "").strip())
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) if nums else 0) + 1
    return f"{prefix}{n:03d}"


def next_unit_id(db: Session) -> str:
    return _next_prefixed_id(db, model=UnitDesignation, field="unit_id", prefix="U")


def next_alias_id(db: Session) -> str:
    return _next_prefixed_id(db, model=UnitDesignationAlias, field="alias_id", prefix="A")


def update_alias_label(db: Session, *, alias_id: str, new_label: str) -> tuple[bool, str, str]:
    """تعديل مسمى بديل. يعيد (نجاح، رسالة خطأ، النص المحفوظ)."""
    aid = (alias_id or "").strip()
    label = (new_label or "").strip()[:300]
    if not aid or not label:
        return False, "أدخل مسمىً صالحاً.", ""
    row = db.get(UnitDesignationAlias, aid)
    if row is None:
        return False, "المسمى غير موجود.", ""
    norm = normalize_designation_text(label)
    if not norm:
        return False, "أدخل مسمىً صالحاً.", ""
    clash = (
        db.query(UnitDesignationAlias)
        .filter(
            UnitDesignationAlias.alias_label_norm == norm,
            UnitDesignationAlias.alias_id != aid,
        )
        .first()
    )
    if clash is not None:
        if clash.unit_id == row.unit_id:
            return False, "المسمى موجود مسبقاً.", ""
        return False, "هذا المسمى مرتبط بدلالة أخرى.", ""
    row.alias_label = label
    row.alias_label_norm = norm
    return True, "", label


def ensure_canonical_alias(db: Session, *, unit_id: str, label: str) -> None:
    label = (label or "").strip()
    if not label:
        return
    norm = normalize_designation_text(label)
    if not norm:
        return
    exists = (
        db.query(UnitDesignationAlias)
        .filter(UnitDesignationAlias.alias_label_norm == norm)
        .first()
    )
    if exists is not None:
        exists.unit_id = unit_id
        exists.alias_label = label
        return
    syn_id = f"S_{unit_id}"
    rec = db.get(UnitDesignationAlias, syn_id)
    if rec is None:
        rec = UnitDesignationAlias(alias_id=syn_id)
        db.add(rec)
    rec.unit_id = unit_id
    rec.alias_label = label
    rec.alias_label_norm = norm
    rec.notes = "دلالة رئيسية"


def apply_canonical_label_to_organization(db: Session, *, old_label: str, new_label: str) -> int:
    """يحدّث تسمية التنظيم إن طابقت الدلالة السابقة — بلا ربط بتمرين."""
    from app.models.domain import InformationBankTreeNode, InformationBankUnitLevel

    old_l = (old_label or "").strip()
    new_l = (new_label or "").strip()
    if not old_l or not new_l or old_l == new_l:
        return 0
    n = 0
    for row in db.query(InformationBankUnitLevel).filter_by(label=old_l).all():
        row.label = new_l
        n += 1
        for node in (
            db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.catalog_unit_key == row.key,
                InformationBankTreeNode.is_folder.is_(True),
            )
            .all()
        ):
            if (node.name or "").strip() == old_l:
                node.name = new_l
    return n
