"""
Provider model configurations.

Each provider has a list of available models with display names.
This is used by the chat interface to show available models.
"""

# Models available for each provider
# Format: {provider: [(model_id, display_name), ...]}
PROVIDER_MODELS = {
    "openai": [
        ("gpt-4o", "GPT-4o"),
        ("gpt-4o-mini", "GPT-4o Mini"),
        ("gpt-4-turbo", "GPT-4 Turbo"),
        ("o1", "o1"),
        ("o1-mini", "o1 Mini"),
        ("o3-mini", "o3 Mini"),
    ],
    "anthropic": [
        ("claude-sonnet-4", "Claude Sonnet 4"),
        ("claude-opus-4", "Claude Opus 4"),
        ("claude-3-5-sonnet-latest", "Claude 3.5 Sonnet"),
        ("claude-3-5-haiku-20241022", "Claude 3.5 Haiku"),
        ("claude-3-opus-20240229", "Claude 3 Opus"),
    ],
    "google": [
        ("gemini-2.5-pro", "Gemini 2.5 Pro"),
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-1.5-pro", "Gemini 1.5 Pro"),
        ("gemini-1.5-flash", "Gemini 1.5 Flash"),
    ],
    "perplexity": [
        ("llama-3.1-sonar-small-128k-online", "Sonar Small (Online)"),
        ("llama-3.1-sonar-large-128k-online", "Sonar Large (Online)"),
        ("llama-3.1-sonar-huge-128k-online", "Sonar Huge (Online)"),
    ],
    "openrouter": [
        ("openai/gpt-4o", "GPT-4o (via OpenRouter)"),
        ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet (via OpenRouter)"),
        ("google/gemini-pro-1.5", "Gemini 1.5 Pro (via OpenRouter)"),
        ("meta-llama/llama-3.1-405b-instruct", "Llama 3.1 405B"),
    ],
}

# Provider display names
PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "perplexity": "Perplexity",
    "openrouter": "OpenRouter",
}


def get_models_for_providers(provider_list: list[str]) -> dict:
    """
    Get available models for a list of providers.

    Args:
        provider_list: List of provider names (e.g., ["openai", "anthropic"])

    Returns:
        Dict of {provider: {"name": display_name, "models": [(id, name), ...]}}
    """
    result = {}
    for provider in provider_list:
        if provider in PROVIDER_MODELS:
            result[provider] = {
                "name": PROVIDER_NAMES.get(provider, provider.title()),
                "models": PROVIDER_MODELS[provider]
            }
    return result
