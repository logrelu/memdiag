"""Synthetic demo traces: a consumer-finance assistant with three users.

Everything here is made up. It is built to show each failure type once.
"""

DOCS = [
    {"id": "doc_platinum", "text": "Platinum Card: purchase APR of 21.49% variable. No annual fee."},
    {"id": "doc_rewards", "text": "Rewards Card: purchase APR of 24.99% variable. Annual fee of $95."},
    {"id": "doc_late_fee", "text": "Late payment fee of $40 applies to all cards."},
    {"id": "doc_hysa", "text": "High-Yield Savings account: rate of 4.10% APY, no minimum balance."},
    {"id": "doc_balance_transfer", "text": "Balance transfer fee of 3% with a 0% intro APR for 15 months."},
]


def _d(i):
    return next(d for d in DOCS if d["id"] == i)


def U(user, sess, ts, text):
    return {"user_id": user, "session_id": sess, "ts": ts, "role": "user", "content": text}


def A(user, sess, ts, text, retrieved=(), ctx=None):
    e = {"user_id": user, "session_id": sess, "ts": ts, "role": "assistant", "content": text,
         "retrieved": [_d(i) for i in retrieved]}
    if ctx:
        e["context_tokens"] = ctx
    return e


TRACES = [
    # --- Maya: moves city and pays off a loan; agent keeps the old facts ---
    U("maya", "m1", "2026-01-05T09:00:00", "Hi, I live in Seattle and I make $85,000 a year. I have a car loan."),
    A("maya", "m1", "2026-01-05T09:00:05", "Thanks, Maya. I'll keep that in mind for your budget.", ctx=1800),
    U("maya", "m2", "2026-02-10T18:20:00", "Quick update: I just moved to Portland. I also paid off my car loan last week!"),
    A("maya", "m2", "2026-02-10T18:20:04", "Congratulations on paying it off! That frees up room in your budget.", ctx=2100),
    U("maya", "m3", "2026-03-02T12:00:00", "Can you suggest a credit union near me?"),
    A("maya", "m3", "2026-03-02T12:00:06", "Since you live in Seattle, BECU is a popular credit union near you.", ctx=2600),
    U("maya", "m3", "2026-03-02T12:01:00", "That's wrong, I moved to Portland."),
    A("maya", "m3", "2026-03-02T12:01:05", "Sorry about that. In Portland, OnPoint Community Credit Union is a good option.", ctx=2700),
    U("maya", "m3", "2026-03-02T12:03:00", "What should I prioritize with extra cash this month?"),
    A("maya", "m3", "2026-03-02T12:03:06", "I'd put extra money toward your car loan balance first.", ctx=2900),
    U("maya", "m3", "2026-03-02T12:04:00", "I paid that off, remember?"),
    U("maya", "m3", "2026-03-02T12:06:00", "What's the APR on the Platinum card?"),
    A("maya", "m3", "2026-03-02T12:06:05", "The Platinum card has a purchase APR of 24.99%.", retrieved=["doc_platinum"], ctx=3400),

    # --- Dev: asks the agent to forget income; agent uses it anyway ---
    U("dev", "d1", "2026-01-08T20:00:00", "I work at Stripe and my income is $140k. My credit score is 712."),
    A("dev", "d1", "2026-01-08T20:00:05", "Got it, thanks Dev.", ctx=1500),
    U("dev", "d1", "2026-01-08T20:01:00", "What's the rate on the high-yield savings account?"),
    A("dev", "d1", "2026-01-08T20:01:04", "The High-Yield Savings account has a rate of 4.10% APY.", retrieved=["doc_hysa"], ctx=1900),
    U("dev", "d2", "2026-02-15T08:30:00", "Please forget my income, I don't want it stored."),
    A("dev", "d2", "2026-02-15T08:30:03", "Done. I won't use it going forward.", ctx=1200),
    U("dev", "d3", "2026-03-05T19:00:00", "Can I afford $2,000 a month in rent?"),
    A("dev", "d3", "2026-03-05T19:00:06", "With your income of $140,000, $2,000 a month is about 17% of gross income, so yes.", ctx=2400),
    U("dev", "d3", "2026-03-05T19:01:00", "I asked you to forget my income."),
    U("dev", "d3", "2026-03-05T19:02:00", "Does my employer offer anything for savings?"),
    A("dev", "d3", "2026-03-05T19:02:05", "Where do you work? Some employers offer savings matches.", ctx=2500),
    U("dev", "d3", "2026-03-05T19:03:00", "I already told you, Stripe. What's the balance transfer fee?"),
    A("dev", "d3", "2026-03-05T19:03:06", "I'm not sure about the balance transfer fee.", retrieved=["doc_late_fee", "doc_hysa"], ctx=2800),
    U("dev", "d3", "2026-03-05T19:04:00", "That's not helpful."),

    # --- Lena: agent leaks Dev's score, invents an employer, ignores a doc ---
    U("lena", "l1", "2026-01-12T14:00:00", "I live in Austin. My credit score is 640."),
    A("lena", "l1", "2026-01-12T14:00:05", "Thanks, Lena. I'll factor that into card suggestions.", ctx=1400),
    U("lena", "l2", "2026-03-06T10:00:00", "Which card can I get approved for?"),
    A("lena", "l2", "2026-03-06T10:00:07", "With a 712 credit score, you'd likely qualify for the Rewards card.", retrieved=["doc_rewards"], ctx=3100),
    U("lena", "l2", "2026-03-06T10:01:00", "That's not me, my score is 640."),
    U("lena", "l2", "2026-03-06T10:02:00", "Any employer benefits I should use?"),
    A("lena", "l2", "2026-03-06T10:02:05", "Since you work at Google, check whether they offer a 401(k) match.", ctx=3300),
    U("lena", "l2", "2026-03-06T10:05:00", "What's the late fee if I miss a payment?"),
    A("lena", "l2", "2026-03-06T10:05:09", "The late fee is $25.",
      retrieved=["doc_platinum", "doc_rewards", "doc_hysa", "doc_balance_transfer", "doc_late_fee"], ctx=48000),
]
