"""Renders a seed into dialogue and the gold note in one pass, so every gold item knows the
segment ids that support it. Numbers are spoken in several formats; the gold note writes them
canonically — the verifier's normalisation is what makes those agree."""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

from filenote.corpus.seed import (
    BABY_NAMES,
    FILLERS_MID,
    MONTHS,
    SMALL_TALK_CLOSERS,
    SMALL_TALK_OPENERS,
    VULNERABILITY_LINES,
    Action,
    Change,
    Goal,
    MeetingSeed,
    Person,
    Topic,
)
from filenote.numbers import format_amount, number_to_words
from filenote.schema import (
    ActionItem,
    Claim,
    ComplianceFlags,
    FileNote,
    MeetingMeta,
    Segment,
    Transcript,
)

FILLERS = ["Um, ", "So, ", "Right, ", "Look, ", "Okay so ", "Yeah, "]
AGREEMENTS = [
    "Yes, let's go ahead with that.",
    "Happy to proceed, let's do it.",
    "Agreed, lock that in.",
]
DEFERRALS = [
    "Can I think about it? Cash flow is tight with the renovation.",
    "I'm not ready to decide that today, can we revisit next time?",
    "Let me sleep on it and come back to you.",
]
PARKS = [
    "Of course, we'll park that and revisit at the next review.",
    "No rush at all, we'll leave it for now and come back to it.",
]
PURPOSE = {
    "initial": (
        "Today is our first proper meeting, so I want to get the full picture and then talk "
        "through where we can help."
    ),
    "annual_review": (
        "This is your annual review, so let's go through what has changed and then the plan."
    ),
    "insurance_review": (
        "Today is the insurance review, so we'll focus on your cover and the premiums."
    ),
    "retirement_planning": (
        "Today we're planning the transition to retirement, so income, super and Centrelink."
    ),
}


@dataclass
class Rendered:
    transcript: Transcript
    gold: FileNote
    small_talk_ids: list[str]
    deferred: list[Claim]
    decision_topics: list[str] = field(default_factory=list)


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


class _Script:
    def __init__(self, seed: MeetingSeed, rng: random.Random) -> None:
        self.seed = seed
        self.rng = rng
        self.segments: list[Segment] = []
        self.small_talk: list[str] = []
        self.t = 0.0
        # first words that must keep their capital after a filler is prepended
        self.proper = {p.first for p in seed.people} | set(MONTHS) | set(BABY_NAMES) | {
            "Northshore", "Centrelink", "Age", "TPD", "Big", "School", "Probate", "Retire",
            "Mortgage", "Fund", "Build", "Overseas", "Help", "Pay", "Getting", "Actually",
        }  # fmt: skip

    def say(self, who: Person, text: str, *, filler: bool = True, small_talk: bool = False) -> str:
        if filler and self.rng.random() < 0.3 and not text.startswith(("Yes", "No", "Sure")):
            first = text.split()[0].strip(",.!?").removesuffix("'s")
            keep = first in {"I", "I'm", "I'd", "I'll", "I've"} or first in self.proper
            body = text if keep or not first[0].isupper() else text[0].lower() + text[1:]
            text = self.rng.choice(FILLERS) + body
        sid = f"s{len(self.segments) + 1:03d}"
        self.segments.append(
            Segment(id=sid, t=round(self.t, 1), speaker=who.name, role=who.role, text=text)
        )
        self.t += 1.5 + 0.38 * len(text.split()) + self.rng.uniform(0.0, 2.5)
        if small_talk:
            self.small_talk.append(sid)
        return sid

    def client(self) -> Person:
        return self.rng.choice(self.seed.clients)

    # ----- number rendering ---------------------------------------------------------------

    def amount(self, value: float) -> str:
        """One of several spoken/written forms; all normalise to ``value``."""
        forms = [format_amount(value), f"{number_to_words(value)} dollars", f"{value:,.0f} dollars"]
        if value >= 1_000 and value % 1_000 == 0:
            forms.append(f"${value / 1_000:,.0f}k")
            forms.append(f"{value / 1_000:,.0f} thousand")
        return self.rng.choice(forms)

    def pct(self, value: float) -> str:
        forms = [f"{value:g} percent", f"{value:g}%", f"{number_to_words(value)} percent"]
        return self.rng.choice(forms)

    def when(self, d: dt.date) -> str:
        forms = [
            f"{d.day} {d.strftime('%B')}",
            f"the {d.day}{_ordinal(d.day)} of {d.strftime('%B')}",
            d.strftime("%d/%m/%Y").lstrip("0"),
            f"{d.day} {d.strftime('%B %Y')}",
        ]
        return self.rng.choice(forms)

    def maybe_restate(self, who: Person, text: str) -> list[str]:
        """An interruption + restatement: the adviser repeats the figure in another form."""
        ids: list[str] = []
        if self.rng.random() < 0.2:
            asks = ["Sorry, say that again?", "Sorry, just to check, what was that figure?"]
            self.say(self.client(), self.rng.choice(asks), filler=False, small_talk=True)
            ids.append(self.say(who, "Yes. " + text, filler=False))
        return ids


# ----- blocks ---------------------------------------------------------------------------------


def _render_change(s: _Script, c: Change) -> Claim:
    client = next(p for p in s.seed.clients if p.name == c.client)
    adv = s.seed.adviser
    ids: list[str] = []
    if c.kind == "new_job":
        assert c.amount is not None
        assert c.amount2 is not None
        ids.append(
            s.say(
                client,
                f"Big change since we last spoke: I started a new job at {c.employer} in "
                f"{c.month}, as a {c.title}. Salary is {s.amount(c.amount)} now.",
            )
        )
        ids.append(
            s.say(adv, f"Congratulations. So {s.amount(c.amount)}, up from {s.amount(c.amount2)}?")
        )
        ids.append(s.say(client, "Yes, that's right.", filler=False))
        text = (
            f"{client.name} started a new job as {c.title} at {c.employer} in {c.month}; "
            f"salary now {format_amount(c.amount)} (previously {format_amount(c.amount2)})."
        )
    elif c.kind == "salary_change":
        assert c.amount is not None
        ids.append(
            s.say(
                client,
                f"My salary went up to {s.amount(c.amount)} in {c.month}, I got a promotion.",
            )
        )
        ids.append(s.say(adv, f"{s.amount(c.amount)}, that's great. I'll update the fact-find."))
        text = (
            f"{client.name}'s salary increased to {format_amount(c.amount)} in {c.month} "
            f"following a promotion."
        )
    elif c.kind == "inheritance":
        assert c.amount is not None
        ids.append(
            s.say(
                client,
                f"My {c.relative} passed away in {c.month}. I'm getting an inheritance of about "
                f"{s.amount(c.amount)}.",
            )
        )
        ids.append(
            s.say(
                adv,
                f"I'm sorry to hear that. {s.amount(c.amount)}, and when will the estate come "
                f"through?",
            )
        )
        ids.append(s.say(client, f"Probate should be finished by {c.month2}."))
        text = (
            f"{client.name} expects an inheritance of about {format_amount(c.amount)} from their "
            f"{c.relative}'s estate; probate expected by {c.month2}."
        )
    elif c.kind == "new_dependant":
        assert c.dependants is not None
        ids.append(s.say(client, f"We had a baby in {c.month}, {c.baby}."))
        ids.append(
            s.say(
                adv, f"Congratulations! So that's {number_to_words(c.dependants)} dependants now."
            )
        )
        ids.append(s.say(client, "Yes, and not much sleep.", filler=False))
        text = (
            f"New dependant {c.baby}, born in {c.month}; the family now has {c.dependants} "
            f"dependants."
        )
    elif c.kind == "mortgage_paid_down":
        assert c.amount is not None
        assert c.amount2 is not None
        ids.append(
            s.say(
                client,
                f"We paid {s.amount(c.amount)} off the mortgage with the bonus. The balance is "
                f"down to {s.amount(c.amount2)}.",
            )
        )
        ids.append(
            s.say(
                adv,
                f"{s.amount(c.amount2)} left. That changes the insurance picture, we'll come to "
                f"that.",
            )
        )
        text = (
            f"Mortgage reduced by {format_amount(c.amount)}; balance now "
            f"{format_amount(c.amount2)}."
        )
    else:
        ids.append(
            s.say(client, f"I had {c.event} in {c.month}. I'm back at work but on reduced hours.")
        )
        ids.append(s.say(adv, "Thanks for telling me. How are you going with it?"))
        ids.append(
            s.say(
                client, "Getting there. The reduced hours are probably until the end of the year."
            )
        )
        text = f"{client.name} had {c.event} in {c.month} and is back at work on reduced hours."
    ids += s.maybe_restate(adv, "as I said, we'll factor that into the plan.")
    return Claim(text=text, evidence=ids)


def _render_goal(s: _Script, g: Goal) -> Claim:
    client = s.client()
    adv = s.seed.adviser
    ids: list[str] = []
    if g.kind == "retire":
        assert g.age is not None
        assert g.amount is not None
        ids.append(
            s.say(
                client,
                f"The main goal is still to retire at {number_to_words(g.age)} with about "
                f"{s.amount(g.amount)} a year to live on.",
            )
        )
        ids.append(s.say(adv, f"Retire at {g.age}, {s.amount(g.amount)} a year of income. Noted."))
        text = f"Retire at age {g.age} with income of about {format_amount(g.amount)} per year."
    elif g.kind == "mortgage_free":
        ids.append(s.say(client, f"We'd like the mortgage gone by {g.year}."))
        ids.append(s.say(adv, f"Mortgage paid off by {g.year}, good."))
        text = f"Pay off the mortgage by {g.year}."
    elif g.kind == "school_fees":
        assert g.amount is not None
        ids.append(
            s.say(
                client,
                f"School fees for {g.who} start in {g.year}, about {s.amount(g.amount)} a year.",
            )
        )
        ids.append(s.say(adv, f"{s.amount(g.amount)} a year from {g.year}. We'll build that in."))
        text = (
            f"Fund school fees for {g.who} of about {format_amount(g.amount)} per year from "
            f"{g.year}."
        )
    elif g.kind == "holiday":
        assert g.amount is not None
        ids.append(
            s.say(
                client,
                f"We want to do a big overseas trip in {g.year}, budget around "
                f"{s.amount(g.amount)}.",
            )
        )
        ids.append(s.say(adv, f"A {s.amount(g.amount)} trip in {g.year}. Fun goal."))
        text = f"Overseas trip in {g.year} with a budget of about {format_amount(g.amount)}."
    elif g.kind == "deposit_help":
        assert g.amount is not None
        ids.append(
            s.say(
                client,
                f"And we'd like to help the kids with a home deposit, {s.amount(g.amount)} or so "
                f"by {g.year}.",
            )
        )
        ids.append(s.say(adv, f"{s.amount(g.amount)} towards a deposit by {g.year}. Understood."))
        text = (
            f"Help the children with a home deposit of about {format_amount(g.amount)} by {g.year}."
        )
    else:
        assert g.amount is not None
        ids.append(
            s.say(
                client,
                f"I'd like a proper emergency fund, {s.amount(g.amount)} sitting in the offset.",
            )
        )
        ids.append(s.say(adv, f"An emergency fund of {s.amount(g.amount)}. Sensible."))
        text = f"Build an emergency fund of {format_amount(g.amount)}."
    return Claim(text=text, evidence=ids)


@dataclass
class _TopicLines:
    topic_lines: list[tuple[Person, str]]
    topic_text: str
    advice_line: str | None = None
    advice_text: str | None = None
    decision_text: str | None = None
    confirm: str = ""


def _topic_lines(s: _Script, t: Topic) -> _TopicLines:
    adv = s.seed.adviser
    client = s.client()
    f = t.figures
    n = t.names
    if t.kind == "super_balance":
        return _TopicLines(
            [
                (
                    adv,
                    f"Your Northshore Super balance is sitting at {s.amount(f['balance'])} as at "
                    f"the end of last month. That's a return of {s.pct(f['return_pct'])} for "
                    f"the year.",
                ),
                (client, "That's better than I expected, to be honest."),
            ],
            f"Northshore Super balance {format_amount(f['balance'])} at the end of last month; "
            f"return of {f['return_pct']:g}% for the year.",
        )
    if t.kind == "concessional":
        out = _TopicLines(
            [
                (
                    adv,
                    f"The concessional contribution cap this year is {s.amount(f['cap'])}. Your "
                    f"employer contributions come to about {s.amount(f['sg'])}, so there is "
                    f"roughly {s.amount(f['headroom'])} of headroom.",
                )
            ],
            f"Concessional contribution cap of {format_amount(f['cap'])}; employer contributions "
            f"about {format_amount(f['sg'])}, headroom about {format_amount(f['headroom'])}.",
            f"You could salary sacrifice {s.amount(f['proposal'])} a year and stay under the cap. "
            f"It's taxed at fifteen percent going in rather than your marginal rate.",
            f"Salary sacrifice of {format_amount(f['proposal'])} per year discussed to use the "
            f"concessional cap (15% contributions tax).",
        )
        if t.decided:
            out.decision_text = (
                f"Client agreed to salary sacrifice {format_amount(f['proposal'])} per year from "
                f"the next pay cycle."
            )
            out.confirm = (
                f"Great, so we'll set up the salary sacrifice at {s.amount(f['proposal'])} a year "
                f"from the next pay cycle."
            )
        return out
    if t.kind == "non_concessional":
        out = _TopicLines(
            [
                (
                    adv,
                    f"On the non-concessional side the cap is {s.amount(f['cap'])} a year, or up "
                    f"to {s.amount(f['bring_forward'])} using the bring-forward rule.",
                )
            ],
            f"Non-concessional cap of {format_amount(f['cap'])} per year, or "
            f"{format_amount(f['bring_forward'])} under the bring-forward rule.",
            f"You could put {s.amount(f['amount'])} into super as a non-concessional "
            f"contribution. Inside super the earnings are taxed at fifteen percent at most.",
            f"Non-concessional contribution of {format_amount(f['amount'])} to super discussed.",
        )
        if t.decided:
            out.decision_text = (
                f"Client agreed to make a non-concessional contribution of "
                f"{format_amount(f['amount'])} to Northshore Super."
            )
            out.confirm = (
                f"Good, we'll proceed with the {s.amount(f['amount'])} non-concessional "
                f"contribution once the funds land."
            )
        return out
    if t.kind == "insurance":
        out = _TopicLines(
            [
                (
                    adv,
                    f"Your cover through Northshore Life is {s.amount(f['life'])} of life cover, "
                    f"{s.amount(f['tpd'])} TPD, and income protection of "
                    f"{s.amount(f['ip_monthly'])} a month. The premium is "
                    f"{s.amount(f['premium'])} a year.",
                )
            ],
            f"Current insurance with Northshore Life: life cover {format_amount(f['life'])}, TPD "
            f"{format_amount(f['tpd'])}, income protection {format_amount(f['ip_monthly'])} per "
            f"month; premium {format_amount(f['premium'])} per year.",
            f"Given the mortgage and the family, I'd suggest increasing the life cover to "
            f"{s.amount(f['life_new'])}.",
            f"Increase in life cover to {format_amount(f['life_new'])} discussed given the "
            f"mortgage and dependants.",
        )
        if t.decided:
            out.decision_text = (
                f"Client agreed to increase life cover to {format_amount(f['life_new'])}."
            )
            out.confirm = (
                f"Okay, we'll increase the life cover to {s.amount(f['life_new'])}, subject to "
                f"underwriting."
            )
        return out
    if t.kind == "fees":
        return _TopicLines(
            [
                (
                    adv,
                    f"On fees: the platform administration fee is {s.pct(f['platform_pct'])} a "
                    f"year and my ongoing advice fee is {s.amount(f['adviser_fee'])} a year, "
                    f"which is on the fee disclosure statement.",
                ),
                (client, "Okay, that's what I had in my notes."),
            ],
            f"Fees: platform administration fee {f['platform_pct']:g}% per year; ongoing advice "
            f"fee {format_amount(f['adviser_fee'])} per year (per the fee disclosure statement).",
        )
    if t.kind == "product_switch":
        out = _TopicLines(
            [
                (
                    adv,
                    f"I compared {n['fund']} with Northshore Super. {n['fund']} is costing you "
                    f"{s.pct(f['current_pct'])} a year all up. Northshore Super would be about "
                    f"{s.pct(f['new_pct'])}.",
                ),
                (client, "That's a big difference over time."),
            ],
            f"Product comparison: {n['fund']} total fees {f['current_pct']:g}% per year versus "
            f"Northshore Super about {f['new_pct']:g}% per year.",
            f"My recommendation would be to switch to Northshore Super, but only once we have "
            f"replacement insurance in place, because your cover sits inside {n['fund']}.",
            f"Switch from {n['fund']} to Northshore Super discussed, conditional on replacement "
            f"insurance being in place first.",
        )
        if t.decided:
            out.decision_text = (
                f"Client agreed to proceed with the switch from {n['fund']} to Northshore Super "
                f"once replacement insurance is in place."
            )
            out.confirm = (
                f"Good. We'll proceed with the switch from {n['fund']} once the replacement "
                f"insurance is in place."
            )
        return out
    if t.kind == "investment_option":
        out = _TopicLines(
            [
                (
                    adv,
                    f"You're in the {n['current']} option at the moment. The {n['proposed']} "
                    f"option has a long-run expected return of about {s.pct(f['expected_pct'])} "
                    f"but with bigger swings.",
                )
            ],
            f"Investment option: currently {n['current']}; {n['proposed']} option discussed with "
            f"an expected return of about {f['expected_pct']:g}% per year and higher volatility.",
            f"With your time horizon I think moving to {n['proposed']} is reasonable, if you're "
            f"comfortable with the volatility.",
            f"Move from the {n['current']} option to {n['proposed']} discussed.",
        )
        if t.decided:
            out.decision_text = (
                f"Client agreed to move the investment option from {n['current']} to "
                f"{n['proposed']}."
            )
            out.confirm = f"Right, we'll move you from {n['current']} to {n['proposed']}."
        return out
    if t.kind == "bdbn":
        year = int(f["lapse_year"])
        out = _TopicLines(
            [
                (
                    adv,
                    f"Your binding death benefit nomination lapses in {year}. It's in favour of "
                    f"your {n['beneficiary']}.",
                )
            ],
            f"Binding death benefit nomination in favour of {n['beneficiary']} lapses in {year}.",
            f"I'd recommend renewing the binding nomination now in favour of your "
            f"{n['beneficiary']} so it doesn't lapse.",
            f"Renewal of the binding death benefit nomination in favour of {n['beneficiary']} "
            f"discussed.",
        )
        if t.decided:
            out.decision_text = (
                f"Client agreed to renew the binding death benefit nomination in favour of "
                f"{n['beneficiary']}."
            )
            out.confirm = "Good, we'll get the nomination form renewed."
        return out
    if t.kind == "pension":
        out = _TopicLines(
            [
                (
                    adv,
                    f"With {s.amount(f['balance'])} in super, an account-based pension would need "
                    f"a minimum drawdown of {s.pct(f['min_pct'])} a year at your age.",
                )
            ],
            f"Account-based pension discussed: super balance {format_amount(f['balance'])}, "
            f"minimum drawdown {f['min_pct']:g}% per year.",
            f"I'd suggest starting the Northshore Pension with an income of "
            f"{s.amount(f['income'])} a year. Earnings in pension phase are tax free.",
            f"Start a Northshore Pension with income of {format_amount(f['income'])} per year "
            f"discussed.",
        )
        if t.decided:
            out.decision_text = (
                f"Client agreed to commence a Northshore Pension with income of "
                f"{format_amount(f['income'])} per year."
            )
            out.confirm = (
                f"Okay, we'll start the Northshore Pension at {s.amount(f['income'])} a year."
            )
        return out
    if t.kind == "age_pension":
        age = int(f["age"])
        out = _TopicLines(
            [
                (
                    adv,
                    f"On Centrelink: your assessable assets are about {s.amount(f['assets'])}, "
                    f"and Age Pension age is {number_to_words(age)}.",
                )
            ],
            f"Centrelink Age Pension: assessable assets about {format_amount(f['assets'])}; Age "
            f"Pension age {age}.",
            f"You can lodge the Age Pension claim up to thirteen weeks before you turn "
            f"{number_to_words(age)}, so I'd suggest lodging in {n['month']}.",
            f"Lodging the Age Pension claim in {n['month']} (up to 13 weeks before age {age}) "
            f"discussed.",
        )
        if t.decided:
            out.decision_text = f"Client agreed to lodge the Age Pension claim in {n['month']}."
            out.confirm = f"Good, we'll lodge the Age Pension claim in {n['month']}."
        return out
    out = _TopicLines(
        [
            (
                adv,
                f"Your insurance premium has gone from {s.amount(f['premium_old'])} to "
                f"{s.amount(f['premium_new'])} a year at the renewal.",
            ),
            (client, "That's a big jump."),
        ],
        f"Insurance premium increased from {format_amount(f['premium_old'])} to "
        f"{format_amount(f['premium_new'])} per year at renewal.",
        "The options are moving to level premiums or trimming the cover. I'd lean towards level "
        "premiums given your age.",
        "Options of moving to level premiums or reducing cover discussed; level premiums "
        "suggested.",
    )
    if t.decided:
        out.decision_text = "Client agreed to move the insurance to level premiums."
        out.confirm = "Okay, we'll switch the policy to level premiums at the next renewal."
    return out


def _render_topic(s: _Script, t: Topic) -> tuple[Claim, Claim | None, Claim | None, Claim | None]:
    """→ (topic claim, advice claim, decision claim, deferred claim)."""
    adv = s.seed.adviser
    lines = _topic_lines(s, t)
    topic_ids = [s.say(who, text) for who, text in lines.topic_lines]
    if t.kind in ("concessional", "insurance"):
        topic_ids += s.maybe_restate(
            adv, "as I said, " + lines.topic_lines[0][1][:1].lower() + lines.topic_lines[0][1][1:]
        )
    topic_claim = Claim(text=lines.topic_text, evidence=topic_ids)
    if lines.advice_line is None or lines.advice_text is None:
        return topic_claim, None, None, None
    advice_ids = [s.say(adv, lines.advice_line)]
    advice_claim = Claim(text=lines.advice_text, evidence=list(advice_ids))
    if t.decided is None:
        return topic_claim, advice_claim, None, None
    if t.decided and lines.decision_text:
        decided_ids = [
            *advice_ids,
            s.say(s.client(), s.rng.choice(AGREEMENTS), filler=False),
            s.say(adv, lines.confirm, filler=False),
        ]
        return (
            topic_claim,
            advice_claim,
            Claim(text=lines.decision_text, evidence=decided_ids),
            None,
        )
    deferred_ids = [
        *advice_ids,
        s.say(s.client(), s.rng.choice(DEFERRALS), filler=False),
        s.say(adv, s.rng.choice(PARKS), filler=False),
    ]
    return topic_claim, advice_claim, None, Claim(text=lines.advice_text, evidence=deferred_ids)


def _render_action(s: _Script, a: Action) -> ActionItem:
    adv = s.seed.adviser
    pp = s.seed.paraplanner
    ids: list[str] = []
    if a.owner == "adviser":
        ids.append(s.say(adv, f"I'll {a.description} and get it to you by {s.when(a.due)}."))
    elif a.owner == "client":
        ids.append(s.say(adv, f"Could you {a.description} by {s.when(a.due)}?"))
        replies = ["Sure, I'll do that.", "Yes, I'll send it through."]
        ids.append(s.say(s.client(), s.rng.choice(replies), filler=False))
    else:
        assert pp is not None
        ids.append(
            s.say(adv, f"{pp.first} will {a.description} and have it ready by {s.when(a.due)}.")
        )
        ids.append(s.say(pp, "I'll have that ready by then.", filler=False))
    desc = a.description[0].upper() + a.description[1:]
    return ActionItem(description=desc, owner=a.owner, due=a.due, evidence=ids)


def _render_compliance(s: _Script) -> ComplianceFlags:
    seed = s.seed
    adv = seed.adviser
    c0 = seed.clients[0]
    comp = seed.compliance
    flags = ComplianceFlags(
        fee_consent_discussed=comp.fee_consent_discussed,
        conflicts_disclosed=comp.conflicts_disclosed,
    )
    if comp.risk_profile_discussed:
        prev = comp.previous_risk_profile
        s.say(
            adv,
            f"On risk profile, last time we had you as {prev}. Are you still comfortable with "
            f"that?",
        )
        if comp.risk_profile_confirmed:
            s.say(c0, "Yes, that still feels right.", filler=False)
        else:
            s.say(c0, f"Actually I'd like to change that to {comp.risk_profile}.", filler=False)
            s.say(
                adv,
                f"Okay, so we'll update your risk profile to {comp.risk_profile} and I'll redo "
                f"the questionnaire with you.",
                filler=False,
            )
        flags.risk_profile_confirmed = comp.risk_profile_confirmed
        flags.risk_profile = comp.risk_profile
    if comp.fee_consent_discussed:
        assert comp.fee_amount is not None
        s.say(
            adv,
            f"Your ongoing fee arrangement is up for renewal. The fee disclosure statement shows "
            f"{s.amount(comp.fee_amount)} for the year, and I need your written consent to keep "
            f"deducting it.",
        )
        s.say(c0, "That's fine, send me the consent form.", filler=False)
    if comp.conflicts_disclosed:
        s.say(
            adv,
            "I should flag that the Northshore managed portfolios are a related product of our "
            "licensee, Northshore Financial Advice. My fee doesn't change either way.",
        )
        s.say(c0, "Understood, thanks for saying.", filler=False)
    vulnerability: list[Claim] = []
    for idx in comp.vulnerability:
        line, note_text = VULNERABILITY_LINES[idx]
        sid = s.say(c0, line, filler=False)
        sid2 = s.say(
            adv,
            "Thank you for telling me. We'll take it at your pace and I'll put the key points "
            "in writing.",
            filler=False,
        )
        vulnerability.append(Claim(text=note_text, evidence=[sid, sid2]))
    flags.vulnerability_indicators = vulnerability
    return flags


def _render_pii_aside(s: _Script) -> None:
    p = s.seed.pii_aside
    if p is None:
        return
    line = {
        "phone": f"Oh, and my new mobile number is {p.value}.",
        "email": f"My new email address is {p.value}, the old one is gone.",
        "address": f"We've moved, by the way. The new address is {p.value}.",
        "dob": f"For the form, I was born on {p.value}.",
        "tfn": f"You asked for my TFN last time, it's {p.value}.",
    }[p.kind]
    s.say(s.seed.clients[0], line, filler=False, small_talk=True)
    s.say(s.seed.adviser, "Thanks, I'll update our records.", filler=False, small_talk=True)


def _filler(s: _Script, idx: int) -> None:
    fa, fc = FILLERS_MID[idx]
    s.say(s.seed.adviser, fa, small_talk=True)
    s.say(s.seed.clients[0], fc, small_talk=True)


def render_meeting(seed: MeetingSeed, rng: random.Random) -> Rendered:
    s = _Script(seed, rng)
    adv = seed.adviser
    c0 = seed.clients[0]
    who = " and ".join(p.name for p in seed.clients)

    opener_a, opener_c = SMALL_TALK_OPENERS[seed.small_talk_open]
    s.say(adv, opener_a, small_talk=True)
    s.say(c0, opener_c, small_talk=True)
    s.say(adv, PURPOSE[seed.type], small_talk=True)

    changes = [_render_change(s, c) for c in seed.changes]
    for idx in seed.fillers_mid[:1]:
        _filler(s, idx)
    s.say(adv, "Let's go through your goals, has anything moved?", small_talk=True)
    goals = [_render_goal(s, g) for g in seed.goals]

    topics: list[Claim] = []
    advice: list[Claim] = []
    decisions: list[Claim] = []
    deferred: list[Claim] = []
    decision_topics: list[str] = []
    for t in seed.topics:
        topic_claim, advice_claim, decision_claim, deferred_claim = _render_topic(s, t)
        topics.append(topic_claim)
        if advice_claim:
            advice.append(advice_claim)
        if decision_claim:
            decisions.append(decision_claim)
            decision_topics.append(t.kind)
        if deferred_claim:
            deferred.append(deferred_claim)
    for idx in seed.fillers_mid[1:]:
        _filler(s, idx)

    flags = _render_compliance(s)
    _render_pii_aside(s)
    actions = [_render_action(s, a) for a in seed.actions]
    follow_up: Claim | None = None
    if seed.follow_up is not None:
        sid1 = s.say(adv, f"Let's lock in the next review for {s.when(seed.follow_up)}.")
        sid2 = s.say(c0, "Works for me.", filler=False)
        follow_up = Claim(
            text=f"Next review scheduled for {seed.follow_up.isoformat()}.", evidence=[sid1, sid2]
        )
    closer_a, closer_c = SMALL_TALK_CLOSERS[seed.small_talk_close]
    s.say(adv, closer_a, small_talk=True)
    s.say(c0, closer_c, small_talk=True)
    while len(s.segments) < 40:
        _filler(s, len(s.segments) % len(FILLERS_MID))

    topic_names = ", ".join(t.kind.replace("_", " ") for t in seed.topics)
    summary = (
        f"{seed.type.replace('_', ' ').capitalize()} meeting with {who} on "
        f"{seed.date.strftime('%d %B %Y')} covering {topic_names}. "
        f"Decisions were made where noted below; other advice was discussed and deferred."
    )
    duration = round(s.t / 60.0)
    transcript = Transcript(
        meeting_id=seed.id,
        date=seed.date,
        type=seed.type,
        attendees=seed.attendees,
        segments=s.segments,
    )
    gold = FileNote(
        meeting=MeetingMeta(
            date=seed.date, type=seed.type, attendees=seed.attendees, duration_minutes=duration
        ),
        summary=summary,
        circumstance_changes=changes,
        goals=goals,
        topics_discussed=topics,
        advice_discussed=advice,
        decisions=decisions,
        action_items=actions,
        compliance=flags,
        follow_up=follow_up,
    )
    return Rendered(
        transcript=transcript,
        gold=gold,
        small_talk_ids=s.small_talk,
        deferred=deferred,
        decision_topics=decision_topics,
    )
