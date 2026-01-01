"""
LLM pricing data for cost calculation.
Prices are in cents per 1M tokens.

This module provides:
1. Static fallback pricing (for when no DB pricing exists)
2. Dynamic pricing from ModelPricing table (date-aware)
3. Comprehensive cost calculation supporting all token types
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PricingInfo:
    """
    Complete pricing information for a model.
    All prices are in cents per 1M tokens.
    """
    # Core pricing
    input_price_per_1m: float = 0
    output_price_per_1m: float = 0

    # Cache pricing (multipliers of input price)
    cache_read_multiplier: Optional[float] = None   # e.g., 0.1 = 90% discount
    cache_write_multiplier: Optional[float] = None  # e.g., 1.25 = 25% premium

    # Reasoning tokens (NULL = use output price)
    reasoning_price_per_1m: Optional[float] = None

    # Multimodal pricing
    image_input_price_per_1m: Optional[float] = None
    audio_input_price_per_1m: Optional[float] = None
    audio_output_price_per_1m: Optional[float] = None
    video_input_price_per_1m: Optional[float] = None

    # Modifiers
    batch_discount: float = 0.5  # 50% discount for batch API
    long_context_threshold: Optional[int] = None
    long_context_multiplier: Optional[float] = None

    # Fixed costs
    base_request_cost_cents: float = 0

    def get_cache_read_price(self) -> float:
        """Get cache read price per 1M tokens."""
        if self.cache_read_multiplier is not None:
            return self.input_price_per_1m * self.cache_read_multiplier
        # Default to 50% of input if no multiplier specified
        return self.input_price_per_1m * 0.5

    def get_cache_write_price(self) -> float:
        """Get cache write price per 1M tokens."""
        if self.cache_write_multiplier is not None:
            return self.input_price_per_1m * self.cache_write_multiplier
        # Default to regular input price if no multiplier
        return self.input_price_per_1m

    def get_reasoning_price(self) -> float:
        """Get reasoning token price per 1M tokens."""
        if self.reasoning_price_per_1m is not None:
            return self.reasoning_price_per_1m
        # Default to output price
        return self.output_price_per_1m


# Static fallback pricing as of late 2024 - used when no DB pricing exists
# Format: (input_price_per_1M, output_price_per_1M) in cents
FALLBACK_PRICING = {
    "openai": {
        "gpt-4o": (250, 1000),
        "gpt-4o-mini": (15, 60),
        "gpt-4-turbo": (1000, 3000),
        "gpt-4": (3000, 6000),
        "gpt-3.5-turbo": (50, 150),
        "o1-preview": (1500, 6000),
        "o1-mini": (300, 1200),
        "o1": (1500, 6000),
        "o3-mini": (110, 440),
    },
    "anthropic": {
        "claude-3-5-sonnet-20241022": (300, 1500),
        "claude-3-5-sonnet-latest": (300, 1500),
        "claude-sonnet-4": (300, 1500),
        "claude-opus-4": (1500, 7500),
        "claude-3-opus-20240229": (1500, 7500),
        "claude-3-sonnet-20240229": (300, 1500),
        "claude-3-haiku-20240307": (25, 125),
        "claude-3-5-haiku-20241022": (100, 500),
    },
    "google": {
        "gemini-1.5-pro": (125, 500),
        "gemini-1.5-flash": (7.5, 30),
        "gemini-1.0-pro": (50, 150),
        "gemini-2.0-flash-exp": (0, 0),
        "gemini-2.5-pro": (125, 1000),
        "gemini-2.5-flash": (15, 60),
    },
    "perplexity": {
        "llama-3.1-sonar-small-128k-online": (20, 20),
        "llama-3.1-sonar-large-128k-online": (100, 100),
        "llama-3.1-sonar-huge-128k-online": (500, 500),
    },
    "openrouter": {
        # OpenRouter has dynamic pricing, these are approximations
        "default": (100, 100),
    },
    "v0": {
        # v0 pricing TBD - using placeholder values
        "v0-1.5-md": (0, 0),
        "v0-1.5-lg": (0, 0),
    },
}

# Default pricing for unknown models (conservative estimate)
DEFAULT_PRICING = (100, 100)


def get_fallback_pricing(provider: str, model: str) -> Tuple[float, float]:
    """Get pricing from static fallback data."""
    provider_pricing = FALLBACK_PRICING.get(provider, {})

    # Try exact model match
    if model in provider_pricing:
        return provider_pricing[model]

    # Try partial match (model names sometimes have version suffixes)
    for model_pattern, prices in provider_pricing.items():
        if model.startswith(model_pattern) or model_pattern in model:
            return prices

    return DEFAULT_PRICING


def get_fallback_pricing_info(provider: str, model: str) -> PricingInfo:
    """Get full PricingInfo from fallback data with sensible defaults."""
    input_price, output_price = get_fallback_pricing(provider, model)

    # Set sensible defaults based on provider
    cache_read_mult = None
    cache_write_mult = None

    if provider == "openai":
        cache_read_mult = 0.5  # OpenAI: 50% discount on cached tokens
    elif provider == "anthropic":
        cache_read_mult = 0.1  # Anthropic: 90% discount on cache reads
        cache_write_mult = 1.25  # Anthropic: 25% premium on cache writes (5-min cache)
    elif provider == "google":
        cache_read_mult = 0.25  # Google: 75% discount on cached tokens

    return PricingInfo(
        input_price_per_1m=input_price,
        output_price_per_1m=output_price,
        cache_read_multiplier=cache_read_mult,
        cache_write_multiplier=cache_write_mult,
    )


async def get_pricing_for_date(
    db: AsyncSession,
    provider: str,
    model: str,
    for_date: date
) -> PricingInfo:
    """
    Get complete pricing info for a model on a specific date from the database.
    Falls back to static pricing if no DB entry exists.
    """
    from app.models import ModelPricing

    # Find the most recent pricing that was effective on or before the given date
    result = await db.execute(
        select(ModelPricing)
        .where(
            ModelPricing.provider == provider,
            ModelPricing.model == model,
            ModelPricing.effective_date <= for_date
        )
        .order_by(ModelPricing.effective_date.desc())
        .limit(1)
    )
    pricing = result.scalar_one_or_none()

    if pricing:
        return PricingInfo(
            input_price_per_1m=pricing.input_price_per_1m,
            output_price_per_1m=pricing.output_price_per_1m,
            cache_read_multiplier=pricing.cache_read_multiplier,
            cache_write_multiplier=pricing.cache_write_multiplier,
            reasoning_price_per_1m=pricing.reasoning_price_per_1m,
            image_input_price_per_1m=pricing.image_input_price_per_1m,
            audio_input_price_per_1m=pricing.audio_input_price_per_1m,
            audio_output_price_per_1m=pricing.audio_output_price_per_1m,
            video_input_price_per_1m=pricing.video_input_price_per_1m,
            batch_discount=pricing.batch_discount or 0.5,
            long_context_threshold=pricing.long_context_threshold,
            long_context_multiplier=pricing.long_context_multiplier,
            base_request_cost_cents=pricing.base_request_cost_cents or 0,
        )

    # Try partial model match in DB
    result = await db.execute(
        select(ModelPricing)
        .where(
            ModelPricing.provider == provider,
            ModelPricing.effective_date <= for_date
        )
        .order_by(ModelPricing.effective_date.desc())
    )
    all_pricing = result.scalars().all()

    for p in all_pricing:
        if model.startswith(p.model) or p.model in model:
            return PricingInfo(
                input_price_per_1m=p.input_price_per_1m,
                output_price_per_1m=p.output_price_per_1m,
                cache_read_multiplier=p.cache_read_multiplier,
                cache_write_multiplier=p.cache_write_multiplier,
                reasoning_price_per_1m=p.reasoning_price_per_1m,
                image_input_price_per_1m=p.image_input_price_per_1m,
                audio_input_price_per_1m=p.audio_input_price_per_1m,
                audio_output_price_per_1m=p.audio_output_price_per_1m,
                video_input_price_per_1m=p.video_input_price_per_1m,
                batch_discount=p.batch_discount or 0.5,
                long_context_threshold=p.long_context_threshold,
                long_context_multiplier=p.long_context_multiplier,
                base_request_cost_cents=p.base_request_cost_cents or 0,
            )

    # Fall back to static pricing
    return get_fallback_pricing_info(provider, model)


def calculate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> int:
    """
    Calculate cost in cents for a request using static fallback pricing.
    This is a synchronous version for simple cases (just input/output tokens).

    Args:
        provider: The LLM provider (openai, anthropic, etc.)
        model: The model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Cost in cents (integer)
    """
    input_price, output_price = get_fallback_pricing(provider, model)

    # Calculate cost (prices are per 1M tokens)
    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price

    # Return as cents, rounded to nearest cent
    total_cents = round(input_cost + output_cost)
    return max(total_cents, 0)


@dataclass
class UsageTokens:
    """Token counts from a usage log, used for cost calculation."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    image_input_tokens: int = 0
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0
    video_input_tokens: int = 0
    is_batch: bool = False
    total_context_tokens: Optional[int] = None


def calculate_full_cost(pricing: PricingInfo, tokens: UsageTokens) -> float:
    """
    Calculate total cost in cents given pricing info and token counts.

    This handles all token types and pricing modifiers:
    - Standard input/output
    - Cache read/write
    - Reasoning tokens
    - Multimodal (image, audio, video)
    - Batch discount
    - Long context multiplier

    Returns:
        Cost in cents (float, for precision in aggregation)
    """
    # Start with base request cost
    total_cost = pricing.base_request_cost_cents

    # Check if long context pricing applies
    context_multiplier = 1.0
    if (pricing.long_context_threshold and
        pricing.long_context_multiplier and
        tokens.total_context_tokens and
        tokens.total_context_tokens > pricing.long_context_threshold):
        context_multiplier = pricing.long_context_multiplier

    # Apply batch discount if applicable
    batch_multiplier = pricing.batch_discount if tokens.is_batch else 1.0

    # Helper to calculate cost for a token type
    def token_cost(count: int, price_per_1m: float) -> float:
        if count <= 0 or price_per_1m <= 0:
            return 0
        return (count / 1_000_000) * price_per_1m * context_multiplier * batch_multiplier

    # Standard input tokens
    total_cost += token_cost(tokens.input_tokens, pricing.input_price_per_1m)

    # Standard output tokens
    total_cost += token_cost(tokens.output_tokens, pricing.output_price_per_1m)

    # Cache read tokens (discounted)
    cache_read_price = pricing.get_cache_read_price()
    total_cost += token_cost(tokens.cache_read_tokens, cache_read_price)

    # Cache write tokens (may have premium)
    cache_write_price = pricing.get_cache_write_price()
    total_cost += token_cost(tokens.cache_write_tokens, cache_write_price)

    # Reasoning tokens
    reasoning_price = pricing.get_reasoning_price()
    total_cost += token_cost(tokens.reasoning_tokens, reasoning_price)

    # Multimodal tokens
    if pricing.image_input_price_per_1m:
        total_cost += token_cost(tokens.image_input_tokens, pricing.image_input_price_per_1m)

    if pricing.audio_input_price_per_1m:
        total_cost += token_cost(tokens.audio_input_tokens, pricing.audio_input_price_per_1m)

    if pricing.audio_output_price_per_1m:
        total_cost += token_cost(tokens.audio_output_tokens, pricing.audio_output_price_per_1m)

    if pricing.video_input_price_per_1m:
        total_cost += token_cost(tokens.video_input_tokens, pricing.video_input_price_per_1m)

    return total_cost


def calculate_input_output_costs(pricing: PricingInfo, tokens: UsageTokens) -> tuple[float, float]:
    """
    Calculate input and output costs separately in cents.

    Input cost includes: input tokens, cache read/write, image/audio/video input
    Output cost includes: output tokens, reasoning tokens, audio output

    Returns:
        Tuple of (input_cost_cents, output_cost_cents)
    """
    # Check if long context pricing applies
    context_multiplier = 1.0
    if (pricing.long_context_threshold and
        pricing.long_context_multiplier and
        tokens.total_context_tokens and
        tokens.total_context_tokens > pricing.long_context_threshold):
        context_multiplier = pricing.long_context_multiplier

    # Apply batch discount if applicable
    batch_multiplier = pricing.batch_discount if tokens.is_batch else 1.0

    # Helper to calculate cost for a token type
    def token_cost(count: int, price_per_1m: float) -> float:
        if count <= 0 or price_per_1m <= 0:
            return 0
        return (count / 1_000_000) * price_per_1m * context_multiplier * batch_multiplier

    # Input-side costs
    input_cost = pricing.base_request_cost_cents  # Base cost goes to input
    input_cost += token_cost(tokens.input_tokens, pricing.input_price_per_1m)
    input_cost += token_cost(tokens.cache_read_tokens, pricing.get_cache_read_price())
    input_cost += token_cost(tokens.cache_write_tokens, pricing.get_cache_write_price())
    if pricing.image_input_price_per_1m:
        input_cost += token_cost(tokens.image_input_tokens, pricing.image_input_price_per_1m)
    if pricing.audio_input_price_per_1m:
        input_cost += token_cost(tokens.audio_input_tokens, pricing.audio_input_price_per_1m)
    if pricing.video_input_price_per_1m:
        input_cost += token_cost(tokens.video_input_tokens, pricing.video_input_price_per_1m)

    # Output-side costs
    output_cost = token_cost(tokens.output_tokens, pricing.output_price_per_1m)
    output_cost += token_cost(tokens.reasoning_tokens, pricing.get_reasoning_price())
    if pricing.audio_output_price_per_1m:
        output_cost += token_cost(tokens.audio_output_tokens, pricing.audio_output_price_per_1m)

    return input_cost, output_cost


async def calculate_cost_for_date(
    db: AsyncSession,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    for_date: date
) -> int:
    """
    Calculate cost in cents using pricing effective on a specific date.
    Simple version that only handles input/output tokens.

    Args:
        db: Database session
        provider: The LLM provider
        model: The model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        for_date: The date to use for pricing lookup

    Returns:
        Cost in cents (integer)
    """
    pricing = await get_pricing_for_date(db, provider, model, for_date)

    tokens = UsageTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    return round(calculate_full_cost(pricing, tokens))


async def calculate_usage_log_cost(
    db: AsyncSession,
    provider: str,
    model: str,
    for_date: date,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    image_input_tokens: int = 0,
    audio_input_tokens: int = 0,
    audio_output_tokens: int = 0,
    video_input_tokens: int = 0,
    is_batch: bool = False,
    total_context_tokens: Optional[int] = None,
) -> float:
    """
    Calculate the full cost for a usage log entry.

    This is the primary function to use when calculating costs for display.
    It looks up pricing from the database for the given date and calculates
    cost based on all token types.

    Returns:
        Cost in cents (float for precision)
    """
    pricing = await get_pricing_for_date(db, provider, model, for_date)

    tokens = UsageTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        image_input_tokens=image_input_tokens,
        audio_input_tokens=audio_input_tokens,
        audio_output_tokens=audio_output_tokens,
        video_input_tokens=video_input_tokens,
        is_batch=is_batch,
        total_context_tokens=total_context_tokens,
    )

    return calculate_full_cost(pricing, tokens)
