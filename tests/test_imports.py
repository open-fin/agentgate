from pathlib import Path

ROOT = Path(__file__).parents[1] / "src" / "agentgate"


def sources_under(*parts):
    return {path: path.read_text(encoding="utf-8") for path in ROOT.joinpath(*parts).rglob("*.py")}


def test_removed_monolithic_modules_are_not_referenced():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.py"))
    assert "agentgate.contracts" not in sources
    assert "agentgate.evaluator.core" not in sources


def test_judge_does_not_depend_on_its_own_adapters():
    """The protocol owner must not import the integrations that implement it.

    Judge evaluators receive a client through EvaluationContext. Importing a
    concrete provider here would make the judge untestable offline and would
    invert the dependency the Target Protocol pattern establishes.
    """
    for path, source in sources_under("evaluator").items():
        assert "agentgate.integrations" not in source, path


def test_judge_never_reuses_the_target_agent_provider():
    """The system under test and the system judging it stay on separate paths."""
    for group in ("evaluator", "integrations"):
        for path, source in sources_under(group).items():
            assert "agentgate.demo" not in source, path


def test_model_providers_only_reach_evaluator_through_the_judge_protocol():
    for path, source in sources_under("integrations", "model_providers").items():
        for line in source.splitlines():
            if "agentgate.evaluator" in line:
                assert "agentgate.evaluator.judge" in line, f"{path}: {line}"
