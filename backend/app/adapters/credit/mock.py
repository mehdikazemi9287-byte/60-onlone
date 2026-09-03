from __future__ import annotations

import hashlib
import threading

from app.adapters.credit.base import (
    CreditBalance,
    CreditOutcome,
    CreditProvider,
    CreditReservation,
)


class MockCreditProvider(CreditProvider):
    """In-memory credit line, sufficient for demos and adapter-level tests."""

    name = "mock"

    def __init__(self, currency: str = "IRR") -> None:
        self._lock = threading.Lock()
        self._currency = currency
        self._limits: dict[str, int] = {}
        self._reserved: dict[str, int] = {}
        self._used: dict[str, int] = {}
        self._reservations: dict[str, tuple[str, int, str]] = {}  # ref -> (subject, amount, state)
        self._idem: dict[str, str] = {}

    # -- test/demo helper --------------------------------------------------
    def set_limit(self, subject_ref: str, limit_minor: int) -> None:
        with self._lock:
            self._limits[subject_ref] = limit_minor
            self._reserved.setdefault(subject_ref, 0)
            self._used.setdefault(subject_ref, 0)

    @staticmethod
    def _ref(key: str) -> str:
        return "cr_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]

    def get_balance(self, subject_ref: str) -> CreditBalance:
        with self._lock:
            return CreditBalance(
                subject_ref=subject_ref,
                limit_minor=self._limits.get(subject_ref, 0),
                reserved_minor=self._reserved.get(subject_ref, 0),
                used_minor=self._used.get(subject_ref, 0),
                currency=self._currency,
            )

    def reserve(self, subject_ref: str, amount_minor: int, idempotency_key: str) -> CreditReservation:
        with self._lock:
            existing = self._idem.get(idempotency_key)
            if existing is not None:
                _, amount, _ = self._reservations[existing]
                return CreditReservation(CreditOutcome.OK, existing, amount, self._currency)
            limit = self._limits.get(subject_ref, 0)
            reserved = self._reserved.get(subject_ref, 0)
            used = self._used.get(subject_ref, 0)
            if amount_minor <= 0 or limit - reserved - used < amount_minor:
                return CreditReservation(
                    CreditOutcome.INSUFFICIENT, "", amount_minor, self._currency
                )
            ref = self._ref(idempotency_key)
            self._reserved[subject_ref] = reserved + amount_minor
            self._reservations[ref] = (subject_ref, amount_minor, "held")
            self._idem[idempotency_key] = ref
            return CreditReservation(CreditOutcome.OK, ref, amount_minor, self._currency)

    def capture(self, reservation_ref: str, idempotency_key: str) -> CreditOutcome:
        with self._lock:
            entry = self._reservations.get(reservation_ref)
            if entry is None:
                return CreditOutcome.NOT_FOUND
            subject, amount, state = entry
            if state == "captured":
                return CreditOutcome.OK
            if state != "held":
                return CreditOutcome.ALREADY_SETTLED
            self._reserved[subject] -= amount
            self._used[subject] = self._used.get(subject, 0) + amount
            self._reservations[reservation_ref] = (subject, amount, "captured")
            return CreditOutcome.OK

    def release(self, reservation_ref: str, idempotency_key: str) -> CreditOutcome:
        with self._lock:
            entry = self._reservations.get(reservation_ref)
            if entry is None:
                return CreditOutcome.NOT_FOUND
            subject, amount, state = entry
            if state == "released":
                return CreditOutcome.OK
            if state != "held":
                return CreditOutcome.ALREADY_SETTLED
            self._reserved[subject] -= amount
            self._reservations[reservation_ref] = (subject, amount, "released")
            return CreditOutcome.OK
