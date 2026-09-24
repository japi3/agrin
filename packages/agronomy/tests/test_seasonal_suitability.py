"""
Which crops belong to the season a farmer is asking about.

Asked in Nashik in September what to sow after the kharif crop, the
suitability card answered with paddy, cotton, soybean, groundnut, maize and
bajra -- every one a kharif crop, each labelled as growing on rain alone from
1063 mm of monsoon. The assistant's own text directly above it was correctly
recommending chickpea and rabi wheat, and warning that rain stops in October.

The card was not wrong about the land. It was answering "what could ever grow
here" while the farmer had asked "what should I sow next", and in a monsoon
climate those have almost opposite answers.
"""

from agronomy.crops import CROPS


NASHIK = 20.0          # northern hemisphere, monsoon climate


class TestSowingMonthsAreDistinctFromGrowingMonths:
    def test_a_kharif_crop_is_sown_at_the_monsoon(self):
        assert set(CROPS["rice_paddy"].sowing_months(NASHIK)) <= {6, 7, 8}

    def test_a_rabi_crop_is_sown_after_the_monsoon(self):
        assert set(CROPS["wheat_rabi"].sowing_months(NASHIK)) <= {10, 11, 12}

    def test_sowing_is_a_subset_of_the_window_the_crop_occupies(self):
        """A crop is sown inside its own season, not outside it."""
        for key, crop in CROPS.items():
            sown = set(crop.sowing_months(NASHIK))
            occupied = set(crop.growing_months(NASHIK))
            assert sown <= occupied, f"{key} sown outside its growing window"

    def test_a_crop_with_no_declared_window_stays_available(self):
        """Missing data means unknown, not 'never sowable'.

        Excluding it would silently drop the crop from every seasonal answer.
        """
        for key, crop in CROPS.items():
            assert crop.sowing_months(NASHIK), f"{key} has no sowable month"


class TestTheSeasonsDoNotCollide:
    def test_rabi_and_kharif_crops_are_not_sown_in_the_same_month(self):
        """The specific confusion behind the bug.

        If wheat and paddy shared a sowing month, asking what to sow in
        October would legitimately return both, and the card would look
        wrong even when it was right.
        """
        kharif = set(CROPS["rice_paddy"].sowing_months(NASHIK))
        rabi = set(CROPS["wheat_rabi"].sowing_months(NASHIK))
        assert not (kharif & rabi)

    def test_october_offers_rabi_crops_and_not_paddy(self):
        """What the farmer in Nashik actually asked."""
        sowable = {
            key for key, crop in CROPS.items()
            if 10 in crop.sowing_months(NASHIK)
            # Crops with no declared window match every month; they say
            # nothing about the season and would mask a real regression.
            and crop.sowing_months_north
        }
        assert "rice_paddy" not in sowable
        assert "cotton" not in sowable
        assert sowable, "October must offer something to sow"
