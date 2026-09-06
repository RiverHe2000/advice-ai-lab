"""Name and filler lists for the synthetic corpus. Every person, address and firm is
invented; combinations are drawn by a seeded generator."""

from __future__ import annotations

FIRST_NAMES: tuple[str, ...] = (
    "Alice", "Benjamin", "Charlotte", "Daniel", "Eleanor", "Felix", "Grace", "Harriet",
    "Isaac", "Josephine", "Kieran", "Lucinda", "Matthew", "Nadia", "Oliver", "Penelope",
    "Quentin", "Rosalind", "Samuel", "Tamsin", "Ursula", "Vincent", "Wendy", "Xavier",
    "Yasmin", "Zachary", "Amelia", "Bruno", "Cordelia", "Desmond", "Evangeline", "Fergus",
    "Georgina", "Hamish", "Imogen", "Jasper", "Katrina", "Leopold", "Miranda", "Nigel",
)  # fmt: skip

SURNAMES: tuple[str, ...] = (
    "Abernathy", "Blackwood", "Carraway", "Dunmore", "Ellsworth", "Fairbanks", "Galloway",
    "Hartigan", "Ingleby", "Jarrow", "Kingsley", "Lockhart", "Marchbanks", "Northcote",
    "Oakes", "Pemberton", "Quilliam", "Ravenscroft", "Stirling", "Thackeray", "Underhill",
    "Vance", "Whitlock", "Yardley", "Ashcombe", "Brightwater", "Colquhoun", "Delacroix",
    "Everard", "Fenwick", "Greenhalgh", "Holloway", "Isherwood", "Kettering", "Lindqvist",
    "Mortlake", "Naismith", "Oldfield", "Prendergast", "Rutherford",
)  # fmt: skip

ADVISERS: tuple[str, ...] = (
    "Margaret Thorne", "David Okonkwo", "Priya Raman", "Thomas Whitfield", "Helen Castellano",
    "James Lindgren", "Sophie Marchetti", "Andrew Ferreira", "Rachel Nakamura",
    "Michael Brennan", "Laura Sandoval", "Peter Halvorsen",
)  # fmt: skip

STREETS: tuple[str, ...] = (
    "Banksia Avenue", "Wattle Street", "Jacaranda Crescent", "Coral Tree Drive",
    "Kurrajong Road", "Grevillea Court", "Lilly Pilly Lane", "Waratah Parade",
)  # fmt: skip

SUBURBS: tuple[tuple[str, str, str], ...] = (
    ("Marlow Bay", "NSW", "2107"), ("Kingsford Heights", "NSW", "2032"),
    ("Willowdale", "VIC", "3172"), ("Ferntree Rise", "VIC", "3156"),
    ("Sandhurst Park", "QLD", "4074"), ("Coralwood", "QLD", "4218"),
    ("Blackwood Hill", "SA", "5051"), ("Silverleaf", "WA", "6153"),
    ("Kingston Reach", "TAS", "7050"), ("Ashford Downs", "ACT", "2914"),
)  # fmt: skip

BANKS: tuple[str, ...] = ("Coastal Mutual Bank", "Meridian Savings Bank", "Ironbark Bank")
INSURERS: tuple[str, ...] = ("Sentinel Life Insurance", "Beacon Assurance", "Harbourline Life")

EMPLOYERS: tuple[str, ...] = (
    "Ridgeway Logistics Pty Ltd", "Corella Health Services", "Blue Gum Engineering",
    "Stonebridge Council", "Halcyon Retail Group", "Quarry Lane Architects",
    "Southern Star Airlines", "Fenwick & Partners Accountants",
)  # fmt: skip

OCCUPATIONS: tuple[str, ...] = (
    "registered nurse", "civil engineer", "primary school teacher", "operations manager",
    "electrician", "solicitor", "project coordinator", "pharmacist", "graphic designer",
    "warehouse supervisor", "self-employed consultant", "retired",
)  # fmt: skip

DISCLOSURE_SENTENCES: tuple[str, ...] = (
    "This advice has been prepared without taking into account any objectives, financial "
    "situation or needs not disclosed to us during the fact-finding process.",
    "Past performance is not a reliable indicator of future performance.",
    "The recommendations in this document are based on the information you provided and on "
    "the product information available to us at the date of preparation.",
    "You should read the Product Disclosure Statement for each recommended product before "
    "deciding whether to acquire or continue to hold it.",
    "Fees are shown inclusive of GST unless otherwise stated and may be indexed annually.",
    "If your circumstances change you should contact your adviser so that the advice can be "
    "reviewed.",
    "Northshore Financial Advice Pty Ltd is the holder of an Australian Financial Services "
    "Licence and is responsible for the advice provided by its authorised representatives.",
    "Where a product replacement is recommended we have compared the fees, features and "
    "insurance cover of the existing and recommended products as required by law.",
    "Concessional contributions are taxed at 15% within the fund and count towards the "
    "concessional contributions cap.",
    "Non-concessional contributions are made from after-tax income and are subject to the "
    "non-concessional contributions cap and the bring-forward rule.",
    "Superannuation benefits are preserved until you reach your preservation age and satisfy "
    "a condition of release.",
    "A binding death benefit nomination directs the trustee on how your superannuation death "
    "benefit is to be paid and lapses after three years unless renewed.",
    "Centrelink Age Pension entitlements depend on the income and assets tests applying at "
    "the time of assessment.",
    "The value of investments can rise and fall and you may receive back less than you "
    "invested.",
    "We act in your best interests under section 961B of the Corporations Act when providing "
    "personal advice.",
    "Our remuneration is set out in the fees section and in the Financial Services Guide "
    "provided to you.",
)  # fmt: skip

LETTER_TOPICS: tuple[str, ...] = (
    "our meeting last week about your retirement timeline",
    "the review of your insurance cover",
    "the documents we still need for your application",
    "your question about making an additional contribution before 30 June",
    "the change of address on your account",
    "the annual review meeting we scheduled",
    "the market update you asked about",
    "your request to update your binding death benefit nomination",
)  # fmt: skip
