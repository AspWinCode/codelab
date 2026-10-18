"""GRD-002/004/005: официальный результат по политике, пересчёт Progress,
ручная корректировка с обязательным комментарием, разблокировка LMS-004."""
import pytest

from app.models import (
    Course,
    CourseVersion,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    ProblemRevision,
    ProjectSubmission,
    ProjectSubmissionStatus,
    Progress,
    Submission,
    SubmissionStatus,
    User,
    Verdict,
)
from app.services.course_admin import build_student_tree, mark_content_item_completed
from app.services.progress_calc import (
    is_item_passed,
    is_item_unlocked,
    recompute_progress_for_project,
    recompute_progress_for_submission,
    resolve_official_score,
)


def _make_course_with_task(db, scoring_policy="best", weight=1.0, required=True):
    course = Course(title="C")
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db.add(version)
    db.flush()
    problem = ProblemRevision(task_id=1, revision_number=1, title="T", scoring_policy=scoring_policy)
    db.add(problem)
    db.flush()
    item = LearningItem(
        course_version_id=version.id,
        type=LearningItemType.TASK,
        title="Задача",
        problem_revision_id=problem.id,
        weight=weight,
        is_required=required,
    )
    db.add(item)
    db.flush()
    return course, version, problem, item


@pytest.mark.parametrize("policy,scores,expected", [
    ("best", [40.0, 100.0, 60.0], 100.0),
    ("last", [40.0, 100.0, 60.0], 60.0),
    ("first_accepted", [(40.0, None), (100.0, Verdict.ACCEPTED), (60.0, Verdict.ACCEPTED)], 100.0),
])
def test_resolve_official_score_policies(db_session, policy, scores, expected):
    course, version, problem, item = _make_course_with_task(db_session, scoring_policy=policy)
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()

    for entry in scores:
        score, verdict = entry if isinstance(entry, tuple) else (entry, Verdict.WRONG_ANSWER)
        db_session.add(Submission(
            user_id=user.id, problem_revision_id=problem.id, code="x",
            status=SubmissionStatus.DONE, verdict=verdict, score=score,
        ))
    db_session.commit()

    assert resolve_official_score(db_session, user.id, problem.id) == expected


def test_manual_override_takes_precedence(db_session):
    course, version, problem, item = _make_course_with_task(db_session, scoring_policy="best")
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    sub = Submission(user_id=user.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=30.0)
    db_session.add(sub)
    db_session.commit()

    assert resolve_official_score(db_session, user.id, problem.id) == 30.0

    sub.manual_score_override = 90.0
    sub.manual_comment = "Проверил руками, тест был кривой"
    db_session.commit()

    # Исходный авто-результат не тронут — только эффективный балл поменялся.
    assert sub.score == 30.0
    assert resolve_official_score(db_session, user.id, problem.id) == 90.0


def test_recompute_progress_after_submission(db_session):
    """Полный балл (Accepted/100) — задача засчитана решённой, очки по
    фактическому баллу (с учётом weight)."""
    course, version, problem, item = _make_course_with_task(db_session, weight=2.0)
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    db_session.add(Enrollment(
        user_id=user.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE,
    ))
    sub = Submission(
        user_id=user.id, problem_revision_id=problem.id, code="x",
        status=SubmissionStatus.DONE, verdict=Verdict.ACCEPTED, score=100.0,
    )
    db_session.add(sub)
    db_session.commit()

    recompute_progress_for_submission(db_session, sub)

    progress = db_session.query(Progress).filter(Progress.user_id == user.id, Progress.course_id == course.id).first()
    assert progress is not None
    assert progress.completed_items == 1
    assert progress.total_items == 1
    assert progress.percent == 100.0
    assert progress.points == 200  # score(100) * weight(2)


def test_partial_score_not_counted_as_completed(db_session):
    """Частичный результат (не все тесты прошли, score < 100, verdict
    Wrong Answer) не должен засчитываться как решённая задача — только
    полный балл. Очки за частичный прогресс всё равно копятся."""
    course, version, problem, item = _make_course_with_task(db_session, weight=2.0)
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    db_session.add(Enrollment(
        user_id=user.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE,
    ))
    sub = Submission(
        user_id=user.id, problem_revision_id=problem.id, code="x",
        status=SubmissionStatus.DONE, verdict=Verdict.WRONG_ANSWER, score=50.0,
    )
    db_session.add(sub)
    db_session.commit()

    assert is_item_passed(db_session, user.id, item) is False

    recompute_progress_for_submission(db_session, sub)

    progress = db_session.query(Progress).filter(Progress.user_id == user.id, Progress.course_id == course.id).first()
    assert progress is not None
    assert progress.completed_items == 0  # не решено — только частичный балл
    assert progress.total_items == 1
    assert progress.percent == 0.0
    assert progress.points == 100  # очки всё же копятся: score(50) * weight(2)

    # Если следом приходит полностью верное решение — задача засчитывается.
    accepted = Submission(
        user_id=user.id, problem_revision_id=problem.id, code="y",
        status=SubmissionStatus.DONE, verdict=Verdict.ACCEPTED, score=100.0,
    )
    db_session.add(accepted)
    db_session.commit()
    recompute_progress_for_submission(db_session, accepted)

    assert is_item_passed(db_session, user.id, item) is True
    db_session.refresh(progress)
    assert progress.completed_items == 1


def test_item_unlocks_after_predecessor_passed(db_session):
    course, version, problem, item = _make_course_with_task(db_session)
    locked_item = LearningItem(
        course_version_id=version.id,
        type=LearningItemType.THEORY,
        title="Следующая тема",
        unlock_rules={"after_item_id": item.id},
    )
    db_session.add(locked_item)
    db_session.commit()

    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    items_by_id = {item.id: item, locked_item.id: locked_item}

    assert is_item_unlocked(db_session, user.id, locked_item, items_by_id) is False

    db_session.add(Submission(user_id=user.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, verdict=Verdict.ACCEPTED, score=100.0))
    db_session.commit()

    assert is_item_unlocked(db_session, user.id, locked_item, items_by_id) is True


def _make_course_with_project(db, weight=1.0, required=True):
    course = Course(title="C")
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db.add(version)
    db.flush()
    item = LearningItem(
        course_version_id=version.id, type=LearningItemType.PROJECT, title="Проект",
        weight=weight, is_required=required,
    )
    db.add(item)
    db.flush()
    return course, version, item


def test_project_passed_only_when_accepted(db_session):
    """Регресс: PROJECT раньше нигде не был учтён в is_item_passed — проект
    никогда не считался пройденным, какой бы статус у сдачи ни был."""
    course, version, item = _make_course_with_project(db_session)
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()

    submitted = ProjectSubmission(
        learning_item_id=item.id, user_id=user.id, attempt_number=1,
        status=ProjectSubmissionStatus.SUBMITTED,
    )
    db_session.add(submitted)
    db_session.commit()
    assert is_item_passed(db_session, user.id, item) is False

    submitted.status = ProjectSubmissionStatus.NEEDS_REVISION
    db_session.commit()
    assert is_item_passed(db_session, user.id, item) is False

    submitted.status = ProjectSubmissionStatus.ACCEPTED
    submitted.score = 85.0
    db_session.commit()
    assert is_item_passed(db_session, user.id, item) is True


def test_recompute_progress_after_project_accepted(db_session):
    course, version, item = _make_course_with_project(db_session, weight=1.0)
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    db_session.add(Enrollment(
        user_id=user.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE,
    ))
    sub = ProjectSubmission(
        learning_item_id=item.id, user_id=user.id, attempt_number=1,
        status=ProjectSubmissionStatus.ACCEPTED, score=90.0,
    )
    db_session.add(sub)
    db_session.commit()

    recompute_progress_for_project(db_session, sub)

    progress = db_session.query(Progress).filter(Progress.user_id == user.id, Progress.course_id == course.id).first()
    assert progress is not None
    assert progress.completed_items == 1
    assert progress.total_items == 1
    assert progress.points == 90


def test_structural_node_completed_reflects_required_children(db_session):
    """Регресс: родительские разделы (module/.../subtopic) никак не
    агрегировали завершённость детей — completed у них всегда был False,
    даже если все обязательные дочерние элементы уже пройдены."""
    course, version, item = _make_course_with_project(db_session)
    module = LearningItem(
        course_version_id=version.id, type=LearningItemType.MODULE, title="Модуль", position=0,
    )
    db_session.add(module)
    db_session.flush()
    item.parent_id = module.id

    optional_theory = LearningItem(
        course_version_id=version.id, type=LearningItemType.THEORY, title="Необязательный материал",
        parent_id=module.id, is_required=False, content="x",
    )
    db_session.add(optional_theory)
    db_session.commit()

    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.commit()

    items = [module, item, optional_theory]

    def module_node():
        tree = build_student_tree(db_session, user.id, items)
        return next(n for n in tree if n.id == module.id)

    # Единственный обязательный ребёнок (проект) ещё не пройден.
    assert module_node().completed is False

    sub = ProjectSubmission(
        learning_item_id=item.id, user_id=user.id, attempt_number=1,
        status=ProjectSubmissionStatus.ACCEPTED, score=100.0,
    )
    db_session.add(sub)
    db_session.commit()

    # Необязательный материал так и не пройден — на завершённость раздела
    # это не влияет, учитываются только обязательные дети.
    assert module_node().completed is True


def test_snap_task_completable_only_by_explicit_action(db_session):
    """snap_task/gdevelop_task/turtle_task не имеют автопроверки (README) —
    единственный способ получить зелёную отметку — явное действие ученика
    через mark_content_item_completed (кнопка на фронте), не сам факт
    существования элемента."""
    course, version, item = _make_course_with_project(db_session)  # версия/курс, проект не используется
    snap_item = LearningItem(course_version_id=version.id, type=LearningItemType.SNAP_TASK, title="Snap!")
    db_session.add(snap_item)
    db_session.commit()

    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.commit()

    tree = build_student_tree(db_session, user.id, [snap_item])
    assert tree[0].completed is False

    mark_content_item_completed(db_session, user.id, snap_item)

    tree = build_student_tree(db_session, user.id, [snap_item])
    assert tree[0].completed is True
