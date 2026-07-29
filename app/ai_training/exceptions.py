"""أخطاء مركز التدريب — رسائل عربية بدون stack traces للمستخدم."""

from __future__ import annotations


class TrainingCenterError(Exception):
    error_code = "training_error"
    user_message = "حدث خطأ في مركز التدريب."

    def __init__(self, message: str | None = None, *, error_code: str | None = None):
        self.user_message = (message or self.user_message).strip()
        if error_code:
            self.error_code = error_code
        super().__init__(self.user_message)


class UnsupportedDocumentTypeError(TrainingCenterError):
    error_code = "unsupported_document_type"
    user_message = "نوع الملف غير مدعوم."


class InvalidDocumentFileError(TrainingCenterError):
    error_code = "invalid_document_file"
    user_message = "الملف غير صالح."


class DocumentTooLargeError(TrainingCenterError):
    error_code = "document_too_large"
    user_message = "حجم الملف يتجاوز الحد المسموح."


class DuplicateDocumentError(TrainingCenterError):
    error_code = "duplicate_document"
    user_message = "يوجد ملف مطابق (نفس بصمة SHA-256)."


class DocumentStorageError(TrainingCenterError):
    error_code = "document_storage_error"
    user_message = "تعذر حفظ الملف."


class DocumentNotFoundError(TrainingCenterError):
    error_code = "document_not_found"
    user_message = "الوثيقة غير موجودة."


class DocumentExtractionError(TrainingCenterError):
    error_code = "document_extraction_error"
    user_message = "فشل استخراج النص."


class DocumentExtractionPartialError(TrainingCenterError):
    error_code = "document_extraction_partial"
    user_message = "استخراج جزئي مع تحذيرات."


class OCRRequiredError(TrainingCenterError):
    error_code = "ocr_required"
    user_message = "الوثيقة تبدو ممسوحة ضوئياً وتحتاج OCR في مرحلة لاحقة."


class ReviewStateError(TrainingCenterError):
    error_code = "review_state_error"
    user_message = "حالة المراجعة لا تسمح بهذه العملية."


class ExtractionApprovalError(TrainingCenterError):
    error_code = "extraction_approval_error"
    user_message = "تعذر اعتماد جودة الاستخراج."


class DocumentAlreadyApprovedError(TrainingCenterError):
    error_code = "document_already_approved"
    user_message = "النسخة معتمدة ومقفلة — أنشئ مراجعة جديدة للتعديل."


class DocumentVersionConflictError(TrainingCenterError):
    error_code = "document_version_conflict"
    user_message = "تعارض في إصدار الوثيقة."
