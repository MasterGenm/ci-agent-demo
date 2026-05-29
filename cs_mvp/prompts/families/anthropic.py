from cs_mvp.prompts.families.base import DefaultPromptFamily


class AnthropicPromptFamily(DefaultPromptFamily):
    """Anthropic prompt family.

    v1.5 keeps the default prompt text. A future version may add XML-style
    delimiters and longer evidence-window conventions here.
    """

    name = "anthropic"
