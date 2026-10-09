"""Подписанный admin-API для LMS: методист/преподаватель работают через свой
аккаунт портала, не заходя в Codelab по браузерной cookie-сессии."""
import hashlib
import hmac
from datetime import datetime, timezone

from app.config import settings
from app.models import Course, CourseVersion, LearningItem, LearningItemType, ProblemRevision, Submission, SubmissionStatus, User


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def test_rejects_bad_signature(client):
    resp = client.post(f"/api/lms-admin/courses?{_staff_qs()}", json={"title": "C"}, headers={"X-LP-Signature": "wrong"})
    assert resp.status_code == 401


def test_rejects_unknown_role(client):
    resp = client.post(
        f"/api/lms-admin/courses?{_staff_qs(role='sales')}",
        json={"title": "C"},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 422


def test_create_course_creates_staff_user_lazily(client, db_session):
    assert db_session.query(User).filter(User.external_ref == "lp-user-1").first() is None

    resp = client.post(
        f"/api/lms-admin/courses?{_staff_qs()}",
        json={"title": "Python с нуля"},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 200
    course = resp.json()
    assert course["title"] == "Python с нуля"

    staff = db_session.query(User).filter(User.external_ref == "lp-user-1").first()
    assert staff is not None
    assert staff.role == "methodist"

    db_course = db_session.query(Course).filter(Course.id == course["id"]).first()
    assert db_course.created_by_id == staff.id


def test_full_authoring_and_publish_flow(client, db_session):
    sig = _sig("lp-user-1")
    qs = _staff_qs()

    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()
    task = client.post(
        f"/api/lms-admin/courses/{course['id']}/tasks?{qs}",
        json={"title": "Сумма", "tests": [{"input": "2 3\n", "expected": "5\n"}]},
        headers={"X-LP-Signature": sig},
    ).json()
    item = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={"type": "task", "title": "Задача 1", "problem_revision_id": task["id"]},
        headers={"X-LP-Signature": sig},
    ).json()

    tree = client.get(f"/api/lms-admin/courses/{course['id']}/tree?{qs}", headers={"X-LP-Signature": sig}).json()
    assert len(tree) == 1 and tree[0]["id"] == item["id"]

    publish_resp = client.post(f"/api/lms-admin/courses/{course['id']}/publish?{qs}", headers={"X-LP-Signature": sig})
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "published"

    db_course = db_session.query(Course).filter(Course.id == course["id"]).first()
    assert db_course.active_version_id is not None


def test_teacher_can_read_published_tree_to_select_projects(client, db_session):
    course = Course(title="Курс преподавателя")
    db_session.add(course)
    db_session.flush()
    published = CourseVersion(
        course_id=course.id,
        version_number=1,
        published_at=datetime.now(timezone.utc),
    )
    draft = CourseVersion(course_id=course.id, version_number=2)
    db_session.add_all([published, draft])
    db_session.flush()
    course.active_version_id = published.id
    published_project = LearningItem(
        course_version_id=published.id,
        type=LearningItemType.PROJECT,
        title="Проект для проверки",
    )
    draft_project = LearningItem(
        course_version_id=draft.id,
        type=LearningItemType.PROJECT,
        title="Черновой проект",
    )
    db_session.add_all([published_project, draft_project])
    db_session.commit()

    qs = _staff_qs(external_ref="lp-teacher-1", full_name="Преподаватель", role="teacher")
    response = client.get(
        f"/api/lms-admin/courses/{course.id}/tree?{qs}",
        headers={"X-LP-Signature": _sig("lp-teacher-1")},
    )

    assert response.status_code == 200
    assert [node["title"] for node in response.json()] == ["Проект для проверки"]


def test_admin_gets_draft_tree_after_publish_and_can_add_item(client, db_session):
    """Регресс: LMS мапит свои роли admin/owner/manager в staff_role="admin"
    (как и methodist, это управляющая роль — см. ensure_course_owner). После
    публикации курса get_tree должен отдавать admin тот же ЧЕРНОВИК, что и
    методисту, а не замороженное опубликованное дерево с id из другой
    course_version_id — иначе "+ Материал" с parent_id оттуда бьёт в 404
    "Родительский элемент не найден в черновике этого курса" (create_item
    ищет parent_id только среди элементов текущего черновика)."""
    methodist_sig = _sig("lp-user-1")
    methodist_qs = _staff_qs()

    course = client.post(
        f"/api/lms-admin/courses?{methodist_qs}", json={"title": "C"}, headers={"X-LP-Signature": methodist_sig},
    ).json()
    module = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{methodist_qs}",
        json={"type": "module", "title": "Модуль 1"},
        headers={"X-LP-Signature": methodist_sig},
    ).json()
    publish_resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/publish?{methodist_qs}", headers={"X-LP-Signature": methodist_sig},
    )
    assert publish_resp.status_code == 200

    admin_sig = _sig("lp-admin-1")
    admin_qs = _staff_qs(external_ref="lp-admin-1", full_name="Админ", role="admin")

    tree = client.get(
        f"/api/lms-admin/courses/{course['id']}/tree?{admin_qs}", headers={"X-LP-Signature": admin_sig},
    ).json()
    assert len(tree) == 1 and tree[0]["title"] == "Модуль 1"
    draft_module_id = tree[0]["id"]
    # Клон публикации завёл НОВЫЙ id элемента в черновике — id из
    # опубликованной версии (module["id"]) больше не валиден как parent_id.
    assert draft_module_id != module["id"]

    created = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{admin_qs}",
        json={"type": "theory", "title": "Урок 1", "parent_id": draft_module_id},
        headers={"X-LP-Signature": admin_sig},
    )
    assert created.status_code == 200, created.text


def test_list_and_grade_submissions(client, db_session):
    sig = _sig("lp-user-2")
    qs = _staff_qs(external_ref="lp-user-2", full_name="Пётр Тренер", role="teacher")

    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db_session.add(version)
    db_session.flush()
    course.active_version_id = version.id

    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача", problem_revision_id=problem.id)
    db_session.add(item)

    student = User(external_ref="lp-student-1", full_name="Ученик", role="student")
    db_session.add(student)
    db_session.flush()
    sub = Submission(user_id=student.id, problem_revision_id=problem.id, code="print(1)", status=SubmissionStatus.DONE, score=40.0)
    db_session.add(sub)
    db_session.commit()

    resp = client.get(f"/api/lms-admin/courses/{course.id}/submissions?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["student_full_name"] == "Ученик"
    assert body[0]["code"] == "print(1)"

    grade_resp = client.put(
        f"/api/lms-admin/courses/{course.id}/submissions/{sub.id}/grade?{qs}",
        json={"score": 90.0, "comment": "Работает, но неаккуратно"},
        headers={"X-LP-Signature": sig},
    )
    assert grade_resp.status_code == 200
    assert grade_resp.json()["manual_score_override"] == 90.0


def test_grade_requires_comment(client, db_session):
    sig = _sig("lp-user-2")
    qs = _staff_qs(external_ref="lp-user-2", full_name="Пётр Тренер", role="teacher")

    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()
    student = User(external_ref="lp-student-1", full_name="Ученик", role="student")
    db_session.add(student)
    db_session.flush()
    sub = Submission(user_id=student.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=10.0)
    db_session.add(sub)
    db_session.commit()

    resp = client.put(
        f"/api/lms-admin/courses/{course.id}/submissions/{sub.id}/grade?{qs}",
        json={"score": 50.0, "comment": "   "},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 422


def test_grade_rejects_submission_from_other_course(client, db_session):
    """course_id в пути — LMS должна мочь проверить, что посылка правда из
    заявленного курса, прежде чем разрешать оценку (закрывает пробел, из-за
    которого раньше эндпоинт не принимал course_id вообще)."""
    sig = _sig("lp-user-2")
    qs = _staff_qs(external_ref="lp-user-2", full_name="Пётр Тренер", role="teacher")

    course_a = Course(title="A")
    course_b = Course(title="B")
    db_session.add_all([course_a, course_b])
    db_session.flush()
    version_a = CourseVersion(course_id=course_a.id, version_number=1)
    db_session.add(version_a)
    db_session.flush()

    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()
    item = LearningItem(course_version_id=version_a.id, type=LearningItemType.TASK, title="Задача", problem_revision_id=problem.id)
    db_session.add(item)

    student = User(external_ref="lp-student-1", full_name="Ученик", role="student")
    db_session.add(student)
    db_session.flush()
    sub = Submission(user_id=student.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=10.0)
    db_session.add(sub)
    db_session.commit()

    # Посылка реально из course_a, но запрос утверждает, что из course_b.
    resp = client.put(
        f"/api/lms-admin/courses/{course_b.id}/submissions/{sub.id}/grade?{qs}",
        json={"score": 50.0, "comment": "test"},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 404
