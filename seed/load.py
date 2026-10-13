"""Insert synthetic seed documents with hand-written fields. Re-running replaces the demo user's data.

Run: uv run python -m seed.load

Some dates are relative to today so the deadline radar always has something on it.
All names, numbers and policies are synthetic.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete

from server.config import DEMO_USER_ID
from server.db import Chunk, Document, Reminder, Session, init_db


def _fmt(d: date) -> str:
    return d.strftime("%d %B %Y")


def seed_documents(today: date) -> list[dict[str, Any]]:
    car_start, car_renew = today - timedelta(days=345), today + timedelta(days=20)
    sub_renew = today + timedelta(days=12)
    lease_start, lease_end = today - timedelta(days=240), today + timedelta(days=125)
    bill_due = today - timedelta(days=3)

    return [
        {
            "doc": dict(
                s3_key="seed/warranty_lg.pdf", doc_type="warranty", title="LG Front Load Washing Machine Warranty Card", vendor="LG",
                item_name="washing machine", item_category="appliance",
                start_date=date(2025, 3, 15), end_date=date(2027, 3, 14),
                fields={
                    "product": "Front Load Washing Machine", "brand": "LG", "model": "FHM1409BDL",
                    "serial": "SYN-405KW-0193", "purchase_date": "2025-03-15",
                    "claim_contact": "LG Service, 1800-000-0001",
                    "covered_parts": [
                        {"part": "motor", "term_years": 10, "page": 1,
                         "quote": "Inverter Direct Drive motor: 10 years from date of purchase"},
                        {"part": "all other parts", "term_years": 2, "page": 1,
                         "quote": "All other parts and labour: 2 years from date of purchase"},
                    ],
                    "exclusions": [
                        {"text": "damage from improper installation", "page": 1,
                         "quote": "Damage from improper installation or voltage fluctuation is not covered"},
                    ],
                    "evidence": {
                        "start_date": {"page": 1, "quote": "Date of purchase: 15 March 2025"},
                        "end_date": {"page": 1, "quote": "Warranty valid until: 14 March 2027"},
                    },
                },
            ),
            "pages": [
                "LG Electronics Warranty Card. Product: Front Load Washing Machine, model FHM1409BDL, "
                "serial SYN-405KW-0193. Date of purchase: 15 March 2025. Warranty valid until: 14 March 2027. "
                "Inverter Direct Drive motor: 10 years from date of purchase. "
                "All other parts and labour: 2 years from date of purchase. "
                "Damage from improper installation or voltage fluctuation is not covered. "
                "To claim, call LG Service on 1800-000-0001 with this card and your invoice."
            ],
        },
        {
            "doc": dict(
                s3_key="seed/warranty_samsung.pdf", doc_type="warranty", title="Samsung Refrigerator Extended Warranty", vendor="Samsung",
                item_name="refrigerator", item_category="appliance",
                start_date=date(2024, 6, 1), end_date=date(2028, 5, 31),
                amount=Decimal("3499.00"), currency="INR",
                fields={
                    "aliases": ["fridge"], "product": "Double Door Refrigerator", "brand": "Samsung",
                    "model": "RT42C5532S8", "serial": "SYN-RF-77812",
                    "claim_contact": "Samsung Care, 1800-000-0002",
                    "covered_parts": [
                        {"part": "compressor", "term_years": 10, "page": 1,
                         "quote": "Digital Inverter compressor is covered for 10 years"},
                    ],
                    "exclusions": [
                        {"text": "cosmetic damage such as scratches and dents", "page": 2,
                         "quote": "Cosmetic damage such as scratches and dents is excluded"},
                        {"text": "bulbs and plastic trays", "page": 2,
                         "quote": "Consumables including bulbs and plastic trays are excluded"},
                    ],
                    "evidence": {
                        "start_date": {"page": 1, "quote": "Extended warranty start: 01 June 2024"},
                        "end_date": {"page": 1, "quote": "Extended warranty end: 31 May 2028"},
                        "amount": {"page": 1, "quote": "Plan price: INR 3,499.00"},
                    },
                },
            ),
            "pages": [
                "Samsung Care+ Extended Warranty Certificate. Product: Double Door Refrigerator RT42C5532S8, "
                "serial SYN-RF-77812. Extended warranty start: 01 June 2024. Extended warranty end: 31 May 2028. "
                "Plan price: INR 3,499.00. Digital Inverter compressor is covered for 10 years. "
                "All other functional parts are covered for the plan term.",
                "Terms and exclusions. Cosmetic damage such as scratches and dents is excluded. "
                "Consumables including bulbs and plastic trays are excluded. "
                "To raise a claim call Samsung Care on 1800-000-0002.",
            ],
        },
        {
            "doc": dict(
                s3_key="seed/insurance_car.pdf", doc_type="insurance", title="Acme Mutual Private Car Policy Schedule", vendor="Acme",
                item_name="car", item_category="vehicle",
                start_date=car_start, end_date=car_renew, renewal_date=car_renew,
                amount=Decimal("14200.00"), currency="INR", auto_renews=False,
                fields={
                    "aliases": ["vehicle", "car insurance"], "policy_number": "SYN-CAR-2291-0045",
                    "vehicle": "Hatchback, registration SYN 01 AB 1234", "deductible": "INR 2,000",
                    "claim_contact": "Acme claims, 1800-000-0003",
                    "exclusions": [
                        {"text": "driving without a valid licence", "page": 1,
                         "quote": "No cover while the vehicle is driven by a person without a valid licence"},
                    ],
                    "evidence": {
                        "start_date": {"page": 1, "quote": f"Period of insurance from {_fmt(car_start)}"},
                        "end_date": {"page": 1, "quote": f"to {_fmt(car_renew)}"},
                        "renewal_date": {"page": 1, "quote": f"Renewal due: {_fmt(car_renew)}"},
                        "amount": {"page": 1, "quote": "Total premium: INR 14,200.00"},
                    },
                },
            ),
            "pages": [
                "Acme Mutual General Insurance. Private Car Package Policy Schedule. Policy number SYN-CAR-2291-0045. "
                f"Vehicle: Hatchback, registration SYN 01 AB 1234. Period of insurance from {_fmt(car_start)} "
                f"to {_fmt(car_renew)}. Renewal due: {_fmt(car_renew)}. Total premium: INR 14,200.00. "
                "Compulsory deductible: INR 2,000 per claim. "
                "No cover while the vehicle is driven by a person without a valid licence. "
                "Claims helpline: 1800-000-0003."
            ],
        },
        {
            "doc": dict(
                s3_key="seed/lease_maple.pdf", doc_type="lease", title="Maple Residency Rental Agreement", vendor="Maple Residency",
                item_name="apartment", item_category="home",
                start_date=lease_start, end_date=lease_end, notice_days=60,
                amount=Decimal("25000.00"), currency="INR",
                fields={
                    "aliases": ["rent", "rental agreement", "flat", "house"],
                    "landlord": "Maple Residency Pvt (synthetic)", "security_deposit": "INR 75,000",
                    "evidence": {
                        "start_date": {"page": 1, "quote": f"commencing on {_fmt(lease_start)}"},
                        "end_date": {"page": 1, "quote": f"ending on {_fmt(lease_end)}"},
                        "amount": {"page": 1, "quote": "monthly rent of INR 25,000"},
                        "notice_days": {"page": 2, "quote": "either party shall give two months' (60 days) written notice"},
                    },
                },
            ),
            "pages": [
                "Rental Agreement. This agreement between Maple Residency (the Landlord) and the Tenant is for "
                f"Flat 4B, a term commencing on {_fmt(lease_start)} and ending on {_fmt(lease_end)}, "
                "at a monthly rent of INR 25,000 payable by the 5th of each month. "
                "Security deposit: INR 75,000, refundable at the end of the term.",
                "Termination. To terminate or not renew this agreement, either party shall give two months' "
                "(60 days) written notice. Pets are allowed with prior written consent of the Landlord.",
            ],
        },
        {
            "doc": dict(
                s3_key="seed/subscription_streamflix.pdf", doc_type="subscription", title="StreamFlix Premium Subscription Terms", vendor="StreamFlix",
                item_name="streaming", item_category="entertainment",
                renewal_date=sub_renew,
                amount=Decimal("649.00"), currency="INR", auto_renews=True,
                fields={
                    "aliases": ["tv", "streaming service"], "plan": "Premium, annual",
                    "evidence": {
                        "renewal_date": {"page": 1, "quote": f"Your plan renews automatically on {_fmt(sub_renew)}"},
                        "amount": {"page": 1, "quote": "INR 649.00 per year"},
                    },
                },
            ),
            "pages": [
                "StreamFlix Premium annual plan. INR 649.00 per year. "
                f"Your plan renews automatically on {_fmt(sub_renew)} unless you cancel before that date "
                "from Account > Membership. Up to 4 screens at once."
            ],
        },
        {
            "doc": dict(
                s3_key="seed/bill_electricity.pdf", doc_type="bill", title="City Power Electricity Bill", vendor="City Power",
                item_name="electricity", item_category="utilities",
                end_date=bill_due,
                amount=Decimal("2340.00"), currency="INR",
                fields={
                    "aliases": ["power bill", "electric bill"], "account_number": "SYN-EB-55001", "units": 312,
                    "evidence": {
                        "end_date": {"page": 1, "quote": f"Due date: {_fmt(bill_due)}"},
                        "amount": {"page": 1, "quote": "Amount payable: INR 2,340.00"},
                    },
                },
            ),
            "pages": [
                "City Power Distribution. Electricity bill for account SYN-EB-55001. Units consumed: 312. "
                f"Amount payable: INR 2,340.00. Due date: {_fmt(bill_due)}. "
                "A late fee of INR 50 applies after the due date."
            ],
        },
        {
            "doc": dict(
                s3_key="seed/warranty_dell_adp.pdf", doc_type="warranty", title="Dell Laptop Accidental Damage Protection Plan", vendor="Dell",
                item_name="laptop", item_category="electronics",
                start_date=date(2025, 8, 1), end_date=date(2027, 7, 31),
                amount=Decimal("4999.00"), currency="INR",
                fields={
                    "aliases": ["computer", "notebook"], "plan_name": "accidental-damage plan",
                    "product": "Inspiron 14 laptop", "serial": "SYN-DL-3390",
                    "claim_contact": "Dell Support, 1800-000-0004",
                    "covered_parts": [
                        {"part": "screen", "page": 1, "quote": "Accidental drops and cracked screens are covered"},
                    ],
                    "exclusions": [
                        {"text": "liquid damage", "page": 2,
                         "quote": "Liquid damage, including spills of any kind, is excluded from this plan"},
                        {"text": "theft or loss", "page": 2, "quote": "Theft or loss of the device is not covered"},
                    ],
                    "evidence": {
                        "start_date": {"page": 1, "quote": "Coverage start: 01 August 2025"},
                        "end_date": {"page": 1, "quote": "Coverage end: 31 July 2027"},
                        "amount": {"page": 1, "quote": "Plan fee: INR 4,999.00"},
                    },
                },
            ),
            "pages": [
                "Dell Accidental Damage Protection. Product: Inspiron 14 laptop, serial SYN-DL-3390. "
                "Coverage start: 01 August 2025. Coverage end: 31 July 2027. Plan fee: INR 4,999.00. "
                "Accidental drops and cracked screens are covered, up to two incidents per year.",
                "Exclusions. Liquid damage, including spills of any kind, is excluded from this plan. "
                "Theft or loss of the device is not covered. Contact Dell Support on 1800-000-0004.",
            ],
        },
        {
            "doc": dict(
                s3_key="seed/insurance_health.png", doc_type="insurance", title="Evergreen Health Insurance Card", vendor="Evergreen",
                item_name="health", item_category="health",
                end_date=date(2027, 3, 31),
                fields={
                    "aliases": ["medical", "health insurance", "hospital"], "member_id": "SYN-HL-880021",
                    "insurer_helpline": "1800-000-0005",
                    "evidence": {"end_date": {"page": 1, "quote": "Valid till: 31 March 2027"}},
                },
            ),
            "pages": [
                "Evergreen Health Insurance. Member ID SYN-HL-880021. Cashless hospitalisation card. "
                "Valid till: 31 March 2027. 24x7 helpline 1800-000-0005."
            ],
        },
    ]


def main() -> None:
    init_db()
    with Session.begin() as s:
        s.execute(delete(Reminder).where(Reminder.user_id == DEMO_USER_ID))
        s.execute(delete(Document).where(Document.user_id == DEMO_USER_ID))
        for item in seed_documents(date.today()):
            doc = Document(user_id=DEMO_USER_ID, **item["doc"])
            s.add(doc)
            s.flush()
            for page, page_text in enumerate(item["pages"], start=1):
                s.add(Chunk(document_id=doc.id, page=page, text=page_text))
    print(f"Seeded {len(seed_documents(date.today()))} documents for user '{DEMO_USER_ID}'.")


if __name__ == "__main__":
    main()
