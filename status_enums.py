"""Centralised status constants for invoices, quotes, and projects.

Import these everywhere instead of spelling out string literals inline.
"""


class InvoiceStatus:
    UNPAID = "Unpaid"
    PAID = "Paid"
    OVERDUE = "Overdue"
    PENDING = "Pending"
    PARTIALLY_PAID = "Partially Paid"

    ALL = (UNPAID, PAID, OVERDUE, PENDING, PARTIALLY_PAID)

    # Statuses that mean money is still owed
    OPEN = frozenset({UNPAID, OVERDUE, PENDING, PARTIALLY_PAID})

    # Statuses that block auto-overdue marking
    CLOSED = frozenset({PAID})


class QuoteStatus:
    # Lifecycle statuses (active pipeline)
    DRAFT      = "Draft"
    SENT       = "Sent"
    IN_REVIEW  = "In Review"
    APPROVED   = "Approved"
    ON_HOLD    = "On Hold"

    # Closed statuses
    COMPLETED  = "Completed"
    CONVERTED  = "Converted"
    REJECTED   = "Rejected"
    EXPIRED    = "Expired"
    CANCELLED  = "Cancelled"

    # Legacy aliases kept for existing data
    CANCEL     = "Cancel"
    NOT_STARTED = "Not Started"

    ALL = (DRAFT, SENT, IN_REVIEW, APPROVED, ON_HOLD,
           COMPLETED, CONVERTED, REJECTED, EXPIRED, CANCELLED)

    # Statuses excluded from "Active Quotes" count
    INACTIVE = frozenset({
        COMPLETED, CONVERTED, REJECTED, EXPIRED, CANCELLED,
        ON_HOLD, CANCEL,  # legacy
    })

    # Quotes older than this many days without a status change are considered stale
    STALE_DAYS = 30


class ProjectStatus:
    ACTIVE = "Active"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    CANCEL = "Cancel"         # legacy spelling

    ALL = (ACTIVE, IN_PROGRESS, COMPLETED, CANCELLED, CANCEL)

    INACTIVE = frozenset({COMPLETED, CANCELLED, CANCEL})
