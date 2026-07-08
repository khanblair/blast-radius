from agent.decision.gate import confirm_decision, render_decision
from agent.decision.models import (
    ADDITIVE,
    AUTO_APPROVED,
    BREAKING,
    HUMAN_CONFIRMED,
    NO_MIGRATION_NEEDED,
    NOT_APPLICABLE,
    MigrationDecision,
    RejectedStrategy,
    StrategyOption,
)


def _breaking_decision(recommended="B"):
    options = [
        StrategyOption("A", "Direct patch", "Patch every consumer in one PR.", "Clean and atomic, but big-bang risk."),
        StrategyOption("B", "Bridge migration", "Compatibility view aliasing old -> new.", "Zero-downtime, more moving parts."),
        StrategyOption("C", "Defer & deprecate", "Recommend a deprecation cycle.", "Avoids risk, doesn't solve it today."),
    ]
    rejected = [RejectedStrategy(sid, f"{sid} rejected because reasons") for sid in ["A", "B", "C"] if sid != recommended]
    return MigrationDecision(
        decision_type=BREAKING,
        rationale="fct_revenue is dashboard-exposed",
        options=options,
        recommended_strategy=recommended,
        rejected=rejected,
    )


# --- render_decision ----------------------------------------------------------


def test_render_decision_includes_rationale_options_and_rejections():
    decision = _breaking_decision(recommended="B")
    text = render_decision(decision)

    assert "MIGRATION DECISION -- BREAKING" in text
    assert "fct_revenue is dashboard-exposed" in text
    assert "B. Bridge migration (RECOMMENDED)" in text
    assert "A. Direct patch" in text
    assert "C. Defer & deprecate" in text
    assert "REJECTED:" in text
    assert "A: A rejected because reasons" in text
    assert "C: C rejected because reasons" in text


def test_render_decision_handles_no_strategy_decision():
    decision = MigrationDecision(decision_type=NO_MIGRATION_NEEDED, rationale="0 affected assets.")
    text = render_decision(decision)

    assert "MIGRATION DECISION -- NO_MIGRATION_NEEDED" in text
    assert "0 affected assets." in text
    assert "OPTIONS:" not in text
    assert "REJECTED:" not in text


# --- confirm_decision: auto-approve (no stdin) --------------------------------


def test_auto_approve_confirms_recommended_strategy_without_prompting():
    decision = _breaking_decision(recommended="B")

    def _should_not_be_called(prompt):
        raise AssertionError("auto-approve must never call input_fn")

    confirmed = confirm_decision(decision, auto_approve=True, input_fn=_should_not_be_called)

    assert confirmed.confirmed_strategy == "B"
    assert confirmed.confirmation_mode == AUTO_APPROVED
    assert confirmed.human_confirmed is False  # auto-approve is a policy bypass, not a human sign-off


def test_auto_approve_on_no_strategy_decision_is_not_applicable():
    decision = MigrationDecision(decision_type=ADDITIVE, rationale="non-breaking by construction")

    confirmed = confirm_decision(decision, auto_approve=True, input_fn=lambda p: (_ for _ in ()).throw(AssertionError()))

    assert confirmed.confirmation_mode == NOT_APPLICABLE
    assert confirmed.human_confirmed is False
    assert confirmed.confirmed_strategy is None


# --- confirm_decision: interactive path (mocked input) ------------------------


def test_interactive_blank_input_accepts_recommendation():
    decision = _breaking_decision(recommended="B")

    confirmed = confirm_decision(decision, auto_approve=False, input_fn=lambda prompt: "")

    assert confirmed.confirmed_strategy == "B"
    assert confirmed.confirmation_mode == HUMAN_CONFIRMED
    assert confirmed.human_confirmed is True


def test_interactive_override_switches_to_chosen_strategy():
    decision = _breaking_decision(recommended="B")

    confirmed = confirm_decision(decision, auto_approve=False, input_fn=lambda prompt: "A")

    assert confirmed.confirmed_strategy == "A"
    assert confirmed.confirmation_mode == HUMAN_CONFIRMED
    assert confirmed.human_confirmed is True


def test_interactive_override_is_case_insensitive_and_trims_whitespace():
    decision = _breaking_decision(recommended="B")

    confirmed = confirm_decision(decision, auto_approve=False, input_fn=lambda prompt: "  c \n")

    assert confirmed.confirmed_strategy == "C"


def test_interactive_invalid_input_falls_back_to_recommendation():
    decision = _breaking_decision(recommended="B")

    confirmed = confirm_decision(decision, auto_approve=False, input_fn=lambda prompt: "not-a-strategy")

    assert confirmed.confirmed_strategy == "B"
    assert confirmed.human_confirmed is True  # still a real human response, just not a valid override


def test_interactive_prompt_mentions_recommended_and_valid_ids():
    decision = _breaking_decision(recommended="B")
    seen_prompts = []

    def _capture(prompt):
        seen_prompts.append(prompt)
        return ""

    confirm_decision(decision, auto_approve=False, input_fn=_capture)

    assert len(seen_prompts) == 1
    assert "B" in seen_prompts[0]
    assert "A" in seen_prompts[0] and "C" in seen_prompts[0]


def test_interactive_on_no_strategy_decision_never_prompts():
    decision = MigrationDecision(decision_type=NO_MIGRATION_NEEDED, rationale="0 affected assets.")

    def _should_not_be_called(prompt):
        raise AssertionError("no-strategy decisions must not prompt")

    confirmed = confirm_decision(decision, auto_approve=False, input_fn=_should_not_be_called)

    assert confirmed.confirmation_mode == NOT_APPLICABLE
    assert confirmed.human_confirmed is False
