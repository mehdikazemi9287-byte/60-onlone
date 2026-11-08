"""Credit provider port.

Designed now so that an organisation wallet, a 60online in-house credit line, a
bank, a leasing company or a fintech BNPL can each be plugged in later as a
separate implementation.

STATUS: the interface and the in-memory mock below are implemented and unit
tested. The employee-credit *purchase flow* (split credit + cash) is NOT
implemented in this commit -- see AUDIT_EVIDENCE.md.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum


class CreditOutcome(str, Enum):
    OK = "ok"
    INSUFFICIENT = "insufficient_credit"
    NOT_FOUND = "not_found"
    ALREADY_SETTLED = "already_settled"


@dataclass(frozen=True)
class CreditBalance:
    subject_ref: str
    limit_minor: int
    reserved_minor: int
    used_minor: int
    currency: str

    @property
    def available_minor(self) -> int:
        return self.limit_minor - self.reserved_minor - self.used_minor


@dataclass(frozen=True)
class CreditReservation:
    outcome: CreditOutcome
    reservation_ref: str
    amount_minor: int
    currency: str


class CreditProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def get_balance(self, subject_ref: str) -> CreditBalance: ...

    @abc.abstractmethod
    def reserve(self, subject_ref: str, amount_minor: int, idempotency_key: str) -> CreditReservation:
        """Hold credit without spending it. MUST be idempotent."""

    @abc.abstractmethod
    def capture(self, reservation_ref: str, idempotency_key: str) -> CreditOutcome:
        """Convert a hold into a spend. MUST be idempotent."""

    @abc.abstractmethod
    def release(self, reservation_ref: str, idempotency_key: str) -> CreditOutcome:
        """Cancel a hold. MUST be idempotent."""
