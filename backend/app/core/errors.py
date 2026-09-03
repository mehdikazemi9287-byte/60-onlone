"""Typed API errors with stable machine-readable codes."""
from __future__ import annotations


class ApiError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}

    def to_dict(self) -> dict:
        body = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            body["error"]["details"] = self.details
        return body


class ValidationError(ApiError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(ApiError):
    status_code = 401
    code = "authentication_required"


class PermissionError_(ApiError):
    status_code = 403
    code = "permission_denied"


class NotFoundError(ApiError):
    status_code = 404
    code = "not_found"


class ConflictError(ApiError):
    status_code = 409
    code = "conflict"


class OutOfStockError(ConflictError):
    code = "out_of_stock"


class PaymentFailedError(ApiError):
    status_code = 402
    code = "payment_failed"


class FulfillmentUnavailableError(ApiError):
    """Raised when no valid supplier can be found for one or more cart items.

    This error MUST be raised BEFORE any PSP charge is attempted.  Checkout
    must treat it the same way as a validation failure: no money moves.
    """
    status_code = 422
    code = "fulfillment_unavailable"
