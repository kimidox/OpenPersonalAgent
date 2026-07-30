from dataclasses import dataclass


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def __repr__(self) -> str:
        return f"TokenUsage(prompt={self.prompt_tokens}, completion={self.completion_tokens}, total={self.total_tokens})"

    @classmethod
    def empty(cls) -> "TokenUsage":
        """构造一个所有 token 计数为零的 TokenUsage 实例。

        Returns:
            TokenUsage: prompt_tokens、completion_tokens、total_tokens 均为 0 的实例。
        """
        return cls(prompt_tokens=0, completion_tokens=0, total_tokens=0)
