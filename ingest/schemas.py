"""Extraction schemas, one per doc_type. Values stay strings here; validate.py parses and grounds them."""

from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["warranty", "insurance", "lease", "subscription", "bill", "other"]


class Grounded(BaseModel):
    """A date, amount or number copied from the document with its evidence."""

    value: str | None = Field(None, description="Dates as YYYY-MM-DD; amounts as a plain number like 14200.00")
    source_quote: str | None = Field(None, description="Exact text copied from the page that states the value")
    page: int | None = Field(None, description="1-based page number of source_quote")


class Clause(BaseModel):
    text: str = Field(description="Short spoken-style summary, e.g. 'liquid damage'")
    page: int
    quote: str = Field(description="Exact text copied from the page")


class CoveredPart(BaseModel):
    part: str = Field(description="Part name, e.g. 'motor'")
    term_years: int | None = Field(None, description="Coverage term for this part in years, if stated")
    page: int
    quote: str = Field(description="Exact text copied from the page")


class Classification(BaseModel):
    doc_type: DocType
    confidence: float = Field(ge=0, le=1)


class BaseExtraction(BaseModel):
    title: str = Field(description="Short descriptive title, e.g. 'LG Washing Machine Warranty Card'")
    vendor: str | None = Field(None, description="Brand, insurer, landlord or provider, short form, e.g. 'LG'")
    item_name: str | None = Field(None, description="Lowercase thing covered or billed, e.g. 'washing machine', 'car'")
    item_category: str | None = Field(None, description="e.g. appliance, vehicle, home, health, electronics")
    aliases: list[str] = Field(default_factory=list, description="Other names a person might say, e.g. 'fridge'")
    start_date: Grounded | None = None
    end_date: Grounded | None = None
    renewal_date: Grounded | None = None
    notice_days: Grounded | None = Field(None, description="Notice period in days")
    amount: Grounded | None = Field(None, description="Main price, premium, fee, rent or amount payable")
    currency: str | None = Field(None, description="ISO code, e.g. INR, USD")
    auto_renews: bool | None = None


class WarrantyExtraction(BaseExtraction):
    """start_date = coverage start (or purchase date), end_date = coverage end."""

    plan_name: str | None = Field(None, description="Only if not a plain warranty, e.g. 'accidental-damage plan'")
    product: str | None = None
    brand: str | None = None
    model: str | None = None
    serial: str | None = None
    claim_contact: str | None = None
    covered_parts: list[CoveredPart] = Field(default_factory=list)
    exclusions: list[Clause] = Field(default_factory=list)


class InsuranceExtraction(BaseExtraction):
    """start_date/end_date = period of insurance; renewal_date if a renewal date is stated."""

    policy_number: str | None = None
    deductible: Grounded | None = None
    claim_contact: str | None = None
    exclusions: list[Clause] = Field(default_factory=list)


class LeaseExtraction(BaseExtraction):
    """start_date/end_date = lease term; amount = monthly rent; notice_days = termination notice."""

    landlord: str | None = None
    property_address: str | None = None
    security_deposit: Grounded | None = None


class SubscriptionExtraction(BaseExtraction):
    """renewal_date = next renewal or billing date."""

    plan: str | None = None
    cancel_instructions: str | None = None


class BillExtraction(BaseExtraction):
    """start_date = bill date or period start, end_date = payment due date, amount = amount payable."""

    account_number: str | None = None


SCHEMAS: dict[str, type[BaseExtraction]] = {
    "warranty": WarrantyExtraction,
    "insurance": InsuranceExtraction,
    "lease": LeaseExtraction,
    "subscription": SubscriptionExtraction,
    "bill": BillExtraction,
    "other": BaseExtraction,
}
