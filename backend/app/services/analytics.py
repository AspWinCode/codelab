"""ANA-001/002: агрегированные метрики по курсу и рейтинг задач по сложности
для методиста. Считаются по данным, которые Judge и так пишет при каждой
проверке — отдельного сбора метрик не требуется."""
from datetime import datetime, timezone
from statistics import median
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Course,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    OgeAttempt,
    Progress,
    Submission,
    Verdict,
)


def course_overview(db: Session, course_id: int) -> dict:
    """ANA-001: процент завершения, средний/медианный балл, число попыток,
    просроченные назначения (Enrollment.ends_at)."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == course_id, Enrollment.status == EnrollmentStatus.ACTIVE)
        .all()
    )
    enrolled_count = len(enrollments)

    progresses = db.query(Progress).filter(Progress.course_id == course_id).all()
    progress_by_user = {p.user_id: p for p in progresses}
    completed_count = sum(1 for p in progresses if p.total_items and p.completed_items >= p.total_items)
    percents = [p.percent for p in progresses]
    avg_score = round(sum(percents) / len(percents), 1) if percents else 0.0
    median_score = round(median(percents), 1) if percents else 0.0

    task_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course.active_version_id, LearningItem.type == LearningItemType.TASK)
        .all()
        if course.active_version_id else []
    )
    problem_ids = [i.problem_revision_id for i in task_items if i.problem_revision_id]
    total_attempts = (
        db.query(Submission).filter(Submission.problem_revision_id.in_(problem_ids)).count()
        if problem_ids else 0
    )

    now = datetime.now(timezone.utc)
    overdue_count = 0
    for e in enrollments:
        ends_at = e.ends_at
        if ends_at is None:
            continue
        # SQLite (используется для локального запуска без Postgres, см. README)
        # не сохраняет tzinfo даже для DateTime(timezone=True) — без этого
        # сравнение naive/aware datetime падает с TypeError.
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if ends_at >= now:
            continue
        p = progress_by_user.get(e.user_id)
        if not (p and p.total_items and p.completed_items >= p.total_items):
            overdue_count += 1

    return {
        "course_id": course_id,
        "enrolled_count": enrolled_count,
        "completed_count": completed_count,
        "completion_percent": round(100 * completed_count / enrolled_count, 1) if enrolled_count else 0.0,
        "avg_score": avg_score,
        "median_score": median_score,
        "total_attempts": total_attempts,
        "overdue_count": overdue_count,
    }


def task_difficulty(db: Session, course_id: int) -> list[dict]:
    """ANA-002: рейтинг задач по доле ошибок, среднему числу попыток до
    решения и числу отказов (зачислен, но ни разу не пытался решить)."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")
    if not course.active_version_id:
        return []

    task_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course.active_version_id, LearningItem.type == LearningItemType.TASK)
        .order_by(LearningItem.position)
        .all()
    )
    enrolled_user_ids = {
        e.user_id
        for e in db.query(Enrollment).filter(Enrollment.course_id == course_id, Enrollment.status == EnrollmentStatus.ACTIVE)
    }

    rows = []
    for item in task_items:
        if not item.problem_revision_id:
            continue
        submissions = (
            db.query(Submission)
            .filter(Submission.problem_revision_id == item.problem_revision_id)
            .order_by(Submission.created_at)
            .all()
        )
        attempted_users = {s.user_id for s in submissions}
        solved_users: set[int] = set()
        attempts_to_solve: list[int] = []
        per_user_attempts: dict[int, int] = {}
        failure_verdicts: dict[str, int] = {}

        for s in submissions:
            per_user_attempts[s.user_id] = per_user_attempts.get(s.user_id, 0) + 1
            if s.verdict == Verdict.ACCEPTED:
                if s.user_id not in solved_users:
                    solved_users.add(s.user_id)
                    attempts_to_solve.append(per_user_attempts[s.user_id])
            elif s.verdict:
                failure_verdicts[s.verdict.value] = failure_verdicts.get(s.verdict.value, 0) + 1

        not_attempted = len(enrolled_user_ids - attempted_users)
        failure_rate = round(100 * (1 - len(solved_users) / len(attempted_users)), 1) if attempted_users else 0.0
        avg_attempts = round(sum(attempts_to_solve) / len(attempts_to_solve), 1) if attempts_to_solve else None
        most_common_failure: Optional[str] = max(failure_verdicts, key=failure_verdicts.get) if failure_verdicts else None

        rows.append({
            "item_id": item.id,
            "title": item.title,
            "attempts_total": len(submissions),
            "students_attempted": len(attempted_users),
            "students_solved": len(solved_users),
            "students_not_attempted": not_attempted,
            "failure_rate_percent": failure_rate,
            "avg_attempts_to_solve": avg_attempts,
            "most_common_failure_verdict": most_common_failure,
        })
    return rows


def _ancestor_title(by_id: dict[int, LearningItem], item_id: int, wanted_type: LearningItemType) -> Optional[str]:
    """Ищет заголовок предка нужного типа, поднимаясь по parent_id. by_id —
    все элементы активной версии курса, загруженные ОДНИМ запросом выше по
    стеку (здесь никаких дополнительных запросов к базе)."""
    node = by_id.get(item_id)
    seen: set[int] = set()
    while node and node.parent_id is not None and node.parent_id not in seen:
        seen.add(node.parent_id)
        node = by_id.get(node.parent_id)
        if node and node.type == wanted_type:
            return node.title
    return None


def oge_task_analytics(db: Session, course_id: int) -> list[dict]:
    """ОГЭ-аналог task_difficulty: по каждому заданию ОГЭ — число
    записанных/решавших/правильных/неправильных попыток, среднее и
    медианное число попыток, дата последней попытки. Все попытки по всем
    заданиям курса читаются ОДНИМ запросом (без N+1 по заданиям)."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")
    if not course.active_version_id:
        return []

    oge_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course.active_version_id, LearningItem.type == LearningItemType.OGE_TASK)
        .order_by(LearningItem.position)
        .all()
    )
    if not oge_items:
        return []
    item_ids = [i.id for i in oge_items]

    all_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course.active_version_id)
        .all()
    )
    by_id = {i.id: i for i in all_items}

    enrolled_user_ids = {
        e.user_id
        for e in db.query(Enrollment).filter(Enrollment.course_id == course_id, Enrollment.status == EnrollmentStatus.ACTIVE)
    }

    attempts = (
        db.query(OgeAttempt)
        .filter(OgeAttempt.item_id.in_(item_ids))
        .order_by(OgeAttempt.created_at)
        .all()
    )
    attempts_by_item: dict[int, list[OgeAttempt]] = {}
    for a in attempts:
        attempts_by_item.setdefault(a.item_id, []).append(a)

    rows = []
    for item in oge_items:
        item_attempts = attempts_by_item.get(item.id, [])
        attempted_users = {a.user_id for a in item_attempts}
        per_user_attempts: dict[int, int] = {}
        last_attempt_at = None
        score_sum = 0.0
        correct_count = 0
        for a in item_attempts:
            per_user_attempts[a.user_id] = per_user_attempts.get(a.user_id, 0) + 1
            score_sum += a.score
            if a.score >= 100.0:
                correct_count += 1
            if last_attempt_at is None or a.created_at > last_attempt_at:
                last_attempt_at = a.created_at

        incorrect_count = len(item_attempts) - correct_count
        not_attempted = len(enrolled_user_ids - attempted_users)
        correct_rate = round(100 * correct_count / len(item_attempts), 1) if item_attempts else 0.0
        attempts_counts = list(per_user_attempts.values())
        avg_attempts = round(sum(attempts_counts) / len(attempts_counts), 1) if attempts_counts else None
        median_attempts = round(median(attempts_counts), 1) if attempts_counts else None
        avg_score = round(score_sum / len(item_attempts), 1) if item_attempts else 0.0

        rows.append({
            "item_id": item.id,
            "title": item.title,
            "module_title": _ancestor_title(by_id, item.id, LearningItemType.MODULE),
            "topic_title": _ancestor_title(by_id, item.id, LearningItemType.TOPIC),
            "enrolled_count": len(enrolled_user_ids),
            "students_attempted": len(attempted_users),
            "correct_count": correct_count,
            "incorrect_count": incorrect_count,
            "correct_rate_percent": correct_rate,
            "avg_attempts": avg_attempts,
            "median_attempts": median_attempts,
            "students_not_attempted": not_attempted,
            "avg_score": avg_score,
            "last_attempt_at": last_attempt_at,
        })
    return rows


def oge_overview(db: Session, course_id: int, tasks: Optional[list[dict]] = None) -> dict:
    """ANA-001 для ОГЭ: сводка по курсу — число заданий, доля решённых,
    средний процент правильных ответов, самые сложные/лёгкие задания,
    статистика по модулям. completion_percent берётся из course_overview,
    т.к. завершённость курса не зависит от типа задания."""
    if tasks is None:
        tasks = oge_task_analytics(db, course_id)

    total_tasks = len(tasks)
    solved_tasks = sum(1 for t in tasks if t["correct_count"] > 0)
    total_attempts = sum(t["correct_count"] + t["incorrect_count"] for t in tasks)
    avg_correct_rate = round(sum(t["correct_rate_percent"] for t in tasks) / total_tasks, 1) if total_tasks else 0.0

    attempted_tasks = [t for t in tasks if (t["correct_count"] + t["incorrect_count"]) > 0]
    ranked = sorted(attempted_tasks, key=lambda t: t["correct_rate_percent"])
    hardest_tasks = ranked[:5]
    easiest_tasks = list(reversed(ranked))[:5]

    by_module: dict[str, dict] = {}
    for t in tasks:
        key = t["module_title"] or "Без модуля"
        agg = by_module.setdefault(key, {"module_title": key, "tasks_count": 0, "attempts_total": 0, "_rate_sum": 0.0})
        agg["tasks_count"] += 1
        agg["attempts_total"] += t["correct_count"] + t["incorrect_count"]
        agg["_rate_sum"] += t["correct_rate_percent"]
    module_stats = []
    for agg in by_module.values():
        rate_sum = agg.pop("_rate_sum")
        agg["avg_correct_rate_percent"] = round(rate_sum / agg["tasks_count"], 1) if agg["tasks_count"] else 0.0
        module_stats.append(agg)

    completion_percent = course_overview(db, course_id)["completion_percent"]

    return {
        "total_tasks": total_tasks,
        "solved_tasks": solved_tasks,
        "avg_correct_rate_percent": avg_correct_rate,
        "total_attempts": total_attempts,
        "completion_percent": completion_percent,
        "hardest_tasks": hardest_tasks,
        "easiest_tasks": easiest_tasks,
        "by_module": module_stats,
    }
