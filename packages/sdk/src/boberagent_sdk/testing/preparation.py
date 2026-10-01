"""Side-effect-free typed E1 preparation test double."""

from boberagent_contracts import RuntimePreparationInput, RuntimePreparationReceipt

from boberagent_sdk.exceptions import InputError


class FakeRuntimePreparationService:
    """Return only explicitly configured receipts; create no Node Resource or workspace."""

    def __init__(self) -> None:
        self._expected: list[tuple[RuntimePreparationInput, RuntimePreparationReceipt]] = []
        self.calls: list[RuntimePreparationInput] = []

    def expect(self, request: RuntimePreparationInput, receipt: RuntimePreparationReceipt) -> None:
        if (
            receipt.preparation_ref != request.permit.spec.preparation_ref
            or receipt.run_ref != request.permit.run_ref
            or receipt.permit_ref != request.permit.permit_ref
        ):
            raise ValueError("fake receipt must match the typed preparation request")
        self._expected.append(
            (
                RuntimePreparationInput.model_validate_json(request.model_dump_json()),
                RuntimePreparationReceipt.model_validate_json(receipt.model_dump_json()),
            )
        )

    async def prepare_runtime(self, request: RuntimePreparationInput) -> RuntimePreparationReceipt:
        validated = RuntimePreparationInput.model_validate_json(request.model_dump_json())
        self.calls.append(validated)
        if not self._expected or self._expected[0][0] != validated:
            raise InputError("unexpected typed runtime preparation request")
        _, receipt = self._expected.pop(0)
        return RuntimePreparationReceipt.model_validate_json(receipt.model_dump_json())

    def assert_expectations_met(self) -> None:
        if self._expected:
            raise AssertionError("expected runtime preparation requests were not observed")
