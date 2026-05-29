from cs_mvp.prompts.families.base import DefaultPromptFamily


class OpenAIPromptFamily(DefaultPromptFamily):
    """OpenAI prompt family.

    v1.5 keeps the default prompt text. A future version may split system/user
    responsibilities or add JSON-mode-specific guidance here.
    """

    name = "openai"
