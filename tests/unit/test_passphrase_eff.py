"""
test_passphrase_eff.py — EFF diceware passphrase generator tests.

Covers:
  - generate_eff_passphrase: format, length, uniqueness, separators
  - generate_eff_passphrase_n: distinct results
  - eff_passphrase_strength: entropy, word count
  - integration with passphrase.generate_master_password_suggestion(style='eff')
  - investigation finding: keepassxc-cli does not support diceware format
"""



import passphrase as _pw
import passphrase_eff as _eff


class TestEffPassphrase:

    def test_returns_string(self):
        phrase = _eff.generate_eff_passphrase()
        assert isinstance(phrase, str)

    def test_default_four_words(self):
        phrase = _eff.generate_eff_passphrase()
        parts = phrase.split("-")
        assert len(parts) == 4

    def test_five_words(self):
        phrase = _eff.generate_eff_passphrase(word_count=5)
        assert len(phrase.split("-")) == 5

    def test_all_lowercase(self):
        phrase = _eff.generate_eff_passphrase()
        assert phrase == phrase.lower()

    def test_words_from_word_list(self):
        phrase = _eff.generate_eff_passphrase()
        for word in phrase.split("-"):
            assert word in _eff._EFF_WORDS

    def test_no_duplicate_words(self):
        phrase = _eff.generate_eff_passphrase()
        words = phrase.split("-")
        assert len(words) == len(set(words))

    def test_meets_min_length(self):
        phrase = _eff.generate_eff_passphrase()
        assert len(phrase) >= _eff._MIN_LENGTH

    def test_custom_separator(self):
        phrase = _eff.generate_eff_passphrase(separator=" ")
        assert " " in phrase
        assert len(phrase.split(" ")) == 4

    def test_deterministic_with_rng(self):
        import random
        rng = random.Random(42)
        p1 = _eff.generate_eff_passphrase(rng=rng)
        rng = random.Random(42)
        p2 = _eff.generate_eff_passphrase(rng=rng)
        assert p1 == p2

    def test_secure_path_unique(self):
        phrases = {_eff.generate_eff_passphrase() for _ in range(10)}
        assert len(phrases) >= 9  # 10 runs should yield at least 9 unique

    def test_word_list_size_reasonable(self):
        # Should have at least 500 words for meaningful entropy
        assert len(_eff._EFF_WORDS) >= 500

    def test_word_list_no_duplicates(self):
        assert len(_eff._EFF_WORDS) == len(set(_eff._EFF_WORDS))

    def test_word_list_all_lowercase(self):
        for w in _eff._EFF_WORDS:
            assert w == w.lower(), f"Word not lowercase: {w}"

    def test_word_list_no_short_words(self):
        for w in _eff._EFF_WORDS:
            assert len(w) >= 3, f"Word too short: {w}"


class TestEffPassphraseN:

    def test_generates_n_phrases(self):
        phrases = _eff.generate_eff_passphrase_n(count=5)
        assert len(phrases) == 5

    def test_all_distinct(self):
        phrases = _eff.generate_eff_passphrase_n(count=5)
        assert len(set(phrases)) == 5

    def test_custom_word_count(self):
        phrases = _eff.generate_eff_passphrase_n(count=3, word_count=5)
        for phrase in phrases:
            assert len(phrase.split("-")) == 5


class TestEffPassphraseStrength:

    def test_strength_word_count(self):
        phrase = "goblin-chrome-summit-tackle"
        s = _eff.eff_passphrase_strength(phrase)
        assert s["word_count"] == 4

    def test_strength_entropy_positive(self):
        phrase = "goblin-chrome-summit-tackle"
        s = _eff.eff_passphrase_strength(phrase)
        assert s["entropy_bits_approx"] > 0

    def test_strength_meets_min_length(self):
        phrase = "goblin-chrome-summit-tackle"
        s = _eff.eff_passphrase_strength(phrase)
        assert s["meets_min_length"] is True

    def test_strength_five_words_more_entropy(self):
        p4 = "goblin-chrome-summit-tackle"
        p5 = "goblin-chrome-summit-tackle-brave"
        s4 = _eff.eff_passphrase_strength(p4)
        s5 = _eff.eff_passphrase_strength(p5)
        assert s5["entropy_bits_approx"] > s4["entropy_bits_approx"]


class TestMasterPasswordSuggestionEff:

    def test_eff_style_returns_hyphenated(self):
        pw, source = _pw.generate_master_password_suggestion(style="eff")
        assert source == "eff"
        assert "-" in pw
        assert len(pw.split("-")) == 4

    def test_eff_style_all_lowercase(self):
        pw, _ = _pw.generate_master_password_suggestion(style="eff")
        assert pw == pw.lower()

    def test_classic_style_still_works(self):
        pw, source = _pw.generate_master_password_suggestion(style="classic")
        assert source == "secrets"
        # Classic format has Capital.word.phrase.N pattern
        assert "." in pw
        assert pw[0].isupper()

    def test_default_style_is_eff(self):
        pw, source = _pw.generate_master_password_suggestion()
        assert source == "eff"

    def test_eff_words_from_wordlist(self):
        from passphrase_eff import _EFF_WORDS
        pw, source = _pw.generate_master_password_suggestion(style="eff")
        for word in pw.split("-"):
            assert word in _EFF_WORDS

    def test_keepassxc_style_falls_back_to_secrets(self):
        # keepassxc-cli is not available in CI — should fall back gracefully
        pw, source = _pw.generate_master_password_suggestion(style="keepassxc")
        # Either keepassxc-cli (if installed) or secrets format
        assert source in ("keepassxc-cli", "secrets")
        assert len(pw) >= 10


class TestKeepassxcInvestigationFindings:
    """Document the investigation findings as executable assertions."""

    def test_keepassxc_cli_not_required(self):
        # The EFF generator works without keepassxc-cli installed
        pw, source = _pw.generate_master_password_suggestion(style="eff")
        assert len(pw) > 0  # works regardless of keepassxc-cli availability

    def test_eff_format_more_readable_than_classic(self):
        # EFF words are common English words — easier to type and remember
        # than Capital.word.phrase.9 with its capital and trailing digit
        eff_pw, _ = _pw.generate_master_password_suggestion(style="eff")
        classic_pw, _ = _pw.generate_master_password_suggestion(style="classic")
        # EFF format uses only hyphens as separator (no digits required)
        assert eff_pw.replace("-", "").isalpha()
        # Classic format uses periods and ends with a digit
        assert "." in classic_pw
        assert classic_pw[-1].isdigit()
