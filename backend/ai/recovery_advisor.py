"""
DunnFlow AI Recovery Advisor foundation.

Architecture:

    Application
        |
        v
    RecoveryAdvisor
        |
        v
    AI Provider
        |
        v
    OpenAI Responses API

Important safety rule:

    AI is advisory only.

The AI layer MUST NOT:
    - create payment attempts
    - execute Razorpay payments
    - mark invoices paid
    - bypass decision-engine guardrails
    - modify financial state

The deterministic recovery engine remains the authority
for financial actions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from backend.ai.prompts import (
    RECOVERY_ADVISOR_SYSTEM_PROMPT,
    RECOVERY_ADVISOR_USER_PROMPT,
)
from backend.ai.recovery_context import RecoveryContext
from backend.ai.historical_decision_context import get_historical_decision_context_dict

from dotenv import load_dotenv

load_dotenv()


DEFAULT_MODEL = "gpt-5.6-luna"


class AIConfigurationError(RuntimeError):
    """Raised when AI configuration is invalid."""


class AIProviderError(RuntimeError):
    """Raised when the AI provider cannot complete a request."""


@dataclass(frozen=True)
class AIRecoveryRecommendation:
    """
    Structured advisory recommendation produced by the AI layer.

    This object is advisory only. It does not authorize or execute
    any financial action.
    """

    priority_score: int
    urgency: str
    recommended_action: str
    confidence: float
    reason: str
    customer_strategy: str

    # Structured, bounded metadata describing whether historical evidence
    # influenced this advisory recommendation. This field is observational
    # only and never authorizes financial execution.
    learning_influence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority_score": self.priority_score,
            "urgency": self.urgency,
            "recommended_action": self.recommended_action,
            "confidence": self.confidence,
            "reason": self.reason,
            "customer_strategy": self.customer_strategy,
            "learning_influence": self.learning_influence,
        }


@dataclass(frozen=True)
class AIUnavailableResult:
    """
    Explicit safe fallback when AI cannot provide advice.

    This result contains no financial recommendation.
    The deterministic recovery policy must decide what happens next.
    """

    available: bool = False
    reason: str = "AI is unavailable. Deterministic policy must decide."
    fallback_required: bool = True


@dataclass(frozen=True)
class AIConfig:
    """
    Runtime configuration for the AI layer.
    """

    provider: str
    api_key: str | None
    model: str
    enabled: bool
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "AIConfig":
        provider = (
            os.getenv("DUNNFLOW_AI_PROVIDER", "openai")
            .strip()
            .lower()
        )

        if provider == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY")
            default_model = "openrouter/free"
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            default_model = DEFAULT_MODEL
        elif provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            default_model = "gemini-2.5-flash"
        else:
            raise AIConfigurationError(
                f"Unsupported AI provider: {provider}"
            )

        model = (
            os.getenv("DUNNFLOW_AI_MODEL")
            or default_model
        )

        enabled_raw = (
            os.getenv("DUNNFLOW_AI_ENABLED", "true")
            .strip()
            .lower()
        )

        enabled = enabled_raw in {
            "1",
            "true",
            "yes",
            "on",
        }

        timeout_raw = os.getenv(
            "DUNNFLOW_AI_TIMEOUT_SECONDS",
            "30",
        )

        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise AIConfigurationError(
                "DUNNFLOW_AI_TIMEOUT_SECONDS must be numeric."
            ) from exc

        if timeout_seconds <= 0:
            raise AIConfigurationError(
                "DUNNFLOW_AI_TIMEOUT_SECONDS must be greater than zero."
            )

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            enabled=enabled,
            timeout_seconds=timeout_seconds,
        )


class AIProvider:
    """
    Provider interface.

    Future providers can implement this interface without
    changing DunnFlow's business modules.
    """

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        raise NotImplementedError


class GeminiProvider(AIProvider):
    """
    Google Gemini provider.

    This class contains provider-specific code only.
    It does not know anything about invoices, payments,
    Razorpay, or recovery authorization.

    AI output remains advisory and is validated by the
    existing DunnFlow AI recommendation boundary.
    """

    def __init__(self, config: AIConfig):
        self.config = config

        if not config.api_key:
            raise AIConfigurationError(
                "GEMINI_API_KEY is not configured."
            )

        try:
            from google import genai
        except ImportError as exc:
            raise AIConfigurationError(
                "The 'google-genai' package is not installed."
            ) from exc

        self._genai = genai

        try:
            self._client = genai.Client(
                api_key=config.api_key
            )
        except Exception as exc:
            raise AIConfigurationError(
                f"Gemini client initialization failed: {exc}"
            ) from exc

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        try:
            response = self._client.models.generate_content(
                model=self.config.model,
                contents=user_prompt,
                config=__import__("google.genai", fromlist=["types"]).types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                ),
            )

        except Exception as exc:
            raise AIProviderError(
                f"Gemini request failed: {exc}"
            ) from exc

        output_text = getattr(
            response,
            "text",
            None,
        )

        if not output_text:
            raise AIProviderError(
                "Gemini returned an empty response."
            )

        return output_text




class OpenAIProvider(AIProvider):
    """
    OpenAI Responses API provider.

    This class contains provider-specific code only.
    It does not know anything about invoices, payments,
    Razorpay, or recovery authorization.
    """

    def __init__(self, config: AIConfig):
        self.config = config

        if not config.api_key:
            raise AIConfigurationError(
                "OPENAI_API_KEY is not configured."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIConfigurationError(
                "The 'openai' package is not installed."
            ) from exc

        self._client = OpenAI(
            api_key=config.api_key,
            timeout=config.timeout_seconds,
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        try:
            response = self._client.responses.create(
                model=self.config.model,
                instructions=system_prompt,
                input=user_prompt,
            )

        except Exception as exc:
            raise AIProviderError(
                f"OpenAI request failed: {exc}"
            ) from exc

        output_text = getattr(
            response,
            "output_text",
            None,
        )

        if not output_text:
            raise AIProviderError(
                "OpenAI returned an empty response."
            )

        return output_text


class OpenRouterProvider(AIProvider):
    """
    OpenRouter provider using its OpenAI-compatible API.

    This provider is advisory only. It cannot authorize,
    execute, or modify any financial operation.
    """

    def __init__(self, config: AIConfig):
        self.config = config

        if not config.api_key:
            raise AIConfigurationError(
                "OPENROUTER_API_KEY is not configured."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIConfigurationError(
                "The 'openai' package is not installed."
            ) from exc

        self._client = OpenAI(
            api_key=config.api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=config.timeout_seconds,
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        try:
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                response_format={
                    "type": "json_object"
                },
            )

        except Exception as exc:
            raise AIProviderError(
                f"OpenRouter request failed: {exc}"
            ) from exc

        choices = getattr(response, "choices", None)

        if not choices:
            raise AIProviderError(
                "OpenRouter returned no choices."
            )

        first_choice = choices[0]

        if first_choice is None:
            raise AIProviderError(
                "OpenRouter returned an empty choice."
            )

        message = getattr(first_choice, "message", None)

        if message is None:
            raise AIProviderError(
                "OpenRouter returned a choice without a message."
            )

        output_text = getattr(message, "content", None)

        if not output_text:
            raise AIProviderError(
                "OpenRouter returned an empty response."
            )

        return output_text


class RecoveryAdvisor:
    """
    High-level AI advisory service.

    This class is deliberately isolated from the financial
    execution system.

    At this foundation stage it provides:
        - configuration loading
        - provider selection
        - availability checking
        - safe provider invocation
        - structured JSON parsing helper

    Actual recovery reasoning will be implemented in Phase 4.2/4.3.
    """

    def __init__(
        self,
        *,
        config: AIConfig | None = None,
        provider: AIProvider | None = None,
    ):
        self.config = (
            config
            if config is not None
            else AIConfig.from_environment()
        )

        self.provider = provider

        if self.provider is None and self.config.enabled:
            if self.config.api_key:
                if self.config.provider == "openrouter":
                    self.provider = OpenRouterProvider(
                        self.config
                    )
                elif self.config.provider == "openai":
                    self.provider = OpenAIProvider(
                        self.config
                    )
                elif self.config.provider == "gemini":
                    self.provider = GeminiProvider(
                        self.config
                    )
                else:
                    raise AIConfigurationError(
                        f"Unsupported AI provider: {self.config.provider}"
                    )

    @property
    def available(self) -> bool:
        """
        Return whether a configured AI provider is available.
        """

        return (
            self.config.enabled
            and self.provider is not None
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Generate an AI response.

        Raises:
            AIConfigurationError:
                AI is not configured.

            AIProviderError:
                Provider request failed.
        """

        if not self.config.enabled:
            raise AIConfigurationError(
                "DunnFlow AI layer is disabled."
            )

        if self.provider is None:
            raise AIConfigurationError(
                "No AI provider is configured."
            )

        return self.provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def safe_generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str | AIUnavailableResult:
        """
        Safely request an AI response without allowing AI failure
        to break the deterministic recovery pipeline.

        If AI is disabled, unconfigured, unavailable, times out,
        rate-limits, or otherwise fails, return an explicit fallback.
        No financial action is selected by this fallback.
        """

        try:
            response = self.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            if not response or not response.strip():
                return AIUnavailableResult(
                    reason="AI unavailable: provider returned an empty response."
                )

            return response

        except (AIConfigurationError, AIProviderError) as exc:
            return AIUnavailableResult(
                reason=f"AI unavailable: {exc}"
            )

    def recommend(
        self,
        context: RecoveryContext,
    ) -> AIRecoveryRecommendation | AIUnavailableResult:
        """
        Generate an advisory recovery recommendation from a
        deterministic RecoveryContext.

        The returned recommendation does not authorize execution.
        Deterministic policy remains the final authority.
        """

        recovery_context = context.to_dict()

        # --------------------------------------------------------------
        # HISTORICAL DECISION CONTEXT
        #
        # Previous DunnFlow decisions and outcomes are supplied to the
        # AI advisor as read-only evidence.
        #
        # AI may use this evidence to improve its recommendation,
        # but deterministic policy remains the financial authority.
        # --------------------------------------------------------------
        try:
            invoice_id = context.invoice.get("invoice_id")

            if invoice_id:
                historical_context = (
                    get_historical_decision_context_dict(
                        str(invoice_id),
                        limit=20,
                    )
                )

                recovery_context["historical_decision_context"] = (
                    historical_context
                )

                # STEP 8C.4: customer behavioral evidence.
                #
                # Customer behavior is supplied by the historical decision
                # context and is advisory evidence only. It must never
                # override deterministic policy or guardrails.
                customer_behavior = historical_context.get(
                    "customer_behavior",
                    {},
                )

                if not isinstance(customer_behavior, dict):
                    customer_behavior = {
                        "available": False,
                        "behavior_signal": "insufficient_history",
                        "evidence_quality": "insufficient",
                        "sample_size": 0,
                        "advisory_only": True,
                        "provenance": {
                            "attribution": "customer_behavior_observation",
                            "episode_granularity": "invoice",
                            "financial_authority": "deterministic_policy",
                        },
                    }

                # Normalize the safety boundary even if the historical
                # context is unavailable or malformed.
                customer_behavior["advisory_only"] = True

                provenance = customer_behavior.get(
                    "provenance",
                    {},
                )

                if not isinstance(provenance, dict):
                    provenance = {}

                provenance["financial_authority"] = (
                    "deterministic_policy"
                )

                customer_behavior["provenance"] = provenance

                recovery_context["customer_behavior"] = (
                    customer_behavior
                )

            else:
                recovery_context["historical_decision_context"] = {
                    "learning_signal": "no_invoice_id"
                }

        except Exception as exc:
            # Historical intelligence is advisory only.
            # Failure to load it must NEVER break recovery.
            recovery_context["historical_decision_context"] = {
                "learning_signal": "historical_context_unavailable",
                "available": False,
                "error": str(exc),
            }


        user_prompt = RECOVERY_ADVISOR_USER_PROMPT.format(
            recovery_context=json.dumps(
                recovery_context,
                indent=2,
                default=str,
            )
        )

        response = self.safe_generate(
            system_prompt=RECOVERY_ADVISOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        if isinstance(response, AIUnavailableResult):
            return response

        try:
            parsed = self.parse_json_response(response)

            required_fields = {
                "priority_score",
                "urgency",
                "recommended_action",
                "confidence",
                "reason",
                "customer_strategy",
            }

            missing = required_fields - parsed.keys()

            if missing:
                raise AIProviderError(
                    "AI recommendation is missing required fields: "
                    + ", ".join(sorted(missing))
                )

            self._validate_recommendation(parsed)

            # ----------------------------------------------------------
            # BOUNDED LEARNING INFLUENCE
            #
            # The AI may indicate whether historical evidence influenced
            # its recommendation, but historical statistics themselves
            # are sourced from DunnFlow's supplied historical context.
            #
            # This prevents the model from inventing sample sizes,
            # recovery rates, or confidence values.
            # ----------------------------------------------------------

            historical_context = recovery_context.get(
                "historical_decision_context",
                {},
            )

            ai_learning = parsed.get(
                "learning_influence",
                {},
            )

            if not isinstance(ai_learning, dict):
                ai_learning = {}

            # ----------------------------------------------------------
            # The historical builder stores learning metadata inside the
            # nested `learning_signal` object. Normalize that structure
            # here while keeping all historical values trusted and bounded.
            # ----------------------------------------------------------

            historical_learning_signal = historical_context.get(
                "learning_signal",
                {},
            )

            if isinstance(historical_learning_signal, dict):
                historical_available = historical_learning_signal.get(
                    "available",
                    False,
                )
                historical_signal = historical_learning_signal.get(
                    "signal"
                )
                historical_sample_size = historical_learning_signal.get(
                    "sample_size"
                )
                historical_confidence = historical_learning_signal.get(
                    "confidence"
                )
                historical_recovery_rate = historical_learning_signal.get(
                    "historical_recovery_rate"
                )
            else:
                # Backward-compatible handling for an older flat/string
                # representation of historical learning context.
                historical_available = historical_context.get(
                    "available",
                    False,
                )
                historical_signal = (
                    historical_learning_signal
                    if isinstance(historical_learning_signal, str)
                    else None
                )
                historical_sample_size = historical_context.get(
                    "sample_size"
                )
                historical_confidence = historical_context.get(
                    "confidence"
                )
                historical_recovery_rate = historical_context.get(
                    "historical_recovery_rate"
                )

            # Historical availability is trusted only when explicitly
            # supplied by DunnFlow's historical context.
            historical_available = (
                historical_available
                if isinstance(historical_available, bool)
                else False
            )

            # The AI may report whether it used available historical
            # evidence, but it cannot manufacture historical evidence.
            ai_used = ai_learning.get("used")

            if isinstance(ai_used, bool):
                learning_used = (
                    ai_used
                    and historical_available
                    and isinstance(historical_signal, str)
                    and historical_signal not in {
                        "historical_context_unavailable",
                        "no_invoice_id",
                    }
                )
            else:
                learning_used = bool(
                    historical_available
                    and isinstance(historical_signal, str)
                    and historical_signal not in {
                        "historical_context_unavailable",
                        "no_invoice_id",
                    }
                )

            # ----------------------------------------------------------
            # STEP 7C: bounded historical AI-action feedback
            #
            # These values come from DunnFlow's read-only historical
            # context. The AI cannot manufacture or override them.
            #
            # They are advisory correlation evidence only.
            # Deterministic policy remains the financial authority.
            # ----------------------------------------------------------
            raw_ai_action_statistics = historical_context.get(
                "ai_action_statistics",
                {},
            )

            bounded_ai_action_feedback: dict[str, Any] = {}

            if isinstance(raw_ai_action_statistics, dict):
                for action_name, raw_stats in (
                    raw_ai_action_statistics.items()
                ):
                    if not isinstance(action_name, str):
                        continue

                    if not isinstance(raw_stats, dict):
                        continue

                    total_cases = raw_stats.get(
                        "total_cases"
                    )
                    recovered_cases = raw_stats.get(
                        "recovered_cases"
                    )
                    recovery_rate = raw_stats.get(
                        "recovery_rate"
                    )
                    agreement_cases = raw_stats.get(
                        "agreement_cases"
                    )
                    disagreement_cases = raw_stats.get(
                        "disagreement_cases"
                    )

                    evidence_quality = raw_stats.get(
                        "evidence_quality"
                    )

                    # Evidence quality is a deterministic historical
                    # evidence-depth classification. It is not AI
                    # confidence, statistical proof, or execution authority.
                    if evidence_quality not in {
                        "insufficient",
                        "limited",
                        "moderate",
                        "strong",
                    }:
                        continue

                    # Strict bounded integer validation.
                    if (
                        not isinstance(total_cases, int)
                        or isinstance(total_cases, bool)
                        or total_cases < 0
                    ):
                        continue

                    if (
                        not isinstance(recovered_cases, int)
                        or isinstance(recovered_cases, bool)
                        or recovered_cases < 0
                        or recovered_cases > total_cases
                    ):
                        continue

                    if (
                        not isinstance(agreement_cases, int)
                        or isinstance(agreement_cases, bool)
                        or agreement_cases < 0
                        or agreement_cases > total_cases
                    ):
                        continue

                    if (
                        not isinstance(disagreement_cases, int)
                        or isinstance(disagreement_cases, bool)
                        or disagreement_cases < 0
                        or disagreement_cases > total_cases
                    ):
                        continue

                    # Strict bounded recovery-rate validation.
                    if (
                        not isinstance(
                            recovery_rate,
                            (int, float),
                        )
                        or isinstance(recovery_rate, bool)
                        or not 0.0 <= float(recovery_rate) <= 1.0
                    ):
                        continue

                    attribution = raw_stats.get(
                        "attribution"
                    )

                    episode_granularity = raw_stats.get(
                        "episode_granularity"
                    )

                    financial_authority = raw_stats.get(
                        "financial_authority"
                    )

                    # Only accept statistics produced by the trusted
                    # Step 7B contract.
                    if attribution != "advisory_correlation":
                        continue

                    if episode_granularity != "invoice":
                        continue

                    if financial_authority != "deterministic_policy":
                        continue

                    bounded_ai_action_feedback[
                        action_name
                    ] = {
                        "total_cases": total_cases,
                        "recovered_cases": recovered_cases,
                        "recovery_rate": float(
                            recovery_rate
                        ),
                        "agreement_cases": agreement_cases,
                        "disagreement_cases": (
                            disagreement_cases
                        ),
                        "evidence_quality": evidence_quality,
                        "attribution": (
                            "advisory_correlation"
                        ),
                        "episode_granularity": "invoice",
                        "financial_authority": (
                            "deterministic_policy"
                        ),
                    }

            ai_action_feedback = {
                "available": bool(
                    bounded_ai_action_feedback
                ),
                "actions": bounded_ai_action_feedback,
                "advisory_only": True,
            }

            learning_influence = {
                "used": learning_used,
                "signal": (
                    historical_signal
                    if isinstance(historical_signal, str)
                    else "historical_context_unavailable"
                ),
                "sample_size": (
                    historical_sample_size
                    if isinstance(historical_sample_size, int)
                    and not isinstance(historical_sample_size, bool)
                    and historical_sample_size >= 0
                    else 0
                ),
                "confidence": (
                    historical_confidence
                    if isinstance(historical_confidence, (int, float))
                    and not isinstance(historical_confidence, bool)
                    and 0.0 <= float(historical_confidence) <= 1.0
                    else 0.0
                ),
                "historical_recovery_rate": (
                    historical_recovery_rate
                    if isinstance(
                        historical_recovery_rate,
                        (int, float),
                    )
                    and not isinstance(historical_recovery_rate, bool)
                    and 0.0 <= float(historical_recovery_rate) <= 1.0
                    else None
                ),
            }

            learning_influence = {
                **learning_influence,
                "ai_action_feedback": ai_action_feedback,
            }

            return AIRecoveryRecommendation(
                priority_score=parsed["priority_score"],
                urgency=parsed["urgency"],
                recommended_action=parsed["recommended_action"],
                confidence=parsed["confidence"],
                reason=parsed["reason"],
                customer_strategy=parsed["customer_strategy"],
                learning_influence=learning_influence,
            )

        except AIProviderError as exc:
            return AIUnavailableResult(
                reason=f"AI recommendation rejected: {exc}"
            )

    @staticmethod
    def _validate_recommendation(
        parsed: dict[str, Any],
    ) -> None:
        """
        Strictly validate an AI recovery recommendation.

        AI output is untrusted input. Validation happens before
        the recommendation becomes an AIRecoveryRecommendation.
        The deterministic recovery policy remains the authority.
        """

        priority_score = parsed["priority_score"]

        if (
            isinstance(priority_score, bool)
            or not isinstance(priority_score, int)
        ):
            raise AIProviderError(
                "AI priority_score must be an integer."
            )

        if not 0 <= priority_score <= 100:
            raise AIProviderError(
                "AI priority_score must be between 0 and 100."
            )

        urgency = parsed["urgency"]

        if not isinstance(urgency, str):
            raise AIProviderError(
                "AI urgency must be a string."
            )

        if urgency not in {
            "low",
            "normal",
            "high",
        }:
            raise AIProviderError(
                "AI urgency must be one of: low, normal, high."
            )

        recommended_action = parsed["recommended_action"]

        allowed_actions = {
            "retry_payment",
            "auto_retry_same_card",
            "customer_action",
            "payment_method_update",
            "manual_review",
            "no_action",
        }

        if not isinstance(recommended_action, str):
            raise AIProviderError(
                "AI recommended_action must be a string."
            )

        if recommended_action not in allowed_actions:
            raise AIProviderError(
                "AI recommended_action is not a valid DunnFlow action."
            )

        confidence = parsed["confidence"]

        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
        ):
            raise AIProviderError(
                "AI confidence must be numeric."
            )

        if not 0.0 <= confidence <= 1.0:
            raise AIProviderError(
                "AI confidence must be between 0.0 and 1.0."
            )

        reason = parsed["reason"]

        if (
            not isinstance(reason, str)
            or not reason.strip()
        ):
            raise AIProviderError(
                "AI reason must be a non-empty string."
            )

        customer_strategy = parsed["customer_strategy"]

        if (
            not isinstance(customer_strategy, str)
            or not customer_strategy.strip()
        ):
            raise AIProviderError(
                "AI customer_strategy must be a non-empty string."
            )


    @staticmethod
    def parse_json_response(
        response_text: str,
    ) -> dict[str, Any]:
        """
        Parse a JSON object returned by the AI provider.

        This is intentionally strict.

        We do not attempt to repair malformed financial
        recommendations at this layer.
        """

        if not response_text or not response_text.strip():
            raise AIProviderError(
                "AI returned an empty response."
            )

        try:
            parsed = json.loads(
                response_text
            )
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "AI response was not valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise AIProviderError(
                "AI response must be a JSON object."
            )

        return parsed


def get_ai_config() -> AIConfig:
    """
    Return the current DunnFlow AI configuration.
    """

    return AIConfig.from_environment()


def is_ai_available() -> bool:
    """
    Return whether a usable AI provider is configured.

    This function never raises for a missing API key.
    Missing configuration simply means AI is unavailable.
    """

    try:
        config = AIConfig.from_environment()

        if not config.enabled:
            return False

        return bool(config.api_key)

    except AIConfigurationError:
        return False


if __name__ == "__main__":
    config = get_ai_config()

    print("=" * 64)
    print("DUNNFLOW AI FOUNDATION")
    print("=" * 64)
    print(f"Enabled:       {config.enabled}")
    print(f"Model:         {config.model}")
    print(
        "API key set:   "
        f"{bool(config.api_key)}"
    )
    print(
        "AI available:  "
        f"{is_ai_available()}"
    )
    print("=" * 64)
