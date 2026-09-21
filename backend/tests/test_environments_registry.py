"""ADM-001/002/003: реестр окружений исполнения."""
import pytest

from app.services.environments import ENVIRONMENTS, get_environment, list_environments


def test_five_environments_registered():
    assert set(ENVIRONMENTS) == {"python3", "python3-data", "cpp17", "sql-sqlite", "arcade"}


def test_get_unknown_environment_raises():
    with pytest.raises(ValueError):
        get_environment("java21")


def test_list_environments_matches_registry():
    assert {e.id for e in list_environments()} == set(ENVIRONMENTS)


def test_arcade_is_flagged_beta_with_explanation():
    arcade = get_environment("arcade")
    assert arcade.status == "beta"
    assert arcade.status_note  # объясняет ограничение, не пустая строка


def test_only_cpp_drops_tmp_noexec():
    for env_id, env in ENVIRONMENTS.items():
        assert env.tmp_exec == (env_id == "cpp17")
