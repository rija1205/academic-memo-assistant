from app.projects.access import ProjectRole, has_required_role


def test_project_role_hierarchy() -> None:
    assert has_required_role(ProjectRole.OWNER, ProjectRole.READER)
    assert has_required_role(ProjectRole.OWNER, ProjectRole.EDITOR)
    assert has_required_role(ProjectRole.OWNER, ProjectRole.OWNER)
    assert has_required_role(ProjectRole.EDITOR, ProjectRole.READER)
    assert has_required_role(ProjectRole.EDITOR, ProjectRole.EDITOR)
    assert not has_required_role(ProjectRole.READER, ProjectRole.EDITOR)
    assert not has_required_role(ProjectRole.READER, ProjectRole.OWNER)
