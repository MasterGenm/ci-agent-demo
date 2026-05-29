from cs_mvp.prompts.families.base import DefaultPromptFamily


class QwenPromptFamily(DefaultPromptFamily):
    """Qwen prompt family.

    v1.5 keeps the default prompt text. A future version may add Chinese-first
    schema explanations and provider-specific JSON guidance here.
    """

    name = "qwen"
