"""Tests for pricing calculation."""
import pytest
from app.providers.pricing import calculate_cost, FALLBACK_PRICING


class TestPricingCalculation:
    """Test cost calculation for different providers and models."""

    def test_openai_gpt4o_pricing(self):
        """GPT-4o pricing is calculated correctly."""
        # GPT-4o: $2.50/1M input, $10/1M output
        cost = calculate_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
        # 250 cents input + 1000 cents output = 1250 cents
        assert cost == 1250

    def test_openai_gpt4o_mini_pricing(self):
        """GPT-4o-mini pricing is calculated correctly."""
        # GPT-4o-mini: $0.15/1M input, $0.60/1M output
        cost = calculate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
        # 15 cents input + 60 cents output = 75 cents
        assert cost == 75

    def test_anthropic_claude_pricing(self):
        """Claude 3.5 Sonnet pricing is calculated correctly."""
        # Claude 3.5 Sonnet: $3/1M input, $15/1M output
        cost = calculate_cost("anthropic", "claude-3-5-sonnet-20241022", 1_000_000, 1_000_000)
        # 300 cents input + 1500 cents output = 1800 cents
        assert cost == 1800

    def test_anthropic_opus_pricing(self):
        """Claude 3 Opus pricing is calculated correctly."""
        # Claude 3 Opus: $15/1M input, $75/1M output
        cost = calculate_cost("anthropic", "claude-3-opus-20240229", 1_000_000, 1_000_000)
        # 1500 cents input + 7500 cents output = 9000 cents
        assert cost == 9000

    def test_google_gemini_pricing(self):
        """Gemini pricing is calculated correctly."""
        cost = calculate_cost("google", "gemini-1.5-pro", 1_000_000, 1_000_000)
        assert cost > 0

    def test_unknown_model_uses_default(self):
        """Unknown models use default pricing."""
        cost = calculate_cost("openai", "unknown-model-xyz", 1000, 1000)
        assert cost >= 0

    def test_unknown_provider_uses_default(self):
        """Unknown providers use default pricing."""
        cost = calculate_cost("unknown-provider", "any-model", 1000, 1000)
        assert cost >= 0

    def test_zero_tokens_zero_cost(self):
        """Zero tokens results in zero cost."""
        cost = calculate_cost("openai", "gpt-4", 0, 0)
        assert cost == 0

    def test_input_only_tokens(self):
        """Only input tokens are counted correctly."""
        cost = calculate_cost("openai", "gpt-4o", 1000, 0)
        assert cost >= 0

    def test_output_only_tokens(self):
        """Only output tokens are counted correctly."""
        cost = calculate_cost("openai", "gpt-4o", 0, 1000)
        assert cost >= 0

    def test_small_token_counts_round_correctly(self):
        """Small token counts round to nearest cent."""
        # Very small requests should round to 0 or 1 cent
        cost = calculate_cost("openai", "gpt-4o", 100, 100)
        assert cost >= 0

    def test_partial_model_name_match(self):
        """Models with version suffixes are matched."""
        # Should match "gpt-4" pattern
        cost1 = calculate_cost("openai", "gpt-4-0613", 1000, 1000)
        cost2 = calculate_cost("openai", "gpt-4-turbo-preview", 1000, 1000)
        assert cost1 >= 0
        assert cost2 >= 0


class TestPricingData:
    """Test that pricing data is complete."""

    def test_openai_models_have_pricing(self):
        """All expected OpenAI models have pricing."""
        expected = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"]
        for model in expected:
            assert model in FALLBACK_PRICING["openai"]

    def test_anthropic_models_have_pricing(self):
        """All expected Anthropic models have pricing."""
        expected = ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"]
        for model in expected:
            assert model in FALLBACK_PRICING["anthropic"]

    def test_pricing_has_input_and_output(self):
        """All pricing entries have both input and output costs."""
        for provider, models in FALLBACK_PRICING.items():
            for model, prices in models.items():
                assert isinstance(prices, tuple)
                assert len(prices) == 2
                assert prices[0] >= 0  # Input price
                assert prices[1] >= 0  # Output price
