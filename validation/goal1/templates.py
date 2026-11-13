"""Phrasing templates for Goal 1 mutations, each with an id and a split.

Held-out templates were written to include phrasings the rule detectors were not written for, so held-out
recall in rules mode measures generalization, not pattern overlap. Never tune detectors on held-out results.
"""
from __future__ import annotations

DEV, HELDOUT = "dev", "heldout"


def T(tid: str, split: str, text: str) -> dict:
    return {"id": tid, "split": split, "text": text}


CITIES = ["Seattle", "Portland", "Denver", "Austin", "Boston", "Chicago", "Phoenix", "Atlanta", "Detroit", "Miami",
          "Dallas", "Houston", "Toronto", "Vancouver", "Dublin", "Lisbon", "Madrid", "Berlin", "Oslo", "Prague"]
EMPLOYERS = ["Stripe", "Target", "Costco", "Adobe", "Pfizer", "Intel", "Nike", "Boeing", "Oracle", "Spotify",
             "Zillow", "Etsy", "Shopify", "Atlassian", "Siemens", "Unilever"]
CHILD_NAMES = ["Lily", "Noah", "Ava", "Leo", "Maya", "Eli", "Zoe", "Max", "Ruby", "Owen"]
BANNED = ["synergy", "delve", "paradigm", "holistic", "leverage"]

ACK = "Got it, thanks for letting me know."

FACT = {
    "city": [T("c_f1", DEV, "By the way, I live in {v}."), T("c_f2", DEV, "I'm based in {v}, for context."),
             T("c_f3", DEV, "Quick note: I live in {v}."),
             T("c_f4", HELDOUT, "For context, home for me is {v}."), T("c_f5", HELDOUT, "I now live in {v}.")],
    "employer": [T("e_f1", DEV, "I work at {v}."), T("e_f2", DEV, "I work for {v}, by the way."),
                 T("e_f3", HELDOUT, "My employer is {v}."), T("e_f4", HELDOUT, "I just joined {v} this year.")],
    "child_age": [T("a_f1", DEV, "My daughter {name} is {v}."), T("a_f2", DEV, "My daughter {name} is {v} years old."),
                  T("a_f3", HELDOUT, "{name}, my daughter, just turned {v}.")],
}
UPDATE = {
    "city": [T("c_u1", DEV, "Update: we just moved to {v}."), T("c_u2", DEV, "I relocated to {v} last month."),
             T("c_u3", HELDOUT, "We packed up and settled in {v} last week."), T("c_u4", HELDOUT, "I'm now in {v}.")],
    "employer": [T("e_u1", DEV, "I started a new job at {v}."), T("e_u2", DEV, "My new job is at {v}."),
                 T("e_u3", HELDOUT, "I left {old} for a role at {v}.")],
}
STALE = {
    "city": [T("c_s1", DEV, "Since you live in {v}, here is a tip."), T("c_s2", DEV, "Given that you're in {v}, this should help."),
             T("c_s3", HELDOUT, "As someone based in {v}, you might like this."),
             T("c_s4", HELDOUT, "Near you in {v}, there are good options.")],
    "employer": [T("e_s1", DEV, "Since you work at {v}, check your benefits."),
                 T("e_s2", HELDOUT, "Your role at {v} probably includes a 401k."),
                 T("e_s3", HELDOUT, "Your benefits through {v} might cover this.")],
}
STALE_CONTROL = {
    "city": [T("c_n1", DEV, "Since you live in {new}, here is a tip."),
             T("c_n2", HELDOUT, "Since you moved from {old} to {new}, this should help.")],
    "employer": [T("e_n1", DEV, "Since you work at {new}, check your benefits."),
                 T("e_n2", HELDOUT, "Congrats on moving from {old} to {new}; check your new benefits.")],
}
REASK = {
    "city": [T("r_c1", DEV, "Where do you live, by the way?"), T("r_c2", DEV, "What city are you in?"),
             T("r_c3", HELDOUT, "Where are you located these days?"), T("r_c4", HELDOUT, "Remind me which city you're in?")],
    "employer": [T("r_e1", DEV, "Where do you work, by the way?"), T("r_e2", HELDOUT, "Who do you work for these days?")],
    "child_age": [T("r_a1", DEV, "How old is {name}?"), T("r_a2", HELDOUT, "How old is your daughter now?")],
}
REASK_CONTROL = [T("r_n1", DEV, "How old is your car, by the way?"),
                 T("r_n2", HELDOUT, "Is the weather nice where you are this week?")]
CONSTRAINT = {
    "max_words": [T("k_w1", DEV, "Keep your answers under {n} words."),
                  T("k_w2", HELDOUT, "From now on, please keep replies under {n} words.")],
    "no_bullets": [T("k_b1", DEV, "Please don't use bullet points."),
                   T("k_b2", HELDOUT, "Never use bullet points in your answers.")],
    "banned_word": [T("k_x1", DEV, "Don't use the word {w}."), T("k_x2", HELDOUT, "Never say the word {w}.")],
    "no_emoji": [T("k_e1", DEV, "No emojis please."), T("k_e2", HELDOUT, "Stop using emojis.")],
}
CONSTRAINT_REVOKE = {"max_words": "You can go longer now.", "no_bullets": "Bullets are fine again.",
                     "no_emoji": "Emojis are fine now."}
REPAIR = [T("p_1", DEV, "I already told you that."), T("p_2", DEV, "As I said, it's in my last message."),
          T("p_3", HELDOUT, "Like I mentioned before, please check again."), T("p_4", HELDOUT, "Did you forget what I said?"),
          T("p_5", HELDOUT, "I said this earlier, please re-read.")]
REPAIR_CONTROL = [T("p_n1", DEV, "Thanks, that helps!"), T("p_n2", HELDOUT, "Great, what else should I know?")]


def pick(pool: list[dict], split: str, rng) -> dict:
    """A template from the pool for this split. A pool without one for the split is a bug, never a fallback:
    falling back would leak dev phrasing into held-out cases."""
    options = [t for t in pool if t["split"] == split]
    if not options:
        raise ValueError(f"no {split} template in pool {[t['id'] for t in pool]}")
    return rng.choice(options)
