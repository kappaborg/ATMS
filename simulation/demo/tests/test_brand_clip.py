"""Unit tests for simulation/demo/brand_clip.py.

We can't load the actual CLIP model in unit tests (~150 MB download, requires
torch + transformers). These tests cover the static parts: the brand-prompts
list shape, that every prompt matches an entry in the emission multiplier
table, and the public interface contract.
"""

from __future__ import annotations

from shared.atms_common.emissions import _DEFAULT_BRAND_MULTIPLIERS
from simulation.demo.brand_clip import DEFAULT_BRAND_PROMPTS, CLIPBrandIdentifier


class TestDefaultBrandPrompts:
    def test_nonempty(self):
        assert len(DEFAULT_BRAND_PROMPTS) > 0

    def test_covers_50_plus_brands(self):
        # The headline reason to use CLIP is coverage — fail if we accidentally
        # trim the list to something close to the trained model's 13.
        assert len(DEFAULT_BRAND_PROMPTS) >= 50

    def test_every_prompt_is_lowercase_and_stripped(self):
        for p in DEFAULT_BRAND_PROMPTS:
            assert p == p.lower().strip()

    def test_no_duplicates(self):
        assert len(DEFAULT_BRAND_PROMPTS) == len(set(DEFAULT_BRAND_PROMPTS))

    def test_every_prompt_has_emission_multiplier(self):
        # If a prompt isn't in the multiplier table, the brand identification
        # is wasted — the estimator falls back to the per-class baseline.
        missing = [p for p in DEFAULT_BRAND_PROMPTS if p not in _DEFAULT_BRAND_MULTIPLIERS]
        assert missing == [], (
            f"{len(missing)} CLIP brands have no emission multiplier: {missing[:10]}"
        )

    def test_high_traffic_brands_present(self):
        # Sanity-check: the most-common brands in real traffic should all
        # be in the prompt list.
        for brand in ("toyota", "honda", "ford", "volkswagen", "tesla", "bmw"):
            assert brand in DEFAULT_BRAND_PROMPTS


class TestCLIPBrandIdentifierConstruction:
    def test_default_construction(self):
        # Construction should not load the model — that's lazy.
        cid = CLIPBrandIdentifier()
        assert cid._brands == DEFAULT_BRAND_PROMPTS
        assert cid._model is None  # not yet loaded
        assert cid._processor is None

    def test_custom_brand_list(self):
        cid = CLIPBrandIdentifier(brands=["tesla", "toyota"])
        assert cid._brands == ["tesla", "toyota"]

    def test_custom_confidence_threshold(self):
        cid = CLIPBrandIdentifier(conf_threshold=0.5)
        assert cid._conf_threshold == 0.5

    def test_identify_batch_empty_input_returns_empty(self):
        cid = CLIPBrandIdentifier()
        # Empty input should return empty list without touching the model
        result = cid.identify_batch([])
        assert result == []

    def test_default_threshold_is_strict(self):
        # The Phase-2 defaults are deliberately strict so CLIP can't
        # confidently-but-wrongly commit. Conf 0.30 + margin 0.05.
        cid = CLIPBrandIdentifier()
        assert cid._conf_threshold == 0.30
        assert cid._min_margin == 0.05

    def test_multi_prompt_expansion(self):
        # With 4 templates per brand, the total prompt count is 4x.
        cid = CLIPBrandIdentifier(brands=["tesla", "toyota", "ford"])
        assert len(cid._prompts) == 12  # 3 brands x 4 templates
        # The brand-index list should map prompt i -> its source brand.
        assert cid._prompt_brand_idx[:4] == [0, 0, 0, 0]
        assert cid._prompt_brand_idx[4:8] == [1, 1, 1, 1]
        assert cid._prompt_brand_idx[8:12] == [2, 2, 2, 2]

    def test_prompts_contain_brand_name(self):
        cid = CLIPBrandIdentifier(brands=["tesla"])
        for p in cid._prompts:
            assert "tesla" in p.lower()

    def test_custom_margin(self):
        cid = CLIPBrandIdentifier(min_margin=0.20)
        assert cid._min_margin == 0.20
