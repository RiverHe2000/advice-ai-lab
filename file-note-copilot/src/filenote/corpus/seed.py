"""The structured meeting seed: who attended, what changed, what was discussed, what was
actually decided (and what was explicitly deferred), the action items, the compliance events
that happened or did not, and the small talk that must stay out of the note."""

from __future__ import annotations

import datetime as dt
import random
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from filenote.pii import make_tfn
from filenote.schema import MEETING_TYPES, Attendee, MeetingType, Owner

ChangeKind = Literal[
    "new_job", "salary_change", "inheritance", "new_dependant", "mortgage_paid_down", "health_event"
]
GoalKind = Literal[
    "retire", "mortgage_free", "school_fees", "holiday", "deposit_help", "emergency_fund"
]
TopicKind = Literal[
    "super_balance",
    "concessional",
    "non_concessional",
    "insurance",
    "fees",
    "product_switch",
    "investment_option",
    "bdbn",
    "pension",
    "age_pension",
    "premiums",
]
PIIKind = Literal["phone", "email", "address", "dob", "tfn"]
RISK_PROFILES = ("Conservative", "Moderately Conservative", "Balanced", "Growth", "High Growth")

FIRST_NAMES = [
    "Sarah", "Priya", "James", "Michael", "Emma", "Daniel", "Olivia", "Liam", "Chloe", "Nathan",
    "Hannah", "Tom", "Mei", "Arjun", "Sophie", "Ben", "Grace", "Lucas", "Isla", "Ravi", "Zoe",
    "Ethan", "Amelia", "Jack", "Nadia", "Oscar", "Layla", "Hugo", "Ruby", "Ali", "Fiona", "Marco",
]  # fmt: skip
LAST_NAMES = [
    "Nguyen", "Patel", "Wilson", "O'Connor", "Chen", "Taylor", "Singh", "Kowalski", "Marsh",
    "Fraser", "Mackenzie", "Rossi", "Hayes", "Doyle", "Petrov", "Anand", "Costa", "Bennett",
    "Okafor", "Harper", "Lindqvist", "Moreau", "Tanaka", "Reilly", "Burke", "Vella", "Whitfield",
]  # fmt: skip
EMPLOYERS = [
    "Harbourline Logistics", "Coastal Health Group", "Redgum Engineering", "Bellbird Media",
    "Southbank Analytics", "Wattle Creek Council", "Kestrel Mining Services", "Ironbark Legal",
    "Blue Gum Pharmacy Group", "Marlin Construction",
]  # fmt: skip
JOB_TITLES = [
    "project manager", "registered nurse", "senior analyst", "operations lead", "teacher",
    "electrician", "pharmacist", "solicitor", "site supervisor", "marketing manager",
]  # fmt: skip
EXTERNAL_FUNDS = [
    "Aurora Super", "Pinnacle Employer Super", "Coastline Super", "MetroCorp Staff Super",
    "Sunline Industry Super",
]  # fmt: skip
RELATIVES = ["mother", "father", "aunt", "uncle", "grandmother"]
HEALTH_EVENTS = ["a knee reconstruction", "a heart scare", "back surgery", "a bout of pneumonia"]
BABY_NAMES = ["Ava", "Noah", "Mia", "Leo", "Ivy", "Theo"]
SMALL_TALK_OPENERS = [
    (
        "How was the drive in? The traffic on the bridge was terrible this morning.",
        "Not too bad, we came in on the train.",
    ),
    (
        "Did you get away over the long weekend?",
        "We did, a few days down the coast. Very relaxing.",
    ),
    (
        "How was the holiday in Tasmania?",
        "Beautiful. We did the Cradle Mountain walk, legs are still sore.",
    ),
    ("Did you catch the footy final on the weekend?", "I did, what a finish. My nephew was there."),
    ("The weather has really turned, hasn't it?", "It has, the garden is loving it though."),
    ("Coffee? The machine is finally fixed.", "Yes please, flat white if that's easy."),
]
SMALL_TALK_CLOSERS = [
    ("Say hello to the kids for me.", "Will do, thanks for your time."),
    ("Enjoy the rest of the week.", "You too, see you next time."),
    ("Safe drive home, the rain is meant to set in this afternoon.", "Thanks, we will."),
    ("Good luck with the renovation.", "We'll need it. Thanks again."),
]
FILLERS_MID = [
    ("Let me just pull up your file, bear with me.", "No problem."),
    ("Sorry, one second, I just need to find that statement.", "Take your time."),
    ("Is the room too warm? I can open a window.", "It's fine, thanks."),
]
VULNERABILITY_LINES = [
    (
        "Since Dad passed I've found it hard to follow these things. My daughter is going to "
        "help me with the paperwork.",
        "Client reports difficulty following financial matters since a bereavement; daughter "
        "assisting with paperwork.",
    ),
    (
        "English isn't my first language, so could you send everything in writing so I can go "
        "through it slowly?",
        "Client asked for all material in writing because English is not their first language.",
    ),
    (
        "I've been off work with depression for a couple of months, so my head isn't really in "
        "this.",
        "Client disclosed being off work with depression for a couple of months and reduced "
        "capacity to engage.",
    ),
    (
        "My hearing isn't great these days, you'll have to speak up a bit.",
        "Client has a hearing impairment; adviser to confirm key points in writing.",
    ),
]
MONTHS = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
]  # fmt: skip


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: Literal["adviser", "client", "paraplanner"]

    @property
    def first(self) -> str:
        return self.name.split()[0]

    def as_attendee(self) -> Attendee:
        return Attendee(name=self.name, role=self.role)


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ChangeKind
    client: str
    month: str
    amount: float | None = None
    amount2: float | None = None
    employer: str | None = None
    title: str | None = None
    relative: str | None = None
    baby: str | None = None
    dependants: int | None = None
    event: str | None = None
    month2: str | None = None


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: GoalKind
    amount: float | None = None
    year: int | None = None
    age: int | None = None
    who: str | None = None


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TopicKind
    figures: dict[str, float] = Field(default_factory=dict)
    names: dict[str, str] = Field(default_factory=dict)
    has_advice: bool = True
    decided: bool | None = None  # None: informational only; True: decision; False: deferred


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    owner: Owner
    due: dt.date


class ComplianceEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_profile_discussed: bool
    risk_profile_confirmed: bool | None = None
    risk_profile: str | None = None
    previous_risk_profile: str | None = None
    fee_consent_discussed: bool
    fee_amount: float | None = None
    conflicts_disclosed: bool
    vulnerability: list[int] = Field(default_factory=list)  # indexes into VULNERABILITY_LINES


class PIIAside(BaseModel):
    """An administrative aside (new phone, e-mail, address, DOB, TFN) that a note must not
    carry and an audit log must redact."""

    model_config = ConfigDict(extra="forbid")

    kind: PIIKind
    value: str


class MeetingSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    date: dt.date
    type: MeetingType
    adviser: Person
    clients: list[Person]
    paraplanner: Person | None = None
    changes: list[Change]
    goals: list[Goal]
    topics: list[Topic]
    actions: list[Action]
    compliance: ComplianceEvents
    follow_up: dt.date | None
    small_talk_open: int
    small_talk_close: int
    fillers_mid: list[int]
    pii_aside: PIIAside | None = None

    @property
    def people(self) -> list[Person]:
        out = [self.adviser, *self.clients]
        if self.paraplanner is not None:
            out.append(self.paraplanner)
        return out

    @property
    def attendees(self) -> list[Attendee]:
        return [p.as_attendee() for p in self.people]


_TOPIC_POOL: dict[MeetingType, list[TopicKind]] = {
    "initial": [
        "super_balance", "concessional", "insurance", "fees", "investment_option", "product_switch",
    ],
    "annual_review": [
        "super_balance", "concessional", "non_concessional", "fees", "product_switch", "bdbn",
        "investment_option",
    ],
    "insurance_review": ["insurance", "premiums", "fees", "super_balance"],
    "retirement_planning": [
        "pension", "age_pension", "non_concessional", "bdbn", "super_balance", "investment_option",
    ],
}  # fmt: skip
_INFORMATIONAL: set[TopicKind] = {"super_balance", "fees"}
_CHANGE_KINDS: list[ChangeKind] = [
    "new_job",
    "salary_change",
    "inheritance",
    "new_dependant",
    "mortgage_paid_down",
    "health_event",
]
_GOAL_KINDS: list[GoalKind] = [
    "retire", "mortgage_free", "school_fees", "holiday", "deposit_help", "emergency_fund",
]  # fmt: skip


def _round_to(value: float, step: float) -> float:
    return float(round(value / step) * step)


def _person(
    rng: random.Random, role: Literal["adviser", "client", "paraplanner"], used: set[str]
) -> Person:
    while True:
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        first = name.split()[0]
        if first not in used:
            used.add(first)
            return Person(name=name, role=role)


def _change(rng: random.Random, kind: ChangeKind, client: Person, n_dependants: int) -> Change:
    month = rng.choice(MONTHS[:8])
    base = {"kind": kind, "client": client.name, "month": month}
    if kind == "new_job":
        return Change(
            **base,
            employer=rng.choice(EMPLOYERS),
            title=rng.choice(JOB_TITLES),
            amount=_round_to(rng.uniform(70_000, 160_000), 1_000),
            amount2=_round_to(rng.uniform(60_000, 120_000), 1_000),
        )
    if kind == "salary_change":
        return Change(**base, amount=_round_to(rng.uniform(75_000, 170_000), 1_000))
    if kind == "inheritance":
        return Change(
            **base,
            relative=rng.choice(RELATIVES),
            amount=_round_to(rng.uniform(40_000, 400_000), 5_000),
            month2=rng.choice(MONTHS[8:]),
        )
    if kind == "new_dependant":
        return Change(**base, baby=rng.choice(BABY_NAMES), dependants=n_dependants + 1)
    if kind == "mortgage_paid_down":
        return Change(
            **base,
            amount=_round_to(rng.uniform(20_000, 90_000), 1_000),
            amount2=_round_to(rng.uniform(150_000, 600_000), 1_000),
        )
    return Change(**base, event=rng.choice(HEALTH_EVENTS))


def _goal(rng: random.Random, kind: GoalKind, year: int, client: Person) -> Goal:
    if kind == "retire":
        return Goal(
            kind=kind,
            age=rng.choice([60, 62, 65, 67]),
            amount=_round_to(rng.uniform(50_000, 110_000), 5_000),
        )
    if kind == "mortgage_free":
        return Goal(kind=kind, year=year + rng.randint(3, 12))
    if kind == "school_fees":
        return Goal(
            kind=kind,
            amount=_round_to(rng.uniform(12_000, 35_000), 1_000),
            year=year + rng.randint(1, 6),
            who=rng.choice(BABY_NAMES),
        )
    if kind == "holiday":
        return Goal(
            kind=kind,
            amount=_round_to(rng.uniform(15_000, 40_000), 1_000),
            year=year + rng.randint(1, 3),
        )
    if kind == "deposit_help":
        return Goal(
            kind=kind,
            amount=_round_to(rng.uniform(40_000, 150_000), 5_000),
            year=year + rng.randint(2, 8),
            who=client.first,
        )
    return Goal(kind=kind, amount=_round_to(rng.uniform(10_000, 40_000), 1_000))


def _topic(rng: random.Random, kind: TopicKind, decided: bool | None) -> Topic:
    f: dict[str, float] = {}
    names: dict[str, str] = {}
    if kind == "super_balance":
        f = {
            "balance": _round_to(rng.uniform(120_000, 950_000), 1_000),
            "return_pct": round(rng.uniform(4.0, 11.5), 1),
        }
    elif kind == "concessional":
        sg = _round_to(rng.uniform(9_000, 20_000), 500)
        headroom = 30_000 - sg
        f = {
            "cap": 30_000,
            "sg": sg,
            "headroom": headroom,
            "proposal": _round_to(headroom * rng.uniform(0.5, 0.95), 500),
        }
    elif kind == "non_concessional":
        f = {
            "cap": 120_000,
            "bring_forward": 360_000,
            "amount": _round_to(rng.uniform(40_000, 300_000), 5_000),
        }
    elif kind == "insurance":
        life = _round_to(rng.uniform(400_000, 1_500_000), 50_000)
        f = {
            "life": life,
            "tpd": _round_to(life * rng.uniform(0.5, 1.0), 50_000),
            "ip_monthly": _round_to(rng.uniform(4_000, 12_000), 500),
            "premium": _round_to(rng.uniform(2_000, 7_000), 100),
            "life_new": life + _round_to(rng.uniform(150_000, 500_000), 50_000),
        }
    elif kind == "fees":
        f = {
            "platform_pct": round(rng.uniform(0.2, 0.6), 2),
            "adviser_fee": _round_to(rng.uniform(2_500, 6_500), 100),
        }
    elif kind == "product_switch":
        names = {"fund": rng.choice(EXTERNAL_FUNDS)}
        f = {
            "current_pct": round(rng.uniform(0.85, 1.4), 2),
            "new_pct": round(rng.uniform(0.45, 0.75), 2),
        }
    elif kind == "investment_option":
        names = {"current": "Balanced", "proposed": rng.choice(["Growth", "High Growth"])}
        f = {"expected_pct": round(rng.uniform(6.0, 8.5), 1)}
    elif kind == "bdbn":
        f = {"lapse_year": float(rng.randint(2026, 2028))}
        names = {"beneficiary": rng.choice(["spouse", "children", "estate"])}
    elif kind == "pension":
        f = {
            "balance": _round_to(rng.uniform(300_000, 1_200_000), 10_000),
            "min_pct": float(rng.choice([4, 5, 6])),
            "income": _round_to(rng.uniform(40_000, 90_000), 1_000),
        }
    elif kind == "age_pension":
        f = {"assets": _round_to(rng.uniform(300_000, 900_000), 10_000), "age": 67.0}
        names = {"month": rng.choice(MONTHS)}
    else:  # premiums
        p1 = _round_to(rng.uniform(2_500, 6_000), 100)
        f = {"premium_old": p1, "premium_new": _round_to(p1 * rng.uniform(1.12, 1.35), 100)}
    return Topic(
        kind=kind, figures=f, names=names, has_advice=kind not in _INFORMATIONAL, decided=decided
    )


def _actions(
    rng: random.Random, seed_topics: list[Topic], when: dt.date, paraplanner: bool
) -> list[Action]:
    pool: list[tuple[str, Owner]] = [
        ("send the ongoing fee consent form for signature", "adviser"),
        ("update the fact-find with the new salary details", "adviser"),
        ("prepare the fee comparison for the review", "adviser"),
        ("send the latest super statement", "client"),
        ("provide the current insurance policy schedule", "client"),
        ("confirm the salary sacrifice amount with payroll", "client"),
    ]
    for t in seed_topics:
        topic = t.kind.replace("_", " ")
        if t.decided:
            pool.append(
                (f"prepare the Statement of Advice for the {topic} recommendation", "adviser")
            )
        if t.decided is False:
            owner: Owner = "paraplanner" if paraplanner else "adviser"
            pool.append((f"model the {topic} options for the next review", owner))
    if paraplanner:
        pool.append(("model the product switch comparison", "paraplanner"))
    rng.shuffle(pool)
    n = rng.randint(2, 5)
    return [
        Action(description=d, owner=o, due=when + dt.timedelta(days=rng.randint(7, 45)))
        for d, o in pool[:n]
    ]


def _pii_aside(rng: random.Random, client: Person) -> PIIAside:
    first = client.first.lower()
    last = client.name.split()[-1].lower().replace("'", "")
    kind: PIIKind = rng.choice(["phone", "email", "address", "dob", "tfn"])
    street = rng.choice(["Wattle", "Banksia", "Gumtree", "Jacaranda"])
    street_type = rng.choice(["Street", "Road", "Avenue", "Crescent"])
    suburb = rng.choice(["Ryde", "Camberwell", "Toowong", "Subiaco"])
    state = rng.choice(["NSW", "VIC", "QLD", "WA"])
    values: dict[str, str] = {
        "phone": f"04{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
        "email": f"{first}.{last}@example.com",
        "address": (
            f"{rng.randint(2, 180)} {street} {street_type}, {suburb} {state} "
            f"{rng.randint(2000, 6999)}"
        ),
        "dob": f"{rng.randint(1, 28)} {rng.choice(MONTHS)} {rng.randint(1950, 1990)}",
        "tfn": make_tfn(rng),
    }
    return PIIAside(kind=kind, value=values[kind])


def generate_seed(index: int, rng: random.Random) -> MeetingSeed:
    used: set[str] = set()
    meeting_type: MeetingType = rng.choice(MEETING_TYPES)
    adviser = _person(rng, "adviser", used)
    clients = [_person(rng, "client", used)]
    if rng.random() < 0.5:
        clients.append(_person(rng, "client", used))
    paraplanner = _person(rng, "paraplanner", used) if rng.random() < 0.3 else None
    when = dt.date(2026, 1, 1) + dt.timedelta(days=rng.randint(0, 240))
    n_dependants = rng.randint(0, 2)

    change_kinds = list(_CHANGE_KINDS)
    rng.shuffle(change_kinds)
    changes = [
        _change(rng, k, rng.choice(clients), n_dependants)
        for k in change_kinds[: rng.randint(1, 3)]
    ]
    goal_kinds = list(_GOAL_KINDS)
    rng.shuffle(goal_kinds)
    goals = [_goal(rng, k, when.year, clients[0]) for k in goal_kinds[: rng.randint(1, 3)]]

    kinds = list(_TOPIC_POOL[meeting_type])
    rng.shuffle(kinds)
    topics: list[Topic] = []
    for k in kinds[: rng.randint(3, 5)]:
        decided: bool | None = None if k in _INFORMATIONAL else rng.random() < 0.6
        topics.append(_topic(rng, k, decided))
    if not any(t.decided is False for t in topics):
        # every meeting carries at least one explicit deferral: the trap the note must avoid
        eligible = [t for t in topics if t.has_advice]
        if eligible:
            rng.choice(eligible).decided = False
    if not any(t.decided for t in topics):
        eligible = [t for t in topics if t.has_advice and t.decided is None]
        if eligible:
            rng.choice(eligible).decided = True

    risk_discussed = rng.random() < 0.75
    prev = rng.choice(RISK_PROFILES)
    confirmed = rng.random() < 0.7
    new_profile = prev if confirmed else rng.choice([p for p in RISK_PROFILES if p != prev])
    compliance = ComplianceEvents(
        risk_profile_discussed=risk_discussed,
        risk_profile_confirmed=confirmed if risk_discussed else None,
        risk_profile=new_profile if risk_discussed else None,
        previous_risk_profile=prev,
        fee_consent_discussed=rng.random() < 0.6,
        fee_amount=_round_to(rng.uniform(2_500, 6_500), 100),
        conflicts_disclosed=rng.random() < 0.5,
        vulnerability=[rng.randrange(len(VULNERABILITY_LINES))] if rng.random() < 0.25 else [],
    )
    follow_up = (
        when + dt.timedelta(days=rng.choice([90, 180, 365])) if rng.random() < 0.85 else None
    )
    pii_aside = _pii_aside(rng, clients[0]) if rng.random() < 0.3 else None

    return MeetingSeed(
        id=f"m{index:04d}",
        date=when,
        type=meeting_type,
        adviser=adviser,
        clients=clients,
        paraplanner=paraplanner,
        changes=changes,
        goals=goals,
        topics=topics,
        actions=_actions(rng, topics, when, paraplanner is not None),
        compliance=compliance,
        follow_up=follow_up,
        small_talk_open=rng.randrange(len(SMALL_TALK_OPENERS)),
        small_talk_close=rng.randrange(len(SMALL_TALK_CLOSERS)),
        fillers_mid=[rng.randrange(len(FILLERS_MID)) for _ in range(rng.randint(0, 2))],
        pii_aside=pii_aside,
    )
