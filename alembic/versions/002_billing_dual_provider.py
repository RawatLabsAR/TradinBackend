"""Dual-provider billing schema — subscriptions + billing_events."""

revision = "002_billing_dual_provider"
down_revision = "001_saas_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tables are created via SQLAlchemy create_all + ensure_billing_columns().
    # This revision documents the billing schema for Alembic-managed deploys.
    pass


def downgrade() -> None:
    pass
