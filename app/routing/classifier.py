import re

from app.routing.schemas import TaskClassification, TaskType


class TaskClassifier:
    """Bounded bilingual rules; evidence contains rule IDs, never private request text."""

    RULES = [
        (TaskType.GITHUB_ACTION, r"\b(pull request|github|commit|branch)\b|جيت هب"),
        (TaskType.MCP_ACTION, r"\bmcp\b"),
        (TaskType.IMAGE_ANALYSIS, r"\b(image|picture|screenshot)\b|صورة"),
        (TaskType.DEBUGGING, r"\b(debug|error|bug|traceback)\b|خطأ|إصلاح"),
        (TaskType.REFACTOR, r"\brefactor\b|إعادة هيكلة"),
        (TaskType.TESTING, r"\b(test|pytest|coverage)\b|اختبار"),
        (TaskType.CODE_EDIT, r"\b(implement|modify|edit|add function)\b|نفذ|تنفيذ|تعديل"),
        (TaskType.REPOSITORY_TASK, r"\b(repository|repo)\b|مستودع"),
        (TaskType.CODE_QA, r"\b(code|function|class)\b|كود|دالة"),
        (TaskType.DOCUMENT_ANALYSIS, r"\b(document|pdf)\b|وثيقة"),
        (TaskType.DATA_ANALYSIS, r"\b(csv|dataset|data analysis)\b|بيانات"),
        (TaskType.PLANNING, r"\b(plan|design)\b|خطة"),
        (TaskType.SEARCH, r"\b(search|find)\b|ابحث"),
    ]

    def classify(self, text, context_size=0):
        text = text[:16000].lower()
        if context_size > 32000:
            return TaskClassification(
                task_type=TaskType.LONG_CONTEXT_REVIEW,
                complexity=4,
                evidence=["large-context"],
                confidence=0.9,
            )
        for task, pattern in self.RULES:
            if re.search(pattern, text):
                return TaskClassification(
                    task_type=task,
                    complexity=min(5, 2 + len(text) // 3000),
                    confidence=0.7,
                    evidence=[task.value.lower()],
                )
        return TaskClassification(task_type=TaskType.GENERAL_CHAT, evidence=["default"])
