#!/usr/bin/env python3
"""
passphrase.py — Readable passphrase generator (Phase 1.F.7).

Generates passwords in Capital.word.phrase.9 format from a curated word list.
Format: one leading-capital word, two-to-three lowercase words, period separators,
trailing digit. Total length 20-30 characters.

Used for:
  - KeePass master password suggestion at forge time
  - Initial service credential generation
  - Temporary root password for broodling spawn (via spawn_planner.py)

Character set: A-Z (leading only), a-z, 0-9, period.
No shell-special characters — passphrases are safe to embed in scripts.

Stdlib only.
"""

import random
import secrets
import string

# ---------------------------------------------------------------------------
# Word list — common 4-8 letter English words suitable for passphrases
# Chosen for: memorability, unambiguous spelling, no offensive content
# ---------------------------------------------------------------------------

_WORDS: tuple[str, ...] = (
    "able", "above", "across", "after", "again", "agent", "agree",
    "ahead", "allow", "alone", "along", "alter", "angle", "ankle",
    "antler", "apply", "apron", "arbor", "arise", "arrow", "atlas",
    "audio", "audit", "avid", "awake", "axle",
    "badge", "baker", "barge", "batch", "beacon", "beach", "bench",
    "berry", "blade", "blank", "blast", "blend", "block", "bloom",
    "blown", "board", "bonus", "boost", "booth", "botch", "bound",
    "brace", "brake", "brand", "brave", "break", "breed", "bride",
    "brief", "brine", "bring", "brisk", "broad", "brook", "brown",
    "brush", "build", "built", "burst", "buyer",
    "cable", "cameo", "canoe", "cargo", "carry", "cedar", "chain",
    "chalk", "chart", "chase", "check", "chief", "child", "chisel",
    "chord", "civic", "civil", "claim", "clamp", "clash", "class",
    "clean", "clear", "clerk", "click", "cliff", "climb", "clock",
    "clone", "close", "cloud", "coach", "coast", "comet", "coral",
    "could", "count", "cover", "craft", "crane", "creek", "crisp",
    "cross", "crust", "cubic", "curve",
    "daily", "dance", "datum", "debug", "delta", "dense", "depot",
    "depth", "derby", "drift", "drive", "drone", "drove", "dryly",
    "dusky", "dwarf",
    "eager", "eagle", "early", "earth", "eight", "elder", "elect",
    "ember", "emote", "empty", "enact", "enter", "equal", "error",
    "event", "every", "exact", "exist", "extra",
    "fable", "facet", "faint", "faith", "false", "fancy", "feast",
    "fetch", "fever", "field", "fifth", "fifty", "final", "first",
    "fixed", "fjord", "flame", "flask", "fleet", "flesh", "float",
    "flood", "floor", "flora", "flour", "flown", "focus", "forge",
    "forth", "found", "frame", "freed", "fresh", "front", "frost",
    "froze", "fully", "funky", "fuzzy",
    "gable", "gecko", "ghost", "given", "glare", "glass", "glide",
    "globe", "gloom", "gloss", "glove", "glyph", "gnome", "grace",
    "grade", "grain", "grand", "grant", "gravel", "great", "green",
    "greet", "grift", "grind", "groan", "grove", "grown", "guard",
    "guide", "guild", "guise", "gusto",
    "haven", "hazel", "heavy", "helix", "herald", "hinge", "hivemind",
    "hoist", "holly", "honey", "honor", "hover", "humid",
    "infer", "input", "inset", "inter",
    "jewel", "jumbo", "juror",
    "kayak", "ketch", "knack", "knave", "kneel", "knoll", "knot",
    "label", "lance", "latch", "layer", "learn", "ledge", "light",
    "limit", "linen", "liner", "lingo", "locus", "lodge", "logic",
    "lower", "lucid", "lunar",
    "maker", "maple", "march", "match", "medal", "merge", "merit",
    "micro", "mixer", "model", "module", "mondo", "moose", "morph",
    "mossy", "motif", "mount", "mouse", "mover", "muddy", "multi",
    "natal", "nerve", "nexus", "noble", "notch", "noted", "novel",
    "offer", "often", "onion", "onset", "optic", "orbit", "orchid",
    "order", "organ", "other", "outer", "outwit", "ovoid",
    "panel", "paper", "parse", "patch", "pause", "payoff", "pearl",
    "pedal", "penny", "perch", "pilot", "pinch", "pixel", "pivot",
    "place", "plain", "plane", "plant", "plate", "plaza", "plead",
    "plume", "plunk", "plush", "polar", "poppy", "poser", "power",
    "press", "pride", "prime", "prism", "probe", "prone", "proof",
    "proto", "prowl", "proxy", "prune", "pulse",
    "query", "quest", "quick", "quirk", "quota",
    "radar", "radio", "raise", "rally", "ramen", "ranch", "range",
    "rapid", "ratio", "reach", "ready", "realm", "rebel", "relay",
    "remix", "renew", "repay", "reset", "reuse", "ridge", "rivet",
    "robin", "rocky", "rough", "round", "route", "rover", "royal",
    "rugby", "ruler", "rural", "rusty",
    "sabre", "saddle", "salvo", "sandy", "scala", "scale", "scene",
    "scout", "screw", "scrub", "seeds", "seize", "serve", "seven",
    "shade", "shaft", "shake", "shape", "share", "sharp", "sheen",
    "shelf", "shell", "shift", "shiny", "shore", "short", "shout",
    "shrub", "sight", "sigma", "sixty", "sized", "skiff", "skill",
    "skimp", "slant", "slate", "sleek", "sleet", "slice", "slide",
    "slope", "sloth", "smart", "smelt", "smile", "smolt", "snare",
    "sneak", "solid", "solve", "sonar", "south", "space", "spare",
    "spark", "spawn", "speak", "speed", "spend", "spike", "spine",
    "spire", "split", "spree", "squad", "squib", "stack", "stage",
    "stale", "stall", "stamp", "stand", "stark", "start", "state",
    "steam", "steel", "steep", "steer", "stein", "stern", "stint",
    "stock", "stoic", "stone", "store", "storm", "story", "stove",
    "strap", "straw", "strip", "strut", "stuck", "study", "style",
    "suite", "super", "surge", "swamp", "sweep", "swept", "swift",
    "swirl", "swoop", "synth",
    "table", "talon", "tawny", "teach", "tenth", "terra", "terse",
    "theme", "thick", "thief", "thing", "think", "third", "thorn",
    "three", "threw", "throw", "thumb", "tiger", "tiled", "timer",
    "titan", "token", "tonal", "touch", "tough", "tower", "trace",
    "track", "trade", "trail", "train", "trait", "trawl", "trend",
    "tried", "trove", "truck", "truly", "tryst", "tuned", "tural",
    "twirl", "twist",
    "ultra", "unbox", "under", "unify", "until", "upper", "urban",
    "usage", "usual", "utter",
    "valid", "valve", "vapor", "vault", "venom", "verge", "verso",
    "video", "vigor", "viral", "vivid", "voice", "volta", "voter",
    "voted", "vouch",
    "water", "weave", "wedge", "weird", "while", "white", "whole",
    "wider", "windy", "wired", "witch", "witty", "woken", "world",
    "worth", "would", "woven",
    "xenon", "xeric",
    "yeast", "yield", "young", "yours",
    "zebra", "zoned", "zonal",
)

# Minimum and maximum total passphrase length (including periods and digit)
_MIN_LEN = 20
_MAX_LEN = 30


def _rng() -> random.Random:
    """Return a secrets-seeded Random for sampling without using SystemRandom directly."""
    seed = int.from_bytes(secrets.token_bytes(8), "big")
    return random.Random(seed)


def generate_passphrase(rng: random.Random | None = None) -> str:
    """
    Generate a readable passphrase in Capital.word.phrase.9 format.

    Format:
      Capital.word1.word2[.word3].digit
      - First word: leading capital, rest lowercase
      - Subsequent words: all lowercase
      - Separated by periods
      - Final trailing digit (0-9)
      - Total length 20-30 characters

    Returns a string such as "Forest.amber.glide.8" or "Brave.sonic.relay.stone.3".
    """
    r = rng or _rng()
    words = list(_WORDS)

    for _attempt in range(200):
        # Pick 2 or 3 body words
        n_words = r.choice([2, 3])
        chosen = r.sample(words, n_words)
        # Capitalise first word
        first = chosen[0].capitalize()
        rest  = chosen[1:]
        digit = str(r.randint(0, 9))
        phrase = ".".join([first] + rest) + "." + digit
        if _MIN_LEN <= len(phrase) <= _MAX_LEN:
            return phrase

    # Fallback: 3 words, force digit — should never be reached with the word list
    chosen = r.sample(words, 3)
    return chosen[0].capitalize() + "." + chosen[1] + "." + chosen[2] + "." + str(r.randint(0, 9))


def generate_passphrase_n(count: int, rng: random.Random | None = None) -> list[str]:
    """Generate `count` distinct passphrases."""
    r = rng or _rng()
    results = []
    seen: set[str] = set()
    for _ in range(count * 10):
        p = generate_passphrase(r)
        if p not in seen:
            seen.add(p)
            results.append(p)
        if len(results) == count:
            break
    return results


def generate_alphanumeric(length: int = 24, rng: random.Random | None = None) -> str:
    """
    Generate an alphanumeric-only password (letters + digits, no special chars).

    Used as fallback for services that reject period characters in passwords.
    Length default matches 24-char typical service credential length.
    """
    r = rng or _rng()
    alphabet = string.ascii_letters + string.digits
    # Ensure at least one uppercase, one lowercase, one digit
    chars = (
        [r.choice(string.ascii_uppercase)]
        + [r.choice(string.ascii_lowercase)]
        + [r.choice(string.digits)]
        + [r.choice(alphabet) for _ in range(max(length - 3, 0))]
    )
    r.shuffle(chars)
    return "".join(chars)


def passphrase_strength(phrase: str) -> dict:
    """
    Return a simple strength breakdown for a passphrase.

    Returns: {length, word_count, has_digit, format_valid, meets_min_length}
    """
    parts = phrase.split(".")
    has_digit = parts[-1].isdigit() if parts else False
    word_parts = parts[:-1] if has_digit else parts
    return {
        "length":           len(phrase),
        "word_count":       len(word_parts),
        "has_digit":        has_digit,
        "format_valid":     (
            len(word_parts) >= 2
            and word_parts[0][:1].isupper()
            and all(w[:1].islower() or w == "" for w in word_parts[1:])
            and has_digit
        ),
        "meets_min_length": len(phrase) >= _MIN_LEN,
    }
